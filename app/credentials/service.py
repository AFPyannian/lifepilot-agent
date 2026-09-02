"""管理用户模型凭据的验证和生命周期。"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from pydantic import SecretStr

from app.credentials.crypto import CredentialCipher
from app.credentials.errors import (
    CredentialNotConfiguredError,
    CredentialValidationError,
)
from app.credentials.models import ProviderCredentialMetadata, ResolvedCredential
from app.repositories.protocols import ProviderCredentialRepositoryProtocol

logger = logging.getLogger("lifepilot.credentials")


class CredentialValidator(Protocol):
    """描述受控验证供应商凭据所需的接口。"""

    def validate(self, secret: SecretStr) -> None:
        """验证凭据；失败时抛出安全业务异常。"""
        ...


class ProviderCredentialService:
    """验证、加密并管理当前用户的 DeepSeek Key。"""

    def __init__(
        self,
        *,
        repository: ProviderCredentialRepositoryProtocol,
        cipher: CredentialCipher | None,
        validator: CredentialValidator,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._validator = validator

    def save_or_rotate(
        self,
        *,
        user_id: str,
        api_key: SecretStr,
    ) -> ProviderCredentialMetadata:
        """验证并创建或原位轮换用户凭据。"""
        clean_value = api_key.get_secret_value().strip()

        if not clean_value or len(clean_value) > 1024:
            raise CredentialValidationError("Invalid DeepSeek credential format.")
        if self._cipher is None:
            raise CredentialValidationError("BYOK encryption is not configured.")

        normalized_secret = SecretStr(clean_value)
        self._validator.validate(normalized_secret)

        existing = self._repository.get(user_id=user_id, provider="deepseek")
        credential_id = existing.id if existing is not None else str(uuid4())
        encrypted = self._cipher.encrypt(
            secret=normalized_secret,
            credential_id=credential_id,
            user_id=user_id,
            provider="deepseek",
        )
        record = self._repository.upsert_active(
            credential_id=credential_id,
            user_id=user_id,
            provider="deepseek",
            encrypted_secret=encrypted.ciphertext,
            encryption_key_version=encrypted.key_version,
            fingerprint=hashlib.sha256(clean_value.encode()).hexdigest(),
            masked_suffix=clean_value[-4:],
            validated_at=datetime.now(UTC),
        )

        logger.info(
            "Provider credential stored user_id=%s provider=deepseek",
            user_id,
        )
        return self._to_metadata(record)

    def resolve_active(self, *, user_id: str) -> ResolvedCredential:
        """仅供模型网关解密当前用户的有效凭据。"""
        record = self._repository.get(user_id=user_id, provider="deepseek")

        if (
            record is None
            or record.status != "active"
            or record.encrypted_secret is None
            or record.encryption_key_version is None
        ):
            raise CredentialNotConfiguredError("Active credential is unavailable.")
        if self._cipher is None:
            raise CredentialNotConfiguredError("BYOK encryption is not configured.")

        return ResolvedCredential(
            credential_id=record.id,
            secret=self._cipher.decrypt(
                ciphertext=record.encrypted_secret,
                key_version=record.encryption_key_version,
                credential_id=record.id,
                user_id=record.user_id,
                provider=record.provider,
            ),
        )

    def get_metadata(self, *, user_id: str) -> ProviderCredentialMetadata | None:
        """读取不会暴露密文和指纹的凭据元数据。"""
        record = self._repository.get(user_id=user_id, provider="deepseek")
        return None if record is None else self._to_metadata(record)

    def mark_used(self, credential_id: str) -> None:
        """记录用户凭据最后成功使用时间。"""
        self._repository.mark_used(
            credential_id=credential_id,
            used_at=datetime.now(UTC),
        )

    def mark_invalid(self, credential_id: str) -> None:
        """将认证失败的单条用户凭据标记为无效。"""
        self._repository.mark_invalid(credential_id=credential_id)

    def revoke(self, *, user_id: str) -> bool:
        """撤销用户凭据并销毁可恢复的密文。"""
        return self._repository.revoke(user_id=user_id, provider="deepseek")

    def delete(self, *, user_id: str) -> bool:
        """删除用户凭据记录。"""
        return self._repository.delete(user_id=user_id, provider="deepseek")

    @staticmethod
    def _to_metadata(record: Any) -> ProviderCredentialMetadata:
        return ProviderCredentialMetadata(
            provider=record.provider,
            masked_suffix=record.masked_suffix,
            status=record.status,
            validated_at=record.validated_at,
            last_used_at=record.last_used_at,
            created_at=record.created_at,
            revoked_at=record.revoked_at,
        )
