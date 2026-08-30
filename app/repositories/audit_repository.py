"""持久化不包含秘密的安全审计事件。"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class AuditEvent:
    """表示后台可查询的一条脱敏审计事件。"""

    id: str
    request_id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    created_at: datetime


class AuditRepository:
    """管理 SQLite 审计事件。"""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def record(
        self,
        *,
        request_id: str,
        user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str | None,
        outcome: str,
    ) -> None:
        """写入一条不含密码、Token 和正文内容的审计事件。"""
        timestamp = datetime.now(UTC).isoformat()

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO audit_events (
                    id, request_id, user_id, action,
                    resource_type, resource_id, outcome, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    request_id,
                    user_id,
                    action,
                    resource_type,
                    resource_id,
                    outcome,
                    timestamp,
                ),
            )

    def list_recent(
        self, *, limit: int = 100, user_id: str | None = None
    ) -> list[AuditEvent]:
        """按时间倒序返回后台审计记录。"""
        bounded_limit = min(max(limit, 1), 500)
        query = """
            SELECT id, request_id, user_id, action, resource_type,
                   resource_id, outcome, created_at
            FROM audit_events
        """
        parameters: list[object] = []
        if user_id is not None:
            query += " WHERE user_id = ?"
            parameters.append(user_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        parameters.append(bounded_limit)
        with closing(self._connect()) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, parameters).fetchall()
        return [
            AuditEvent(
                id=row["id"],
                request_id=row["request_id"],
                user_id=row["user_id"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                outcome=row["outcome"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    user_id TEXT,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT,
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_events_user_created
                ON audit_events (user_id, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_audit_events_request
                ON audit_events (request_id);
                """
            )
