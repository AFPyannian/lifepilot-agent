"""定义多用户 Agent 的可信运行身份。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    """保存单次 Agent 执行所属的服务端用户。"""

    user_id: str


def checkpoint_thread_id(
    user_id: str,
    public_thread_id: str,
) -> str:
    """生成用户隔离的内部 Checkpoint 会话标识。"""
    return f"user:{user_id}:thread:{public_thread_id}"


def checkpoint_config(
    user_id: str,
    public_thread_id: str,
) -> dict[str, dict[str, str]]:
    """构造只包含用户隔离会话标识的 Checkpoint 配置。"""
    return {
        "configurable": {
            "thread_id": checkpoint_thread_id(
                user_id,
                public_thread_id,
            ),
            "user_id": user_id,
        }
    }


def user_id_from_config(config: Mapping[str, Any]) -> str:
    """从服务端运行配置读取并验证用户身份。"""
    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id")

    if not isinstance(user_id, str) or not user_id.strip():
        raise RuntimeError("Agent 运行配置缺少可信用户身份。")

    return user_id
