"""script_generations 增加 review 列（教师闸门审阅载荷，#34）。

闸门暂停时把 GateReview 载荷（中间产物快照）落库，教师端经
ScriptDetail.review 读取；恢复时清空。

Revision ID: 0007_gate_review
Revises: 0006_llm_usage_purpose_len
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0007_gate_review"
down_revision: str | None = "0006_llm_usage_purpose_len"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "script_generations",
        sa.Column("review", JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("script_generations", "review")
