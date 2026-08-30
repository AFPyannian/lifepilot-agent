"""定义用户模型凭据领域对象。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import SecretStr

ProviderName = Literal["deepseek"]
CredentialStatus = Literal["active", "invalid", "revoked"]
ModelMode = Literal["BYOK", "PLATFORM"]


@dataclass(frozen=True)
class ProviderCredentialRecord:
    """数据库内部使用的完整凭据记录。"""

    id: str
    user_id: str
    provider: ProviderName
    encrypted_secret: str | None
    encryption_key_version: str | None
    fingerprint: str | None
    masked_suffix: str
    status: CredentialStatus
    validated_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class ProviderCredentialMetadata:
    """允许返回给用户的凭据元数据。"""

    provider: ProviderName
    masked_suffix: str
    status: CredentialStatus
    validated_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class ResolvedCredential:
    """只允许模型网关在单次调用中使用的解密凭据。"""

    credential_id: str
    secret: SecretStr
