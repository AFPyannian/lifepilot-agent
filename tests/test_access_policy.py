"""验证集中访问策略组合账号、开关、凭据和授权。"""

from types import SimpleNamespace

from app.access.errors import AccessDeniedError
from app.access.models import Capability
from app.access.policy import AccessPolicy
from app.api.server import create_app
from app.repositories.auth_repository import AuthRepository
from app.repositories.entitlement_repository import EntitlementRepository
from tests.helpers import AuthenticatedTestClient


class FakeCredentialService:
    def __init__(self, active_users: set[str]) -> None:
        self._active_users = active_users

    def get_metadata(self, *, user_id: str):
        if user_id not in self._active_users:
            return None
        return SimpleNamespace(status="active")


def test_access_policy_requires_entitlement_or_active_byok_credential(tmp_path) -> None:
    database_path = tmp_path / "access.db"
    auth = AuthRepository(database_path)
    alice = auth.create_user(
        user_id="alice-id",
        username="alice",
        password_hash="test",
        role="user",
    )
    entitlements = EntitlementRepository(database_path)
    policy = AccessPolicy(
        settings=SimpleNamespace(
            byok_enabled=True,
            platform_model_enabled=True,
        ),  # type: ignore[arg-type]
        auth_repository=auth,
        entitlement_repository=entitlements,
        credential_service=FakeCredentialService({alice.id}),  # type: ignore[arg-type]
    )

    assert policy.evaluate(user_id=alice.id, capability=Capability.AGENT_CHAT).allowed
    assert policy.evaluate(user_id=alice.id, capability=Capability.MODEL_BYOK).allowed
    assert policy.evaluate(
        user_id=alice.id, capability=Capability.MODEL_PLATFORM
    ).allowed

    auth.set_user_status(alice.id, "disabled")
    decision = policy.evaluate(user_id=alice.id, capability=Capability.MODEL_BYOK)
    assert not decision.allowed
    assert decision.reason_code == "account_inactive"


def test_authorize_raises_safe_access_error(tmp_path) -> None:
    database_path = tmp_path / "denied.db"
    auth = AuthRepository(database_path)
    user = auth.create_user(
        user_id="new-id",
        username="new-user",
        password_hash="test",
        role="user",
    )
    entitlements = EntitlementRepository(database_path)
    policy = AccessPolicy(
        settings=SimpleNamespace(
            byok_enabled=True,
            platform_model_enabled=True,
        ),  # type: ignore[arg-type]
        auth_repository=auth,
        entitlement_repository=entitlements,
        credential_service=FakeCredentialService(set()),  # type: ignore[arg-type]
    )

    try:
        policy.authorize(user_id=user.id, capability=Capability.MODEL_BYOK)
    except AccessDeniedError as error:
        assert error.reason_code == "credential_required"
        assert "DeepSeek" in error.user_message
    else:
        raise AssertionError("Expected AccessDeniedError")


class DeniedPolicy:
    def authorize(self, *, user_id: str, capability: Capability) -> None:
        del user_id
        raise AccessDeniedError(
            capability=capability,
            reason_code="entitlement_required",
            user_message="当前账号尚未获得平台模型使用权限。",
        )


class ConversationSpy:
    def __init__(self) -> None:
        self.calls = 0

    def record_message(self, **kwargs) -> None:
        del kwargs
        self.calls += 1


def test_chat_denial_happens_before_conversation_write() -> None:
    conversations = ConversationSpy()
    app = create_app(
        agent_graph=object(),
        access_policy=DeniedPolicy(),  # type: ignore[arg-type]
        conversation_repository=conversations,  # type: ignore[arg-type]
    )
    with AuthenticatedTestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"message": "hello", "model_mode": "PLATFORM"},
        )

    assert response.status_code == 403
    assert conversations.calls == 0
