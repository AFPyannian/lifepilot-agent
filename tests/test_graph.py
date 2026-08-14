from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)
from langgraph.checkpoint.memory import InMemorySaver

from app.graph import build_graph


class FakeChatModel:
    """A deterministic model used only in tests."""

    def invoke(self, messages):
        human_messages = [
            message
            for message in messages
            if isinstance(message, HumanMessage)
        ]

        return AIMessage(
            content=(
                f"已处理第 "
                f"{len(human_messages)} "
                f"条用户消息"
            )
        )


def build_test_graph():
    """Create a graph without calling a real API."""
    return build_graph(
        model=FakeChatModel(),
        checkpointer=InMemorySaver(),
    )


def test_graph_returns_ai_response():
    graph = build_test_graph()

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
    assert (
        result["messages"][-1].content
        == "已处理第 1 条用户消息"
    )


def test_same_thread_keeps_history():
    graph = build_test_graph()

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
    assert (
        result["messages"][-1].content
        == "已处理第 2 条用户消息"
    )


def test_different_threads_are_isolated():
    graph = build_test_graph()

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
    assert (
        result["messages"][-1].content
        == "已处理第 1 条用户消息"
    )