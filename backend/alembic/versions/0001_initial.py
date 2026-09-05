"""core mvp persistence baseline

Sessions / Materials / Scripts / EventBranches / Events / Snapshots / Commands.
events: (branch_id, sequence) unique; causation/correlation/schema_version.
sessions: active_branch_id + head_event_id + version (optimistic lock).

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("current_stage", sa.String(32), nullable=False, server_default="init"),
        sa.Column("script_id", sa.Integer(), nullable=True),
        sa.Column("material_id", sa.Integer(), nullable=True),
        sa.Column("player_role", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("active_branch_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("head_event_id", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "idx_sessions_active_branch", "sessions", ["active_branch_id"]
    )

    op.create_table(
        "materials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id", pg.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False
        ),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("collection_output", pg.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    op.create_table(
        "scripts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id", pg.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("script_data", pg.JSONB(), nullable=False),
        sa.Column("verification", pg.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    op.create_table(
        "event_branches",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", pg.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False
        ),
        sa.Column("root_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parent_branch_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_command_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "idx_event_branches_session", "event_branches", ["session_id"]
    )

    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id", pg.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False
        ),
        sa.Column(
            "branch_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("event_branches.id"),
            nullable=False,
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("causation_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("correlation_id", pg.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("events.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.UniqueConstraint("branch_id", "sequence", name="uq_events_branch_sequence"),
    )
    op.create_index("idx_events_session", "events", ["session_id", "id"])

    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id", pg.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False
        ),
        sa.Column(
            "event_id", sa.BigInteger(), sa.ForeignKey("events.id"), nullable=False
        ),
        sa.Column("state_machine", sa.Text(), nullable=False),
        sa.Column("character_memories", pg.JSONB(), nullable=False),
        sa.Column("plot_context", pg.JSONB(), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("idx_snapshots_session", "snapshots", ["session_id", "event_id"])

    op.create_table(
        "commands",
        sa.Column("command_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id", pg.UUID(as_uuid=True), sa.ForeignKey("sessions.id"), nullable=False
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="received"),
        sa.Column(
            "result_event_id",
            sa.BigInteger(),
            sa.ForeignKey("events.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("commands")
    op.drop_index("idx_snapshots_session", table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_index("idx_events_session", table_name="events")
    op.drop_table("events")
    op.drop_index("idx_event_branches_session", table_name="event_branches")
    op.drop_table("event_branches")
    op.drop_table("scripts")
    op.drop_table("materials")
    op.drop_index("idx_sessions_active_branch", table_name="sessions")
    op.drop_table("sessions")
