import logging
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import (
    StreamingResponse,
)
from langchain_core.messages import (
    HumanMessage,
)
from langgraph.types import Command

from app.api.execution import (
    extract_latest_ai_reply,
    resume_pending_execution,
)
from app.api.interrupts import (
    extract_invoke_interrupt,
    find_pending_interrupt,
    normalize_approval_request,
)
from app.api.schemas import (
    ApprovalDecision,
    ApprovalResumeResponse,
    ChatRequest,
    ChatResponse,
    HealthResponse,
)
from app.api.streaming import (
    stream_chat_events,
)
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
    return HealthResponse(
        status="ok",
        service="lifepilot-agent",
    )


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="与 LifePilot Agent 对话",
)
def chat(
    payload: ChatRequest,
    request: Request,
) -> ChatResponse:
    graph, graph_lock = (
        _get_graph_dependencies(request)
    )

    config = {
        "configurable": {
            "thread_id": payload.thread_id,
        }
    }

    try:
        # 创建新会话元数据，
        # 或刷新已有会话的更新时间。
        _record_conversation(
            request=request,
            thread_id=payload.thread_id,
            message=payload.message,
        )

        with graph_lock:
            # 首先检查当前会话是否存在
            # 等待用户处理的人工审批。
            pending_interrupt = (
                find_pending_interrupt(
                    graph=graph,
                    config=config,
                )
            )

            if pending_interrupt is not None:
                raise HTTPException(
                    status_code=(
                        status.HTTP_409_CONFLICT
                    ),
                    detail=(
                        "当前会话存在等待审批的"
                        "操作，请先批准或拒绝"
                        "该操作。"
                    ),
                )

            # 只有确认不是人工审批中断后，
            # 才允许使用旧的自动恢复机制。
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

            # 本次执行可能刚刚触发
            # interrupt()，必须检查结果。
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

    # 必须单独保留HTTPException，
    # 否则409会被转换成500。
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
    graph, graph_lock = (
        _get_graph_dependencies(request)
    )

    # StreamingResponse开始发送后，
    # 已经无法再可靠修改HTTP状态码。
    # 因此会话元数据应在创建响应前登记。
    _record_conversation(
        request=request,
        thread_id=payload.thread_id,
        message=payload.message,
    )

    event_iterator = stream_chat_events(
        graph=graph,
        graph_lock=graph_lock,
        message=payload.message,
        thread_id=payload.thread_id,
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
    graph, graph_lock = (
        _get_graph_dependencies(request)
    )

    config = {
        "configurable": {
            "thread_id": payload.thread_id,
        }
    }

    try:
        # 审批属于会话中的一次交互，
        # 因此刷新会话的最近使用时间。
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

            # 一次请求可能涉及多个危险工具，
            # 恢复一个后仍可能出现下一个审批。
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
    """读取FastAPI生命周期中创建的Graph。"""

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
    """
    创建新会话元数据或刷新已有会话时间。

    第一次消息会成为默认标题；
    后续消息只更新updated_at。
    """

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

    # 现有FakeGraph测试不会注入
    # ConversationRepository和Settings。
    # 为了不破坏原有测试，缺少测试依赖时跳过。
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
    """
    刷新审批恢复后的会话时间。

    touch不会创建一个不存在的会话。
    """

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