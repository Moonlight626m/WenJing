"""script library: scripts 去 session 绑定 + 生命周期，materials 去 session

剧本实体化（issue #19 / ADR-0002 §3）：
- scripts：移除 session_id（改由 sessions.script_id 反向引用），新增
  material_id / description / status / visibility / updated_at，title 改名 name，
  script_data 允许为空（草稿尚未生成）。
- materials：移除 session_id（素材独立归属）。
- sessions：移除 material_id（剧本经 script_id 引用，素材归属剧本）。

假定 ADR-0002 破坏式重建已生效（无旧匿名数据）；如需回退请 `make db-reset`。

Revision ID: 0003_script_library
Revises: 0002_resource_ownership
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0003_script_library"
down_revision: str | None = "0002_resource_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== scripts：去 session 绑定 + 生命周期列 =====
    op.drop_column("scripts", "session_id")
    op.alter_column("scripts", "title", new_column_name="name")
    op.add_column(
        "scripts",
        sa.Column(
            "material_id",
            sa.Integer(),
            sa.ForeignKey("materials.id"),
            nullable=True,
        ),
    )
    op.add_column("scripts", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "scripts",
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="draft"
        ),
    )
    op.add_column(
        "scripts",
        sa.Column(
            "visibility", sa.String(16), nullable=False, server_default="org"
        ),
    )
    op.add_column(
        "scripts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.alter_column("scripts", "script_data", nullable=True)
    op.create_index("ix_scripts_material_id", "scripts", ["material_id"])
    op.create_index("ix_scripts_status", "scripts", ["status"])

    # ===== materials：去 session 绑定 =====
    op.drop_column("materials", "session_id")

    # ===== sessions：素材归属剧本，移除 material_id =====
    op.drop_column("sessions", "material_id")


def downgrade() -> None:
    bind = op.get_bind()
    # 回退会给被删列补 NOT NULL（无默认）：仅空库可执行，否则给出可读报错。
    for table in ("scripts", "materials", "sessions"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError(
                f"downgrade 0003 需要空库：{table} 存在数据；"
                "请先 `make db-reset`（ADR-0002 破坏式重建）。"
            )
    op.add_column("sessions", sa.Column("material_id", sa.Integer(), nullable=True))

    op.add_column(
        "materials",
        sa.Column(
            "session_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
    )

    op.drop_index("ix_scripts_status", table_name="scripts")
    op.drop_index("ix_scripts_material_id", table_name="scripts")
    op.alter_column("scripts", "script_data", nullable=False)
    op.drop_column("scripts", "updated_at")
    op.drop_column("scripts", "visibility")
    op.drop_column("scripts", "status")
    op.drop_column("scripts", "description")
    op.drop_column("scripts", "material_id")
    op.alter_column("scripts", "name", new_column_name="title")
    op.add_column(
        "scripts",
        sa.Column(
            "session_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id"),
            nullable=False,
        ),
    )
