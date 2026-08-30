"""验证授权迁移、发放、过期和撤销。"""

from datetime import UTC, datetime, timedelta

from app.access.models import Capability, EntitlementSource
from app.repositories.auth_repository import AuthRepository
from app.repositories.entitlement_repository import EntitlementRepository


def test_existing_users_receive_one_time_platform_entitlement(tmp_path) -> None:
    database_path = tmp_path / "entitlements.db"
    auth = AuthRepository(database_path)
    existing = auth.create_user(
        user_id="existing-id",
        username="existing",
        password_hash="test",
        role="user",
    )

    repository = EntitlementRepository(database_path)
    assert repository.has_active(
        user_id=existing.id,
        capability=Capability.MODEL_PLATFORM,
    )

    new_user = auth.create_user(
        user_id="new-id",
        username="new-user",
        password_hash="test",
        role="user",
    )
    EntitlementRepository(database_path)
    assert not repository.has_active(
        user_id=new_user.id,
        capability=Capability.MODEL_PLATFORM,
    )


def test_entitlement_can_expire_and_be_revoked(tmp_path) -> None:
    database_path = tmp_path / "lifecycle.db"
    auth = AuthRepository(database_path)
    user = auth.create_user(
        user_id="user-id",
        username="user",
        password_hash="test",
        role="user",
    )
    repository = EntitlementRepository(database_path)
    expired = repository.grant(
        user_id=user.id,
        capability=Capability.MODEL_BYOK,
        source=EntitlementSource.ADMIN,
        created_by=None,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    assert not repository.has_active(
        user_id=user.id,
        capability=Capability.MODEL_BYOK,
    )
    assert repository.revoke(expired.id)
    assert not repository.revoke(expired.id)
