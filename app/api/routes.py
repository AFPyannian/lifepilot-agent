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

from app.api.execution import (
    extract_latest_ai_reply,
    resume_pending_execution,
)
from app.api.schemas import (
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
        with graph_lock:
            resume_pending_execution(
                graph=graph,
                config=config,
            )

            result = graph.invoke(
                {
                    "messages": [
                        HumanMessage(
                            content=payload.message
                        )
                    ]
                },
                config=config,
            )

        reply = extract_latest_ai_reply(
            result.get("messages", [])
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


def _get_graph_dependencies(
    request: Request,
) -> tuple[Any, Any]:
    """读取 FastAPI 生命周期中创建的 Graph。"""

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

    if graph is None or graph_lock is None:
        raise HTTPException(
            status_code=(
                status
                .HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail="LifePilot 尚未完成初始化。",
        )

    return graph, graph_lock