"""使用当前活动主密钥重新加密旧版本的用户模型凭据。"""

import argparse

from app.config import get_settings
from app.credentials.crypto import CredentialCipher
from app.repositories.provider_credential_repository import (
    ProviderCredentialRepository,
)


def rewrap_credentials(source_version: str) -> int:
    """将指定旧版本密文逐条安全迁移到当前活动版本。"""
    settings = get_settings()
    keyring = settings.provider_credential_keyring()
    target_version = settings.provider_credential_active_key_version

    if source_version == target_version:
        raise ValueError("源版本不能与当前活动版本相同。")
    if source_version not in keyring:
        raise ValueError("源版本主密钥不在当前密钥环中。")
    if target_version not in keyring:
        raise ValueError("活动版本主密钥不在当前密钥环中。")

    repository = ProviderCredentialRepository(settings.app_database_path)
    cipher = CredentialCipher(
        keyring=keyring,
        active_key_version=target_version,
    )
    records = repository.list_by_key_version(source_version)
    migrated = 0

    for record in records:
        if record.encrypted_secret is None or record.encryption_key_version is None:
            continue

        secret = cipher.decrypt(
            ciphertext=record.encrypted_secret,
            key_version=record.encryption_key_version,
            credential_id=record.id,
            user_id=record.user_id,
            provider=record.provider,
        )
        encrypted = cipher.encrypt(
            secret=secret,
            credential_id=record.id,
            user_id=record.user_id,
            provider=record.provider,
        )

        if repository.replace_encrypted_secret(
            credential_id=record.id,
            encrypted_secret=encrypted.ciphertext,
            encryption_key_version=encrypted.key_version,
        ):
            migrated += 1

    return migrated


def main() -> None:
    """解析旧版本参数并输出不含凭据内容的迁移结果。"""
    parser = argparse.ArgumentParser(description="重新封装 LifePilot 用户模型凭据。")
    parser.add_argument(
        "--from-version",
        required=True,
        help="需要迁移的旧主密钥版本，例如 v1。",
    )
    args = parser.parse_args()
    migrated = rewrap_credentials(args.from_version)
    print(f"已重新加密 {migrated} 条模型凭据。")


if __name__ == "__main__":
    main()
