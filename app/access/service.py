"""提供本地管理员授权用例。"""

from datetime import datetime

from app.access.models import Capability, EntitlementRecord, EntitlementSource
from app.repositories.entitlement_repository import EntitlementRepository


class EntitlementService:
    """封装授权发放、撤销和查询。"""

    def __init__(self, repository: EntitlementRepository) -> None:
        self._repository = repository

    def grant_admin(
        self,
        *,
        user_id: str,
        created_by: str,
        capability: Capability,
        expires_at: datetime | None = None,
    ) -> EntitlementRecord:
        return self._repository.grant(
            user_id=user_id,
            capability=capability,
            source=EntitlementSource.ADMIN,
            created_by=created_by,
            expires_at=expires_at,
        )

    def revoke(self, entitlement_id: str) -> bool:
        return self._repository.revoke(entitlement_id)

    def list_for_user(self, user_id: str) -> list[EntitlementRecord]:
        return self._repository.list_for_user(user_id)
