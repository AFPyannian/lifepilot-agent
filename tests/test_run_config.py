"""验证 LangGraph 运行配置元数据。"""

from types import SimpleNamespace

from app.api.run_config import (
    build_run_config,
)


def test_build_run_config() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    app_environment=("development"),
                    agent_recursion_limit=40,
                )
            )
        ),
        state=SimpleNamespace(request_id="request-001"),
    )

    config = build_run_config(
        request=request,
        user_id="test-user",
        thread_id="thread-001",
        operation="stream_chat",
    )

    assert config["configurable"] == {
        "thread_id": "user:test-user:thread:thread-001",
        "user_id": "test-user",
    }

    assert config["recursion_limit"] == 40

    assert config["run_name"] == "lifepilot_stream_chat"

    assert "development" in config["tags"]

    assert config["metadata"] == {
        "request_id": "request-001",
        "thread_id": "thread-001",
        "user_id": "test-user",
        "environment": "development",
        "operation": "stream_chat",
    }
