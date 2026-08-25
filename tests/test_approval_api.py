from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.api.server import create_app


class FakeApprovalGraph:
    def __init__(
        self,
        pending: bool = True,
    ) -> None:
        self.pending = pending

        self.request = {
            "kind": "tool_approval",
            "tool_name": "delete_todo",
            "message": (
                "是否确认删除这个待办事项？"
            ),
            "arguments": {
                "todo_id": 1,
            },
        }

        self.last_command: (
            Command | None
        ) = None

        self.last_config: (
            dict[str, Any] | None
        ) = None

    def get_state(
        self,
        config: dict[str, Any],
    ) -> SimpleNamespace:
        tasks = ()

        if self.pending:
            tasks = (
                SimpleNamespace(
                    interrupts=(
                        SimpleNamespace(
                            value=self.request
                        ),
                    )
                ),
            )

        return SimpleNamespace(
            next=(
                ("tools",)
                if self.pending
                else ()
            ),
            tasks=tasks,
        )

    def invoke(
        self,
        command: Command,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        assert isinstance(
            command,
            Command,
        )

        self.last_command = command
        self.last_config = config
        self.pending = False

        approved = bool(
            command.resume["approved"]
        )

        reply = (
            "删除操作已经执行。"
            if approved
            else "删除操作已经取消。"
        )

        return {
            "messages": [
                AIMessage(
                    content=reply
                )
            ]
        }


def test_resume_approved_operation() -> None:
    graph = FakeApprovalGraph()

    app = create_app(
        agent_graph=graph
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/resume",
            json={
                "thread_id": "approval-test",
                "approved": True,
            },
        )

    assert response.status_code == 200

    assert response.json() == {
        "status": "completed",
        "thread_id": "approval-test",
        "reply": "删除操作已经执行。",
        "approval_request": None,
    }

    assert graph.pending is False

    assert (
            graph.last_config[
                "configurable"
            ]
            == {
                "thread_id": "approval-test",
            }
    )

    assert (
            graph.last_config["run_name"]
            == "lifepilot_resume_approval"
    )

    assert (
        graph.last_config[
            "metadata"
        ]["request_id"]
    )


def test_resume_rejected_operation() -> None:
    graph = FakeApprovalGraph()

    app = create_app(
        agent_graph=graph
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/resume",
            json={
                "thread_id": "approval-test",
                "approved": False,
            },
        )

    assert response.status_code == 200
    assert "取消" in response.json()["reply"]


def test_resume_requires_pending_operation() -> None:
    graph = FakeApprovalGraph(
        pending=False
    )

    app = create_app(
        agent_graph=graph
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat/resume",
            json={
                "thread_id": "approval-test",
                "approved": True,
            },
        )

    assert response.status_code == 409