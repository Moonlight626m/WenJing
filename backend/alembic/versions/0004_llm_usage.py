"""llm usage: 新增 llm_usage 逐次调用 token 计量表

运营计量（issue #22 / ADR-0002 §5）：每次 LLM 调用写一行，含
provider/model/purpose + prompt/completion/total tokens + org/user/script/session。
script_id/session_id 为逻辑引用（无 FK），避免删除草稿/回收会话被外键阻塞。

Revision ID: 0004_llm_usage
Revises: 0003_script_library
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004_llm_usage"
down_revision: str | None = "0003_script_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column(
            "org_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("script_id", sa.BigInteger(), nullable=True),
        sa.Column("session_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_llm_usage_org_id", "llm_usage", ["org_id"])
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"])
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])
    op.create_index(
        "idx_llm_usage_org_created", "llm_usage", ["org_id", "created_at"]
    )
    op.create_index(
        "idx_llm_usage_purpose_created", "llm_usage", ["purpose", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("idx_llm_usage_purpose_created", table_name="llm_usage")
    op.drop_index("idx_llm_usage_org_created", table_name="llm_usage")
    op.drop_index("ix_llm_usage_created_at", table_name="llm_usage")
    op.drop_index("ix_llm_usage_user_id", table_name="llm_usage")
    op.drop_index("ix_llm_usage_org_id", table_name="llm_usage")
    op.drop_table("llm_usage")
