"""持久化用户能力授权并迁移既有平台模型权限。"""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.access.models import (
    Capability,
    EntitlementRecord,
    EntitlementSource,
    EntitlementStatus,
)

MIGRATION_VERSION = "2026_08_phase3_platform_entitlements"


class EntitlementRepository:
    """管理 SQLite 中可撤销、可过期的能力授权。"""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def has_active(
        self,
        *,
        user_id: str,
        capability: Capability,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(UTC)
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM entitlements
                WHERE user_id = ? AND capability = ? AND status = 'active'
                  AND starts_at <= ?
                  AND (expires_at IS NULL OR expires_at > ?)
                LIMIT 1
                """,
                (user_id, capability.value, current.isoformat(), current.isoformat()),
            ).fetchone()
        return row is not None

    def grant(
        self,
        *,
        user_id: str,
        capability: Capability,
        source: EntitlementSource,
        created_by: str | None,
        expires_at: datetime | None = None,
        starts_at: datetime | None = None,
    ) -> EntitlementRecord:
        entitlement_id = str(uuid4())
        created_at = datetime.now(UTC)
        effective_at = starts_at or created_at
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO entitlements (
                    id, user_id, capability, source, status, starts_at,
                    expires_at, created_by, created_at, revoked_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, NULL)
                """,
                (
                    entitlement_id,
                    user_id,
                    capability.value,
                    source.value,
                    effective_at.isoformat(),
                    None if expires_at is None else expires_at.isoformat(),
                    created_by,
                    created_at.isoformat(),
                ),
            )
        record = self.get(entitlement_id)
        if record is None:
            raise RuntimeError("创建授权后无法读取授权记录。")
        return record

    def get(self, entitlement_id: str) -> EntitlementRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT id, user_id, capability, source, status, starts_at,
                       expires_at, created_by, created_at, revoked_at
                FROM entitlements WHERE id = ?
                """,
                (entitlement_id,),
            ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_for_user(self, user_id: str) -> list[EntitlementRecord]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, user_id, capability, source, status, starts_at,
                       expires_at, created_by, created_at, revoked_at
                FROM entitlements
                WHERE user_id = ?
                ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def revoke(self, entitlement_id: str) -> bool:
        revoked_at = datetime.now(UTC).isoformat()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE entitlements
                SET status = 'revoked', revoked_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (revoked_at, entitlement_id),
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
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS entitlements (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    capability TEXT NOT NULL CHECK (capability IN (
                        'agent.chat', 'model.byok', 'model.platform'
                    )),
                    source TEXT NOT NULL CHECK (source IN (
                        'migration', 'admin', 'subscription', 'promotion'
                    )),
                    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
                    starts_at TEXT NOT NULL,
                    expires_at TEXT,
                    created_by TEXT,
                    created_at TEXT NOT NULL,
                    revoked_at TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_entitlements_access
                ON entitlements (user_id, capability, status, expires_at);
                """
            )
            migration = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (MIGRATION_VERSION,),
            ).fetchone()
            if migration is None:
                timestamp = datetime.now(UTC).isoformat()
                users = connection.execute(
                    "SELECT id FROM users WHERE status = 'active'"
                ).fetchall()
                connection.executemany(
                    """
                    INSERT INTO entitlements (
                        id, user_id, capability, source, status, starts_at,
                        expires_at, created_by, created_at, revoked_at
                    ) VALUES (?, ?, 'model.platform', 'migration', 'active',
                              ?, NULL, NULL, ?, NULL)
                    """,
                    [(str(uuid4()), row["id"], timestamp, timestamp) for row in users],
                )
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (MIGRATION_VERSION, timestamp),
                )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> EntitlementRecord:
        return EntitlementRecord(
            id=row["id"],
            user_id=row["user_id"],
            capability=Capability(row["capability"]),
            source=EntitlementSource(row["source"]),
            status=EntitlementStatus(row["status"]),
            starts_at=datetime.fromisoformat(row["starts_at"]),
            expires_at=(
                None
                if row["expires_at"] is None
                else datetime.fromisoformat(row["expires_at"])
            ),
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
            revoked_at=(
                None
                if row["revoked_at"] is None
                else datetime.fromisoformat(row["revoked_at"])
            ),
        )
