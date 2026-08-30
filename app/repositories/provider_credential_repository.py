"""持久化用户加密后的模型供应商凭据。"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from app.credentials.models import ProviderCredentialRecord


class ProviderCredentialRepository:
    """管理每名用户唯一的 DeepSeek 凭据记录。"""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def get(
        self,
        *,
        user_id: str,
        provider: str,
    ) -> ProviderCredentialRecord | None:
        """读取指定用户的凭据记录。"""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, user_id, provider, encrypted_secret,
                       encryption_key_version, fingerprint, masked_suffix,
                       status, validated_at, last_used_at, created_at,
                       updated_at, revoked_at
                FROM provider_credentials
                WHERE user_id = ? AND provider = ?
                """,
                (user_id, provider),
            ).fetchone()

        return None if row is None else self._row_to_record(row)

    def list_by_key_version(
        self,
        key_version: str,
    ) -> list[ProviderCredentialRecord]:
        """列出需要重新封装的有效凭据。"""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, provider, encrypted_secret,
                       encryption_key_version, fingerprint, masked_suffix,
                       status, validated_at, last_used_at, created_at,
                       updated_at, revoked_at
                FROM provider_credentials
                WHERE encryption_key_version = ?
                  AND encrypted_secret IS NOT NULL
                ORDER BY created_at
                """,
                (key_version,),
            ).fetchall()

        return [self._row_to_record(row) for row in rows]

    def upsert_active(
        self,
        *,
        credential_id: str,
        user_id: str,
        provider: str,
        encrypted_secret: str,
        encryption_key_version: str,
        fingerprint: str,
        masked_suffix: str,
        validated_at: datetime,
    ) -> ProviderCredentialRecord:
        """创建或原位轮换用户凭据。"""
        timestamp = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO provider_credentials (
                    id, user_id, provider, encrypted_secret,
                    encryption_key_version, fingerprint, masked_suffix,
                    status, validated_at, last_used_at, created_at,
                    updated_at, revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, NULL, ?, ?, NULL)
                ON CONFLICT(user_id, provider)
                DO UPDATE SET
                    encrypted_secret = excluded.encrypted_secret,
                    encryption_key_version = excluded.encryption_key_version,
                    fingerprint = excluded.fingerprint,
                    masked_suffix = excluded.masked_suffix,
                    status = 'active',
                    validated_at = excluded.validated_at,
                    last_used_at = NULL,
                    updated_at = excluded.updated_at,
                    revoked_at = NULL
                """,
                (
                    credential_id,
                    user_id,
                    provider,
                    encrypted_secret,
                    encryption_key_version,
                    fingerprint,
                    masked_suffix,
                    validated_at.isoformat(),
                    timestamp,
                    timestamp,
                ),
            )

        record = self.get(user_id=user_id, provider=provider)

        if record is None:
            raise RuntimeError("保存模型凭据后无法读取记录。")

        return record

    def replace_encrypted_secret(
        self,
        *,
        credential_id: str,
        encrypted_secret: str,
        encryption_key_version: str,
    ) -> bool:
        """更新主密钥轮换后的密文。"""
        timestamp = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE provider_credentials
                SET encrypted_secret = ?, encryption_key_version = ?, updated_at = ?
                WHERE id = ? AND encrypted_secret IS NOT NULL
                """,
                (
                    encrypted_secret,
                    encryption_key_version,
                    timestamp,
                    credential_id,
                ),
            )
            return cursor.rowcount > 0

    def mark_used(self, *, credential_id: str, used_at: datetime) -> None:
        """记录一次成功的凭据使用。"""
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE provider_credentials
                SET last_used_at = ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (used_at.isoformat(), used_at.isoformat(), credential_id),
            )

    def mark_invalid(self, *, credential_id: str) -> None:
        """只禁用发生认证错误的凭据。"""
        timestamp = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE provider_credentials
                SET status = 'invalid', updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (timestamp, credential_id),
            )

    def revoke(self, *, user_id: str, provider: str) -> bool:
        """撤销凭据并清除所有可恢复 Key 的字段。"""
        timestamp = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE provider_credentials
                SET encrypted_secret = NULL,
                    encryption_key_version = NULL,
                    fingerprint = NULL,
                    status = 'revoked',
                    updated_at = ?,
                    revoked_at = ?
                WHERE user_id = ? AND provider = ? AND status != 'revoked'
                """,
                (timestamp, timestamp, user_id, provider),
            )
            return cursor.rowcount > 0

    def delete(self, *, user_id: str, provider: str) -> bool:
        """物理删除用户凭据元数据。"""
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                DELETE FROM provider_credentials
                WHERE user_id = ? AND provider = ?
                """,
                (user_id, provider),
            )
            return cursor.rowcount > 0

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_credentials (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    encrypted_secret TEXT,
                    encryption_key_version TEXT,
                    fingerprint TEXT,
                    masked_suffix TEXT NOT NULL,
                    status TEXT NOT NULL,
                    validated_at TEXT,
                    last_used_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    UNIQUE (user_id, provider),
                    CHECK (provider IN ('deepseek')),
                    CHECK (status IN ('active', 'invalid', 'revoked')),
                    CHECK (
                        status != 'active'
                        OR (
                            encrypted_secret IS NOT NULL
                            AND encryption_key_version IS NOT NULL
                            AND fingerprint IS NOT NULL
                        )
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_provider_credentials_user_status
                ON provider_credentials (user_id, status);
                """
            )

    @staticmethod
    def _optional_datetime(value: str | None) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)

    @classmethod
    def _row_to_record(cls, row: sqlite3.Row) -> ProviderCredentialRecord:
        return ProviderCredentialRecord(
            id=row["id"],
            user_id=row["user_id"],
            provider=row["provider"],
            encrypted_secret=row["encrypted_secret"],
            encryption_key_version=row["encryption_key_version"],
            fingerprint=row["fingerprint"],
            masked_suffix=row["masked_suffix"],
            status=row["status"],
            validated_at=cls._optional_datetime(row["validated_at"]),
            last_used_at=cls._optional_datetime(row["last_used_at"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            revoked_at=cls._optional_datetime(row["revoked_at"]),
        )
