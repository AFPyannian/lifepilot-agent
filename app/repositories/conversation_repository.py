"""持久化会话元数据。"""


import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Conversation:
    """表示一条会话元数据记录。"""

    owner_id: str
    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationRepository:
    """管理 SQLite 中的会话元数据。"""

    def __init__(
        self,
        database_path: str | Path,
    ) -> None:
        """保存数据库路径并初始化会话表。"""
        self._database_path = Path(
            database_path
        )

        self._database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize_database()

    def record_message(
        self,
        owner_id: str,
        thread_id: str,
        first_message: str,
    ) -> None:
        """根据首条消息创建会话，或刷新已有会话。"""

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        title = self._build_title(
            first_message
        )

        with closing(
            self._connect()
        ) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO conversations (
                        owner_id,
                        thread_id,
                        title,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (
                        owner_id,
                        thread_id
                    )
                    DO UPDATE SET
                        updated_at =
                            excluded.updated_at
                    """,
                    (
                        owner_id,
                        thread_id,
                        title,
                        timestamp,
                        timestamp,
                    ),
                )

    def touch(
        self,
        owner_id: str,
        thread_id: str,
    ) -> bool:
        """刷新会话最后活动时间。"""

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        with closing(
            self._connect()
        ) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE conversations
                    SET updated_at = ?
                    WHERE owner_id = ?
                      AND thread_id = ?
                    """,
                    (
                        timestamp,
                        owner_id,
                        thread_id,
                    ),
                )

                return cursor.rowcount > 0

    def list_conversations(
        self,
        owner_id: str,
        limit: int = 50,
    ) -> list[Conversation]:
        """按最近活动时间返回指定用户的会话。"""

        if limit <= 0:
            raise ValueError(
                "会话列表数量必须大于0"
            )

        with closing(
            self._connect()
        ) as connection:
            rows = connection.execute(
                """
                SELECT
                    owner_id,
                    thread_id,
                    title,
                    created_at,
                    updated_at
                FROM conversations
                WHERE owner_id = ?
                ORDER BY
                    updated_at DESC,
                    created_at DESC
                LIMIT ?
                """,
                (
                    owner_id,
                    limit,
                ),
            ).fetchall()

        return [
            self._row_to_conversation(
                row
            )
            for row in rows
        ]

    def get(
        self,
        owner_id: str,
        thread_id: str,
    ) -> Conversation | None:
        """读取指定用户拥有的一段会话。"""

        with closing(
            self._connect()
        ) as connection:
            row = connection.execute(
                """
                SELECT
                    owner_id,
                    thread_id,
                    title,
                    created_at,
                    updated_at
                FROM conversations
                WHERE owner_id = ?
                  AND thread_id = ?
                """,
                (
                    owner_id,
                    thread_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_conversation(
            row
        )

    def rename(
        self,
        owner_id: str,
        thread_id: str,
        title: str,
    ) -> bool:
        """修改指定用户拥有的会话标题。"""

        clean_title = " ".join(
            title.split()
        )

        if not clean_title:
            raise ValueError(
                "会话标题不能为空"
            )

        if len(clean_title) > 80:
            raise ValueError(
                "会话标题不能超过80个字符"
            )

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        with closing(
            self._connect()
        ) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE conversations
                    SET
                        title = ?,
                        updated_at = ?
                    WHERE owner_id = ?
                      AND thread_id = ?
                    """,
                    (
                        clean_title,
                        timestamp,
                        owner_id,
                        thread_id,
                    ),
                )

                return cursor.rowcount > 0

    def delete(
        self,
        owner_id: str,
        thread_id: str,
    ) -> bool:
        """删除指定用户拥有的会话元数据。"""

        with closing(
            self._connect()
        ) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    DELETE FROM conversations
                    WHERE owner_id = ?
                      AND thread_id = ?
                    """,
                    (
                        owner_id,
                        thread_id,
                    ),
                )

                return cursor.rowcount > 0

    def _connect(
        self,
    ) -> sqlite3.Connection:
        """打开启用行对象访问的 SQLite 连接。"""
        connection = sqlite3.connect(
            self._database_path
        )

        connection.row_factory = (
            sqlite3.Row
        )

        return connection

    def _initialize_database(
        self,
    ) -> None:
        """创建会话表和查询索引。"""
        with closing(
            self._connect()
        ) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS
                        conversations (
                            owner_id TEXT NOT NULL,
                            thread_id TEXT NOT NULL,
                            title TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            PRIMARY KEY (
                                owner_id,
                                thread_id
                            )
                        )
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_conversations_owner_updated
                    ON conversations (
                        owner_id,
                        updated_at DESC
                    )
                    """
                )

    @staticmethod
    def _row_to_conversation(
        row: sqlite3.Row,
    ) -> Conversation:
        """将数据库行转换为会话对象。"""
        return Conversation(
            owner_id=row["owner_id"],
            thread_id=row["thread_id"],
            title=row["title"],
            created_at=(
                datetime.fromisoformat(
                    row["created_at"]
                )
            ),
            updated_at=(
                datetime.fromisoformat(
                    row["updated_at"]
                )
            ),
        )

    @staticmethod
    def _build_title(
        message: str,
    ) -> str:
        """根据首条消息生成长度受限的默认标题。"""
        normalized = " ".join(
            message.split()
        )

        if not normalized:
            return "新对话"

        if len(normalized) <= 30:
            return normalized

        return normalized[:30] + "…"