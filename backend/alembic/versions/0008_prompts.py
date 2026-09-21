"""新增 prompts 表（PromptMgr 组件：prompt 文案 DB 覆盖层）。

键为「阶段 × 节点 × 版本 × 段落」四维唯一；代码 defaults 是单源，\
本表只存覆盖行；每次生成调用实时读取（spec 裁决）。

Revision ID: 0008_prompts
Revises: 0007_gate_review
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB  # noqa: F401  (与相邻迁移风格一致)

from alembic import op

revision: str = "0008_prompts"
down_revision: str | None = "0007_gate_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("node", sa.String(length=60), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("section", sa.String(length=60), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "stage", "node", "version", "section", name="uq_prompts_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("prompts")
