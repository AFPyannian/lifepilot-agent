"""构造 LangGraph 与 LangSmith 共用的运行配置。"""


from typing import Any

from fastapi import Request


def build_run_config(
    request: Request,
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

    owner_id = getattr(
        settings,
        "owner_id",
        "unknown",
    )

    return {
        "configurable": {
            "thread_id": thread_id,
        },
        "run_name": (
            f"lifepilot_{operation}"
        ),
        "tags": [
            "lifepilot",
            "fastapi",
            environment,
            operation,
        ],
        "metadata": {
            "request_id": request_id,
            "thread_id": thread_id,
            "owner_id": owner_id,
            "environment": environment,
            "operation": operation,
        },
    }