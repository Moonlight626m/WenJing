"""prompt 取值载体与存储端口（PromptMgr 组件，多阶段可扩展）。

设计（spec 裁决）：
- prompt 不再硬编码于业务代码：system/准则/判据类文案落 `prompts` 表，
  每次使用走 DB I/O；缺行/禁用/DB 异常时回退代码内默认（defaults），
  功能永不因缺表挂掉。
- 键为「阶段 × 节点 × 版本 × 段落」四维：(stage, node, version, section)，
  新阶段只需写新 stage 值，表结构与 manager 不变。
- 输出契约文本（字段类型说明）与业务运行期无关，留在代码不落库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class PromptStore(Protocol):
    """prompt 覆盖层存储端口（infrastructure/db/prompt_store.py 实现）。"""

    async def load(self, stage: str, node: str, version: str) -> dict[str, str]:
        """读取某 (stage, node, version) 的启用段落：{section: body}。"""
        ...


@dataclass(frozen=True)
class PromptBundle:
    """一次生成调用的 prompt 段落集合（已合并 DB 覆盖与代码默认）。"""

    stage: str
    node: str
    version: str
    sections: dict[str, str] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)  # section -> db | default

    def text(self, section: str) -> str:
        try:
            return self.sections[section]
        except KeyError as exc:  # pragma: no cover - 编码期错误，直接暴露
            raise KeyError(f"prompt section missing: {self.stage}/{self.node}/{section}") from exc

    @property
    def db_sections(self) -> int:
        """来自 DB 覆盖的段落数（观测用）。"""
        return sum(1 for s in self.sources.values() if s == "db")


def default_bundle(stage: str, node: str, version: str, sections: dict[str, str]) -> PromptBundle:
    return PromptBundle(
        stage=stage,
        node=node,
        version=version,
        sections=dict(sections),
        sources={s: "default" for s in sections},
    )


__all__ = ["PromptBundle", "PromptStore", "default_bundle"]
