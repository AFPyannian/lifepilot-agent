import json
from collections.abc import (
    Iterable,
    Iterator,
)
from typing import Any
from urllib.parse import quote

import httpx


class LifePilotApiError(RuntimeError):
    """调用 LifePilot API 失败。"""


class ApprovalRequired(
    LifePilotApiError
):
    """Agent 暂停并等待用户审批。"""

    def __init__(
        self,
        request: dict[str, Any],
    ) -> None:
        super().__init__(
            "操作需要用户审批。"
        )

        self.request = request


def iter_sse_events(
    lines: Iterable[str],
) -> Iterator[tuple[str, str]]:
    """解析 SSE 文本行。"""

    event_name = "message"
    data_lines: list[str] = []

    for raw_line in lines:
        # 兼容 CRLF。
        line = raw_line.rstrip("\r")

        # 空行代表一条事件结束。
        if line == "":
            if data_lines:
                yield (
                    event_name,
                    "\n".join(data_lines),
                )

            event_name = "message"
            data_lines = []
            continue

        # 以冒号开头的是注释或心跳。
        if line.startswith(":"):
            continue

        field, separator, value = (
            line.partition(":")
        )

        if not separator:
            continue

        # SSE规范只忽略冒号后的
        # 第一个空格。
        if value.startswith(" "):
            value = value[1:]

        if field == "event":
            event_name = value

        elif field == "data":
            data_lines.append(value)

    # 连接关闭前没有最后一个空行时，
    # 仍然处理最后一条事件。
    if data_lines:
        yield (
            event_name,
            "\n".join(data_lines),
        )


class LifePilotApiClient:
    """调用 LifePilot FastAPI 后端。"""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 180.0,
        transport: (
            httpx.BaseTransport | None
        ) = None,
    ) -> None:
        clean_base_url = (
            base_url.strip().rstrip("/")
        )

        if not clean_base_url:
            raise ValueError(
                "LifePilot API 地址不能为空。"
            )

        self._base_url = clean_base_url

        self._timeout = httpx.Timeout(
            timeout_seconds,
            connect=10.0,
        )

        # 测试时可注入 MockTransport。
        self._transport = transport

    def is_healthy(self) -> bool:
        """检查 FastAPI 是否可访问。"""

        try:
            with (
                self._create_http_client()
                as client
            ):
                response = client.get(
                    "/api/v1/health"
                )

                response.raise_for_status()
                data = response.json()

            return (
                isinstance(data, dict)
                and data.get("status") == "ok"
            )

        except (
            httpx.HTTPError,
            ValueError,
        ):
            return False

    def upload_document(
        self,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        """上传并导入知识库文档。"""

        return self._request_json(
            method="POST",
            path=(
                "/api/v1/knowledge/documents"
            ),
            files={
                "file": (
                    filename,
                    content,
                    content_type,
                )
            },
        )

    def list_documents(
        self,
    ) -> list[dict[str, Any]]:
        """读取知识库文档列表。"""

        data = self._request_json(
            method="GET",
            path=(
                "/api/v1/knowledge/documents"
            ),
        )

        documents = data.get(
            "documents",
            [],
        )

        if not isinstance(
            documents,
            list,
        ):
            raise LifePilotApiError(
                "知识库列表响应格式不正确。"
            )

        return documents

    def delete_document(
        self,
        filename: str,
    ) -> bool:
        """通过侧边栏直接删除知识库文档。"""

        encoded_filename = quote(
            filename,
            safe="",
        )

        data = self._request_json(
            method="DELETE",
            path=(
                "/api/v1/knowledge/documents/"
                f"{encoded_filename}"
            ),
        )

        return bool(
            data.get("deleted")
        )

    def stream_chat(
        self,
        message: str,
        thread_id: str,
    ) -> Iterator[str]:
        """发送消息并逐段返回 Agent 文本。"""

        try:
            with (
                self._create_http_client()
                as client
            ):
                with client.stream(
                    method="POST",
                    url="/api/v1/chat/stream",
                    json={
                        "message": message,
                        "thread_id": thread_id,
                    },
                ) as response:
                    response.raise_for_status()

                    content_type = (
                        response.headers.get(
                            "content-type",
                            "",
                        )
                    )

                    if (
                        not content_type
                        .lower()
                        .startswith(
                            "text/event-stream"
                        )
                    ):
                        raise LifePilotApiError(
                            "后端没有返回 SSE 流。"
                        )

                    for (
                        event_name,
                        raw_data,
                    ) in iter_sse_events(
                        response.iter_lines()
                    ):
                        data = (
                            self._parse_event_data(
                                raw_data
                            )
                        )

                        if event_name == "start":
                            continue

                        if event_name == "token":
                            content = data.get(
                                "content"
                            )

                            if (
                                isinstance(
                                    content,
                                    str,
                                )
                                and content
                            ):
                                yield content

                            continue

                        if (
                            event_name
                            == "approval_required"
                        ):
                            approval_request = (
                                data.get(
                                    "request"
                                )
                            )

                            if not isinstance(
                                approval_request,
                                dict,
                            ):
                                approval_request = {
                                    "kind": (
                                        "tool_approval"
                                    ),
                                    "tool_name": (
                                        "unknown"
                                    ),
                                    "message": (
                                        "是否批准"
                                        "该操作？"
                                    ),
                                    "arguments": {},
                                }

                            raise ApprovalRequired(
                                approval_request
                            )

                        if event_name == "error":
                            error_message = (
                                data.get(
                                    "message",
                                    (
                                        "LifePilot "
                                        "生成回答时"
                                        "发生错误。"
                                    ),
                                )
                            )

                            raise LifePilotApiError(
                                str(error_message)
                            )

                        if event_name == "done":
                            return

            # 没有收到done、error或
            # approval_required，说明连接异常。
            raise LifePilotApiError(
                "流式连接意外中断。"
            )

        except LifePilotApiError:
            raise

        except httpx.HTTPStatusError as error:
            detail = (
                self._extract_http_error(
                    error.response
                )
            )

            raise LifePilotApiError(
                detail
            ) from error

        except httpx.ConnectError as error:
            raise LifePilotApiError(
                "无法连接 LifePilot 后端，"
                "请确认 FastAPI 已经启动。"
            ) from error

        except httpx.TimeoutException as error:
            raise LifePilotApiError(
                "请求超时，请稍后重试。"
            ) from error

        except httpx.HTTPError as error:
            raise LifePilotApiError(
                "与 LifePilot 后端"
                "通信失败。"
            ) from error

    def resume_chat(
        self,
        thread_id: str,
        approved: bool,
    ) -> str:
        """批准或拒绝等待中的敏感操作。"""

        data = self._request_json(
            method="POST",
            path="/api/v1/chat/resume",
            json={
                "thread_id": thread_id,
                "approved": approved,
            },
        )

        response_status = data.get(
            "status"
        )

        # 恢复一个操作后，可能还有
        # 另一个危险操作需要审批。
        if (
            response_status
            == "approval_required"
        ):
            approval_request = data.get(
                "approval_request",
                {},
            )

            if not isinstance(
                approval_request,
                dict,
            ):
                approval_request = {}

            raise ApprovalRequired(
                approval_request
            )

        if response_status != "completed":
            raise LifePilotApiError(
                "后端返回了未知的审批状态。"
            )

        reply = data.get("reply")

        if (
            not isinstance(reply, str)
            or not reply.strip()
        ):
            raise LifePilotApiError(
                "Agent 恢复执行后没有"
                "返回有效回答。"
            )

        return reply

    def _request_json(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """发送普通HTTP请求并读取JSON对象。"""

        try:
            with (
                self._create_http_client()
                as client
            ):
                response = client.request(
                    method=method,
                    url=path,
                    **kwargs,
                )

                response.raise_for_status()
                data = response.json()

            if not isinstance(data, dict):
                raise LifePilotApiError(
                    "后端响应格式不正确。"
                )

            return data

        except LifePilotApiError:
            raise

        except httpx.HTTPStatusError as error:
            detail = (
                self._extract_http_error(
                    error.response
                )
            )

            raise LifePilotApiError(
                detail
            ) from error

        except httpx.ConnectError as error:
            raise LifePilotApiError(
                "无法连接 LifePilot 后端，"
                "请确认 FastAPI 已经启动。"
            ) from error

        except httpx.TimeoutException as error:
            raise LifePilotApiError(
                "请求超时，请稍后重试。"
            ) from error

        except httpx.HTTPError as error:
            raise LifePilotApiError(
                "与 LifePilot 后端"
                "通信失败。"
            ) from error

        except ValueError as error:
            raise LifePilotApiError(
                "后端返回了无法解析的数据。"
            ) from error

    def _create_http_client(
        self,
    ) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    @staticmethod
    def _parse_event_data(
        raw_data: str,
    ) -> dict[str, Any]:
        try:
            data = json.loads(
                raw_data
            )

        except json.JSONDecodeError as error:
            raise LifePilotApiError(
                "后端返回了无法解析的"
                " SSE 数据。"
            ) from error

        if not isinstance(data, dict):
            raise LifePilotApiError(
                "SSE 事件数据格式不正确。"
            )

        return data

    @staticmethod
    def _extract_http_error(
        response: httpx.Response,
    ) -> str:
        try:
            data = response.json()

            if isinstance(data, dict):
                detail = data.get(
                    "detail"
                )

                if isinstance(detail, str):
                    return detail

        except ValueError:
            pass

        return (
            "后端请求失败，状态码："
            f"{response.status_code}"
        )