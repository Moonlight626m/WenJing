"""assets: 新增资产元数据表

资产元数据（ADR-0005 §4/§6，issue #42）：对象字节存对象存储，DB 只存元数据。
object_key 仅在本表与 ObjectStoragePort 内部；署名/许可字段供详情页展示。
script_id/session_id 为逻辑引用（无 FK）。

Revision ID: 0010_assets
Revises: 0009_media_usage
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0010_assets"
down_revision: str | None = "0009_media_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("asset_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("object_key", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("source", sa.String(16), nullable=False, server_default="generated"),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("width", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "org_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id"),
            nullable=False,
        ),
        sa.Column("script_id", sa.BigInteger(), nullable=True),
        sa.Column("session_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("dedup_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("author", sa.String(256), nullable=False, server_default=""),
        sa.Column("license", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("license_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_assets_org_id", "assets", ["org_id"])
    op.create_index("ix_assets_created_at", "assets", ["created_at"])
    op.create_index("idx_assets_org_dedup", "assets", ["org_id", "dedup_key"])
    op.create_index("idx_assets_script", "assets", ["script_id"])
    op.create_index("idx_assets_session", "assets", ["session_id"])


def downgrade() -> None:
    op.drop_index("idx_assets_session", table_name="assets")
    op.drop_index("idx_assets_script", table_name="assets")
    op.drop_index("idx_assets_org_dedup", table_name="assets")
    op.drop_index("ix_assets_created_at", table_name="assets")
    op.drop_index("ix_assets_org_id", table_name="assets")
    op.drop_table("assets")
