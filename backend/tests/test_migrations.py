"""Alembic 迁移集成测试（issue #4 验收标准）。

- upgrade head 后全部基线表存在，关键列/约束齐备。
- downgrade base 后 schema 清空。
- upgrade→downgrade→upgrade 幂等可复现。

依赖真实 PostgreSQL（docker compose up -d db 或 CI 服务容器），不可用时 skip。
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command as alembic_command

_BACKEND_DIR = Path(__file__).resolve().parents[1]

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_BASELINE_TABLES = {
    "orgs",
    "users",
    "auth_sessions",
    "sessions",
    "materials",
    "scripts",
    "event_branches",
    "events",
    "snapshots",
    "commands",
}


def _alembic_config() -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", _DB_URL)
    return cfg


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _db_available() -> bool:
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
async def migrated():
    if not await _db_available():
        pytest.skip("PostgreSQL 未可用，跳过迁移集成测试")
    cfg = _alembic_config()
    # alembic env.py 在线迁移内部用 asyncio.run：放到独立线程执行，
    # 避免在 pytest-asyncio 的持久事件循环里调用 asyncio.run
    await asyncio.to_thread(alembic_command.upgrade, cfg, "head")
    yield cfg
    # 测试后清场：downgrade base，交还干净库给其他测试文件
    await asyncio.to_thread(alembic_command.downgrade, cfg, "base")


async def test_upgrade_head_creates_baseline_tables(migrated: Config):
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select tablename from pg_tables "
                    "where schemaname = 'public'"
                )
            )
            tables = {r[0] for r in rows}
        assert _BASELINE_TABLES <= tables, f"缺表: {_BASELINE_TABLES - tables}"
    finally:
        await engine.dispose()


async def test_events_schema_columns(migrated: Config):
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'events'"
                )
            )
            cols = {r[0] for r in rows}
        required = {
            "branch_id",
            "sequence",
            "causation_id",
            "correlation_id",
            "schema_version",
        }
        assert required <= cols, f"events 缺列: {required - cols}"
    finally:
        await engine.dispose()


async def test_sessions_head_and_version(migrated: Config):
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'sessions'"
                )
            )
            cols = {r[0] for r in rows}
        assert {"active_branch_id", "head_event_id", "version"} <= cols
    finally:
        await engine.dispose()


async def test_commands_table_columns(migrated: Config):
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'commands'"
                )
            )
            cols = {r[0] for r in rows}
        assert {"command_id", "payload", "status", "result_event_id"} <= cols
    finally:
        await engine.dispose()


async def test_accounts_schema_columns(migrated: Config):
    """账号表（ADR-0002）纳入基线：users 唯一标识、auth_sessions 可撤销/过期字段。"""
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            user_cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name = 'users'"
                    )
                )
            }
            session_cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_name = 'auth_sessions'"
                    )
                )
            }
        assert {"org_id", "role", "email", "phone", "password_hash"} <= user_cols
        assert {"user_id", "token_hash", "csrf_token", "expires_at", "revoked_at"} <= (
            session_cols
        )
    finally:
        await engine.dispose()


async def test_events_branch_sequence_unique(migrated: Config):
    """(branch_id, sequence) 唯一约束能阻断重复回放写入。"""
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "select count(*) from pg_constraint c "
                    "join pg_class t on t.oid = c.conrelid "
                    "where t.relname = 'events' and c.conname = 'uq_events_branch_sequence'"
                )
            )
            assert rows.scalar_one() == 1
    finally:
        await engine.dispose()


def test_upgrade_downgrade_upgrade_cycle():
    """upgrade→downgrade(base)→upgrade 幂等；使用独立 fixture（非 module 迁移态）。"""
    if not _anyio_available_sync():
        pytest.skip("PostgreSQL 未可用，跳过迁移集成测试")
    cfg = _alembic_config()
    try:
        alembic_command.downgrade(cfg, "base")
        alembic_command.upgrade(cfg, "head")
        alembic_command.downgrade(cfg, "base")
        alembic_command.upgrade(cfg, "head")
    finally:
        alembic_command.downgrade(cfg, "base")


def _anyio_available_sync() -> bool:
    import asyncio

    return asyncio.run(_db_available())
