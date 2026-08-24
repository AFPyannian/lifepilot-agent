import httpx
import pytest

from app.clients import (
    ApprovalRequired,
    LifePilotApiClient,
    LifePilotApiError,
    iter_sse_events,
)


def test_iter_sse_events() -> None:
    lines = [
        "event: start",
        'data: {"thread_id":"test"}',
        "",
        "event: token",
        'data: {"content":"你好"}',
        "",
        "event: done",
        'data: {"thread_id":"test"}',
        "",
    ]

    assert list(iter_sse_events(lines)) == [
        (
            "start",
            '{"thread_id":"test"}',
        ),
        (
            "token",
            '{"content":"你好"}',
        ),
        (
            "done",
            '{"thread_id":"test"}',
        ),
    ]


def test_sse_parser_supports_comments_and_eof() -> None:
    lines = [
        ": heartbeat",
        "event: example",
        "data: first line",
        "data: second line",
    ]

    assert list(iter_sse_events(lines)) == [
        (
            "example",
            "first line\nsecond line",
        )
    ]


def test_health_check() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert (
            request.url.path
            == "/api/v1/health"
        )

        return httpx.Response(
            status_code=200,
            json={
                "status": "ok",
                "service": (
                    "lifepilot-agent"
                ),
            },
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    assert client.is_healthy() is True


def test_stream_chat_returns_tokens() -> None:
    sse_body = (
        "event: start\n"
        'data: {"thread_id":"test"}\n'
        "\n"
        "event: token\n"
        'data: {"content":"你"}\n'
        "\n"
        "event: token\n"
        'data: {"content":"好"}\n'
        "\n"
        "event: done\n"
        'data: {"thread_id":"test"}\n'
        "\n"
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert (
            request.url.path
            == "/api/v1/chat/stream"
        )

        return httpx.Response(
            status_code=200,
            headers={
                "content-type": (
                    "text/event-stream; "
                    "charset=utf-8"
                )
            },
            text=sse_body,
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    tokens = list(
        client.stream_chat(
            message="你好",
            thread_id="test",
        )
    )

    assert tokens == ["你", "好"]
    assert "".join(tokens) == "你好"


def test_stream_chat_raises_sse_error() -> None:
    sse_body = (
        "event: start\n"
        'data: {"thread_id":"test"}\n'
        "\n"
        "event: error\n"
        'data: {"message":"模型暂时不可用"}\n'
        "\n"
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={
                "content-type": (
                    "text/event-stream"
                )
            },
            text=sse_body,
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    with pytest.raises(
        LifePilotApiError,
        match="模型暂时不可用",
    ):
        list(
            client.stream_chat(
                message="你好",
                thread_id="test",
            )
        )


def test_stream_chat_detects_incomplete_stream() -> None:
    sse_body = (
        "event: start\n"
        'data: {"thread_id":"test"}\n'
        "\n"
        "event: token\n"
        'data: {"content":"部分回答"}\n'
        "\n"
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={
                "content-type": (
                    "text/event-stream"
                )
            },
            text=sse_body,
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    with pytest.raises(
        LifePilotApiError,
        match="流式连接意外中断",
    ):
        list(
            client.stream_chat(
                message="你好",
                thread_id="test",
            )
        )


def test_http_error_uses_safe_detail() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=503,
            json={
                "detail": "模型服务暂时不可用。"
            },
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    with pytest.raises(
        LifePilotApiError,
        match="模型服务暂时不可用",
    ):
        list(
            client.stream_chat(
                message="你好",
                thread_id="test",
            )
        )


def test_upload_document() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert (
            request.url.path
            == "/api/v1/knowledge/documents"
        )

        assert request.method == "POST"

        content_type = request.headers[
            "content-type"
        ]

        assert content_type.startswith(
            "multipart/form-data"
        )

        return httpx.Response(
            status_code=200,
            json={
                "filename": "guide.md",
                "chunk_count": 2,
                "already_indexed": False,
            },
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    result = client.upload_document(
        filename="guide.md",
        content=b"# Guide",
        content_type="text/markdown",
    )

    assert result["filename"] == "guide.md"
    assert result["chunk_count"] == 2


def test_list_documents() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "documents": [
                    {
                        "filename": (
                            "guide.md"
                        ),
                        "chunk_count": 2,
                    }
                ]
            },
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    assert client.list_documents() == [
        {
            "filename": "guide.md",
            "chunk_count": 2,
        }
    ]


def test_delete_document_encodes_filename() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert request.method == "DELETE"

        assert (
            b"%E5%AD%A6%E4%B9%A0.md"
            in request.url.raw_path
        )

        return httpx.Response(
            status_code=200,
            json={
                "filename": "学习.md",
                "deleted": True,
            },
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    assert (
        client.delete_document(
            "学习.md"
        )
        is True
    )


def test_stream_chat_requires_approval() -> None:
    sse_body = (
        "event: start\n"
        'data: {"thread_id":"test"}\n'
        "\n"
        "event: approval_required\n"
        'data: {"thread_id":"test",'
        '"request":{"tool_name":"delete_todo",'
        '"message":"确认删除？",'
        '"arguments":{"todo_id":1}}}\n'
        "\n"
    )

    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            headers={
                "content-type": (
                    "text/event-stream"
                )
            },
            text=sse_body,
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    with pytest.raises(
        ApprovalRequired
    ) as error_info:
        list(
            client.stream_chat(
                message="删除待办1",
                thread_id="test",
            )
        )

    assert (
        error_info.value.request[
            "tool_name"
        ]
        == "delete_todo"
    )


def test_resume_chat() -> None:
    def handler(
        request: httpx.Request,
    ) -> httpx.Response:
        assert (
            request.url.path
            == "/api/v1/chat/resume"
        )

        return httpx.Response(
            status_code=200,
            json={
                "status": "completed",
                "thread_id": "test",
                "reply": "删除操作已经取消。",
                "approval_request": None,
            },
        )

    client = LifePilotApiClient(
        base_url="http://testserver",
        transport=httpx.MockTransport(
            handler
        ),
    )

    reply = client.resume_chat(
        thread_id="test",
        approved=False,
    )

    assert reply == "删除操作已经取消。"