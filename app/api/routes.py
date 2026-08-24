import logging
from collections.abc import Sequence
from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
    status,
)
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
)

from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
)
from app.exceptions import LifePilotError


logger = logging.getLogger("lifepilot.api")

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
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LifePilot 尚未完成初始化。",
        )

    config = {
        "configurable": {
            "thread_id": payload.thread_id,
        }
    }

    try:
        # 当前使用单个 SQLite Checkpointer 连接。
        # 检查状态、恢复执行和添加新消息必须放在同一把锁中，
        # 防止多个请求同时操作 Graph。
        with graph_lock:
            _resume_pending_execution(
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

        reply = _extract_latest_ai_reply(
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
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error.user_message,
        ) from error

    except Exception as error:
        logger.exception(
            "Unexpected Agent API error "
            "thread_id=%s",
            payload.thread_id,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LifePilot 处理请求时发生内部错误。",
        ) from error


def _resume_pending_execution(
    graph: Any,
    config: dict[str, Any],
) -> None:
    """恢复当前会话中未完成的 Graph 节点。"""

    snapshot = graph.get_state(config)

    if not snapshot.next:
        return

    logger.warning(
        "Pending Agent execution detected "
        "next_nodes=%s",
        snapshot.next,
    )

    # None 表示不追加新的 HumanMessage，
    # 直接从 Checkpoint 中的未完成节点继续。
    graph.invoke(
        None,
        config=config,
    )

    resumed_snapshot = graph.get_state(config)

    if resumed_snapshot.next:
        raise RuntimeError(
            "恢复执行后仍然存在未完成节点"
        )


def _extract_latest_ai_reply(
    messages: Sequence[BaseMessage],
) -> str:
    """从 Graph 状态中提取最后一条有效 AI 回复。"""

    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue

        content = message.content

        if isinstance(content, str):
            clean_content = content.strip()

            if clean_content:
                return clean_content

        if isinstance(content, list):
            text_parts: list[str] = []

            for block in content:
                if isinstance(block, str):
                    text_parts.append(block)
                    continue

                if isinstance(block, dict):
                    text = block.get("text")

                    if isinstance(text, str):
                        text_parts.append(text)

            combined_text = "".join(
                text_parts
            ).strip()

            if combined_text:
                return combined_text

    raise RuntimeError(
        "Agent 没有返回有效的 AI 消息"
    )