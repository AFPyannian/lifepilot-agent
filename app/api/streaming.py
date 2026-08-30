"""将 LangGraph 流式事件转换为 SSE 响应。"""

import json
import logging
from collections.abc import (
    Iterator,
    Mapping,
)
from typing import Any

from langchain_core.messages import (
    HumanMessage,
)

from app.api.execution import (
    resume_pending_execution,
)
from app.api.interrupts import (
    find_pending_interrupt,
    normalize_approval_request,
)
from app.credentials.errors import CredentialError
from app.exceptions import LifePilotError, ModelServiceError
from app.identity import AgentContext
from app.locks import execution_scope

logger = logging.getLogger("lifepilot.api.streaming")


def create_sse_event(
    event: str,
    data: Mapping[str, Any],
) -> str:
    """将事件名称和数据编码为一条 SSE 消息。"""

    json_data = json.dumps(
        dict(data),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return f"event: {event}\ndata: {json_data}\n\n"


def stream_chat_events(
    graph: Any,
    graph_lock: Any,
    message: str,
    thread_id: str,
    config: dict[str, Any],
    context: AgentContext,
    model_mode: str = "PLATFORM",
) -> Iterator[str]:
    """执行 Agent 并依次产生开始、文本、审批、完成或错误事件。"""

    yield create_sse_event(
        event="start",
        data={
            "thread_id": thread_id,
        },
    )

    try:
        approval_request: dict[str, Any] | None = None

        with execution_scope(graph_lock, context.user_id, thread_id):
            pending_interrupt = find_pending_interrupt(
                graph=graph,
                config=config,
            )

            if pending_interrupt is not None:
                approval_request = normalize_approval_request(pending_interrupt)

            else:
                resume_pending_execution(
                    graph=graph,
                    config=config,
                    context=context,
                )

                stream = graph.stream(
                    {
                        "messages": [HumanMessage(content=message)],
                        "model_mode": model_mode,
                    },
                    config=config,
                    context=context,
                    stream_mode="messages",
                    version="v2",
                )

                for part in stream:
                    if part.get("type") != "messages":
                        continue

                    stream_data = part.get("data")

                    if (
                        not isinstance(
                            stream_data,
                            tuple,
                        )
                        or len(stream_data) != 2
                    ):
                        continue

                    message_chunk, metadata = stream_data

                    if not isinstance(
                        metadata,
                        dict,
                    ):
                        continue

                    if metadata.get("langgraph_node") != "assistant":
                        continue

                    content = getattr(
                        message_chunk,
                        "content",
                        "",
                    )

                    text = _extract_stream_text(content)

                    if text:
                        yield create_sse_event(
                            event="token",
                            data={
                                "content": text,
                            },
                        )

                pending_interrupt = find_pending_interrupt(
                    graph=graph,
                    config=config,
                )

                if pending_interrupt is not None:
                    approval_request = normalize_approval_request(pending_interrupt)

        if approval_request is not None:
            logger.info(
                "Agent approval required thread_id=%s tool=%s",
                thread_id,
                approval_request.get("tool_name"),
            )

            yield create_sse_event(
                event="approval_required",
                data={
                    "thread_id": thread_id,
                    "request": approval_request,
                },
            )

            return

        logger.info(
            "Agent stream completed thread_id=%s",
            thread_id,
        )

        yield create_sse_event(
            event="done",
            data={
                "thread_id": thread_id,
            },
        )

    except (CredentialError, ModelServiceError) as error:
        logger.warning(
            "Sensitive Agent stream error thread_id=%s error_type=%s",
            thread_id,
            type(error).__name__,
        )

        yield create_sse_event(
            event="error",
            data={
                "message": error.user_message,
            },
        )

    except LifePilotError as error:
        logger.exception("Expected Agent stream error thread_id=%s", thread_id)

        yield create_sse_event(
            event="error",
            data={"message": error.user_message},
        )

    except Exception:
        logger.exception(
            "Unexpected Agent stream error thread_id=%s",
            thread_id,
        )

        yield create_sse_event(
            event="error",
            data={
                "message": ("LifePilot 生成回答时发生内部错误。"),
            },
        )


def _extract_stream_text(
    content: Any,
) -> str:
    """从 LangGraph 消息事件中提取可展示文本。"""

    if isinstance(content, str):
        return content

    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []

    for block in content:
        if isinstance(block, str):
            text_parts.append(block)
            continue

        if isinstance(block, dict):
            text = block.get("text")

            if isinstance(text, str):
                text_parts.append(text)

    return "".join(text_parts)
