"""管理 SQLite LangGraph Checkpointer 的生命周期。"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


@contextmanager
def open_sqlite_checkpointer(database_path: str | Path) -> Iterator[SqliteSaver]:
    """打开 SQLite Checkpointer，并在退出上下文时关闭数据库连接。"""
    resolved_path = Path(database_path)

    resolved_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = sqlite3.connect(
        resolved_path,
        check_same_thread=False,
    )

    try:
        yield SqliteSaver(connection)
    finally:
        connection.close()
