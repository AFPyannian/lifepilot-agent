"""使用 SQLite 持久化用户资料和长期记忆。"""


import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

"""
跨会话的长期记忆
1. 并非保存全部聊天记录，而是保存有价值信息，以供需要时使用。
2. 核心： 记忆什么内容、什么时候注入、什么时候更新、什么时候遗忘、什么时候召回
3. 一般架构为: 对话 —— 提取值得记忆的信息 —— 存储 —— 检索 —— 注入当前上下文
4. 记忆内容大致包括：用户资料(偏好、习惯、背景等)、事件记忆(发生过的事件)、经验记忆(从过往会话中沉淀出的内容)、...
"""

@dataclass(frozen=True)
class UserProfile:
    """表示用户的结构化资料。"""

    owner_id: str
    display_name: str | None
    occupation: str | None
    current_goal: str | None
    response_style: str | None
    updated_at: str


@dataclass(frozen=True)
class UserMemory:
    """表示一条用户长期记忆。"""

    id: int
    owner_id: str
    category: str
    content: str
    created_at: str
    updated_at: str


class UserMemoryRepository:
    """管理 SQLite 中的用户资料和长期记忆。"""

    def __init__(self,database_path: str | Path) -> None:
        """保存数据库路径并初始化记忆相关数据表。"""
        self._database_path = Path(database_path)

        self._database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        """打开启用行对象访问的 SQLite 连接。"""
        connection = sqlite3.connect(
            self._database_path
        )
        connection.row_factory = sqlite3.Row

        return connection

    def _initialize_database(self) -> None:
        """创建用户资料、长期记忆及其索引。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS
                        user_profiles (
                            owner_id TEXT PRIMARY KEY,
                            display_name TEXT,
                            occupation TEXT,
                            current_goal TEXT,
                            response_style TEXT,
                            updated_at TEXT NOT NULL
                        )
                    """
                )

                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS
                        user_memories (
                            id INTEGER PRIMARY KEY,
                            owner_id TEXT NOT NULL,
                            category TEXT NOT NULL,
                            content TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            UNIQUE (
                                owner_id,
                                category,
                                content
                            )
                        )
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_user_memories_owner
                    ON user_memories (owner_id)
                    """
                )

    def get_profile(
        self,
        owner_id: str,
    ) -> UserProfile | None:
        """读取指定用户的结构化资料。"""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    owner_id,
                    display_name,
                    occupation,
                    current_goal,
                    response_style,
                    updated_at
                FROM user_profiles
                WHERE owner_id = ?
                """,
                (owner_id,),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_profile(row)

    def update_profile(
        self,
        owner_id: str,
        display_name: str | None = None,
        occupation: str | None = None,
        current_goal: str | None = None,
        response_style: str | None = None,
    ) -> UserProfile:
        """创建或部分更新用户资料。"""
        if all(
            value is None
            for value in (
                display_name,
                occupation,
                current_goal,
                response_style,
            )
        ):
            raise ValueError(
                "At least one profile field is required."
            )

        existing = self.get_profile(owner_id)

        updated_display_name = self._merge_field(
            new_value=display_name,
            old_value=(
                existing.display_name
                if existing is not None
                else None
            ),
            field_name="display name",
        )

        updated_occupation = self._merge_field(
            new_value=occupation,
            old_value=(
                existing.occupation
                if existing is not None
                else None
            ),
            field_name="occupation",
        )

        updated_goal = self._merge_field(
            new_value=current_goal,
            old_value=(
                existing.current_goal
                if existing is not None
                else None
            ),
            field_name="current goal",
        )

        updated_style = self._merge_field(
            new_value=response_style,
            old_value=(
                existing.response_style
                if existing is not None
                else None
            ),
            field_name="response style",
        )

        updated_at = datetime.now(
            timezone.utc
        ).isoformat()

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO user_profiles (
                        owner_id,
                        display_name,
                        occupation,
                        current_goal,
                        response_style,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(owner_id)
                    DO UPDATE SET
                        display_name =
                            excluded.display_name,
                        occupation =
                            excluded.occupation,
                        current_goal =
                            excluded.current_goal,
                        response_style =
                            excluded.response_style,
                        updated_at =
                            excluded.updated_at
                    """,
                    (
                        owner_id,
                        updated_display_name,
                        updated_occupation,
                        updated_goal,
                        updated_style,
                        updated_at,
                    ),
                )

        return UserProfile(
            owner_id=owner_id,
            display_name=updated_display_name,
            occupation=updated_occupation,
            current_goal=updated_goal,
            response_style=updated_style,
            updated_at=updated_at,
        )

    def add_memory(
        self,
        owner_id: str,
        category: str,
        content: str,
    ) -> UserMemory:
        """添加长期记忆，重复内容则返回已有记录。"""
        normalized_category = category.strip()
        normalized_content = content.strip()

        if not normalized_category:
            raise ValueError(
                "Memory category cannot be empty."
            )

        if not normalized_content:
            raise ValueError(
                "Memory content cannot be empty."
            )

        if len(normalized_category) > 50:
            raise ValueError(
                "Memory category is too long."
            )

        if len(normalized_content) > 500:
            raise ValueError(
                "Memory content is too long."
            )

        with closing(self._connect()) as connection:
            existing_row = connection.execute(
                """
                SELECT
                    id,
                    owner_id,
                    category,
                    content,
                    created_at,
                    updated_at
                FROM user_memories
                WHERE owner_id = ?
                  AND category = ?
                  AND content = ?
                """,
                (
                    owner_id,
                    normalized_category,
                    normalized_content,
                ),
            ).fetchone()

            if existing_row is not None:
                return self._row_to_memory(
                    existing_row
                )

            timestamp = datetime.now(
                timezone.utc
            ).isoformat()

            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO user_memories (
                        owner_id,
                        category,
                        content,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        owner_id,
                        normalized_category,
                        normalized_content,
                        timestamp,
                        timestamp,
                    ),
                )

                memory_id = cursor.lastrowid

        if memory_id is None:
            raise RuntimeError(
                "Failed to obtain the memory ID."
            )

        return UserMemory(
            id=memory_id,
            owner_id=owner_id,
            category=normalized_category,
            content=normalized_content,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def list_recent(
        self,
        owner_id: str,
        limit: int = 20,
    ) -> list[UserMemory]:
        """返回指定用户最近更新的长期记忆。"""
        safe_limit = max(
            1,
            min(limit, 100),
        )

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    owner_id,
                    category,
                    content,
                    created_at,
                    updated_at
                FROM user_memories
                WHERE owner_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (
                    owner_id,
                    safe_limit,
                ),
            ).fetchall()

        return [
            self._row_to_memory(row)
            for row in rows
        ]

    def search(
        self,
        owner_id: str,
        query: str,
    ) -> list[UserMemory]:
        """在记忆分类和内容中搜索。"""
        normalized_query = query.strip()

        if not normalized_query:
            return []

        pattern = f"%{normalized_query}%"

        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    owner_id,
                    category,
                    content,
                    created_at,
                    updated_at
                FROM user_memories
                WHERE owner_id = ?
                  AND (
                      category LIKE ?
                      OR content LIKE ?
                  )
                ORDER BY updated_at DESC, id DESC
                """,
                (
                    owner_id,
                    pattern,
                    pattern,
                ),
            ).fetchall()

        return [
            self._row_to_memory(row)
            for row in rows
        ]

    def delete_memory(
        self,
        owner_id: str,
        memory_id: int,
    ) -> bool:
        """删除指定用户的一条长期记忆。"""
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    DELETE FROM user_memories
                    WHERE id = ?
                      AND owner_id = ?
                    """,
                    (
                        memory_id,
                        owner_id,
                    ),
                )

                return cursor.rowcount > 0

    @staticmethod
    def _merge_field(
        new_value: str | None,
        old_value: str | None,
        field_name: str,
    ) -> str | None:
        """合并并校验一个可选资料字段。"""
        if new_value is None:
            return old_value

        normalized_value = new_value.strip()

        if not normalized_value:
            raise ValueError(
                f"{field_name} cannot be empty."
            )

        if len(normalized_value) > 500:
            raise ValueError(
                f"{field_name} is too long."
            )

        return normalized_value

    @staticmethod
    def _row_to_profile(
        row: sqlite3.Row,
    ) -> UserProfile:
        """将数据库行转换为用户资料对象。"""
        return UserProfile(
            owner_id=row["owner_id"],
            display_name=row["display_name"],
            occupation=row["occupation"],
            current_goal=row["current_goal"],
            response_style=row["response_style"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_memory(
        row: sqlite3.Row,
    ) -> UserMemory:
        """将数据库行转换为长期记忆对象。"""
        return UserMemory(
            id=row["id"],
            owner_id=row["owner_id"],
            category=row["category"],
            content=row["content"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )