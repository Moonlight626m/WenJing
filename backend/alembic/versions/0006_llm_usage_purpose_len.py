"""llm_usage.purpose 拓宽到 varchar(32)。

`collect_materials`（17 字符）超出原 varchar(16)，usage 记录每次都
静默失败（llm_usage_record_failed 告警）。模型层同步 String(32)。

Revision ID: 0006_llm_usage_purpose_len
Revises: 0005_script_generations
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_llm_usage_purpose_len"
down_revision: str | None = "0005_script_generations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "llm_usage", "purpose", type_=sa.String(32), existing_type=sa.String(16)
    )


def downgrade() -> None:
    op.alter_column(
        "llm_usage", "purpose", type_=sa.String(16), existing_type=sa.String(32)
    )
