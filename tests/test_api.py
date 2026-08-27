"""验证聊天与健康检查 API。"""

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.api.server import create_app


class FakeGraph:
    """模拟聊天、恢复和失败状态的测试图。"""

    def __init__(
        self,
        pending: bool = False,
        fail: bool = False,
    ) -> None:
        self.pending = pending
        self.fail = fail

        self.last_input: dict[str, Any] | None = None

        self.last_config: dict[str, Any] | None = None

        self.resume_count = 0

    def get_state(
        self,
        config: dict[str, Any],
    ) -> SimpleNamespace:
        next_nodes = ("tools",) if self.pending else ()

        return SimpleNamespace(next=next_nodes)

    def invoke(
        self,
        input_data: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self.last_config = config

        if input_data is None:
            self.pending = False
            self.resume_count += 1

            return {"messages": [AIMessage(content="旧任务恢复完成。")]}

        if self.fail:
            raise RuntimeError("不应返回给客户端的内部错误")

        self.last_input = input_data

        return {
            "messages": [
                *input_data["messages"],
                AIMessage(content="这是测试回答。"),
            ]
        }


def test_health_check() -> None:
    app = create_app(agent_graph=FakeGraph())

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "lifepilot-agent",
    }


def test_chat_endpoint() -> None:
    fake_graph = FakeGraph()

    app = create_app(agent_graph=fake_graph)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "你好",
                "thread_id": "test-thread-001",
            },
        )

    assert response.status_code == 200

    assert response.json() == {
        "reply": "这是测试回答。",
        "thread_id": "test-thread-001",
    }

    assert fake_graph.last_config["configurable"] == {
        "thread_id": "test-thread-001",
    }

    assert fake_graph.last_config["run_name"] == "lifepilot_chat"

    assert fake_graph.last_config["metadata"]["thread_id"] == "test-thread-001"

    assert fake_graph.last_config["metadata"]["request_id"]


def test_chat_strips_message() -> None:
    fake_graph = FakeGraph()

    app = create_app(agent_graph=fake_graph)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "  你好  ",
                "thread_id": "test-thread",
            },
        )

    assert response.status_code == 200

    assert fake_graph.last_input["messages"][0].content == "你好"


def test_chat_rejects_blank_message() -> None:
    app = create_app(agent_graph=FakeGraph())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "   ",
                "thread_id": "test-thread",
            },
        )

    assert response.status_code == 422


def test_chat_rejects_invalid_thread_id() -> None:
    app = create_app(agent_graph=FakeGraph())

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "你好",
                "thread_id": "../unsafe",
            },
        )

    assert response.status_code == 422


def test_pending_execution_is_resumed() -> None:
    fake_graph = FakeGraph(pending=True)

    app = create_app(agent_graph=fake_graph)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "继续处理",
                "thread_id": "recovery-test",
            },
        )

    assert response.status_code == 200
    assert fake_graph.resume_count == 1
    assert fake_graph.pending is False


def test_internal_error_is_hidden() -> None:
    app = create_app(agent_graph=FakeGraph(fail=True))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "触发错误",
                "thread_id": "error-test",
            },
        )

    assert response.status_code == 500

    assert response.json() == {"detail": ("LifePilot 处理请求时发生内部错误。")}

    assert "不应返回给客户端的内部错误" not in response.text
