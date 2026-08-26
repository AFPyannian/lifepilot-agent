"""使用 SQLite 持久化用户笔记。"""


import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class NoteItem:
    """表示数据库中的一条笔记。"""

    id: int
    owner_id: str
    title: str
    content: str
    created_at: str
    updated_at: str


class NoteRepository:
    """管理 SQLite 中的用户笔记。"""

    def __init__(
        self,
        database_path: str | Path,
    ) -> None:
        """保存数据库路径并初始化笔记表。"""
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
        """创建笔记表和查询索引。"""
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notes (
                        id INTEGER PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_notes_owner_id
                    ON notes (owner_id)
                    """
                )

    def add(
        self,
        owner_id: str,
        title: str,
        content: str,
    ) -> NoteItem:
        """创建并返回一条用户笔记。"""
        normalized_title = title.strip()
        normalized_content = content.strip()

        if not normalized_title:
            raise ValueError(
                "Note title cannot be empty."
            )

        if not normalized_content:
            raise ValueError(
                "Note content cannot be empty."
            )

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO notes (
                        owner_id,
                        title,
                        content,
                        created_at,
                        updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        owner_id,
                        normalized_title,
                        normalized_content,
                        timestamp,
                        timestamp,
                    ),
                )

                note_id = cursor.lastrowid

        if note_id is None:
            raise RuntimeError(
                "Failed to obtain the new note ID."
            )

        return NoteItem(
            id=note_id,
            owner_id=owner_id,
            title=normalized_title,
            content=normalized_content,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def list_all(
        self,
        owner_id: str,
    ) -> list[NoteItem]:
        """返回指定用户的全部笔记。"""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    owner_id,
                    title,
                    content,
                    created_at,
                    updated_at
                FROM notes
                WHERE owner_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (owner_id,),
            ).fetchall()

        return [
            self._row_to_item(row)
            for row in rows
        ]

    def get_by_id(
        self,
        owner_id: str,
        note_id: int,
    ) -> NoteItem | None:
        """读取指定用户的一条笔记。"""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    owner_id,
                    title,
                    content,
                    created_at,
                    updated_at
                FROM notes
                WHERE id = ?
                  AND owner_id = ?
                """,
                (
                    note_id,
                    owner_id,
                ),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_item(row)

    def search(
        self,
        owner_id: str,
        query: str,
    ) -> list[NoteItem]:
        """在指定用户的笔记标题和正文中搜索。"""
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
                    title,
                    content,
                    created_at,
                    updated_at
                FROM notes
                WHERE owner_id = ?
                  AND (
                      title LIKE ?
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
            self._row_to_item(row)
            for row in rows
        ]

    def update(
        self,
        owner_id: str,
        note_id: int,
        title: str | None = None,
        content: str | None = None,
    ) -> NoteItem | None:
        """部分更新并返回一条用户笔记。"""
        existing = self.get_by_id(
            owner_id=owner_id,
            note_id=note_id,
        )

        if existing is None:
            return None

        if title is None:
            updated_title = existing.title
        else:
            updated_title = title.strip()

            if not updated_title:
                raise ValueError(
                    "Note title cannot be empty."
                )

        if content is None:
            updated_content = existing.content
        else:
            updated_content = content.strip()

            if not updated_content:
                raise ValueError(
                    "Note content cannot be empty."
                )

        updated_at = datetime.now(
            timezone.utc
        ).isoformat()

        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    UPDATE notes
                    SET
                        title = ?,
                        content = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND owner_id = ?
                    """,
                    (
                        updated_title,
                        updated_content,
                        updated_at,
                        note_id,
                        owner_id,
                    ),
                )

        return NoteItem(
            id=existing.id,
            owner_id=existing.owner_id,
            title=updated_title,
            content=updated_content,
            created_at=existing.created_at,
            updated_at=updated_at,
        )

    def delete(
        self,
        owner_id: str,
        note_id: int,
    ) -> bool:
        """删除指定用户的一条笔记。"""
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    DELETE FROM notes
                    WHERE id = ?
                      AND owner_id = ?
                    """,
                    (
                        note_id,
                        owner_id,
                    ),
                )

                return cursor.rowcount > 0

    @staticmethod
    def _row_to_item(
        row: sqlite3.Row,
    ) -> NoteItem:
        """将数据库行转换为笔记对象。"""
        return NoteItem(
            id=row["id"],
            owner_id=row["owner_id"],
            title=row["title"],
            content=row["content"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )