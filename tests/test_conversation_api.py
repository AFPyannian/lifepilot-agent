"""验证历史会话管理接口。"""

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.api.server import create_app
from app.repositories.conversation_repository import (
    ConversationRepository,
)


class FakeCheckpointer:
    """记录线程删除调用的测试 Checkpointer。"""

    def __init__(self) -> None:
        self.deleted_thread_ids: list[str] = []

    def delete_thread(
        self,
        thread_id: str,
    ) -> None:
        self.deleted_thread_ids.append(thread_id)


class FakeConversationGraph:
    """提供可控会话状态的测试图。"""

    def __init__(
        self,
        messages: (list[Any] | None) = None,
        pending_approval: (dict[str, Any] | None) = None,
        checkpointer: (FakeCheckpointer | None) = None,
    ) -> None:
        self.messages = messages if messages is not None else []

        self.pending_approval = pending_approval

        self.checkpointer = checkpointer

        self.last_config: dict[str, Any] | None = None

    def get_state(
        self,
        config: dict[str, Any],
    ) -> SimpleNamespace:
        self.last_config = config

        tasks = ()

        if self.pending_approval is not None:
            tasks = (
                SimpleNamespace(
                    interrupts=(SimpleNamespace(value=(self.pending_approval)),)
                ),
            )

        return SimpleNamespace(
            values={
                "messages": self.messages,
            },
            next=(("tools",) if tasks else ()),
            tasks=tasks,
        )


def create_repository(
    tmp_path,
) -> ConversationRepository:
    return ConversationRepository(tmp_path / "application.db")


def create_test_app(
    repository: ConversationRepository,
    graph: FakeConversationGraph,
):
    settings = SimpleNamespace(owner_id="owner-1")

    return create_app(
        agent_graph=graph,
        settings=settings,
        conversation_repository=(repository),
    )


def test_list_conversations_only_returns_current_owner(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="我的会话",
    )

    repository.record_message(
        owner_id="owner-2",
        thread_id="thread-2",
        first_message="其他用户的会话",
    )

    graph = FakeConversationGraph()

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations")

    assert response.status_code == 200

    response_data = response.json()

    assert len(response_data["conversations"]) == 1

    conversation = response_data["conversations"][0]

    assert conversation["thread_id"] == "thread-1"

    assert conversation["title"] == "我的会话"

    assert "created_at" in conversation
    assert "updated_at" in conversation


def test_get_conversation_restores_messages_and_approval(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="删除待办测试",
    )

    approval_request = {
        "kind": "tool_approval",
        "tool_name": "delete_todo",
        "message": ("是否确认删除这个待办事项？"),
        "arguments": {
            "todo_id": 1,
        },
    }

    graph = FakeConversationGraph(
        messages=[
            SystemMessage(content="内部系统消息"),
            HumanMessage(content="删除待办1"),
            AIMessage(content="我准备删除该待办。"),
            ToolMessage(
                content="内部工具结果",
                tool_call_id="call-1",
            ),
        ],
        pending_approval=(approval_request),
    )

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations/thread-1")

    assert response.status_code == 200

    response_data = response.json()

    assert response_data["thread_id"] == "thread-1"

    assert response_data["title"] == "删除待办测试"

    assert response_data["messages"] == [
        {
            "role": "user",
            "content": "删除待办1",
        },
        {
            "role": "assistant",
            "content": ("我准备删除该待办。"),
        },
    ]

    assert response_data["pending_approval"] == approval_request

    assert graph.last_config == {
        "configurable": {
            "thread_id": "thread-1",
        }
    }


def test_get_missing_conversation_returns_404(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    graph = FakeConversationGraph()

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations/missing-thread")

    assert response.status_code == 404

    assert response.json() == {"detail": "会话不存在。"}


def test_conversation_rejects_invalid_thread_id(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    graph = FakeConversationGraph()

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/conversations/invalid%20thread")

    assert response.status_code == 422


def test_rename_conversation(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="旧标题",
    )

    graph = FakeConversationGraph()

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.patch(
            ("/api/v1/conversations/thread-1"),
            json={"title": ("  LangGraph   学习会话  ")},
        )

    assert response.status_code == 200

    response_data = response.json()

    assert response_data["thread_id"] == "thread-1"

    assert response_data["title"] == "LangGraph 学习会话"

    stored_conversation = repository.get(
        owner_id="owner-1",
        thread_id="thread-1",
    )

    assert stored_conversation is not None

    assert stored_conversation.title == "LangGraph 学习会话"


def test_rename_missing_conversation_returns_404(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    graph = FakeConversationGraph()

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.patch(
            ("/api/v1/conversations/missing-thread"),
            json={
                "title": "新标题",
            },
        )

    assert response.status_code == 404


def test_delete_conversation_removes_metadata_and_checkpoints(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="准备删除的会话",
    )

    checkpointer = FakeCheckpointer()

    graph = FakeConversationGraph(checkpointer=checkpointer)

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.delete("/api/v1/conversations/thread-1")

    assert response.status_code == 200

    assert response.json() == {
        "thread_id": "thread-1",
        "deleted": True,
    }

    assert checkpointer.deleted_thread_ids == ["thread-1"]

    assert (
        repository.get(
            owner_id="owner-1",
            thread_id="thread-1",
        )
        is None
    )


def test_owner_cannot_delete_other_owner_checkpoint(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    repository.record_message(
        owner_id="owner-2",
        thread_id="private-thread",
        first_message="其他用户的会话",
    )

    checkpointer = FakeCheckpointer()

    graph = FakeConversationGraph(checkpointer=checkpointer)

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.delete("/api/v1/conversations/private-thread")

    assert response.status_code == 200

    assert response.json() == {
        "thread_id": "private-thread",
        "deleted": False,
    }

    assert checkpointer.deleted_thread_ids == []

    assert (
        repository.get(
            owner_id="owner-2",
            thread_id="private-thread",
        )
        is not None
    )


def test_delete_requires_checkpointer(
    tmp_path,
) -> None:
    repository = create_repository(tmp_path)

    repository.record_message(
        owner_id="owner-1",
        thread_id="thread-1",
        first_message="测试会话",
    )

    graph = FakeConversationGraph(checkpointer=None)

    app = create_test_app(
        repository=repository,
        graph=graph,
    )

    with TestClient(app) as client:
        response = client.delete("/api/v1/conversations/thread-1")

    assert response.status_code == 503

    assert response.json() == {"detail": ("Checkpoint服务不可用。")}

    assert (
        repository.get(
            owner_id="owner-1",
            thread_id="thread-1",
        )
        is not None
    )
