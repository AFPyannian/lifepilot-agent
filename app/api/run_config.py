"""构造 LangGraph 与 LangSmith 共用的运行配置。"""

from typing import Any

from fastapi import Request

from app.identity import checkpoint_thread_id


def build_run_config(
    request: Request,
    user_id: str,
    thread_id: str,
    operation: str,
) -> dict[str, Any]:
    """构造 Checkpoint、追踪标签和请求元数据配置。"""

    settings = getattr(
        request.app.state,
        "settings",
        None,
    )

    request_id = getattr(
        request.state,
        "request_id",
        "unknown",
    )

    environment = getattr(
        settings,
        "app_environment",
        "test",
    )

    return {
        "configurable": {
            "thread_id": checkpoint_thread_id(
                user_id,
                thread_id,
            ),
            "user_id": user_id,
        },
        "recursion_limit": getattr(
            settings,
            "agent_recursion_limit",
            25,
        ),
        "run_name": (f"lifepilot_{operation}"),
        "tags": [
            "lifepilot",
            "fastapi",
            environment,
            operation,
        ],
        "metadata": {
            "request_id": request_id,
            "thread_id": thread_id,
            "user_id": user_id,
            "environment": environment,
            "operation": operation,
        },
    }
