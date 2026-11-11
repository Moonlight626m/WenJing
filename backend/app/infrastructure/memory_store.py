"""文件系统 `MemoryStore` 默认实现（stage3-chronicle-redesign §1.4）。

单实例部署（每学生一台设备一局）下的默认存储：一个实例就是
`<root>/<instance_id>/` 目录，事件行 (`events.jsonl`) 是追加权威，
`memory/` 只是派生缓存（`snapshots/` 暂未启用，见设计 §5.1）。

`read_events()` / `chronicle()` 读的是**追加镜像全量**：回溯后放弃的旧分支行
保留可审计，但镜像未存分支血缘，因此不会按活动分支裁剪（设计 §7）。

并发约束：
- **单写者**：`open()` 拿 `instance.lock`（`O_CREAT|O_EXCL` 文件创建锁，
  不用 POSIX-only 的 fcntl 锁，Windows 机房兼容）；拿不到即抛错。
- **追加语义**：`O_APPEND` 写入并 `fsync`；进程崩溃留下尾部不完整行时，
  下次 `open()` 以「最后一行能否 `json.loads`」收端——非破坏性坏行偏移写
  空字节隔断，坏行日志警告后跳过。
- **缓存原子替换**：`memory/<character>.json` 先写临时文件再 `os.replace`。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.domain.game.chronicle import derive_chronicle
from app.domain.game.event import GameEvent
from app.infrastructure.errx import codes, new

logger = logging.getLogger("wenjing.infra.memory_store")

SCHEMA_VERSION = 1
_LOCK_NAME = "instance.lock"
#: 空锁（创建后、写 PID 前崩溃）超过这个年龄视为残留，可安全接管。
_STALE_EMPTY_LOCK_SECONDS = 60.0
_EVENTS_NAME = "events.jsonl"
_META_NAME = "meta.json"
_MEMORY_DIR = "memory"


class FileMemoryStore:
    """本地文件系统实例目录存储（默认实现）。"""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        #: `events.jsonl` 已写入事件的去重键（惰性加载）
        self._seen: set[tuple[int, int]] | None = None

    # ===== 生命周期 =====

    async def open(self, *, script_name: str = "") -> None:
        """打开实例：建目录、拿单写者锁、写/读 meta、修复坏行尾部。"""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._open_sync, script_name)

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._close_sync)

    def _lock_path(self) -> Path:
        return self.dir / _LOCK_NAME

    def _events_path(self) -> Path:
        return self.dir / _EVENTS_NAME

    def _meta_path(self) -> Path:
        return self.dir / _META_NAME

    def _open_sync(self, script_name: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        lock = self._lock_path()
        try:
            self._lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # 崩溃恢复：上次进程留下的锁若属于已死进程，接管它；仍活着则拒绝。
            if not self._take_over_stale_lock(lock):
                raise new(
                    codes.PER_WRITE_FAILED,
                    extra={
                        "reason": "instance locked",
                        "path": str(lock),
                    },
                ) from None
            try:
                self._lock_fd = os.open(
                    lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
            except FileExistsError:
                raise new(
                    codes.PER_WRITE_FAILED,
                    extra={"reason": "instance locked", "path": str(lock)},
                ) from None
        os.write(self._lock_fd, str(os.getpid()).encode())
        if not self._meta_path().exists():
            self._atomic_write_json(
                self._meta_path(),
                {
                    "script_name": script_name,
                    "created_at": time.time(),
                    "schema_version": SCHEMA_VERSION,
                },
            )
        self._repair_tail()
        self._seen = None

    @staticmethod
    def _take_over_stale_lock(lock: Path) -> bool:
        """锁持有进程已死 → 删除残留锁并允许重开。

        Windows 上 `os.kill(pid, 0)` 走 `TerminateProcess`，会把仍活着的持锁
        进程杀掉，因此非 POSIX 平台一律保守拒绝接管。
        """
        try:
            pid = int(lock.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            pid = 0
        if pid <= 0:
            # 崩溃在「创建锁」与「写入 PID」之间会留下空锁；按年龄判定残留，
            # 避免目录被永久锁死（正常写入窗口只有微秒级）。
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                return False
            if age <= _STALE_EMPTY_LOCK_SECONDS:
                return False
            try:
                lock.unlink()
            except OSError:
                return False
            logger.warning("memory_store_stale_lock_reclaimed", extra={"pid": 0})
            return True
        if os.name != "posix":
            return False
        try:
            os.kill(pid, 0)  # POSIX：探测进程存活
        except ProcessLookupError:
            try:
                lock.unlink()
            except OSError:
                return False
            logger.warning("memory_store_stale_lock_reclaimed", extra={"pid": pid})
            return True
        except OSError:
            return False
        return False

    def _close_sync(self) -> None:
        fd = getattr(self, "_lock_fd", None)
        if fd is not None:
            os.close(fd)
            del self._lock_fd
            try:
                self._lock_path().unlink()
            except FileNotFoundError:
                pass

    def _repair_tail(self) -> None:
        """追加日志的崩溃恢复：尾部不完整行隔断（不删除历史字节）。"""
        path = self._events_path()
        if not path.exists():
            return
        data = path.read_bytes()
        if not data:
            return
        # 从尾部找最后一个完整行结束符；其后任何字节都是半行
        complete_end = data.rfind(b"\n")
        tail = data[complete_end + 1 :]
        if not tail:
            return
        try:
            json.loads(tail)
        except ValueError:
            logger.warning("memory_store_trailing_partial_line", extra={"bytes": len(tail)})
            with open(path, "ab") as f:
                f.write(b"\n")

    # ===== 读 =====

    async def read_events(self, *, limit: int | None = None) -> list[GameEvent]:
        """读镜像全部事件行（含回溯后放弃的旧分支行，可审计）。"""
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, self._read_rows_sync)
        if limit is not None:
            rows = rows[-limit:]
        return rows

    def _read_rows_sync(self) -> list[GameEvent]:
        path = self._events_path()
        if not path.exists():
            return []
        out: list[GameEvent] = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                logger.warning("memory_store_bad_line_skipped", extra={"line": i})
                continue
            out.append(
                GameEvent(
                    event_id=int(row.get("event_id", 0)),
                    event_type=str(row.get("event_type", "")),
                    payload=dict(row.get("payload") or {}),
                    parent_id=row.get("parent_id"),
                    branch_id=int(row.get("branch_id", 1)),
                    timestamp=float(row.get("timestamp", 0) or 0),
                )
            )
        return out

    async def chronicle(self, *, viewer: str | None = None) -> str:
        events = await self.read_events()
        return derive_chronicle(events, viewer=viewer)

    async def private_knowledge(self, character: str) -> tuple[str, ...]:
        cache = self.dir / _MEMORY_DIR / f"{character}.json"
        loop = asyncio.get_running_loop()

        def _read() -> tuple[str, ...]:
            if not cache.exists():
                return ()
            try:
                rows = json.loads(cache.read_text(encoding="utf-8"))
                return tuple(str(r) for r in rows if str(r).strip())
            except ValueError:
                logger.warning("memory_cache_corrupt_rebuild", extra={"character": character})
                return ()

        return await loop.run_in_executor(None, _read)

    # ===== 写 =====

    async def append_event(
        self, event: GameEvent, *, character: str | None = None
    ) -> None:
        """追加一条事件（带 `character` = 该角色的私有事件日志）。"""
        loop = asyncio.get_running_loop()
        row: dict[str, Any] = event.to_dict()
        if character is not None:
            row["character"] = character
        line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
        await loop.run_in_executor(None, self._append_sync, line.encode("utf-8"))

    async def sync_events(self, events: Iterable[GameEvent]) -> None:
        """把事件流增量镜像到 `events.jsonl`（按 `(branch_id, event_id)` 去重）。

        实例目录是事件流的**镜像载体**（单实例部署下即本地事件日志）；权威仍
        在事件存储。回溯放弃的旧分支事件已写入的行保留（可审计），不回删。
        """
        if self._seen is None:
            self._load_seen()
        loop = asyncio.get_running_loop()
        payloads: list[bytes] = []
        new_keys: list[tuple[int, int]] = []
        for event in events:
            key = (event.branch_id, event.event_id)
            if key in self._seen:
                continue
            new_keys.append(key)
            payloads.append(
                (
                    json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n"
                ).encode("utf-8")
            )
        if not payloads:
            return
        # 落盘成功后才登记去重键：写失败时下一轮 flush 仍会重试这批事件。
        await loop.run_in_executor(None, self._append_sync, b"".join(payloads))
        self._seen.update(new_keys)

    def _load_seen(self) -> None:
        seen: set[tuple[int, int]] = set()
        for event in self._read_rows_sync():
            key = (event.branch_id, event.event_id)
            if key in seen:
                # 恢复后事件 id 可能重新从 1 编；同键不同内容时以先写入者为准。
                continue
            seen.add(key)
        self._seen = seen

    def _append_sync(self, data: bytes) -> None:
        # O_APPEND 单进程内写者恒定；fsync 保证断电下行的完整性
        fd = os.open(self._events_path(), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)

    async def save_private_knowledge(self, character: str, items: list[str]) -> None:
        """刷新角色私有知识缓存（派生数据，丢了可从事件重建）。"""
        path = self.dir / _MEMORY_DIR / f"{character}.json"
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._atomic_write_json, path, items)

    def _atomic_write_json(self, path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)


async def open_file_memory_store(
    root: str | Path, instance_id: str, *, script_name: str = ""
) -> FileMemoryStore:
    """打开（或创建）一个本地实例目录。单写者冲突立即见错。"""
    store = FileMemoryStore(Path(root) / instance_id)
    await store.open(script_name=script_name)
    return store


__all__ = ["FileMemoryStore", "open_file_memory_store"]
