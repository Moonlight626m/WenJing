"""media usage: 新增 media_usage 媒体计量表

媒体计量（issue #41 / ADR-0005 §12）：每次图片/TTS/ASR 调用写一行，含
kind/provider/model/units/size + org/user/script/session + meta JSONB。
与 token 语义的 llm_usage 分离；script_id/session_id 为逻辑引用（无 FK）。

Revision ID: 0009_media_usage
Revises: 0008_prompts
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0009_media_usage"
down_revision: str | None = "0008_prompts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default="0"),
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
            "meta",
            pg.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_media_usage_org_id", "media_usage", ["org_id"])
    op.create_index("ix_media_usage_user_id", "media_usage", ["user_id"])
    op.create_index("ix_media_usage_created_at", "media_usage", ["created_at"])
    op.create_index(
        "idx_media_usage_org_created", "media_usage", ["org_id", "created_at"]
    )
    op.create_index(
        "idx_media_usage_kind_created", "media_usage", ["kind", "created_at"]
    )
    op.create_index("idx_media_usage_session", "media_usage", ["session_id"])


def downgrade() -> None:
    op.drop_index("idx_media_usage_session", table_name="media_usage")
    op.drop_index("idx_media_usage_kind_created", table_name="media_usage")
    op.drop_index("idx_media_usage_org_created", table_name="media_usage")
    op.drop_index("ix_media_usage_created_at", table_name="media_usage")
    op.drop_index("ix_media_usage_user_id", table_name="media_usage")
    op.drop_index("ix_media_usage_org_id", table_name="media_usage")
    op.drop_table("media_usage")
