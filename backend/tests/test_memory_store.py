"""MemoryStore 端口 + 文件系统实例实现（stage3-chronicle-redesign §1.3/§1.4）。

覆盖：打开/锁互斥、追加与崩溃恢复（尾部坏行）、限知编年史、私有知识缓存、
CharacterInstance 刷盘、以及 SessionApplication 的 fs 后端接线（null 后端
不下盘）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from app.domain.game.event import GameEvent
from app.domain.game.memory import MemoryStore


def _event(event_id: int, event_type: str, **payload: object) -> GameEvent:
    return GameEvent(
        event_id=event_id, event_type=event_type, payload=dict(payload)
    )


@pytest.fixture()
def instance_root(tmp_path: Path) -> Path:
    return tmp_path / "instances"


async def test_open_creates_layout_and_lock(instance_root: Path) -> None:
    from app.infrastructure.memory_store import open_file_memory_store

    store = await open_file_memory_store(instance_root, "inst-1", script_name="背影")
    try:
        assert isinstance(store, MemoryStore)
        assert (instance_root / "inst-1").is_dir()
        assert (instance_root / "inst-1" / "instance.lock").exists()
        meta = json.loads((instance_root / "inst-1" / "meta.json").read_text("utf-8"))
        assert meta["script_name"] == "背影"
        assert meta["schema_version"] == 1
    finally:
        await store.close()
    assert not (instance_root / "inst-1" / "instance.lock").exists()


async def test_lock_is_exclusive(instance_root: Path) -> None:
    from app.infrastructure.errx import Error
    from app.infrastructure.memory_store import open_file_memory_store

    first = await open_file_memory_store(instance_root, "inst-1")
    try:
        with pytest.raises(Error):
            await open_file_memory_store(instance_root, "inst-1")
    finally:
        await first.close()
    # 释放后可重新打开
    second = await open_file_memory_store(instance_root, "inst-1")
    await second.close()


async def test_stale_empty_lock_reclaimed(instance_root: Path) -> None:
    """崩溃在写 PID 前留下空锁：超过阈值后按残留接管。"""
    from app.infrastructure.memory_store import open_file_memory_store

    directory = instance_root / "inst-1"
    directory.mkdir(parents=True)
    lock = directory / "instance.lock"
    lock.write_text("", encoding="utf-8")
    old = time.time() - 120
    os.utime(lock, (old, old))

    store = await open_file_memory_store(instance_root, "inst-1")
    await store.close()


async def test_append_and_read_roundtrip(instance_root: Path) -> None:
    from app.infrastructure.memory_store import open_file_memory_store

    store = await open_file_memory_store(instance_root, "inst-1")
    try:
        await store.append_event(_event(1, "world_chronicle", round=1, text="a"))
        await store.append_event(_event(2, "world_chronicle", round=2, text="b"))
        # 每行合法 JSONL，且 fsync 后立即可读
        await store.append_event(_event(3, "player_action", type="speak"))
        events = await store.read_events()
        assert [e.event_id for e in events] == [1, 2, 3]
        assert await store.chronicle() == "a\n\nb"
    finally:
        await store.close()


async def test_crash_tail_partial_line_repaired(instance_root: Path) -> None:
    """崩溃恢复：尾部半截行被隔断，完整行全部可读。"""
    from app.infrastructure.memory_store import open_file_memory_store

    store = await open_file_memory_store(instance_root, "inst-1")
    await store.append_event(_event(1, "world_chronicle", round=1, text="完整"))
    await store.close()
    # 模拟断电：追加一把没有结束符的半行
    path = instance_root / "inst-1" / "events.jsonl"
    with open(path, "ab") as f:
        f.write(b'{"event_id": 2, "event_type": "wo')

    store = await open_file_memory_store(instance_root, "inst-1")
    try:
        events = await store.read_events()
        assert [e.event_id for e in events] == [1]
    finally:
        await store.close()


async def test_chronicle_viewer_limit_knowledge(instance_root: Path) -> None:
    """限知视角：viewer 只看到自己在场的编年史段。"""
    from app.infrastructure.memory_store import open_file_memory_store

    store = await open_file_memory_store(instance_root, "inst-1")
    try:
        await store.append_event(
            _event(1, "world_chronicle", round=1, text="父亲和我都在场",
                   present=["我", "父亲"], location_key="scene_1")
        )
        await store.append_event(
            _event(2, "world_chronicle", round=2, text="只有父亲的独白",
                   present=["父亲"], location_key="scene_2")
        )
        mine = await store.chronicle(viewer="我")
        assert "父亲和我都在场" in mine
        assert "独白" not in mine
        full = await store.chronicle()
        assert "独白" in full
    finally:
        await store.close()


async def test_private_knowledge_cache_roundtrip(instance_root: Path) -> None:
    from app.infrastructure.memory_store import open_file_memory_store

    store = await open_file_memory_store(instance_root, "inst-1")
    try:
        await store.save_private_knowledge("父亲", ["哎，现在写信不便"])
        assert await store.private_knowledge("父亲") == ("哎，现在写信不便",)
        assert await store.private_knowledge("我") == ()
    finally:
        await store.close()


async def test_character_instance_persists_derived_memory(instance_root: Path) -> None:
    """CharacterInstance 把进程内记忆窗口刷成实例目录的派生缓存。"""
    from types import SimpleNamespace

    from app.domain.agents.character import CharacterInstance
    from app.infrastructure.memory_store import open_file_memory_store

    agent = SimpleNamespace(
        memory=SimpleNamespace(
            personal_log=["提议：送行"], working_memory=[{"role": "父亲", "content": "事已如此"}]
        )
    )
    inst = CharacterInstance(agent=agent, name="父亲", memory=None)
    await inst.persist_private_knowledge()  # 无句柄 no-op，不抛

    store = await open_file_memory_store(instance_root, "inst-1")
    inst2 = CharacterInstance(agent=agent, name="父亲", memory=store)
    await inst2.persist_private_knowledge()
    await store.close()
    rows = (instance_root / "inst-1" / "memory" / "父亲.json").read_text("utf-8")
    data = json.loads(rows)
    assert "提议：送行" in data
    assert any("事已如此" in item for item in data)


def test_session_application_wires_memory_backend(tmp_path: Path) -> None:
    """fs 后端接线：root 配置流转到 SessionApplication，null 后端不建 store。"""
    from app.services.session_runtime import SessionApplication

    class _NullLLM:
        pass

    app = SessionApplication(
        session_factory=None,  # 不触库：只验证接线
        agent_llm=_NullLLM(),  # type: ignore[arg-type]
        memory_backend="fs",
        memory_fs_root=str(tmp_path),
    )
    assert app._memory_backend == "fs"
    assert app._memory_fs_root == str(tmp_path)

    plain = SessionApplication(
        session_factory=None,
        agent_llm=_NullLLM(),  # type: ignore[arg-type]
    )
    assert plain._memory_backend == "null"


async def test_sync_events_mirrors_incrementally(instance_root: Path) -> None:
    """事件镜像：增量写、按 (branch_id, event_id) 去重、可重开续写。"""
    from app.infrastructure.memory_store import open_file_memory_store

    store = await open_file_memory_store(instance_root, "inst-1")
    await store.sync_events(
        [_event(1, "player_action", text="a"), _event(2, "world_chronicle", text="b")]
    )
    await store.sync_events(
        [_event(2, "world_chronicle", text="b"), _event(3, "character_speech", text="c")]
    )
    assert [e.event_id for e in await store.read_events()] == [1, 2, 3]
    await store.close()

    # 重新打开：去重基线从文件恢复，不重复写
    store = await open_file_memory_store(instance_root, "inst-1")
    try:
        await store.sync_events([_event(3, "character_speech", text="c")])
        assert [e.event_id for e in await store.read_events()] == [1, 2, 3]
    finally:
        await store.close()
