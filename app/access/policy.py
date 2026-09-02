"""在单一边界判断账号与模型能力。"""

from typing import Protocol

from app.access.errors import AccessDeniedError
from app.access.models import AccessDecision, Capability
from app.config import Settings
from app.credentials.service import ProviderCredentialService
from app.repositories.protocols import (
    AuthRepositoryProtocol,
    EntitlementRepositoryProtocol,
)


class AccessPolicyProtocol(Protocol):
    """描述 API 与模型网关依赖的访问策略接口。"""

    def evaluate(self, *, user_id: str, capability: Capability) -> AccessDecision: ...

    def authorize(self, *, user_id: str, capability: Capability) -> None: ...


class AccessPolicy:
    """组合账号状态、实例开关、用户凭据和授权记录。"""

    def __init__(
        self,
        *,
        settings: Settings,
        auth_repository: AuthRepositoryProtocol,
        entitlement_repository: EntitlementRepositoryProtocol,
        credential_service: ProviderCredentialService,
    ) -> None:
        self._settings = settings
        self._auth_repository = auth_repository
        self._entitlement_repository = entitlement_repository
        self._credential_service = credential_service

    def evaluate(self, *, user_id: str, capability: Capability) -> AccessDecision:
        """返回能力判断，供 API 展示或网关强制执行。"""
        user = self._auth_repository.get_user_by_id(user_id)
        if user is None or user.status != "active":
            return self._deny(capability, "account_inactive", "当前账号不可用。")

        if capability == Capability.AGENT_CHAT:
            return self._allow(capability)

        if capability == Capability.MODEL_BYOK:
            if not self._settings.byok_enabled:
                return self._deny(
                    capability,
                    "byok_disabled",
                    "当前实例未开放用户自带模型 Key。",
                )
            metadata = self._credential_service.get_metadata(user_id=user_id)
            if metadata is None or metadata.status != "active":
                return self._deny(
                    capability,
                    "credential_required",
                    "请先配置有效的 DeepSeek API Key。",
                )
            return self._allow(capability)

        if capability == Capability.MODEL_PLATFORM:
            if not self._settings.platform_model_enabled:
                return self._deny(
                    capability,
                    "platform_disabled",
                    "当前实例未开放平台模型。",
                )
            if not self._entitlement_repository.has_active(
                user_id=user_id,
                capability=capability,
            ):
                return self._deny(
                    capability,
                    "entitlement_required",
                    "当前账号尚未获得平台模型使用权限。",
                )
            return self._allow(capability)

        return self._deny(capability, "unknown_capability", "当前功能不可用。")

    def authorize(self, *, user_id: str, capability: Capability) -> None:
        """强制执行授权判断，拒绝时抛出安全业务异常。"""
        decision = self.evaluate(user_id=user_id, capability=capability)
        if not decision.allowed:
            raise AccessDeniedError(
                capability=decision.capability,
                reason_code=decision.reason_code,
                user_message=decision.user_message,
            )

    @staticmethod
    def _allow(capability: Capability) -> AccessDecision:
        return AccessDecision(True, capability, "allowed", "允许使用。")

    @staticmethod
    def _deny(
        capability: Capability,
        reason_code: str,
        user_message: str,
    ) -> AccessDecision:
        return AccessDecision(False, capability, reason_code, user_message)


class AllowAllAccessPolicy:
    """仅用于注入静态图的测试边界。"""

    def evaluate(self, *, user_id: str, capability: Capability) -> AccessDecision:
        del user_id
        return AccessDecision(True, capability, "allowed", "允许使用。")

    def authorize(self, *, user_id: str, capability: Capability) -> None:
        del user_id, capability
