"""使用 SQLite 原子维护用户月度模型配额。"""

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

from app.quota.models import QuotaStatus, UserQuota


class QuotaRepository:
    """为本地模式提供与 PostgreSQL 一致的配额语义。"""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_database()

    def get_status(self, user_id: str, period_start: date) -> QuotaStatus:
        with closing(self._connect()) as connection:
            quota = self._read_quota(connection, user_id)
            usage = connection.execute(
                """
                SELECT request_count, token_count
                FROM quota_usage
                WHERE user_id = ? AND period_start = ?
                """,
                (user_id, period_start.isoformat()),
            ).fetchone()
        return QuotaStatus(
            quota=quota,
            period_start=period_start,
            request_count=0 if usage is None else int(usage["request_count"]),
            token_count=0 if usage is None else int(usage["token_count"]),
        )

    def set_quota(
        self,
        *,
        user_id: str,
        monthly_request_limit: int | None,
        monthly_token_limit: int | None,
        updated_by: str | None,
    ) -> UserQuota:
        self._validate_limit(monthly_request_limit)
        self._validate_limit(monthly_token_limit)
        updated_at = datetime.now(UTC)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO user_quotas (
                    user_id, monthly_request_limit, monthly_token_limit,
                    updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    monthly_request_limit = excluded.monthly_request_limit,
                    monthly_token_limit = excluded.monthly_token_limit,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    monthly_request_limit,
                    monthly_token_limit,
                    updated_by,
                    updated_at.isoformat(),
                ),
            )
        return UserQuota(
            user_id=user_id,
            monthly_request_limit=monthly_request_limit,
            monthly_token_limit=monthly_token_limit,
            updated_by=updated_by,
            updated_at=updated_at,
        )

    def reserve_model_request(self, user_id: str, period_start: date) -> bool:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                quota = self._read_quota(connection, user_id)
                usage = connection.execute(
                    """
                    SELECT request_count, token_count
                    FROM quota_usage
                    WHERE user_id = ? AND period_start = ?
                    """,
                    (user_id, period_start.isoformat()),
                ).fetchone()
                requests = 0 if usage is None else int(usage["request_count"])
                tokens = 0 if usage is None else int(usage["token_count"])
                if (
                    quota.monthly_request_limit is not None
                    and requests >= quota.monthly_request_limit
                ) or (
                    quota.monthly_token_limit is not None
                    and tokens >= quota.monthly_token_limit
                ):
                    connection.rollback()
                    return False
                connection.execute(
                    """
                    INSERT INTO quota_usage (
                        user_id, period_start, request_count, token_count
                    ) VALUES (?, ?, 1, 0)
                    ON CONFLICT(user_id, period_start) DO UPDATE SET
                        request_count = quota_usage.request_count + 1
                    """,
                    (user_id, period_start.isoformat()),
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def add_tokens(self, user_id: str, period_start: date, tokens: int) -> None:
        if tokens <= 0:
            return
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO quota_usage (
                    user_id, period_start, request_count, token_count
                ) VALUES (?, ?, 0, ?)
                ON CONFLICT(user_id, period_start) DO UPDATE SET
                    token_count = quota_usage.token_count + excluded.token_count
                """,
                (user_id, period_start.isoformat(), tokens),
            )

    def _read_quota(self, connection: sqlite3.Connection, user_id: str) -> UserQuota:
        row = connection.execute(
            """
            SELECT user_id, monthly_request_limit, monthly_token_limit,
                   updated_by, updated_at
            FROM user_quotas WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            return UserQuota(user_id, None, None, None, datetime.now(UTC))
        return UserQuota(
            user_id=row["user_id"],
            monthly_request_limit=row["monthly_request_limit"],
            monthly_token_limit=row["monthly_token_limit"],
            updated_by=row["updated_by"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _validate_limit(value: int | None) -> None:
        if value is not None and value <= 0:
            raise ValueError("配额必须大于 0 或留空。")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_quotas (
                    user_id TEXT PRIMARY KEY,
                    monthly_request_limit INTEGER
                        CHECK (monthly_request_limit > 0),
                    monthly_token_limit INTEGER
                        CHECK (monthly_token_limit > 0),
                    updated_by TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                    FOREIGN KEY (updated_by) REFERENCES users (id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS quota_usage (
                    user_id TEXT NOT NULL,
                    period_start TEXT NOT NULL,
                    request_count INTEGER NOT NULL DEFAULT 0
                        CHECK (request_count >= 0),
                    token_count INTEGER NOT NULL DEFAULT 0
                        CHECK (token_count >= 0),
                    PRIMARY KEY (user_id, period_start),
                    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
                );
                """
            )
