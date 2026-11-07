"""Stage1 五类校验（issue #11 验收标准 3）。

结构 / 证据覆盖 / 人物一致性 / 事件顺序 / 教学适配。
每个校验器返回 issue 列表（空 = 通过）；全部通过才允许 ScriptPackage 进入游戏。
"""

from __future__ import annotations

from app.contracts.content import TextAnalysis
from app.contracts.material import EvidenceSourceType
from app.contracts.script import BranchScene, Scene, ScriptPackage

VALIDATORS: tuple[str, ...] = (
    "structure",
    "evidence",
    "characters",
    "event_order",
    "teaching",
    "branches",
    "replay",
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


def validate_branches(pkg: ScriptPackage, analysis: TextAnalysis) -> list[str]:
    """伪分支校验（branch-montage-dm §4）：分支不得触碰关键事件大纲。

    只查结构：branch_id 唯一、分支 beat 非关键事件、参与者/分支人物取自
    原文人物、分支场景必须有介入点。value_turn 与结局忠实性属于语义层，
    由 doubter v3 的 branch_audit_rules 承担，此处不做文本判断。
    """
    issues: list[str] = []
    source_names = {c.name for c in analysis.characters}
    ending_beat = pkg.stage2_ending_beat_id
    for scene in pkg.scenes:
        branch_ids = [b.branch_id for b in scene.branches]
        if len(set(branch_ids)) != len(branch_ids):
            issues.append(f"scene {scene.scene_id} duplicate branch ids")
        if scene.branches and scene.interaction_point is None:
            issues.append(f"scene {scene.scene_id} has branches without interaction_point")
        for branch in scene.branches:
            for p in branch.participants:
                if p not in source_names:
                    issues.append(f"branch {branch.branch_id} participant not in source: {p}")
            if not branch.beats:
                issues.append(f"branch {branch.branch_id} has no beats")
            for beat in branch.beats:
                if beat.is_key_event:
                    issues.append(f"branch {branch.branch_id} beat is_key_event not allowed")
                if beat.evidence_refs:
                    issues.append(f"branch {branch.branch_id} beat carries evidence_refs")
                if beat.beat_id == ending_beat:
                    issues.append(f"branch {branch.branch_id} beat_id collides with ending")
    return issues


def validate_replay(pkg: ScriptPackage) -> list[str]:
    """珊瑚图校验（design play-through-redesign §A3）。

    旧剧本（无 options/dialogue/endings）恒通过——新字段全为可选是零迁移的前提。
    只查确定性结构；台词质量/结局忠实性仍由 doubter 承担。
    """
    issues: list[str] = []

    scene_ids = [s.scene_id for s in pkg.scenes]
    scene_by_id = {s.scene_id: s for s in pkg.scenes}
    ending_ids = {e.ending_id for e in pkg.endings}
    has_graph = any(s.options for s in pkg.scenes) or bool(pkg.endings)

    if len(ending_ids) != len(pkg.endings):
        issues.append("duplicate ending_id")
    if len(pkg.endings) > 4:
        issues.append("too many endings (max 4)")
    if has_graph:
        if not pkg.endings:
            issues.append("graph script requires endings")
        elif not any(e.kind == "canonical" for e in pkg.endings):
            issues.append("graph script requires at least one canonical ending")

    for scene in pkg.scenes:
        branch_ids = {b.branch_id for b in scene.branches}
        distractor_count = 0
        for option in scene.options:
            if option.kind == "distractor":
                distractor_count += 1
            targets = [
                option.branch_id is not None,
                option.target_scene_id is not None,
                option.ending_id is not None,
            ]
            if sum(targets) > 1:
                issues.append(
                    f"scene {scene.scene_id} option {option.option_id} has multiple targets"
                )
            if option.branch_id is not None and option.branch_id not in branch_ids:
                issues.append(
                    f"scene {scene.scene_id} option {option.option_id} "
                    f"references unknown branch {option.branch_id}"
                )
            if (
                option.target_scene_id is not None
                and option.target_scene_id not in scene_ids
            ):
                issues.append(
                    f"scene {scene.scene_id} option {option.option_id} "
                    f"references unknown scene {option.target_scene_id}"
                )
            if option.ending_id is not None and option.ending_id not in ending_ids:
                issues.append(
                    f"scene {scene.scene_id} option {option.option_id} "
                    f"references unknown ending {option.ending_id}"
                )
        if distractor_count > 2:
            issues.append(f"scene {scene.scene_id} has more than 2 distractor options")

        for branch in scene.branches:
            if branch.return_scene_id is not None and branch.return_scene_id not in scene_ids:
                issues.append(
                    f"branch {branch.branch_id} returns to unknown scene "
                    f"{branch.return_scene_id}"
                )
            if branch.ending_id is not None and branch.ending_id not in ending_ids:
                issues.append(
                    f"branch {branch.branch_id} references unknown ending {branch.ending_id}"
                )
            if len(branch.dialogue) > 4:
                issues.append(f"branch {branch.branch_id} has more than 4 dialogue lines")

        participants = set(scene.participants)
        for beat in scene.beats:
            for line in beat.dialogue:
                if line.speaker is not None and line.speaker not in participants:
                    issues.append(
                        f"scene {scene.scene_id} dialogue speaker not in participants: "
                        f"{line.speaker}"
                    )
        for branch in scene.branches:
            allowed = set(branch.participants) or participants
            for line in branch.dialogue:
                if line.speaker is not None and line.speaker not in allowed:
                    issues.append(
                        f"branch {branch.branch_id} dialogue speaker not in participants: "
                        f"{line.speaker}"
                    )

    if has_graph:
        issues.extend(_check_replay_cycles(pkg, scene_by_id))
        issues.extend(_check_key_event_traversal(pkg))
        issues.extend(_check_canonical_ending(pkg))
    return issues


def _resolve_branch_target(
    branch: BranchScene, next_scene_id: int | None
) -> int | None:
    """分支播完去哪个场景；None = 终局或回决策点（都不是主干推进）。

    终局分支（`ending_id` 非空）不回主干，即使 `return_mode` 是 `continue`
    也不得把主线往下带——这是「分支是终局」的唯一判据。
    """
    if branch.ending_id is not None:
        return None
    if branch.return_mode == "choice":
        return None
    return branch.return_scene_id or next_scene_id


def _scene_targets(scene: Scene, next_scene_id: int | None) -> list[int]:
    """该场景向外的场景边：决策点目标 + 无 options 时的隐式主干续接。

    没有 options 的场景是线性播放，隐式续接主干下一场；有 options 时
    主干只经「全空目标」的选项续接，不再无条件续接。
    """
    if not scene.options:
        return [next_scene_id] if next_scene_id is not None else []
    targets: list[int] = []
    for option in scene.options:
        if option.ending_id is not None:
            continue
        if option.target_scene_id is not None:
            targets.append(option.target_scene_id)
        elif option.branch_id is not None:
            branch = next(
                (b for b in scene.branches if b.branch_id == option.branch_id), None
            )
            if branch is None:
                continue
            target = _resolve_branch_target(branch, next_scene_id)
            if target is not None:
                targets.append(target)
        elif next_scene_id is not None:
            targets.append(next_scene_id)
    return targets


def _check_replay_cycles(pkg: ScriptPackage, scene_by_id: dict[int, Scene]) -> list[str]:
    """隐含环检测：`continue` 回边与主干续接连成的环；`choice` 回决策点不算环。"""
    issues: list[str] = []
    scene_ids = [s.scene_id for s in pkg.scenes]

    def next_scene(scene_id: int) -> int | None:
        idx = scene_ids.index(scene_id)
        return scene_ids[idx + 1] if idx + 1 < len(scene_ids) else None

    def has_cycle_from(scene_id: int, seen: frozenset[int]) -> bool:
        if scene_id in seen:
            return True
        seen = seen | {scene_id}
        for target in _scene_targets(scene_by_id[scene_id], next_scene(scene_id)):
            if target in scene_by_id and has_cycle_from(target, seen):
                return True
        return False

    for scene_id in scene_ids:
        if has_cycle_from(scene_id, frozenset()):
            issues.append(f"scene {scene_id} is part of an implicit cycle")
            break
    return issues


def _check_key_event_traversal(pkg: ScriptPackage) -> list[str]:
    """关键事件顺序：canonical 推进只能向前，且不得跳过含关键事件的场景。

    场景顺序即原文顺序、beat_id 全局递增（`validate_structure` 已保证），
    所以「向后跳」或「跨过关键事件场景」就是原文事件顺序被打乱。
    """
    issues: list[str] = []
    scene_ids = [s.scene_id for s in pkg.scenes]
    index = {sid: i for i, sid in enumerate(scene_ids)}
    key_scenes = {
        i
        for i, scene in enumerate(pkg.scenes)
        if any(beat.is_key_event for beat in scene.beats)
    }

    def check_jump(where: str, start: int, target: int) -> None:
        if target <= start:
            issues.append(f"{where} jumps backward to scene {scene_ids[target]}")
            return
        skipped = sorted(i for i in key_scenes if start < i < target)
        if skipped:
            issues.append(
                f"{where} skips key event scene {scene_ids[skipped[0]]}"
            )

    for i, scene in enumerate(pkg.scenes):
        for option in scene.options:
            if option.kind != "canonical":
                continue
            if (
                option.target_scene_id is not None
                and option.target_scene_id in index
            ):
                check_jump(
                    f"scene {scene.scene_id} option {option.option_id}",
                    i,
                    index[option.target_scene_id],
                )
            elif option.branch_id is not None:
                branch = next(
                    (b for b in scene.branches if b.branch_id == option.branch_id),
                    None,
                )
                if (
                    branch is not None
                    and branch.ending_id is None
                    and branch.return_mode == "continue"
                    and branch.return_scene_id in index
                ):
                    check_jump(
                        f"branch {branch.branch_id}",
                        i,
                        index[branch.return_scene_id],
                    )
    return issues


def _check_canonical_ending(pkg: ScriptPackage) -> list[str]:
    """沿 canonical 路径必须能到达 canonical 结局（存在性判定）。"""
    canonical_endings = {e.ending_id for e in pkg.endings if e.kind == "canonical"}
    if not canonical_endings:
        return []
    scene_ids = [s.scene_id for s in pkg.scenes]
    scene_by_id: dict[int, Scene] = {s.scene_id: s for s in pkg.scenes}

    def reached(scene_id: int, seen: frozenset[int]) -> bool:
        if scene_id in seen:
            return False
        seen = seen | {scene_id}
        scene = scene_by_id[scene_id]
        idx = scene_ids.index(scene_id)
        next_scene_id = scene_ids[idx + 1] if idx + 1 < len(scene_ids) else None
        if not scene.options:
            # 线性场景：续接主干下一场；最后一场即 stage2_ending_beat
            if next_scene_id is None:
                return True
            return reached(next_scene_id, seen)
        for option in scene.options:
            if option.kind != "canonical":
                continue
            if option.ending_id in canonical_endings:
                return True
            if option.target_scene_id is not None:
                if option.target_scene_id in scene_by_id and reached(
                    option.target_scene_id, seen
                ):
                    return True
            elif option.branch_id is not None:
                branch = next(
                    (b for b in scene.branches if b.branch_id == option.branch_id),
                    None,
                )
                if branch is None:
                    continue
                if branch.ending_id is not None:
                    if branch.ending_id in canonical_endings:
                        return True
                    continue  # 终局分支（非 canonical）不是主线推进
                target = _resolve_branch_target(branch, next_scene_id)
                if target is not None and reached(target, seen):
                    return True
            elif next_scene_id is None:
                # 最后一场的全空目标 = 到达主干结局
                return True
            elif reached(next_scene_id, seen):
                return True
        return False

    if not reached(scene_ids[0], frozenset()):
        return ["canonical path does not reach a canonical ending"]
    return []


def validate_all(pkg: ScriptPackage, analysis: TextAnalysis) -> dict[str, list[str]]:
    """运行全部七类校验，返回 {validator_name: issues}（空 issues = 通过）。"""
    return {
        "structure": validate_structure(pkg),
        "evidence": validate_evidence(pkg),
        "characters": validate_characters(pkg, analysis),
        "event_order": validate_event_order(pkg, analysis),
        "teaching": validate_teaching(pkg),
        "branches": validate_branches(pkg, analysis),
        "replay": validate_replay(pkg),
    }
