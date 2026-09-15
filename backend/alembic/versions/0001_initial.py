"""new baseline: core persistence + multi-user accounts

破坏式重建基线（issue #17 / ADR-0002）：旧匿名数据无保留价值，基线重设为
账号体系（orgs/users/auth_sessions）+ 既有游戏持久化表。

Sessions / Materials / Scripts / EventBranches / Events / Snapshots / Commands.
events: (branch_id, sequence) unique; causation/correlation/schema_version.
sessions: active_branch_id + head_event_id + version (optimistic lock).
accounts: orgs; users(org_id, role, email/phone unique, password_hash);
          auth_sessions(user_id, token_hash unique, csrf_token, sliding expiry).

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
    # ===== 账号体系（issue #17 / ADR-0002）=====
    op.create_table(
        "orgs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    op.create_table(
        "users",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", pg.UUID(as_uuid=True), sa.ForeignKey("orgs.id"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="student"),
        sa.Column("email", sa.String(254), nullable=True, unique=True),
        sa.Column("phone", sa.String(32), nullable=True, unique=True),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("idx_users_org", "users", ["org_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", pg.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_auth_sessions_user", "auth_sessions", ["user_id"])

    # ===== 游戏持久化 =====
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
    op.drop_index("idx_auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("idx_users_org", table_name="users")
    op.drop_table("users")
    op.drop_table("orgs")
