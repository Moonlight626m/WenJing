"""PromptManager：DB 覆盖层解析 + 代码默认回退（PromptMgr 组件核心）。

- 每次调用实时读 DB（不做长缓存；单 worker + 连接池开销可忽略，spec 裁决）；
- store 为 None（未接线/测试）或 DB 异常/无行时回退 defaults，并记观测日志；
- 段落合并语义：DB enabled 行逐段覆盖默认，未覆盖段落保持默认。
"""

from __future__ import annotations

import logging

from app.domain.prompts.bundle import PromptBundle, PromptStore, default_bundle
from app.domain.prompts.defaults import DEFAULTS

logger = logging.getLogger("wenjing.prompts")


class PromptManager:
    """业务侧唯一入口：bundle(stage, node, version) -> PromptBundle。"""

    def __init__(self, store: PromptStore | None = None) -> None:
        self._store = store

    async def bundle(self, stage: str, node: str, version: str) -> PromptBundle:
        fallback = DEFAULTS.get((stage, node, version))
        if fallback is None:  # pragma: no cover - 编码期错误（版本未注册）
            raise KeyError(f"prompt defaults not registered: {stage}/{node}/{version}")
        rows: dict[str, str] = {}
        if self._store is not None:
            try:
                rows = await self._store.load(stage, node, version)
            except Exception as exc:  # noqa: BLE001 - DB 异常不阻塞生成
                logger.warning(
                    "prompt_store_load_failed fallback=defaults stage=%s node=%s "
                    "version=%s reason=%s",
                    stage,
                    node,
                    version,
                    exc,
                )
                rows = {}
        if not rows:
            return default_bundle(stage, node, version, fallback)
        sections = dict(fallback)
        sources = {s: "default" for s in fallback}
        for section, body in rows.items():
            if section not in sections:
                logger.warning(
                    "prompt_db_unknown_section_ignored stage=%s node=%s section=%s",
                    stage,
                    node,
                    section,
                )
                continue
            sections[section] = body
            sources[section] = "db"
        return PromptBundle(
            stage=stage, node=node, version=version, sections=sections, sources=sources
        )


__all__ = ["PromptManager"]
