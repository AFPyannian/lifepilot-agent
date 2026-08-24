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
from app.exceptions import LifePilotError


logger = logging.getLogger(
    "lifepilot.api.streaming"
)


def create_sse_event(
    event: str,
    data: Mapping[str, Any],
) -> str:
    """把事件名称和数据编码成 SSE 格式。"""

    json_data = json.dumps(
        dict(data),
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return (
        f"event: {event}\n"
        f"data: {json_data}\n\n"
    )


def stream_chat_events(
    graph: Any,
    graph_lock: Any,
    message: str,
    thread_id: str,
) -> Iterator[str]:
    """执行 Agent 并生成 SSE 事件。"""

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    yield create_sse_event(
        event="start",
        data={
            "thread_id": thread_id,
        },
    )

    try:
        approval_request: (
            dict[str, Any] | None
        ) = None

        with graph_lock:
            # 先检查是否存在人工审批中断。
            # 这种状态不能调用 invoke(None)。
            pending_interrupt = (
                find_pending_interrupt(
                    graph=graph,
                    config=config,
                )
            )

            if pending_interrupt is not None:
                approval_request = (
                    normalize_approval_request(
                        pending_interrupt
                    )
                )

            else:
                # 只有确认不是人工审批后，
                # 才恢复普通未完成节点。
                resume_pending_execution(
                    graph=graph,
                    config=config,
                )

                stream = graph.stream(
                    {
                        "messages": [
                            HumanMessage(
                                content=message
                            )
                        ]
                    },
                    config=config,
                    stream_mode="messages",
                    version="v2",
                )

                for part in stream:
                    if (
                        part.get("type")
                        != "messages"
                    ):
                        continue

                    stream_data = part.get(
                        "data"
                    )

                    if (
                        not isinstance(
                            stream_data,
                            tuple,
                        )
                        or len(stream_data) != 2
                    ):
                        continue

                    message_chunk, metadata = (
                        stream_data
                    )

                    if not isinstance(
                        metadata,
                        dict,
                    ):
                        continue

                    if (
                        metadata.get(
                            "langgraph_node"
                        )
                        != "assistant"
                    ):
                        continue

                    content = getattr(
                        message_chunk,
                        "content",
                        "",
                    )

                    text = _extract_stream_text(
                        content
                    )

                    if text:
                        yield create_sse_event(
                            event="token",
                            data={
                                "content": text,
                            },
                        )

                # messages流本身不会作为普通文本
                # 返回审批内容，所以执行后查询状态。
                pending_interrupt = (
                    find_pending_interrupt(
                        graph=graph,
                        config=config,
                    )
                )

                if pending_interrupt is not None:
                    approval_request = (
                        normalize_approval_request(
                            pending_interrupt
                        )
                    )

        if approval_request is not None:
            logger.info(
                "Agent approval required "
                "thread_id=%s tool=%s",
                thread_id,
                approval_request.get(
                    "tool_name"
                ),
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
            "Agent stream completed "
            "thread_id=%s",
            thread_id,
        )

        yield create_sse_event(
            event="done",
            data={
                "thread_id": thread_id,
            },
        )

    except LifePilotError as error:
        logger.exception(
            "Expected Agent stream error "
            "thread_id=%s",
            thread_id,
        )

        yield create_sse_event(
            event="error",
            data={
                "message": error.user_message,
            },
        )

    except Exception:
        logger.exception(
            "Unexpected Agent stream error "
            "thread_id=%s",
            thread_id,
        )

        yield create_sse_event(
            event="error",
            data={
                "message": (
                    "LifePilot 生成回答时"
                    "发生内部错误。"
                ),
            },
        )


def _extract_stream_text(
    content: Any,
) -> str:
    """从模型消息块中提取可展示文本。"""

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