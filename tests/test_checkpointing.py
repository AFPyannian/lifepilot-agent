"""验证 SQLite Checkpointer 的持久化行为。"""

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)
from langgraph.checkpoint.memory import InMemorySaver

from app.checkpointing import (
    open_sqlite_checkpointer,
)
from app.graph import build_graph
from app.identity import AgentContext, checkpoint_config, checkpoint_thread_id
from app.repositories.note_repository import (
    NoteRepository,
)
from app.repositories.todo_repository import (
    TodoRepository,
)
from app.repositories.user_memory_repository import (
    UserMemoryRepository,
)


class FakeChatModel:
    """提供无需外部 API 的确定性测试模型。"""

    def bind_tools(self, tools):
        """接收工具并返回当前测试模型。"""
        return self

    def invoke(self, messages):
        """返回包含用户消息数量的固定回答。"""
        human_messages = [
            message for message in messages if isinstance(message, HumanMessage)
        ]

        return AIMessage(content=(f"已看到 {len(human_messages)} 条用户消息"))


def test_in_memory_checkpointer_still_works(tmp_path):
    application_database_path = tmp_path / "application.db"

    graph = build_graph(
        model=FakeChatModel(),
        checkpointer=InMemorySaver(),
        todo_repository=TodoRepository(application_database_path),
        note_repository=NoteRepository(application_database_path),
        memory_repository=UserMemoryRepository(application_database_path),
    )

    config = checkpoint_config("test-user", "memory-thread")

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="第一条消息"),
            ],
        },
        config=config,
        context=AgentContext(user_id="test-user"),
    )

    assert len(result["messages"]) == 2


def test_sqlite_checkpointer_survives_reopen(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "LANGGRAPH_STRICT_MSGPACK",
        "true",
    )

    checkpoint_path = tmp_path / "checkpoints.db"

    application_database_path = tmp_path / "application.db"

    config = checkpoint_config("test-user", "persistent-thread")

    with open_sqlite_checkpointer(checkpoint_path) as first_checkpointer:
        first_graph = build_graph(
            model=FakeChatModel(),
            checkpointer=first_checkpointer,
            todo_repository=TodoRepository(application_database_path),
            note_repository=NoteRepository(application_database_path),
            memory_repository=UserMemoryRepository(application_database_path),
        )

        first_result = first_graph.invoke(
            {
                "messages": [
                    HumanMessage(content="第一条消息"),
                ],
            },
            config=config,
            context=AgentContext(user_id="test-user"),
        )

        assert len(first_result["messages"]) == 2

    with open_sqlite_checkpointer(checkpoint_path) as second_checkpointer:
        second_graph = build_graph(
            model=FakeChatModel(),
            checkpointer=second_checkpointer,
            todo_repository=TodoRepository(application_database_path),
            note_repository=NoteRepository(application_database_path),
            memory_repository=UserMemoryRepository(application_database_path),
        )

        second_result = second_graph.invoke(
            {
                "messages": [
                    HumanMessage(content="第二条消息"),
                ],
            },
            config=config,
            context=AgentContext(user_id="test-user"),
        )

        assert len(second_result["messages"]) == 4

        assert second_result["messages"][-1].content == "已看到 2 条用户消息"


def test_delete_thread_removes_checkpoints(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "LANGGRAPH_STRICT_MSGPACK",
        "true",
    )

    checkpoint_path = tmp_path / "checkpoints.db"

    application_database_path = tmp_path / "application.db"

    config = checkpoint_config("test-user", "delete-thread")

    with open_sqlite_checkpointer(checkpoint_path) as checkpointer:
        graph = build_graph(
            model=FakeChatModel(),
            checkpointer=checkpointer,
            todo_repository=TodoRepository(application_database_path),
            note_repository=NoteRepository(application_database_path),
            memory_repository=(UserMemoryRepository(application_database_path)),
        )

        graph.invoke(
            {"messages": [HumanMessage(content="测试消息")]},
            config=config,
            context=AgentContext(user_id="test-user"),
        )

        assert graph.get_state(config).values["messages"]

        checkpointer.delete_thread(checkpoint_thread_id("test-user", "delete-thread"))

        empty_snapshot = graph.get_state(config)

        assert empty_snapshot.values.get("messages", []) == []
