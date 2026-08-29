"""提供多用户 API 测试使用的认证辅助对象。"""

from typing import Any

from fastapi.testclient import TestClient

from app.auth.models import Principal

TEST_ACCESS_TOKEN = "test-session-token"
TEST_PRINCIPAL = Principal(
    user_id="owner-1",
    username="alice",
    role="user",
    status="active",
    session_id="session-1",
)


class FakeAuthService:
    """在测试中验证固定 Session Token。"""

    def __init__(self, principal: Principal = TEST_PRINCIPAL) -> None:
        self.principal = principal

    def authenticate(self, access_token: str) -> Principal | None:
        if access_token != TEST_ACCESS_TOKEN:
            return None
        return self.principal

    def logout(self, principal: Principal) -> bool:
        return principal.session_id == self.principal.session_id

    def logout_all(self, principal: Principal) -> int:
        return 1 if principal.user_id == self.principal.user_id else 0


class AuthenticatedTestClient(TestClient):
    """自动为请求注入固定 Session 的 TestClient。"""

    def __init__(self, app: Any, **kwargs: Any) -> None:
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault(
            "Authorization",
            f"Bearer {TEST_ACCESS_TOKEN}",
        )
        super().__init__(app, headers=headers, **kwargs)

    def __enter__(self) -> "AuthenticatedTestClient":
        client = super().__enter__()
        self.app.state.auth_service = FakeAuthService()
        return client


def user_config(user_id: str = "test-user") -> dict[str, dict[str, str]]:
    """构造直接调用 Agent 工具使用的可信配置。"""
    return {"configurable": {"user_id": user_id}}
