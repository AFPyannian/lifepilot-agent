"""建立 PostgreSQL 生产业务库和 pgvector 表。

Revision ID: 20260831_01
Revises: None
"""

from collections.abc import Sequence

from alembic import op

from app.database_models import Base

revision: str = "20260831_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """启用 pgvector 并创建阶段四的完整业务表。"""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=False)
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw "
        "ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """按外键依赖逆序删除业务表，保留共享 vector 扩展。"""
    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw")
    for table in reversed(Base.metadata.sorted_tables):
        op.drop_table(table.name)
