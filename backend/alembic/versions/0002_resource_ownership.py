"""resource ownership: sessions/materials/scripts 加 owner_user_id + org_id

归属改造（issue #18 / ADR-0002）：为三张业务资源表补 `org_id` 与
`owner_user_id`，作为跨 org 隔离与「仅 owner 可见」的判定依据。

假定 ADR-0002 的破坏式重建已生效（游戏表为空）；若库中残留旧匿名数据，
请先 `make db-reset` 再迁移。

Revision ID: 0002_resource_ownership
Revises: 0001_initial
Create Date: 2026-09-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0002_resource_ownership"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("sessions", "materials", "scripts")


def upgrade() -> None:
    bind = op.get_bind()
    # 归属列 NOT NULL 且无合理默认值：仅当三表为空时可直接补列。
    # 若存在旧匿名数据，给出可读报错，避免迁移在中途以晦涩的约束错误失败。
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError(
                f"{table} 存在旧数据，无法补 NOT NULL 归属列；"
                "请先执行 `make db-reset`（ADR-0002 破坏式重建）后重试。"
            )
    for table in _TABLES:
        op.add_column(
            table,
            sa.Column(
                "org_id",
                pg.UUID(as_uuid=True),
                sa.ForeignKey("orgs.id"),
                nullable=False,
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "owner_user_id",
                pg.UUID(as_uuid=True),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
        )
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])
        op.create_index(f"ix_{table}_owner_user_id", table, ["owner_user_id"])


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_owner_user_id", table_name=table)
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_column(table, "owner_user_id")
        op.drop_column(table, "org_id")
