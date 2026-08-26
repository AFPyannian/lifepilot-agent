"""验证 SSE 事件编码和流式输出。"""


from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
)

from app.api.server import create_app
from app.api.streaming import (
    create_sse_event,
)


class FakeStreamingGraph:
    """提供可控事件序列的流式测试图。"""

    def __init__(
        self,
        pending: bool = False,
        fail: bool = False,
    ) -> None:
        self.pending = pending
        self.fail = fail
        self.resume_count = 0

        self.last_input: (
            dict[str, Any] | None
        ) = None

        self.last_config: (
            dict[str, Any] | None
        ) = None

        self.last_stream_mode: (
            str | None
        ) = None

        self.last_version: (
            str | None
        ) = None

    def get_state(
        self,
        config: dict[str, Any],
    ) -> SimpleNamespace:
        return SimpleNamespace(
            next=(
                ("tools",)
                if self.pending
                else ()
            )
        )

    def invoke(
        self,
        input_data: dict[str, Any] | None,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if input_data is None:
            self.pending = False
            self.resume_count += 1

            return {
                "messages": [
                    AIMessage(
                        content="恢复完成"
                    )
                ]
            }

        raise AssertionError(
            "流式接口不应调用普通 invoke"
        )

    def stream(
        self,
        input_data: dict[str, Any],
        config: dict[str, Any],
        *,
        stream_mode: str,
        version: str,
    ):
        self.last_input = input_data
        self.last_config = config
        self.last_stream_mode = stream_mode
        self.last_version = version

        if self.fail:
            raise RuntimeError(
                "不应发送给客户端的内部错误"
            )

        yield {
            "type": "messages",
            "ns": (),
            "data": (
                AIMessageChunk(
                    content="不应显示"
                ),
                {
                    "langgraph_node": "tools"
                },
            ),
        }

        for token in [
            "这是",
            "流式",
            "回答。",
        ]:
            yield {
                "type": "messages",
                "ns": (),
                "data": (
                    AIMessageChunk(
                        content=token
                    ),
                    {
                        "langgraph_node": (
                            "assistant"
                        )
                    },
                ),
            }


def read_stream_response(
    graph: FakeStreamingGraph,
) -> tuple[int, str, str]:
    app = create_app(
        agent_graph=graph
    )

    with TestClient(app) as client:
        with client.stream(
            method="POST",
            url="/api/v1/chat/stream",
            json={
                "message": "你好",
                "thread_id": "stream-test",
            },
        ) as response:
            body = "".join(
                response.iter_text()
            )

            return (
                response.status_code,
                response.headers[
                    "content-type"
                ],
                body,
            )


def test_create_sse_event() -> None:
    event = create_sse_event(
        event="token",
        data={
            "content": "你好\n世界",
        },
    )

    assert event == (
        "event: token\n"
        'data: {"content":"你好\\n世界"}\n'
        "\n"
    )


def test_stream_chat_endpoint() -> None:
    graph = FakeStreamingGraph()

    status_code, content_type, body = (
        read_stream_response(
            graph=graph,
        )
    )

    assert status_code == 200

    assert content_type.startswith(
        "text/event-stream"
    )

    assert (
        'event: start\n'
        'data: {"thread_id":"stream-test"}'
        in body
    )

    assert (
        'event: token\n'
        'data: {"content":"这是"}'
        in body
    )

    assert (
        'event: token\n'
        'data: {"content":"流式"}'
        in body
    )

    assert (
        'event: done\n'
        'data: {"thread_id":"stream-test"}'
        in body
    )

    assert "不应显示" not in body
    assert graph.last_stream_mode == "messages"
    assert graph.last_version == "v2"


def test_stream_resumes_pending_execution() -> None:
    graph = FakeStreamingGraph(
        pending=True
    )

    _, _, body = read_stream_response(
        graph=graph,
    )

    assert graph.resume_count == 1
    assert graph.pending is False
    assert "event: done" in body


def test_stream_returns_safe_error_event() -> None:
    graph = FakeStreamingGraph(
        fail=True
    )

    status_code, _, body = (
        read_stream_response(
            graph=graph,
        )
    )


    assert status_code == 200

    assert "event: error" in body

    assert (
        "LifePilot 生成回答时发生内部错误"
        in body
    )

    assert (
        "不应发送给客户端的内部错误"
        not in body
    )

    assert "event: done" not in body
