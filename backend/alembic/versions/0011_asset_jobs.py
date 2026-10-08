"""asset_jobs: 新增运行期配图任务表；assets 增失败原因

运行期（Stage3）每次配图尝试一行，支撑两件进程内状态做不到的事（ADR-0005 §5，
issue #57）：每会话生图上限（跨重启有效）与崩溃后的启动重排/TTL 降级。
session_id/script_id/user_id 为逻辑引用（无 FK，与 assets 一致）。

Revision ID: 0011_asset_jobs
Revises: 0010_assets
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0011_asset_jobs"
down_revision: str | None = "0010_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # assets.reason：失败原因摘要（诊断/失败率归因，#57）
    op.add_column(
        "assets",
        sa.Column("reason", sa.String(200), nullable=False, server_default=""),
    )
    op.create_table(
        "asset_jobs",
        sa.Column("job_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("scene_key", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "org_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id"),
            nullable=False,
        ),
        sa.Column("script_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("asset_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(200), nullable=False, server_default=""),
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
        sa.UniqueConstraint(
            "session_id", "scene_key", name="uq_asset_jobs_session_scene"
        ),
    )
    op.create_index("ix_asset_jobs_org_id", "asset_jobs", ["org_id"])
    op.create_index("ix_asset_jobs_created_at", "asset_jobs", ["created_at"])
    op.create_index("idx_asset_jobs_status_created", "asset_jobs", ["status", "created_at"])
    op.create_index("idx_asset_jobs_session", "asset_jobs", ["session_id"])


def downgrade() -> None:
    op.drop_column("assets", "reason")
    op.drop_index("idx_asset_jobs_session", table_name="asset_jobs")
    op.drop_index("idx_asset_jobs_status_created", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_created_at", table_name="asset_jobs")
    op.drop_index("ix_asset_jobs_org_id", table_name="asset_jobs")
    op.drop_table("asset_jobs")
