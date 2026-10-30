"""asset_jobs 增 kind/prompt_context：崩溃恢复不再丢失配图语义

branch-montage-dm §5：运行期配图不再只有 background（DM 场景发
scene_montage 完整场面图，画师层消费 prompt_context 转写结构化外貌/锚点）。
旧列恢复重排时把 request 补成默认 kind∈background、context 为空——
场面图任务被降级重跑成空镜背景。新列让持久票据携带完整 request。

Revision ID: 0012_asset_jobs_kind
Revises: 0011_asset_jobs
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0012_asset_jobs_kind"
down_revision: str | None = "0011_asset_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "asset_jobs",
        sa.Column("kind", sa.String(32), nullable=False, server_default="background"),
    )
    op.add_column(
        "asset_jobs",
        sa.Column("prompt_context", pg.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("asset_jobs", "prompt_context")
    op.drop_column("asset_jobs", "kind")
