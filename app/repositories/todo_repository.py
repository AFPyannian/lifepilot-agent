import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class TodoItem:
    """数据库中存储的一条待办事项。frozen=True设置其不可修改"""

    id: int
    owner_id: str
    task: str
    is_completed: bool
    created_at: str


class TodoRepository:
    """管理存储在 SQLite 数据库中的待办事项"""

    def __init__(self, database_path: str | Path) -> None:
        """配置一个数据库"""

        # 导入数据库路径
        self._database_path = Path(database_path)

        # 创建数据库目录
        self._database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # 初始化数据库
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        """打开一个已配置好的数据库连接"""

        # 连接数据库
        connection = sqlite3.connect(
            self._database_path
        )

        connection.row_factory = sqlite3.Row

        return connection

    def _initialize_database(self) -> None:
        """创建所需的数据库表和索引"""

        # 外层 with 是资源关闭(执行完后连接就会关闭), 内层 with 是事务管理
        with closing(self._connect()) as connection:
            with connection:
                # 创建 todos 表
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

                # 创建索引
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS
                        idx_todos_owner_id
                    ON todos (owner_id)
                    """
                )

    def add(self, owner_id: str, task: str) -> TodoItem:
        """为指定用户添加一个待办事项"""

        # 规范化输入
        normalized_task = task.strip()
        if not normalized_task:
            raise ValueError(
                "Todo content cannot be empty."
            )

        # 创建 UTC 时间
        created_at = datetime.now(
            timezone.utc
        ).isoformat()

        with closing(self._connect()) as connection:
            with connection:
                # 插入数据库
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

                # 自动生成ID
                todo_id = cursor.lastrowid

        # 检查ID
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
        """查询指定用户的全部待办事项"""
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
        """将指定用户的指定待办事项标记为已完成"""
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
        """删除指定用户的指定待办事项"""
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
        """把 SQLite 数据库的一行转换成 Python 的 TodoItem"""
        return TodoItem(
            id=row["id"],
            owner_id=row["owner_id"],
            task=row["task"],
            is_completed=bool(row["is_completed"]),
            created_at=row["created_at"],
        )