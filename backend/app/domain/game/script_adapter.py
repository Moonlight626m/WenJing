"""契约剧本包 → 引擎剧本的显式转换（#5 竖切接缝①）。

`contracts.script.ScriptPackage`（冻结契约、带证据）是 Stage1 的对外产物；
`core.types.Script`（纯 dataclass）是 GameRuntime 的运行时输入。
转换只保留引擎推进所需的字段；证据/教学重点留在契约层供前端与审计使用。
"""

from __future__ import annotations

from app.contracts.script import ScriptPackage
from app.domain.game.types import Beat, CharacterSetting, Scene, Script


def script_package_to_script(pkg: ScriptPackage) -> Script:
    """ScriptPackage → 引擎 Script。playable_roles 是可扮演的权威来源。"""
    playable = set(pkg.playable_roles)
    characters = [
        CharacterSetting(
            name=c.name,
            public_background=c.public_background,
            personality_traits=list(c.personality_traits),
            is_player_playable=c.is_player_playable or c.name in playable,
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
