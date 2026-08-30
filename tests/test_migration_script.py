"""验证旧版 local-user 数据迁移的关键行为。"""

import sqlite3

from scripts.migrate_local_user import (
    LEGACY_OWNER_ID,
    _migrate_application_database,
    _migrate_checkpoints,
    _migrate_source_files,
)


def test_migrates_application_rows_to_target_user(tmp_path) -> None:
    database_path = tmp_path / "application.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE todos (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO todos (id, owner_id) VALUES (?, ?)",
            [("legacy", LEGACY_OWNER_ID), ("other", "other-user")],
        )

    _migrate_application_database(database_path, "target-user")

    with sqlite3.connect(database_path) as connection:
        rows = dict(connection.execute("SELECT id, owner_id FROM todos"))
    assert rows == {"legacy": "target-user", "other": "other-user"}


def test_checkpoint_migration_is_user_namespaced_and_idempotent(tmp_path) -> None:
    database_path = tmp_path / "checkpoints.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE checkpoints (thread_id TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO checkpoints (thread_id) VALUES (?)",
            [("main",), ("user:other-user:thread:main",)],
        )

    _migrate_checkpoints(database_path, "target-user")
    _migrate_checkpoints(database_path, "target-user")

    with sqlite3.connect(database_path) as connection:
        thread_ids = {
            row[0] for row in connection.execute("SELECT thread_id FROM checkpoints")
        }
    assert thread_ids == {
        "user:target-user:thread:main",
        "user:other-user:thread:main",
    }


def test_source_files_move_into_target_user_directory(tmp_path) -> None:
    source_root = tmp_path / "knowledge"
    source_root.mkdir()
    (source_root / "guide.md").write_text("legacy", encoding="utf-8")
    (source_root / ".gitkeep").touch()
    (source_root / "existing-user").mkdir()

    _migrate_source_files(source_root, "target-user")

    assert not (source_root / "guide.md").exists()
    assert (source_root / "target-user" / "guide.md").read_text(
        encoding="utf-8"
    ) == "legacy"
    assert (source_root / "existing-user").is_dir()
    assert (source_root / ".gitkeep").is_file()
    assert not (source_root / "target-user" / ".gitkeep").exists()
