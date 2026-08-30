"""验证邀请制注册、管理员授权和秘密存储边界。"""

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.auth.passwords import hash_password
from app.auth.rate_limit import LoginRateLimiter
from app.auth.service import AuthService
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository

ADMIN_PASSWORD = "admin-correct-horse"
USER_PASSWORD = "user-correct-horse"
NEW_PASSWORD = "new-correct-horse-battery"


class FakeGraph:
    """提供注册 API 测试所需的最小图。"""

    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(next=())


def create_registration_app(
    tmp_path,
    *,
    mode: str = "invite",
    max_failures: int = 10,
):
    """创建使用真实认证数据库的注册测试应用。"""
    database_path = tmp_path / "application.db"
    repository = AuthRepository(database_path)
    admin = repository.create_user(
        user_id="admin-id",
        username="admin",
        password_hash=hash_password(ADMIN_PASSWORD),
        role="admin",
    )
    repository.create_user(
        user_id="user-id",
        username="existing-user",
        password_hash=hash_password(USER_PASSWORD),
        role="user",
    )
    service = AuthService(
        repository,
        session_ttl_hours=1,
        registration_mode=mode,  # type: ignore[arg-type]
    )
    settings = SimpleNamespace(
        api_rate_limit_enabled=False,
        agent_recursion_limit=25,
        app_environment="test",
        auth_invitation_max_ttl_hours=720,
    )
    app = create_app(
        agent_graph=FakeGraph(),
        settings=settings,
        auth_service=service,
        audit_repository=AuditRepository(database_path),
        registration_rate_limiter=LoginRateLimiter(max_failures, 60),
    )
    return app, repository, admin, database_path


def login(client: TestClient, username: str, password: str) -> str:
    """登录并返回测试 Session。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def create_invitation(client: TestClient, admin_token: str) -> dict[str, Any]:
    """通过管理员 API 创建邀请码。"""
    response = client.post(
        "/api/v1/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"expires_in_hours": 72},
    )
    assert response.status_code == 201
    return response.json()


def test_registration_is_closed_by_default(tmp_path) -> None:
    app, _repository, _admin, _database_path = create_registration_app(
        tmp_path,
        mode="closed",
    )

    with TestClient(app) as client:
        status_response = client.get("/api/v1/auth/registration")
        register_response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "new-user",
                "password": NEW_PASSWORD,
                "invite_code": "lp_invite_invalid-code",
            },
        )

    assert status_response.json() == {"mode": "closed", "enabled": False}
    assert register_response.status_code == 403


def test_admin_can_create_invitation_and_user_can_register(tmp_path) -> None:
    app, repository, _admin, _database_path = create_registration_app(tmp_path)

    with TestClient(app) as client:
        admin_token = login(client, "admin", ADMIN_PASSWORD)
        invitation = create_invitation(client, admin_token)
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "alice",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
            },
        )

        assert response.status_code == 201
        result = response.json()
        assert result["user"]["role"] == "user"
        assert result["user"]["status"] == "active"
        me_response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {result['access_token']}"},
        )
        assert me_response.json()["username"] == "alice"

    assert repository.get_user_by_username("alice") is not None


def test_invitation_cannot_be_used_twice(tmp_path) -> None:
    app, _repository, _admin, _database_path = create_registration_app(tmp_path)

    with TestClient(app) as client:
        invitation = create_invitation(
            client,
            login(client, "admin", ADMIN_PASSWORD),
        )
        first = client.post(
            "/api/v1/auth/register",
            json={
                "username": "alice",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
            },
        )
        second = client.post(
            "/api/v1/auth/register",
            json={
                "username": "bob",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
            },
        )

    assert first.status_code == 201
    assert second.status_code == 400


def test_duplicate_username_does_not_consume_invitation(tmp_path) -> None:
    app, _repository, _admin, _database_path = create_registration_app(tmp_path)

    with TestClient(app) as client:
        invitation = create_invitation(
            client,
            login(client, "admin", ADMIN_PASSWORD),
        )
        duplicate = client.post(
            "/api/v1/auth/register",
            json={
                "username": "existing-user",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
            },
        )
        retry = client.post(
            "/api/v1/auth/register",
            json={
                "username": "new-user",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
            },
        )

    assert duplicate.status_code == 400
    assert retry.status_code == 201


def test_registration_rejects_client_supplied_role(tmp_path) -> None:
    app, _repository, _admin, _database_path = create_registration_app(tmp_path)

    with TestClient(app) as client:
        invitation = create_invitation(
            client,
            login(client, "admin", ADMIN_PASSWORD),
        )
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "attacker",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
                "role": "admin",
            },
        )

    assert response.status_code == 422


def test_normal_user_cannot_manage_invitations(tmp_path) -> None:
    app, _repository, _admin, _database_path = create_registration_app(tmp_path)

    with TestClient(app) as client:
        user_token = login(client, "existing-user", USER_PASSWORD)
        response = client.post(
            "/api/v1/admin/invitations",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"expires_in_hours": 72},
        )

    assert response.status_code == 403


def test_admin_can_list_and_revoke_invitation(tmp_path) -> None:
    app, _repository, _admin, _database_path = create_registration_app(tmp_path)

    with TestClient(app) as client:
        admin_token = login(client, "admin", ADMIN_PASSWORD)
        invitation = create_invitation(client, admin_token)
        headers = {"Authorization": f"Bearer {admin_token}"}
        listed = client.get("/api/v1/admin/invitations", headers=headers)
        revoked = client.delete(
            f"/api/v1/admin/invitations/{invitation['id']}",
            headers=headers,
        )
        denied = client.post(
            "/api/v1/auth/register",
            json={
                "username": "alice",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
            },
        )

    assert listed.status_code == 200
    listed_item = listed.json()["invitations"][0]
    assert "invite_code" not in listed_item
    assert "code_hash" not in listed_item
    assert revoked.json() == {"id": invitation["id"], "revoked": True}
    assert denied.status_code == 400


def test_registration_failures_are_rate_limited(tmp_path) -> None:
    app, _repository, _admin, _database_path = create_registration_app(
        tmp_path,
        max_failures=2,
    )
    payload = {
        "username": "alice",
        "password": NEW_PASSWORD,
        "invite_code": "lp_invite_invalid-code",
    }

    with TestClient(app) as client:
        assert client.post("/api/v1/auth/register", json=payload).status_code == 400
        assert client.post("/api/v1/auth/register", json=payload).status_code == 400
        limited = client.post("/api/v1/auth/register", json=payload)

    assert limited.status_code == 429
    assert "retry-after" in limited.headers


def test_registration_secrets_are_not_stored_in_plaintext(tmp_path) -> None:
    app, _repository, _admin, database_path = create_registration_app(tmp_path)

    with TestClient(app) as client:
        admin_token = login(client, "admin", ADMIN_PASSWORD)
        invitation = create_invitation(client, admin_token)
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "alice",
                "password": NEW_PASSWORD,
                "invite_code": invitation["invite_code"],
            },
        )
        access_token = response.json()["access_token"]

    database_bytes = database_path.read_bytes()
    assert NEW_PASSWORD.encode() not in database_bytes
    assert invitation["invite_code"].encode() not in database_bytes
    assert access_token.encode() not in database_bytes
