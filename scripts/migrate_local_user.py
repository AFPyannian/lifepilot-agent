"""将 V1.0.0 的 local-user 数据离线迁移到真实用户 UUID。"""

import argparse
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings, get_settings
from app.identity import checkpoint_thread_id
from app.repositories.auth_repository import AuthRepository

LEGACY_OWNER_ID = "local-user"
OWNER_TABLES = (
    "todos",
    "notes",
    "user_profiles",
    "user_memories",
    "conversations",
)


def _backup(settings: Settings) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_root = settings.app_database_path.parent / "migration-backups" / timestamp
    backup_root.mkdir(parents=True, exist_ok=False)

    for source in (
        settings.app_database_path,
        settings.checkpoint_database_path,
    ):
        if source.exists():
            shutil.copy2(source, backup_root / source.name)

    if settings.knowledge_source_directory.exists():
        shutil.copytree(
            settings.knowledge_source_directory,
            backup_root / "knowledge_base",
        )

    if settings.chroma_persist_directory.exists():
        shutil.copytree(
            settings.chroma_persist_directory,
            backup_root / "chroma",
        )

    return backup_root


def _migrate_application_database(
    database_path: Path,
    target_user_id: str,
) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for table in OWNER_TABLES:
                table_exists = connection.execute(
                    """
                    SELECT 1
                    FROM sqlite_master
                    WHERE type = 'table' AND name = ?
                    """,
                    (table,),
                ).fetchone()
                if table_exists is None:
                    continue
                connection.execute(
                    f"UPDATE {table} SET owner_id = ? WHERE owner_id = ?",
                    (target_user_id, LEGACY_OWNER_ID),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _migrate_checkpoints(
    database_path: Path,
    target_user_id: str,
) -> None:
    if not database_path.exists():
        return

    with sqlite3.connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            checkpoint_tables = [
                table for table in ("checkpoints", "writes") if table in table_names
            ]
            thread_ids: set[str] = set()
            for table in checkpoint_tables:
                thread_ids.update(
                    row[0]
                    for row in connection.execute(
                        f"SELECT DISTINCT thread_id FROM {table}"
                    )
                )

            for old_thread_id in thread_ids:
                if old_thread_id.startswith("user:"):
                    continue
                new_thread_id = checkpoint_thread_id(
                    target_user_id,
                    old_thread_id,
                )
                for table in checkpoint_tables:
                    connection.execute(
                        f"UPDATE {table} SET thread_id = ? WHERE thread_id = ?",
                        (new_thread_id, old_thread_id),
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _migrate_source_files(
    source_root: Path,
    target_user_id: str,
) -> None:
    if not source_root.exists():
        return

    target_directory = source_root / target_user_id
    target_directory.mkdir(parents=True, exist_ok=True)

    for source in source_root.iterdir():
        if not source.is_file():
            continue
        destination = target_directory / source.name
        if destination.exists():
            raise FileExistsError(f"迁移目标文件已经存在：{destination}")
        source.replace(destination)


def _migrate_chroma(
    persist_directory: Path,
    target_user_id: str,
) -> None:
    if not persist_directory.exists():
        return

    import chromadb
    from chromadb.errors import NotFoundError

    client = chromadb.PersistentClient(path=str(persist_directory))
    try:
        collection = client.get_collection("lifepilot_knowledge")
    except NotFoundError:
        return

    result = collection.get(
        where={"owner_id": LEGACY_OWNER_ID},
        include=["metadatas"],
    )
    ids = result.get("ids", [])
    metadatas = result.get("metadatas", [])
    if not ids or not metadatas:
        return

    updated_metadatas = []
    for metadata in metadatas:
        updated = dict(metadata or {})
        updated["owner_id"] = target_user_id
        updated_metadatas.append(updated)

    collection.update(
        ids=ids,
        metadatas=updated_metadatas,
    )


def main() -> None:
    """备份并迁移旧版单用户数据。"""
    parser = argparse.ArgumentParser(
        description="迁移 V1.0.0 local-user 数据；运行前必须停止后端"
    )
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认已经停止后端并允许执行迁移",
    )
    args = parser.parse_args()

    if not args.confirm:
        parser.error("请停止后端并增加 --confirm。")

    settings = get_settings()
    user = AuthRepository(settings.app_database_path).get_user_by_username(
        args.username
    )
    if user is None:
        parser.error("目标用户不存在，请先使用 python -m scripts.user_admin 创建账号。")

    backup_root = _backup(settings)
    print(f"迁移前备份已创建：{backup_root}")

    try:
        _migrate_application_database(
            settings.app_database_path,
            user.id,
        )
        _migrate_checkpoints(
            settings.checkpoint_database_path,
            user.id,
        )
        _migrate_source_files(
            settings.knowledge_source_directory,
            user.id,
        )
        _migrate_chroma(
            settings.chroma_persist_directory,
            user.id,
        )
    except Exception:
        print(f"迁移失败，请从以下目录恢复：{backup_root}")
        raise

    print(f"local-user 数据已经迁移到：{user.username}（{user.id}）")


if __name__ == "__main__":
    main()
