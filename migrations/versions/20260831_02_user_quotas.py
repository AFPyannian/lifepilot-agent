"""增加可原子执行的用户月度模型配额。

Revision ID: 20260831_02
Revises: 20260831_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_02"
down_revision: str | None = "20260831_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建用户配额配置和 UTC 月度原子计数表。"""
    op.create_table(
        "user_quotas",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("monthly_request_limit", sa.Integer(), nullable=True),
        sa.Column("monthly_token_limit", sa.BigInteger(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "monthly_request_limit IS NULL OR monthly_request_limit > 0",
            name="ck_user_quotas_requests",
        ),
        sa.CheckConstraint(
            "monthly_token_limit IS NULL OR monthly_token_limit > 0",
            name="ck_user_quotas_tokens",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "quota_usage",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("request_count >= 0", name="ck_quota_usage_requests"),
        sa.CheckConstraint("token_count >= 0", name="ck_quota_usage_tokens"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "period_start"),
    )


def downgrade() -> None:
    """先删除周期计数，再删除配额配置。"""
    op.drop_table("quota_usage")
    op.drop_table("user_quotas")
