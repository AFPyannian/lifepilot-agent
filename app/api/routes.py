"""提供同步聊天、流式聊天和审批恢复接口。"""


import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.api.execution import extract_latest_ai_reply, resume_pending_execution
from app.api.interrupts import extract_invoke_interrupt, find_pending_interrupt, normalize_approval_request
from app.api.schemas import ApprovalDecision, ApprovalResumeResponse, ChatRequest, ChatResponse, HealthResponse
from app.api.streaming import stream_chat_events
from app.api.run_config import build_run_config
from app.exceptions import LifePilotError


logger = logging.getLogger(
    "lifepilot.api"
)

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="检查 LifePilot 服务状态",
)
def health_check() -> HealthResponse:
    """返回 LifePilot 服务存活状态。"""
    return HealthResponse(
        status="ok",
        service="lifepilot-agent",
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="与 LifePilot Agent 对话",
)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """执行一次同步 Agent 对话，并返回回答或审批请求。"""
    graph, graph_lock = (
        _get_graph_dependencies(request)
    )

    config = build_run_config(
        request=request,
        thread_id=payload.thread_id,
        operation="chat",
    )

    try:

        _record_conversation(
            request=request,
            thread_id=payload.thread_id,
            message=payload.message,
        )

        with graph_lock:

            pending_interrupt = (
                find_pending_interrupt(
                    graph=graph,
                    config=config,
                )
            )

            if pending_interrupt is not None:
                raise HTTPException(
                    status_code= status.HTTP_409_CONFLICT,
                    detail= "当前会话存在等待审批的操作，请先批准或拒绝该操作。",
                )


            resume_pending_execution(
                graph=graph,
                config=config,
            )

            result = graph.invoke(
                {
                    "messages": [
                        HumanMessage(
                            content=(
                                payload.message
                            )
                        )
                    ]
                },
                config=config,
            )


            invoke_interrupt = (
                extract_invoke_interrupt(
                    result
                )
            )

            if invoke_interrupt is not None:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail=(
                        "本次操作需要用户审批，"
                        "请使用流式聊天接口获取"
                        "审批内容，并通过恢复接口"
                        "批准或拒绝该操作。"
                    ),
                )

        reply = extract_latest_ai_reply(
            result.get(
                "messages",
                [],
            )
        )

        logger.info(
            "Agent API request completed "
            "thread_id=%s",
            payload.thread_id,
        )

        return ChatResponse(
            reply=reply,
            thread_id=payload.thread_id,
        )


    except HTTPException:
        raise

    except LifePilotError as error:
        logger.exception(
            "Expected Agent API error "
            "thread_id=%s",
            payload.thread_id,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=error.user_message,
        ) from error

    except Exception as error:
        logger.exception(
            "Unexpected Agent API error "
            "thread_id=%s",
            payload.thread_id,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "LifePilot 处理请求时"
                "发生内部错误。"
            ),
        ) from error


@router.post(
    "/chat/stream",
    response_class=StreamingResponse,
    summary="与 LifePilot Agent 流式对话",
    responses={
        200: {
            "content": {
                "text/event-stream": {}
            },
            "description": "SSE 流式响应",
        }
    },
)
def chat_stream(
    payload: ChatRequest,
    request: Request,
) -> StreamingResponse:
    """创建逐段返回 Agent 输出的 SSE 响应。"""
    graph, graph_lock = (
        _get_graph_dependencies(request)
    )


    _record_conversation(
        request=request,
        thread_id=payload.thread_id,
        message=payload.message,
    )

    config = build_run_config(
        request=request,
        thread_id=payload.thread_id,
        operation="stream_chat",
    )

    event_iterator = stream_chat_events(
        graph=graph,
        graph_lock=graph_lock,
        message=payload.message,
        thread_id=payload.thread_id,
        config=config,
    )

    return StreamingResponse(
        content=event_iterator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/chat/resume",
    response_model=ApprovalResumeResponse,
    summary="批准或拒绝待执行操作",
)
def resume_chat(
    payload: ApprovalDecision,
    request: Request,
) -> ApprovalResumeResponse:
    """根据用户决定恢复等待审批的 Agent 执行。"""
    graph, graph_lock = (
        _get_graph_dependencies(request)
    )

    config = build_run_config(
        request=request,
        thread_id=payload.thread_id,
        operation="resume_approval",
    )

    try:


        _touch_conversation(
            request=request,
            thread_id=payload.thread_id,
        )

        with graph_lock:
            existing_interrupt = (
                find_pending_interrupt(
                    graph=graph,
                    config=config,
                )
            )

            if existing_interrupt is None:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail=(
                        "当前会话没有等待审批的"
                        "操作。"
                    ),
                )

            result = graph.invoke(
                Command(
                    resume={
                        "approved": (
                            payload.approved
                        ),
                    }
                ),
                config=config,
            )


            pending_interrupt = (
                extract_invoke_interrupt(
                    result
                )
            )

            if pending_interrupt is None:
                pending_interrupt = (
                    find_pending_interrupt(
                        graph=graph,
                        config=config,
                    )
                )

        if pending_interrupt is not None:
            return ApprovalResumeResponse(
                status="approval_required",
                thread_id=payload.thread_id,
                approval_request=(
                    normalize_approval_request(
                        pending_interrupt
                    )
                ),
            )

        reply = extract_latest_ai_reply(
            result.get(
                "messages",
                [],
            )
        )

        logger.info(
            "Agent approval resolved "
            "thread_id=%s approved=%s",
            payload.thread_id,
            payload.approved,
        )

        return ApprovalResumeResponse(
            status="completed",
            thread_id=payload.thread_id,
            reply=reply,
        )

    except HTTPException:
        raise

    except LifePilotError as error:
        logger.exception(
            "Expected approval resume error "
            "thread_id=%s",
            payload.thread_id,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=error.user_message,
        ) from error

    except Exception as error:
        logger.exception(
            "Unexpected approval resume error "
            "thread_id=%s",
            payload.thread_id,
        )

        raise HTTPException(
            status_code=(
                status
                .HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "LifePilot 恢复审批操作时"
                "发生内部错误。"
            ),
        ) from error


def _get_graph_dependencies(
    request: Request,
) -> tuple[Any, Any]:
    """读取 Agent 图和并发锁。"""

    graph = getattr(
        request.app.state,
        "agent_graph",
        None,
    )

    graph_lock = getattr(
        request.app.state,
        "graph_lock",
        None,
    )

    if (
        graph is None
        or graph_lock is None
    ):
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "LifePilot 尚未完成初始化。"
            ),
        )

    return graph, graph_lock


def _record_conversation(
    request: Request,
    thread_id: str,
    message: str,
) -> None:
    """创建会话元数据或刷新最后活动时间。"""

    repository = getattr(
        request.app.state,
        "conversation_repository",
        None,
    )

    settings = getattr(
        request.app.state,
        "settings",
        None,
    )


    if (
        repository is None
        or settings is None
    ):
        return

    repository.record_message(
        owner_id=settings.owner_id,
        thread_id=thread_id,
        first_message=message,
    )


def _touch_conversation(
    request: Request,
    thread_id: str,
) -> None:
    """刷新已经存在的会话活动时间。"""

    repository = getattr(
        request.app.state,
        "conversation_repository",
        None,
    )

    settings = getattr(
        request.app.state,
        "settings",
        None,
    )

    if (
        repository is None
        or settings is None
    ):
        return

    repository.touch(
        owner_id=settings.owner_id,
        thread_id=thread_id,
    )