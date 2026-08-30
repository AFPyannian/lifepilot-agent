"""持久化模型调用事件并提供用户级汇总。"""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import cast

from app.credentials.models import ModelMode
from app.usage.models import UsageEvent, UsageStatus, UsageSummary


class UsageRepository:
    """用事件 ID 保证模型调用事件写入幂等。"""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def begin(self, event: UsageEvent) -> bool:
        """创建 started 事件；重复 event_id 不会重复计数。"""
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO usage_events (
                    event_id, request_id, user_id, thread_id, provider, model,
                    credential_mode, input_tokens, output_tokens, total_tokens,
                    status, error_code, started_at, completed_at, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL,
                          'started', NULL, ?, NULL, NULL)
                """,
                (
                    event.event_id,
                    event.request_id,
                    event.user_id,
                    event.thread_id,
                    event.provider,
                    event.model,
                    event.credential_mode,
                    event.started_at.isoformat(),
                ),
            )
            return cursor.rowcount > 0

    def mark_succeeded(
        self,
        *,
        event_id: str,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        completed_at: datetime,
        duration_ms: int,
    ) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET status = 'succeeded', input_tokens = ?, output_tokens = ?,
                    total_tokens = ?, completed_at = ?, duration_ms = ?
                WHERE event_id = ? AND status = 'started'
                """,
                (
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    completed_at.isoformat(),
                    duration_ms,
                    event_id,
                ),
            )
            return cursor.rowcount > 0

    def mark_failed(
        self,
        *,
        event_id: str,
        error_code: str,
        completed_at: datetime,
        duration_ms: int,
    ) -> bool:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                UPDATE usage_events
                SET status = 'failed', error_code = ?, completed_at = ?,
                    duration_ms = ?
                WHERE event_id = ? AND status = 'started'
                """,
                (error_code, completed_at.isoformat(), duration_ms, event_id),
            )
            return cursor.rowcount > 0

    def list_for_user(
        self,
        *,
        user_id: str,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[UsageEvent]:
        bounded_limit = min(max(limit, 1), 100)
        query = """
            SELECT event_id, request_id, user_id, thread_id, provider, model,
                   credential_mode, input_tokens, output_tokens, total_tokens,
                   status, error_code, started_at, completed_at, duration_ms
            FROM usage_events WHERE user_id = ?
        """
        parameters: list[object] = [user_id]
        if before is not None:
            query += " AND started_at < ?"
            parameters.append(before.isoformat())
        query += " ORDER BY started_at DESC, event_id DESC LIMIT ?"
        parameters.append(bounded_limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._row_to_event(row) for row in rows]

    def summarize(
        self,
        *,
        user_id: str,
        since: datetime,
        until: datetime,
    ) -> UsageSummary:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT COUNT(DISTINCT request_id) AS requests,
                       SUM(status = 'succeeded') AS successful_calls,
                       SUM(status = 'failed') AS failed_calls,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       SUM(status = 'succeeded' AND credential_mode = 'BYOK')
                           AS byok_calls,
                       SUM(status = 'succeeded' AND credential_mode = 'PLATFORM')
                           AS platform_calls
                FROM usage_events
                WHERE user_id = ? AND started_at >= ? AND started_at < ?
                """,
                (user_id, since.isoformat(), until.isoformat()),
            ).fetchone()
        return UsageSummary(
            since=since,
            until=until,
            requests=int(row["requests"] or 0),
            successful_calls=int(row["successful_calls"] or 0),
            failed_calls=int(row["failed_calls"] or 0),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            total_tokens=int(row["total_tokens"] or 0),
            byok_calls=int(row["byok_calls"] or 0),
            platform_calls=int(row["platform_calls"] or 0),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    provider TEXT NOT NULL CHECK (provider = 'deepseek'),
                    model TEXT NOT NULL,
                    credential_mode TEXT NOT NULL
                        CHECK (credential_mode IN ('BYOK', 'PLATFORM')),
                    input_tokens INTEGER CHECK (input_tokens >= 0),
                    output_tokens INTEGER CHECK (output_tokens >= 0),
                    total_tokens INTEGER CHECK (total_tokens >= 0),
                    status TEXT NOT NULL
                        CHECK (status IN ('started', 'succeeded', 'failed')),
                    error_code TEXT CHECK (error_code IS NULL OR error_code IN (
                        'provider_auth', 'provider_rate_limit',
                        'provider_unavailable', 'provider_error'
                    )),
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    duration_ms INTEGER CHECK (duration_ms >= 0),
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE RESTRICT
                );

                CREATE INDEX IF NOT EXISTS idx_usage_events_user_started
                ON usage_events (user_id, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_request
                ON usage_events (request_id);
                CREATE INDEX IF NOT EXISTS idx_usage_events_mode_started
                ON usage_events (credential_mode, started_at DESC);
                """
            )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> UsageEvent:
        return UsageEvent(
            event_id=row["event_id"],
            request_id=row["request_id"],
            user_id=row["user_id"],
            thread_id=row["thread_id"],
            provider=row["provider"],
            model=row["model"],
            credential_mode=cast(ModelMode, row["credential_mode"]),
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            total_tokens=row["total_tokens"],
            status=cast(UsageStatus, row["status"]),
            error_code=row["error_code"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=(
                None
                if row["completed_at"] is None
                else datetime.fromisoformat(row["completed_at"])
            ),
            duration_ms=row["duration_ms"],
        )
