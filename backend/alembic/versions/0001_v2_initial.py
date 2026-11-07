"""v2 初始基线（合并 0001–0012 后的单一基线）

新库 `wenjing_v2` 的起点：把冻结的旧迁移链（`alembic/legacy_versions/`）
合并成一份等价 schema。**不做数据迁移**——旧库只读保留，剧本重新生成入新库。

旧链留在 `legacy_versions/` 供对照/审计，但不再被 Alembic 扫描；
之后的新 schema 改动从本基线起以 0002+ 增量迁移表达。

Revision ID: 0001_v2_initial
Revises:
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_v2_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "prompts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("node", sa.String(length=60), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("section", sa.String(length=60), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stage", "node", "version", "section", name="uq_prompts_key"),
    )
    op.create_table(
        "asset_jobs",
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("scene_key", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'background'::character varying"),
        ),
        sa.Column("prompt_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("script_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'::character varying"),
        ),
        sa.Column("asset_id", sa.UUID(), nullable=True),
        sa.Column(
            "reason",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.PrimaryKeyConstraint("job_id"),
        sa.UniqueConstraint("session_id", "scene_key", name="uq_asset_jobs_session_scene"),
    )
    op.create_index("idx_asset_jobs_session", "asset_jobs", ["session_id"], unique=False)
    op.create_index(
        "idx_asset_jobs_status_created", "asset_jobs", ["status", "created_at"], unique=False
    )
    op.create_index(op.f("ix_asset_jobs_created_at"), "asset_jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_asset_jobs_org_id"), "asset_jobs", ["org_id"], unique=False)
    op.create_table(
        "assets",
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'::character varying"),
        ),
        sa.Column(
            "source",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'generated'::character varying"),
        ),
        sa.Column(
            "provider",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "model",
            sa.String(length=128),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column("width", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("height", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("script_id", sa.BigInteger(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column(
            "dedup_key",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "reason",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "author",
            sa.String(length=256),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "license",
            sa.String(length=128),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "source_url",
            sa.String(length=1024),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "license_url",
            sa.String(length=1024),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_index("idx_assets_org_dedup", "assets", ["org_id", "dedup_key"], unique=False)
    op.create_index("idx_assets_script", "assets", ["script_id"], unique=False)
    op.create_index("idx_assets_session", "assets", ["session_id"], unique=False)
    op.create_index(op.f("ix_assets_created_at"), "assets", ["created_at"], unique=False)
    op.create_index(op.f("ix_assets_org_id"), "assets", ["org_id"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'student'::character varying"),
        ),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("nickname", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("phone"),
    )
    op.create_index(op.f("ix_users_org_id"), "users", ["org_id"], unique=False)
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_auth_sessions_token_hash"), "auth_sessions", ["token_hash"], unique=True
    )
    op.create_index(op.f("ix_auth_sessions_user_id"), "auth_sessions", ["user_id"], unique=False)
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("script_id", sa.BigInteger(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_llm_usage_org_created", "llm_usage", ["org_id", "created_at"], unique=False
    )
    op.create_index(
        "idx_llm_usage_purpose_created", "llm_usage", ["purpose", "created_at"], unique=False
    )
    op.create_index(op.f("ix_llm_usage_created_at"), "llm_usage", ["created_at"], unique=False)
    op.create_index(op.f("ix_llm_usage_org_id"), "llm_usage", ["org_id"], unique=False)
    op.create_index(op.f("ix_llm_usage_user_id"), "llm_usage", ["user_id"], unique=False)
    op.create_table(
        "materials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("collection_output", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_materials_org_id"), "materials", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_materials_owner_user_id"), "materials", ["owner_user_id"], unique=False
    )
    op.create_table(
        "media_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "model",
            sa.String(length=128),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column("units", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("size", sa.BigInteger(), nullable=False, server_default=sa.text("'0'::bigint")),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("script_id", sa.BigInteger(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_media_usage_kind_created", "media_usage", ["kind", "created_at"], unique=False
    )
    op.create_index(
        "idx_media_usage_org_created", "media_usage", ["org_id", "created_at"], unique=False
    )
    op.create_index("idx_media_usage_session", "media_usage", ["session_id"], unique=False)
    op.create_index(op.f("ix_media_usage_created_at"), "media_usage", ["created_at"], unique=False)
    op.create_index(op.f("ix_media_usage_org_id"), "media_usage", ["org_id"], unique=False)
    op.create_index(op.f("ix_media_usage_user_id"), "media_usage", ["user_id"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "current_stage",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'init'::character varying"),
        ),
        sa.Column("script_id", sa.Integer(), nullable=True),
        sa.Column("player_role", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'::character varying"),
        ),
        sa.Column("active_branch_id", sa.UUID(), nullable=True),
        sa.Column("head_event_id", sa.BigInteger(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sessions_active_branch", "sessions", ["active_branch_id"], unique=False)
    op.create_index(op.f("ix_sessions_org_id"), "sessions", ["org_id"], unique=False)
    op.create_index(op.f("ix_sessions_owner_user_id"), "sessions", ["owner_user_id"], unique=False)
    op.create_table(
        "event_branches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("root_sequence", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("parent_branch_id", sa.UUID(), nullable=True),
        sa.Column("created_by_command_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_event_branches_session", "event_branches", ["session_id"], unique=False)
    op.create_table(
        "scripts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("material_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'::character varying"),
        ),
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'org'::character varying"),
        ),
        sa.Column("script_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["materials.id"],
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scripts_material_id"), "scripts", ["material_id"], unique=False)
    op.create_index(op.f("ix_scripts_org_id"), "scripts", ["org_id"], unique=False)
    op.create_index(op.f("ix_scripts_owner_user_id"), "scripts", ["owner_user_id"], unique=False)
    # 旧链 0003 建的筛选索引（剧本库按状态过滤）；模型同步声明 index=True
    op.create_index("ix_scripts_status", "scripts", ["status"], unique=False)
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("causation_id", sa.UUID(), nullable=True),
        sa.Column("correlation_id", sa.UUID(), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["event_branches.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "sequence", name="uq_events_branch_sequence"),
    )
    op.create_index("idx_events_session", "events", ["session_id", "id"], unique=False)
    op.create_table(
        "script_generations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("script_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["orgs.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(["script_id"], ["scripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_script_generations_script_id"), "script_generations", ["script_id"], unique=False
    )
    op.create_table(
        "commands",
        sa.Column("command_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'received'::text")),
        sa.Column("result_event_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["result_event_id"],
            ["events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("command_id"),
    )
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("state_machine", sa.Text(), nullable=False),
        sa.Column("character_memories", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("plot_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["events.id"],
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_snapshots_session", "snapshots", ["session_id", "event_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index("idx_snapshots_session", table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_table("commands")
    op.drop_index(op.f("ix_script_generations_script_id"), table_name="script_generations")
    op.drop_table("script_generations")
    op.drop_index("idx_events_session", table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_scripts_owner_user_id"), table_name="scripts")
    op.drop_index(op.f("ix_scripts_org_id"), table_name="scripts")
    op.drop_index(op.f("ix_scripts_material_id"), table_name="scripts")
    op.drop_index("ix_scripts_status", table_name="scripts")
    op.drop_table("scripts")
    op.drop_index("idx_event_branches_session", table_name="event_branches")
    op.drop_table("event_branches")
    op.drop_index(op.f("ix_sessions_owner_user_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_org_id"), table_name="sessions")
    op.drop_index("idx_sessions_active_branch", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index(op.f("ix_media_usage_user_id"), table_name="media_usage")
    op.drop_index(op.f("ix_media_usage_org_id"), table_name="media_usage")
    op.drop_index(op.f("ix_media_usage_created_at"), table_name="media_usage")
    op.drop_index("idx_media_usage_session", table_name="media_usage")
    op.drop_index("idx_media_usage_org_created", table_name="media_usage")
    op.drop_index("idx_media_usage_kind_created", table_name="media_usage")
    op.drop_table("media_usage")
    op.drop_index(op.f("ix_materials_owner_user_id"), table_name="materials")
    op.drop_index(op.f("ix_materials_org_id"), table_name="materials")
    op.drop_table("materials")
    op.drop_index(op.f("ix_llm_usage_user_id"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_org_id"), table_name="llm_usage")
    op.drop_index(op.f("ix_llm_usage_created_at"), table_name="llm_usage")
    op.drop_index("idx_llm_usage_purpose_created", table_name="llm_usage")
    op.drop_index("idx_llm_usage_org_created", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_index(op.f("ix_auth_sessions_user_id"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_token_hash"), table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(op.f("ix_users_org_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_assets_org_id"), table_name="assets")
    op.drop_index(op.f("ix_assets_created_at"), table_name="assets")
    op.drop_index("idx_assets_session", table_name="assets")
    op.drop_index("idx_assets_script", table_name="assets")
    op.drop_index("idx_assets_org_dedup", table_name="assets")
    op.drop_table("assets")
    op.drop_index(op.f("ix_asset_jobs_org_id"), table_name="asset_jobs")
    op.drop_index(op.f("ix_asset_jobs_created_at"), table_name="asset_jobs")
    op.drop_index("idx_asset_jobs_status_created", table_name="asset_jobs")
    op.drop_index("idx_asset_jobs_session", table_name="asset_jobs")
    op.drop_table("asset_jobs")
    op.drop_table("prompts")
    op.drop_table("orgs")
