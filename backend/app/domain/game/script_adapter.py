"""契约剧本包 → 引擎剧本的显式转换（#5 竖切接缝①）。

`contracts.script.ScriptPackage`（冻结契约、带证据）是 Stage1 的对外产物；
`core.types.Script`（纯 dataclass）是 GameRuntime 的运行时输入。
转换只保留引擎推进所需的字段；证据/教学重点留在契约层供前端与审计使用。
"""

from __future__ import annotations

from app.contracts.script import CharacterProfile, ScriptPackage
from app.domain.game.types import Beat, CharacterSetting, Scene, Script


def _speech_style_text(c: CharacterProfile) -> str:
    """SpeechStyle 五要素 → persona 文本（运行时 character identity 引用）。"""
    s = c.speech_style
    if s is None:
        return ""
    parts = [f"语言时代层：{s.era_layer}", f"句长与节奏：{s.sentence_rhythm}"]
    if s.address_terms:
        parts.append(f"称谓习惯：{s.address_terms}")
    if s.catchphrases:
        parts.append(f"口头禅：{s.catchphrases}")
    parts.append(f"情绪表达：{s.emotion_expression}")
    text = "；".join(p for p in parts if not p.endswith("："))
    if s.sample_lines:
        text += "。示例语气：" + " / ".join(s.sample_lines[:2])
    return text


def _knowledge_boundary_text(c: CharacterProfile) -> str:
    kb = c.knowledge_boundary
    if not kb.knows and not kb.not_knows:
        return ""
    parts = []
    if kb.knows:
        parts.append("你知道：" + "；".join(kb.knows))
    if kb.not_knows:
        parts.append("你不知道：" + "；".join(kb.not_knows))
    return "。".join(parts)


def script_package_to_script(pkg: ScriptPackage) -> Script:
    """ScriptPackage → 引擎 Script。playable_roles 是可扮演的权威来源。"""
    playable = set(pkg.playable_roles)
    characters = [
        CharacterSetting(
            name=c.name,
            public_background=c.public_background,
            personality_traits=[t.label for t in c.personality_traits],
            speech_style=_speech_style_text(c),
            knowledge_boundary=_knowledge_boundary_text(c),
            is_player_playable=c.is_player_playable.value or c.name in playable,
        )
        for c in pkg.characters
    ]
    scenes = [
        Scene(
            scene_id=s.scene_id,
            title=s.title,
            participants=list(s.participants),
            beats=[
                Beat(beat_id=b.beat_id, description=b.description) for b in s.beats
            ],
        )
        for s in pkg.scenes
    ]
    return Script(
        title=pkg.title,
        characters=characters,
        scenes=scenes,
        stage2_ending_beat_id=pkg.stage2_ending_beat_id,
    )
