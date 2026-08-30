"""使用带认证的加密算法保护用户模型凭据。"""

import base64
import os
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

from app.credentials.errors import CredentialDecryptionError


@dataclass(frozen=True)
class EncryptedCredential:
    """保存可持久化的密文和主密钥版本。"""

    ciphertext: str
    key_version: str


class CredentialCipher:
    """使用 AES-256-GCM 加密并校验模型凭据。"""

    def __init__(
        self,
        *,
        keyring: Mapping[str, bytes],
        active_key_version: str,
    ) -> None:
        if active_key_version not in keyring:
            raise ValueError("当前主密钥版本不存在")
        if any(len(key) != 32 for key in keyring.values()):
            raise ValueError("AES-256-GCM主密钥必须为32字节")

        self._keyring = dict(keyring)
        self._active_key_version = active_key_version

    @property
    def active_key_version(self) -> str:
        """返回新凭据使用的主密钥版本。"""
        return self._active_key_version

    def encrypt(
        self,
        *,
        secret: SecretStr,
        credential_id: str,
        user_id: str,
        provider: str,
    ) -> EncryptedCredential:
        """加密凭据，并将密文绑定到用户和凭据记录。"""
        nonce = os.urandom(12)
        plaintext = secret.get_secret_value().encode("utf-8")
        aad = self._build_aad(
            credential_id=credential_id,
            user_id=user_id,
            provider=provider,
        )
        ciphertext = AESGCM(self._keyring[self._active_key_version]).encrypt(
            nonce,
            plaintext,
            aad,
        )
        payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")

        return EncryptedCredential(
            ciphertext=payload,
            key_version=self._active_key_version,
        )

    def decrypt(
        self,
        *,
        ciphertext: str,
        key_version: str,
        credential_id: str,
        user_id: str,
        provider: str,
    ) -> SecretStr:
        """解密凭据；记录被调换或篡改时安全失败。"""
        key = self._keyring.get(key_version)

        if key is None:
            raise CredentialDecryptionError("Credential key version is unavailable.")

        try:
            payload = base64.urlsafe_b64decode(ciphertext)

            if len(payload) <= 12:
                raise ValueError("Encrypted credential payload is too short.")

            plaintext = AESGCM(key).decrypt(
                payload[:12],
                payload[12:],
                self._build_aad(
                    credential_id=credential_id,
                    user_id=user_id,
                    provider=provider,
                ),
            )
            return SecretStr(plaintext.decode("utf-8"))
        except (ValueError, InvalidTag, UnicodeDecodeError):
            raise CredentialDecryptionError(
                "Provider credential decryption failed."
            ) from None

    @staticmethod
    def _build_aad(
        *,
        credential_id: str,
        user_id: str,
        provider: str,
    ) -> bytes:
        """生成阻止跨用户和跨供应商调换密文的附加认证数据。"""
        return f"lifepilot:{credential_id}:{user_id}:{provider}".encode()
