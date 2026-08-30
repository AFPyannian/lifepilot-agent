"""执行业务库迁移，并一次性初始化 LangGraph Checkpoint 表。"""

import argparse
import os

from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver


def main() -> None:
    parser = argparse.ArgumentParser(description="初始化 LifePilot PostgreSQL")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument(
        "--checkpoint-database-url",
        default=os.environ.get("CHECKPOINT_DATABASE_URL"),
    )
    args = parser.parse_args()

    if not args.database_url or not args.checkpoint_database_url:
        parser.error("必须配置 DATABASE_URL 和 CHECKPOINT_DATABASE_URL")

    os.environ["DATABASE_URL"] = args.database_url
    command.upgrade(Config("alembic.ini"), "head")

    with PostgresSaver.from_conn_string(args.checkpoint_database_url) as checkpointer:
        checkpointer.setup()

    print("业务库和 Checkpoint 表初始化完成。")


if __name__ == "__main__":
    main()
