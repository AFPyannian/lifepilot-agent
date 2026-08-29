"""验证登录、注销、密码修改和登录失败限流。"""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.auth.passwords import hash_password
from app.auth.rate_limit import LoginRateLimiter
from app.auth.service import AuthService
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository

PASSWORD = "correct-horse-battery"


class FakeGraph:
    """提供认证 API 测试所需的最小图。"""

    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(next=())


def create_auth_app(tmp_path, max_failures: int = 5):
    """创建使用真实认证仓储的测试应用。"""
    repository = AuthRepository(tmp_path / "application.db")
    user = repository.create_user(
        user_id=str(uuid4()),
        username="alice",
        password_hash=hash_password(PASSWORD),
        role="user",
    )
    service = AuthService(repository, session_ttl_hours=1)
    settings = SimpleNamespace(
        api_rate_limit_enabled=False,
        agent_recursion_limit=25,
        app_environment="test",
    )
    app = create_app(
        agent_graph=FakeGraph(),
        settings=settings,
        auth_service=service,
        audit_repository=AuditRepository(tmp_path / "application.db"),
        login_rate_limiter=LoginRateLimiter(max_failures, 60),
    )
    return app, repository, user


def login(client: TestClient, password: str = PASSWORD):
    """向测试应用发送登录请求。"""
    return client.post(
        "/api/v1/auth/login",
        json={"username": "alice", "password": password},
    )


def test_login_and_logout_lifecycle(tmp_path) -> None:
    app, _repository, _user = create_auth_app(tmp_path)

    with TestClient(app) as client:
        login_response = login(client)
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]

        headers = {"Authorization": f"Bearer {token}"}
        me_response = client.get("/api/v1/auth/me", headers=headers)
        assert me_response.json()["username"] == "alice"

        logout_response = client.post("/api/v1/auth/logout", headers=headers)
        assert logout_response.status_code == 200
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_login_uses_same_error_for_unknown_user_and_wrong_password(tmp_path) -> None:
    app, _repository, _user = create_auth_app(tmp_path)

    with TestClient(app) as client:
        wrong_password = login(client, "wrong-password")
        unknown_user = client.post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "wrong-password"},
        )

    assert wrong_password.status_code == 401
    assert unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


def test_login_failures_are_rate_limited(tmp_path) -> None:
    app, _repository, _user = create_auth_app(tmp_path, max_failures=2)

    with TestClient(app) as client:
        assert login(client, "wrong-password").status_code == 401
        assert login(client, "wrong-password").status_code == 401
        limited = login(client, PASSWORD)

    assert limited.status_code == 429
    assert "retry-after" in limited.headers


def test_password_change_revokes_every_session(tmp_path) -> None:
    app, _repository, _user = create_auth_app(tmp_path)

    with TestClient(app) as client:
        first_token = login(client).json()["access_token"]
        second_token = login(client).json()["access_token"]
        response = client.post(
            "/api/v1/auth/password",
            headers={"Authorization": f"Bearer {first_token}"},
            json={
                "current_password": PASSWORD,
                "new_password": "new-correct-horse-battery",
            },
        )

        assert response.status_code == 204
        for token in (first_token, second_token):
            assert (
                client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                ).status_code
                == 401
            )


def test_logout_all_revokes_every_session(tmp_path) -> None:
    app, _repository, _user = create_auth_app(tmp_path)

    with TestClient(app) as client:
        first_token = login(client).json()["access_token"]
        second_token = login(client).json()["access_token"]
        response = client.post(
            "/api/v1/auth/logout-all",
            headers={"Authorization": f"Bearer {first_token}"},
        )

        assert response.status_code == 200
        assert response.json() == {"revoked": True}
        for token in (first_token, second_token):
            assert (
                client.get(
                    "/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                ).status_code
                == 401
            )


def test_audit_events_do_not_store_password_or_session_token(tmp_path) -> None:
    app, _repository, _user = create_auth_app(tmp_path)
    supplied_password = "never-store-this-password"

    with TestClient(app) as client:
        denied = login(client, supplied_password)
        granted = login(client)
        token = granted.json()["access_token"]

    assert supplied_password not in denied.text
    database_bytes = (tmp_path / "application.db").read_bytes()
    assert supplied_password.encode() not in database_bytes
    assert token.encode() not in database_bytes
