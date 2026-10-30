"""Stage1 五类校验（issue #11 验收标准 3）。

结构 / 证据覆盖 / 人物一致性 / 事件顺序 / 教学适配。
每个校验器返回 issue 列表（空 = 通过）；全部通过才允许 ScriptPackage 进入游戏。
"""

from __future__ import annotations

from app.contracts.content import TextAnalysis
from app.contracts.material import EvidenceSourceType
from app.contracts.script import ScriptPackage

VALIDATORS: tuple[str, ...] = (
    "structure",
    "evidence",
    "characters",
    "event_order",
    "teaching",
)


def validate_structure(pkg: ScriptPackage) -> list[str]:
    issues: list[str] = []
    if not pkg.characters:
        issues.append("characters empty")
    if not pkg.scenes:
        issues.append("scenes empty")
    beat_ids: list[int] = []
    for scene in pkg.scenes:
        if not scene.beats:
            issues.append(f"scene {scene.scene_id} has no beats")
        for beat in scene.beats:
            beat_ids.append(beat.beat_id)
    if beat_ids != sorted(beat_ids) or len(set(beat_ids)) != len(beat_ids):
        issues.append("beat ids must be unique and ordered")
    if pkg.stage2_ending_beat_id not in beat_ids:
        issues.append("stage2_ending_beat_id not found in beats")
    if not pkg.playable_roles:
        issues.append("playable_roles empty")
    return issues


def validate_evidence(pkg: ScriptPackage) -> list[str]:
    issues: list[str] = []
    key_beats = [b for s in pkg.scenes for b in s.beats if b.is_key_event]
    for beat in key_beats:
        original = [
            e
            for e in beat.evidence_refs
            if e.source_type == EvidenceSourceType.ORIGINAL_TEXT.value
            and getattr(e, "excerpt", "")
        ]
        if not original:
            issues.append(f"key beat {beat.beat_id} lacks original-text evidence")
    return issues


def validate_characters(pkg: ScriptPackage, analysis: TextAnalysis) -> list[str]:
    issues: list[str] = []
    source_names = {c.name for c in analysis.characters}
    for char in pkg.characters:
        if char.name not in source_names:
            issues.append(f"fabricated character not in source: {char.name}")
    for scene in pkg.scenes:
        for p in scene.participants:
            if p not in source_names:
                issues.append(f"scene participant not in source: {p}")
    for role in pkg.playable_roles:
        if role not in {c.name for c in pkg.characters}:
            issues.append(f"playable role not a script character: {role}")
    return issues


def validate_event_order(pkg: ScriptPackage, analysis: TextAnalysis) -> list[str]:
    """关键 beat 的出现顺序必须符合原文关键事件顺序（不能倒序/跳序乱序）。"""
    issues: list[str] = []
    ordered_titles = [ke.title for ke in sorted(analysis.key_events, key=lambda k: k.order)]
    last_index = -1
    for scene in pkg.scenes:
        for beat in scene.beats:
            if not beat.is_key_event:
                continue
            idx = _match_index(beat.description, ordered_titles)
            if idx is None:
                continue  # 无法匹配的 beat 由 evidence/characters 校验把关
            if idx < last_index:
                issues.append(f"key beat {beat.beat_id} reverses source event order")
                return issues
            last_index = idx
    return issues


def _match_index(description: str, ordered_titles: list[str]) -> int | None:
    for i, title in enumerate(ordered_titles):
        if title and (title in description or description in title):
            return i
    return None


def validate_teaching(pkg: ScriptPackage) -> list[str]:
    issues: list[str] = []
    if not pkg.teaching_focus:
        issues.append("teaching_focus empty")
    char_names = {c.name for c in pkg.characters}
    if not set(pkg.playable_roles) <= char_names:
        issues.append("playable_roles must be script characters")
    for char in pkg.characters:
        if not char.public_background.strip():
            issues.append(f"character {char.name} lacks public_background")
    return issues


def validate_all(pkg: ScriptPackage, analysis: TextAnalysis) -> dict[str, list[str]]:
    """运行全部五类校验，返回 {validator_name: issues}（空 issues = 通过）。"""
    return {
        "structure": validate_structure(pkg),
        "evidence": validate_evidence(pkg),
        "characters": validate_characters(pkg, analysis),
        "event_order": validate_event_order(pkg, analysis),
        "teaching": validate_teaching(pkg),
    }
