"""验证阶段四管理员用户、审计、授权和全局用量后台。"""

from types import SimpleNamespace
from typing import Any

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.auth.passwords import hash_password
from app.auth.service import AuthService
from app.repositories.audit_repository import AuditRepository
from app.repositories.auth_repository import AuthRepository
from app.repositories.entitlement_repository import EntitlementRepository
from app.repositories.usage_repository import UsageRepository


class FakeGraph:
    def get_state(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(next=())


def test_admin_can_manage_users_entitlements_audit_and_usage(tmp_path) -> None:
    database_path = tmp_path / "admin.db"
    auth_repository = AuthRepository(database_path)
    auth_repository.create_user(
        user_id="admin-id",
        username="admin",
        password_hash=hash_password("admin-correct-horse"),
        role="admin",
    )
    auth_repository.create_user(
        user_id="user-id",
        username="alice",
        password_hash=hash_password("alice-correct-horse"),
        role="user",
    )
    audit_repository = AuditRepository(database_path)
    entitlement_repository = EntitlementRepository(database_path)
    usage_repository = UsageRepository(database_path)
    app = create_app(
        agent_graph=FakeGraph(),
        settings=SimpleNamespace(
            api_rate_limit_enabled=False,
            agent_recursion_limit=25,
            app_environment="test",
            auth_invitation_max_ttl_hours=720,
        ),
        auth_service=AuthService(auth_repository),
        audit_repository=audit_repository,
        entitlement_repository=entitlement_repository,
        usage_repository=usage_repository,
    )

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin-correct-horse"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        users = client.get("/api/v1/admin/users", headers=headers)
        assert users.status_code == 200
        assert {user["username"] for user in users.json()["users"]} == {
            "admin",
            "alice",
        }

        disabled = client.patch(
            "/api/v1/admin/users/user-id/status",
            headers=headers,
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"

        granted = client.post(
            "/api/v1/admin/users/user-id/entitlements",
            headers=headers,
            json={"capability": "agent.chat"},
        )
        assert granted.status_code == 201

        entitlements = client.get(
            "/api/v1/admin/users/user-id/entitlements", headers=headers
        )
        assert any(
            item["capability"] == "agent.chat"
            for item in entitlements.json()["entitlements"]
        )

        audit = client.get("/api/v1/admin/audit-events", headers=headers)
        assert audit.status_code == 200
        assert any(
            event["action"] == "user.status_updated" for event in audit.json()["events"]
        )

        usage = client.get("/api/v1/admin/usage/summary", headers=headers)
        assert usage.status_code == 200
        assert usage.json()["active_users"] == 0
