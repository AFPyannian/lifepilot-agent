"""验证 Agent 图构建和消息处理行为。"""

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import build_graph
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
    """提供仅用于图测试的确定性模型。"""

    def bind_tools(self, tools):
        """接收并保存图绑定的工具。"""
        return self

    def invoke(self, messages):
        """返回预设消息或基于输入生成测试回答。"""
        human_messages = [
            message for message in messages if isinstance(message, HumanMessage)
        ]

        return AIMessage(content=(f"已处理第 {len(human_messages)} 条用户消息"))


def build_test_graph(tmp_path):
    """构建不访问真实模型和知识库的测试图。"""
    database_path = tmp_path / "application.db"

    return build_graph(
        model=FakeChatModel(),
        checkpointer=InMemorySaver(),
        todo_repository=TodoRepository(database_path),
        note_repository=NoteRepository(database_path),
        memory_repository=UserMemoryRepository(database_path),
        owner_id="test-user",
    )


def test_graph_returns_ai_response(tmp_path):
    graph = build_test_graph(tmp_path)

    config = {
        "configurable": {
            "thread_id": "response-test",
        }
    }

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="你好"),
            ],
        },
        config=config,
    )

    assert len(result["messages"]) == 2
    assert isinstance(
        result["messages"][-1],
        AIMessage,
    )
    assert result["messages"][-1].content == "已处理第 1 条用户消息"


def test_same_thread_keeps_history(tmp_path):
    graph = build_test_graph(tmp_path)

    config = {
        "configurable": {
            "thread_id": "same-thread",
        }
    }

    graph.invoke(
        {
            "messages": [
                HumanMessage(content="第一条"),
            ],
        },
        config=config,
    )

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="第二条"),
            ],
        },
        config=config,
    )

    assert len(result["messages"]) == 4
    assert result["messages"][-1].content == "已处理第 2 条用户消息"


def test_different_threads_are_isolated(tmp_path):
    graph = build_test_graph(tmp_path)

    first_config = {
        "configurable": {
            "thread_id": "thread-one",
        }
    }
    second_config = {
        "configurable": {
            "thread_id": "thread-two",
        }
    }

    graph.invoke(
        {
            "messages": [
                HumanMessage(content="线程一消息"),
            ],
        },
        config=first_config,
    )

    result = graph.invoke(
        {
            "messages": [
                HumanMessage(content="线程二消息"),
            ],
        },
        config=second_config,
    )

    assert len(result["messages"]) == 2
    assert result["messages"][-1].content == "已处理第 1 条用户消息"
