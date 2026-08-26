"""使用 SQLite 持久化用户待办事项。"""


import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TodoItem:
    """表示数据库中的一条待办事项。"""

    id: int
    owner_id: str
    task: str
    is_completed: bool
    created_at: str


class TodoRepository:
    """管理 SQLite 中的用户待办事项。"""

    def __init__(self, database_path: str | Path) -> None:
        """保存数据库路径并初始化待办表。"""


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
        """创建待办表和查询索引。"""


        with closing(self._connect()) as connection:
            with connection:

                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS todos (
                        id INTEGER PRIMARY KEY,
                        owner_id TEXT NOT NULL,
                        task TEXT NOT NULL,
                        is_completed INTEGER NOT NULL
                            DEFAULT 0
                            CHECK (is_completed IN (0, 1)),
                        created_at TEXT NOT NULL
                    )
                    """
                )


                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_todos_owner_id
                    ON todos (owner_id)
                    """
                )

    def add(self, owner_id: str, task: str) -> TodoItem:
        """创建并返回一条用户待办。"""


        normalized_task = task.strip()
        if not normalized_task:
            raise ValueError(
                "Todo content cannot be empty."
            )


        created_at = datetime.now(
            timezone.utc
        ).isoformat()

        with closing(self._connect()) as connection:
            with connection:

                cursor = connection.execute(
                    """
                    INSERT INTO todos (
                        owner_id,
                        task,
                        is_completed,
                        created_at
                    )
                    VALUES (?, ?, 0, ?)
                    """,
                    (
                        owner_id,
                        normalized_task,
                        created_at,
                    ),
                )


                todo_id = cursor.lastrowid


        if todo_id is None:
            raise RuntimeError(
                "Failed to obtain the new todo ID."
            )

        return TodoItem(
            id=todo_id,
            owner_id=owner_id,
            task=normalized_task,
            is_completed=False,
            created_at=created_at,
        )

    def list_all(self, owner_id: str) -> list[TodoItem]:
        """返回指定用户的全部待办。"""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    owner_id,
                    task,
                    is_completed,
                    created_at
                FROM todos
                WHERE owner_id = ?
                ORDER BY id
                """,
                (owner_id,),
            ).fetchall()

        return [
            self._row_to_item(row)
            for row in rows
        ]

    def mark_completed(self, owner_id: str, todo_id: int) -> bool:
        """将指定用户的一条待办标记为完成。"""
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    UPDATE todos
                    SET is_completed = 1
                    WHERE id = ?
                      AND owner_id = ?
                    """,
                    (
                        todo_id,
                        owner_id,
                    ),
                )

                return cursor.rowcount > 0

    def delete(self, owner_id: str, todo_id: int) -> bool:
        """删除指定用户的一条待办。"""
        with closing(self._connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    DELETE FROM todos
                    WHERE id = ?
                      AND owner_id = ?
                    """,
                    (
                        todo_id,
                        owner_id,
                    ),
                )

                return cursor.rowcount > 0

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> TodoItem:
        """将数据库行转换为待办对象。"""
        return TodoItem(
            id=row["id"],
            owner_id=row["owner_id"],
            task=row["task"],
            is_completed=bool(row["is_completed"]),
            created_at=row["created_at"],
        )