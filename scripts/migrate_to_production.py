"""将阶段 0～3 的 SQLite、Checkpoint 和本地知识文件迁移到生产组件。"""

import argparse
import os
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import MetaData, Table, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert

from app.config import Settings
from app.database import Database
from app.knowledge.loaders import SUPPORTED_SUFFIXES
from app.knowledge.production_service import ProductionKnowledgeService

TABLE_ORDER = (
    "users",
    "user_quotas",
    "quota_usage",
    "auth_sessions",
    "registration_invites",
    "todos",
    "notes",
    "conversations",
    "user_profiles",
    "user_memories",
    "provider_credentials",
    "entitlements",
    "usage_events",
    "audit_events",
)


def _source_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _convert_row(table: Table, row: sqlite3.Row) -> dict[str, object]:
    """按目标列裁剪 SQLite 行并转换时区日期字段。"""
    values: dict[str, object] = {}
    for column in table.columns:
        if column.name in row:
            value = row[column.name]
        elif column.name == "created_at" and "updated_at" in row:
            value = row["updated_at"]
        else:
            continue
        if value is not None and isinstance(column.type.python_type, type):
            if column.type.python_type is datetime and isinstance(value, str):
                value = datetime.fromisoformat(value)
            elif column.type.python_type is bool:
                value = bool(value)
        values[column.name] = value
    return values


def migrate_business_data(sqlite_path: Path, database_url: str) -> dict[str, int]:
    """按外键顺序幂等复制业务数据并返回目标计数。"""
    engine = create_engine(database_url, pool_pre_ping=True)
    metadata = MetaData()
    counts: dict[str, int] = {}
    try:
        with closing(sqlite3.connect(sqlite_path)) as source:
            source.row_factory = sqlite3.Row
            available = _source_tables(source)
            with engine.begin() as destination:
                for table_name in TABLE_ORDER:
                    if table_name not in available:
                        continue
                    table = Table(table_name, metadata, autoload_with=destination)
                    rows = source.execute(f'SELECT * FROM "{table_name}"').fetchall()
                    for row in rows:
                        statement = (
                            insert(table)
                            .values(**_convert_row(table, row))
                            .on_conflict_do_nothing()
                        )
                        destination.execute(statement)
                    counts[table_name] = int(
                        destination.scalar(select(func.count()).select_from(table)) or 0
                    )
                for table_name in ("todos", "notes", "user_memories"):
                    if table_name not in available:
                        continue
                    destination.execute(
                        text(
                            "SELECT setval(pg_get_serial_sequence(:table_name, 'id'), "
                            "GREATEST(COALESCE((SELECT MAX(id) FROM "
                            + table_name
                            + "), 1), 1), "
                            "EXISTS(SELECT 1 FROM " + table_name + "))"
                        ),
                        {"table_name": table_name},
                    )
    finally:
        engine.dispose()
    return counts


def migrate_checkpoints(sqlite_path: Path, database_url: str) -> int:
    """通过 Checkpointer 公共接口复制检查点和待处理写入。"""
    migrated = 0
    with (
        SqliteSaver.from_conn_string(str(sqlite_path)) as source,
        PostgresSaver.from_conn_string(database_url) as destination,
    ):
        items = list(source.list(None))
        for item in reversed(items):
            config = item.parent_config or {
                "configurable": {
                    "thread_id": item.config["configurable"]["thread_id"],
                    "checkpoint_ns": item.config["configurable"].get(
                        "checkpoint_ns", ""
                    ),
                }
            }
            saved_config = destination.put(
                config,
                item.checkpoint,
                item.metadata,
                item.checkpoint.get("channel_versions", {}),
            )
            pending_by_task: dict[str, list[tuple[str, Any]]] = {}
            for task_id, channel, value in item.pending_writes or []:
                pending_by_task.setdefault(task_id, []).append((channel, value))
            for task_id, writes in pending_by_task.items():
                destination.put_writes(saved_config, writes, task_id)
            migrated += 1
    return migrated


def migrate_knowledge_files(
    source_directory: Path, database_url: str, settings: Settings
) -> int:
    """上传本地源文件并投递重新向量化任务，不复制 Chroma 内部数据。"""
    database = Database(settings)
    queued = 0
    try:
        service = ProductionKnowledgeService(database, settings)
        for owner_directory in _owner_directories(source_directory):
            for source_path in owner_directory.iterdir():
                if (
                    not source_path.is_file()
                    or source_path.suffix.lower() not in SUPPORTED_SUFFIXES
                ):
                    continue
                with source_path.open("rb") as source:
                    _result, task_id = service.submit_upload(
                        owner_id=owner_directory.name,
                        filename=source_path.name,
                        source=source,
                        content_type=None,
                    )
                queued += int(task_id is not None)
    finally:
        database.close()
    return queued


def _owner_directories(source_directory: Path) -> Iterable[Path]:
    if not source_directory.exists():
        return []
    return sorted(path for path in source_directory.iterdir() if path.is_dir())


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 LifePilot 阶段四生产数据")
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path, required=True)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument(
        "--checkpoint-database-url",
        default=os.environ.get("CHECKPOINT_DATABASE_URL"),
    )
    parser.add_argument("--knowledge-directory", type=Path)
    parser.add_argument("--include-knowledge", action="store_true")
    args = parser.parse_args()

    if not args.database_url or not args.checkpoint_database_url:
        parser.error("必须配置 DATABASE_URL 和 CHECKPOINT_DATABASE_URL")

    counts = migrate_business_data(args.sqlite, args.database_url)
    print("业务表迁移完成：", counts)
    checkpoint_count = migrate_checkpoints(
        args.checkpoints, args.checkpoint_database_url
    )
    print(f"Checkpoint 迁移完成：{checkpoint_count}")

    if args.include_knowledge:
        if args.knowledge_directory is None:
            parser.error("--include-knowledge 需要 --knowledge-directory")
        settings = Settings(
            infrastructure_mode="production",
            database_url=args.database_url,
            checkpoint_database_url=args.checkpoint_database_url,
        )
        queued = migrate_knowledge_files(
            args.knowledge_directory, args.database_url, settings
        )
        print(f"知识文件已上传并排队：{queued}")


if __name__ == "__main__":
    main()
