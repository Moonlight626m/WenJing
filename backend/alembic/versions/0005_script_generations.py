"""script_generations：剧本生成尝试的观测表（issue #28）。

LangGraph checkpointer（AsyncPostgresSaver 自建表）负责可恢复性；
本表负责业务观测面：每节点状态 / doubter 事件 / 错误详情。同一剧本
可有多次尝试（重新生成 = 新行），教师端经 GenerationProgress 契约读取。

Revision ID: 0005_script_generations
Revises: 0004_llm_usage
Create Date: 2026-09-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0005_script_generations"
down_revision: str | None = "0004_llm_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "script_generations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "script_id",
            sa.Integer(),
            sa.ForeignKey("scripts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("org_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("progress", pg.JSONB(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_script_generations_script_id", "script_generations", ["script_id"])


def downgrade() -> None:
    op.drop_table("script_generations")
