"""离线 tick 台账（design play-through-redesign §B6，M7）

`session_ticks(session_id, tick_index)` 唯一键 = claim-first 幂等闸。

Revision ID: 0002_session_ticks
Revises: 0001_v2_initial
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0002_session_ticks"
down_revision: str | None = "0001_v2_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_ticks",
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("tick_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id", "tick_index"),
    )


def downgrade() -> None:
    op.drop_table("session_ticks")
