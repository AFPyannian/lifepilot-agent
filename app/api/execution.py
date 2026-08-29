"""封装 LangGraph 执行恢复和回答提取逻辑。"""

import logging
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
)

from app.identity import AgentContext

logger = logging.getLogger("lifepilot.api.execution")


def resume_pending_execution(
    graph: Any,
    config: dict[str, Any],
    context: AgentContext,
) -> None:
    """不追加用户消息，直接恢复会话中未完成的普通节点。"""

    snapshot = graph.get_state(config)

    if not snapshot.next:
        return

    logger.warning(
        "Pending Agent execution detected next_nodes=%s",
        snapshot.next,
    )

    graph.invoke(
        None,
        config=config,
        context=context,
    )

    resumed_snapshot = graph.get_state(config)

    if resumed_snapshot.next:
        raise RuntimeError("恢复执行后仍然存在未完成节点")


def extract_latest_ai_reply(
    messages: Sequence[BaseMessage],
) -> str:
    """从执行结果中提取最后一条非空模型文本。"""

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

            combined_text = "".join(text_parts).strip()

            if combined_text:
                return combined_text

    raise RuntimeError("Agent 没有返回有效的 AI 消息")
