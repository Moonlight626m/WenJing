"""empty initial migration (skeleton)

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 骨架阶段：无业务表。模型定义后由 autogenerate 生成真实迁移。
    pass


def downgrade() -> None:
    pass
