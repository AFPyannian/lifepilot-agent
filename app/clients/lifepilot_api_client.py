"""实现 Streamlit 使用的 LifePilot HTTP 与 SSE 客户端。"""

import json
from collections.abc import (
    Iterable,
    Iterator,
)
from typing import Any
from urllib.parse import quote

import httpx


class LifePilotApiError(RuntimeError):
    """表示 LifePilot HTTP 或 SSE 请求失败。"""


class ApprovalRequired(LifePilotApiError):
    """携带后端返回的待审批操作。"""

    def __init__(
        self,
        request: dict[str, Any],
    ) -> None:
        """保存结构化审批请求。"""
        super().__init__("操作需要用户审批。")

        self.request = request


def iter_sse_events(
    lines: Iterable[str],
) -> Iterator[tuple[str, str]]:
    """按 SSE 规范解析事件名称和多行数据。"""

    event_name = "message"
    data_lines: list[str] = []

    for raw_line in lines:
        line = raw_line.rstrip("\r")

        if line == "":
            if data_lines:
                yield (
                    event_name,
                    "\n".join(data_lines),
                )

            event_name = "message"
            data_lines = []
            continue

        if line.startswith(":"):
            continue

        field, separator, value = line.partition(":")

        if not separator:
            continue

        value = value.removeprefix(" ")

        if field == "event":
            event_name = value

        elif field == "data":
            data_lines.append(value)

    if data_lines:
        yield (
            event_name,
            "\n".join(data_lines),
        )


class LifePilotApiClient:
    """封装 LifePilot 后端的同步 HTTP 客户端。"""

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 180.0,
        transport: (httpx.BaseTransport | None) = None,
        access_token: str | None = None,
    ) -> None:
        """校验服务地址并保存认证、超时和测试传输配置。"""
        clean_base_url = base_url.strip().rstrip("/")

        if not clean_base_url:
            raise ValueError("LifePilot API 地址不能为空。")

        self._base_url = clean_base_url

        self._timeout = httpx.Timeout(
            timeout_seconds,
            connect=10.0,
        )

        self._transport = transport

        self._headers: dict[str, str] = {}

        normalized_token = access_token.strip() if access_token is not None else ""

        if normalized_token:
            self._headers["Authorization"] = f"Bearer {normalized_token}"

    def login(
        self,
        username: str,
        password: str,
    ) -> dict[str, Any]:
        """使用账号密码登录并返回 Session。"""
        return self._request_json(
            method="POST",
            path="/api/v1/auth/login",
            json={
                "username": username,
                "password": password,
            },
        )

    def get_registration_status(self) -> dict[str, Any]:
        """读取后端注册策略。"""
        return self._request_json(
            method="GET",
            path="/api/v1/auth/registration",
        )

    def register(
        self,
        username: str,
        password: str,
        invite_code: str,
    ) -> dict[str, Any]:
        """使用邀请码注册并返回 Session。"""
        return self._request_json(
            method="POST",
            path="/api/v1/auth/register",
            json={
                "username": username,
                "password": password,
                "invite_code": invite_code,
            },
        )

    def create_invitation(self, expires_in_hours: int) -> dict[str, Any]:
        """管理员创建一次性邀请码。"""
        return self._request_json(
            method="POST",
            path="/api/v1/admin/invitations",
            json={"expires_in_hours": expires_in_hours},
        )

    def list_invitations(self) -> list[dict[str, Any]]:
        """管理员查询邀请码列表。"""
        data = self._request_json(
            method="GET",
            path="/api/v1/admin/invitations",
        )
        invitations = data.get("invitations", [])
        if not isinstance(invitations, list):
            raise LifePilotApiError("后端返回的邀请码列表格式不正确。")
        return invitations

    def revoke_invitation(self, invitation_id: str) -> bool:
        """管理员撤销邀请码。"""
        data = self._request_json(
            method="DELETE",
            path=(f"/api/v1/admin/invitations/{quote(invitation_id, safe='')}"),
        )
        return bool(data.get("revoked"))

    def list_admin_users(self, limit: int = 100) -> list[dict[str, Any]]:
        """管理员查询用户列表。"""
        data = self._request_json(
            method="GET",
            path="/api/v1/admin/users",
            params={"limit": limit},
        )
        users = data.get("users", [])
        if not isinstance(users, list):
            raise LifePilotApiError("后端返回的用户列表格式不正确。")
        return users

    def update_admin_user_status(self, user_id: str, user_status: str) -> None:
        """管理员启用或禁用账号。"""
        self._request(
            method="PATCH",
            path=f"/api/v1/admin/users/{quote(user_id, safe='')}/status",
            json={"status": user_status},
        )

    def list_admin_audit_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """管理员查询脱敏审计事件。"""
        data = self._request_json(
            method="GET",
            path="/api/v1/admin/audit-events",
            params={"limit": limit},
        )
        events = data.get("events", [])
        if not isinstance(events, list):
            raise LifePilotApiError("后端返回的审计列表格式不正确。")
        return events

    def get_admin_usage_summary(self, days: int = 30) -> dict[str, Any]:
        """管理员查询全局模型用量。"""
        return self._request_json(
            method="GET",
            path="/api/v1/admin/usage/summary",
            params={"days": days},
        )

    def get_admin_user_quota(self, user_id: str) -> dict[str, Any]:
        """管理员查询用户当前月度模型配额。"""
        return self._request_json(
            method="GET",
            path=f"/api/v1/admin/users/{quote(user_id, safe='')}/quota",
        )

    def update_admin_user_quota(
        self,
        user_id: str,
        *,
        monthly_request_limit: int | None,
        monthly_token_limit: int | None,
    ) -> dict[str, Any]:
        """管理员设置用户月度请求和 Token 上限。"""
        return self._request_json(
            method="PUT",
            path=f"/api/v1/admin/users/{quote(user_id, safe='')}/quota",
            json={
                "monthly_request_limit": monthly_request_limit,
                "monthly_token_limit": monthly_token_limit,
            },
        )

    def get_current_user(self) -> dict[str, Any]:
        """读取当前 Session 对应的用户。"""
        return self._request_json(
            method="GET",
            path="/api/v1/auth/me",
        )

    def logout(self) -> bool:
        """撤销当前 Session。"""
        data = self._request_json(
            method="POST",
            path="/api/v1/auth/logout",
        )
        return bool(data.get("revoked"))

    def logout_all(self) -> bool:
        """撤销当前用户的全部 Session。"""
        data = self._request_json(
            method="POST",
            path="/api/v1/auth/logout-all",
        )
        return bool(data.get("revoked"))

    def change_password(
        self,
        current_password: str,
        new_password: str,
    ) -> None:
        """修改密码；成功后全部 Session 都会失效。"""
        self._request(
            method="POST",
            path="/api/v1/auth/password",
            json={
                "current_password": current_password,
                "new_password": new_password,
            },
        )

    def get_model_access(self) -> dict[str, Any]:
        """读取当前账号可以使用的模型模式。"""
        return self._request_json(
            method="GET",
            path="/api/v1/model/access",
        )

    def get_usage_summary(self) -> dict[str, Any]:
        """读取当前账号本月的模型调用用量。"""
        return self._request_json(
            method="GET",
            path="/api/v1/usage/summary",
        )

    def list_usage_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """读取当前账号最近的模型调用事件。"""
        response = self._request(
            method="GET",
            path="/api/v1/usage/events",
            params={"limit": limit},
        )
        try:
            data = response.json()
        except ValueError as error:
            raise LifePilotApiError("后端返回了无法解析的用量事件。") from error
        if not isinstance(data, list):
            raise LifePilotApiError("后端返回了无效的用量事件。")
        return data

    def get_deepseek_credential(self) -> dict[str, Any]:
        """读取当前账号的掩码 DeepSeek 凭据元数据。"""
        return self._request_json(
            method="GET",
            path="/api/v1/model/credentials/deepseek",
        )

    def save_deepseek_credential(self, api_key: str) -> dict[str, Any]:
        """验证并创建或轮换当前账号的 DeepSeek Key。"""
        return self._request_json(
            method="PUT",
            path="/api/v1/model/credentials/deepseek",
            json={"api_key": api_key},
        )

    def revoke_deepseek_credential(self) -> None:
        """撤销当前账号的 DeepSeek Key。"""
        self._request(
            method="POST",
            path="/api/v1/model/credentials/deepseek/revoke",
        )

    def delete_deepseek_credential(self) -> None:
        """物理删除当前账号的 DeepSeek 凭据记录。"""
        self._request(
            method="DELETE",
            path="/api/v1/model/credentials/deepseek",
        )

    def is_healthy(self) -> bool:
        """检查后端健康接口是否可用。"""

        try:
            with self._create_http_client() as client:
                response = client.get("/api/v1/health")

                response.raise_for_status()
                data = response.json()

            return isinstance(data, dict) and data.get("status") == "ok"

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
        """上传并索引一份知识文档。"""

        return self._request_json(
            method="POST",
            path=("/api/v1/knowledge/documents"),
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
        """返回知识库文档列表。"""

        data = self._request_json(
            method="GET",
            path=("/api/v1/knowledge/documents"),
        )

        documents = data.get(
            "documents",
            [],
        )

        if not isinstance(
            documents,
            list,
        ):
            raise LifePilotApiError("知识库列表响应格式不正确。")

        return documents

    def delete_document(
        self,
        filename: str,
    ) -> bool:
        """删除指定知识文档。"""

        encoded_filename = quote(
            filename,
            safe="",
        )

        data = self._request_json(
            method="DELETE",
            path=(f"/api/v1/knowledge/documents/{encoded_filename}"),
        )

        return bool(data.get("deleted"))

    def list_conversations(
        self,
    ) -> list[dict[str, Any]]:
        """返回历史会话摘要列表。"""

        data = self._request_json(
            method="GET",
            path="/api/v1/conversations",
        )

        conversations = data.get(
            "conversations",
            [],
        )

        if not isinstance(
            conversations,
            list,
        ):
            raise LifePilotApiError("历史会话响应格式不正确。")

        return conversations

    def get_conversation(
        self,
        thread_id: str,
    ) -> dict[str, Any]:
        """读取一段历史会话的详细状态。"""

        encoded_thread_id = quote(
            thread_id,
            safe="",
        )

        return self._request_json(
            method="GET",
            path=(f"/api/v1/conversations/{encoded_thread_id}"),
        )

    def rename_conversation(
        self,
        thread_id: str,
        title: str,
    ) -> dict[str, Any]:
        """修改历史会话标题。"""

        encoded_thread_id = quote(
            thread_id,
            safe="",
        )

        return self._request_json(
            method="PATCH",
            path=(f"/api/v1/conversations/{encoded_thread_id}"),
            json={
                "title": title,
            },
        )

    def delete_conversation(
        self,
        thread_id: str,
    ) -> bool:
        """删除历史会话及其执行状态。"""

        encoded_thread_id = quote(
            thread_id,
            safe="",
        )

        data = self._request_json(
            method="DELETE",
            path=(f"/api/v1/conversations/{encoded_thread_id}"),
        )

        return bool(data.get("deleted"))

    def stream_chat(
        self,
        message: str,
        thread_id: str,
        model_mode: str = "PLATFORM",
    ) -> Iterator[str]:
        """发送聊天请求并逐段产生模型文本。"""

        try:
            with (
                self._create_http_client() as client,
                client.stream(
                    method="POST",
                    url="/api/v1/chat/stream",
                    json={
                        "message": message,
                        "thread_id": thread_id,
                        "model_mode": model_mode,
                    },
                ) as response,
            ):
                response.raise_for_status()

                content_type = response.headers.get(
                    "content-type",
                    "",
                )

                if not content_type.lower().startswith("text/event-stream"):
                    raise LifePilotApiError("后端没有返回 SSE 流。")

                for (
                    event_name,
                    raw_data,
                ) in iter_sse_events(response.iter_lines()):
                    data = self._parse_event_data(raw_data)

                    if event_name == "start":
                        continue

                    if event_name == "token":
                        content = data.get("content")

                        if (
                            isinstance(
                                content,
                                str,
                            )
                            and content
                        ):
                            yield content

                        continue

                    if event_name == "approval_required":
                        approval_request = data.get("request")

                        if not isinstance(
                            approval_request,
                            dict,
                        ):
                            approval_request = {
                                "kind": ("tool_approval"),
                                "tool_name": ("unknown"),
                                "message": ("是否批准该操作？"),
                                "arguments": {},
                            }

                        raise ApprovalRequired(approval_request)

                    if event_name == "error":
                        error_message = data.get(
                            "message",
                            ("LifePilot 生成回答时发生错误。"),
                        )

                        raise LifePilotApiError(str(error_message))

                    if event_name == "done":
                        return

            raise LifePilotApiError("流式连接意外中断。")

        except LifePilotApiError:
            raise

        except httpx.HTTPStatusError as error:
            detail = self._extract_http_error(error.response)

            raise LifePilotApiError(detail) from error

        except httpx.ConnectError as error:
            raise LifePilotApiError(
                "无法连接 LifePilot 后端，请确认 FastAPI 已经启动。"
            ) from error

        except httpx.TimeoutException as error:
            raise LifePilotApiError("请求超时，请稍后重试。") from error

        except httpx.HTTPError as error:
            raise LifePilotApiError("与 LifePilot 后端通信失败。") from error

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

        response_status = data.get("status")

        if response_status == "approval_required":
            approval_request = data.get(
                "approval_request",
                {},
            )

            if not isinstance(
                approval_request,
                dict,
            ):
                approval_request = {}

            raise ApprovalRequired(approval_request)

        if response_status != "completed":
            raise LifePilotApiError("后端返回了未知的审批状态。")

        reply = data.get("reply")

        if not isinstance(reply, str) or not reply.strip():
            raise LifePilotApiError("Agent 恢复执行后没有返回有效回答。")

        return reply

    def _request_json(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """发送普通请求并返回 JSON 对象。"""

        response = self._request(method=method, path=path, **kwargs)

        try:
            data = response.json()

            if not isinstance(data, dict):
                raise LifePilotApiError("后端响应格式不正确。")

            return data

        except LifePilotApiError:
            raise

        except ValueError as error:
            raise LifePilotApiError("后端返回了无法解析的数据。") from error

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """发送普通请求并统一转换连接、超时和状态错误。"""
        try:
            with self._create_http_client() as client:
                response = client.request(
                    method=method,
                    url=path,
                    **kwargs,
                )
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as error:
            detail = self._extract_http_error(error.response)
            raise LifePilotApiError(detail) from error
        except httpx.ConnectError as error:
            raise LifePilotApiError(
                "无法连接 LifePilot 后端，请确认 FastAPI 已经启动。"
            ) from error
        except httpx.TimeoutException as error:
            raise LifePilotApiError("请求超时，请稍后重试。") from error
        except httpx.HTTPError as error:
            raise LifePilotApiError("与 LifePilot 后端通信失败。") from error

    def _create_http_client(
        self,
    ) -> httpx.Client:
        """创建共享基础地址和超时配置的 HTTPX 客户端。"""
        return httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers=self._headers,
        )

    @staticmethod
    def _parse_event_data(
        raw_data: str,
    ) -> dict[str, Any]:
        """将 SSE 数据解析为 JSON 对象。"""
        try:
            data = json.loads(raw_data)

        except json.JSONDecodeError as error:
            raise LifePilotApiError("后端返回了无法解析的 SSE 数据。") from error

        if not isinstance(data, dict):
            raise LifePilotApiError("SSE 事件数据格式不正确。")

        return data

    @staticmethod
    def _extract_http_error(
        response: httpx.Response,
    ) -> str:
        """从错误响应中提取安全的用户提示。"""
        try:
            data = response.json()

            if isinstance(data, dict):
                detail = data.get("detail")

                if isinstance(detail, str):
                    return detail

        except ValueError:
            pass

        return f"后端请求失败，状态码：{response.status_code}"
