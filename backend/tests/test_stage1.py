"""Schema-first Stage1 生成与验证测试（issue #11 验收标准）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.llm_service import LLMService
from app.content.pipeline import ContentPipeline
from app.contracts.content import TextAnalysis
from app.contracts.material import MaterialInput, MaterialSource
from app.contracts.script import ScriptPackage
from app.errx import Error as WJError
from app.generation.stage1 import (
    PROMPT_VERSION,
    Stage1Generator,
    synthesize_script_package,
)
from app.generation.validators import validate_all

REPO_ROOT = Path(__file__).resolve().parents[2]


class ScriptLLM:
    """按预设响应队列返回 JSON（可模拟非法/合法/重试）。"""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, session_id: str = ""):
        self.calls.append(messages)
        if not self._responses:
            return self._last
        self._last = self._responses.pop(0)
        if isinstance(self._last, Exception):
            raise self._last
        return self._last


def _load_analysis(name: str) -> TextAnalysis:
    data = json.loads((REPO_ROOT / "contracts" / "fixtures" / f"{name}.json").read_text())
    return TextAnalysis.model_validate(data)


def _analysis_from_text(text: str) -> TextAnalysis:
    return ContentPipeline().analyze(
        MaterialInput(source=MaterialSource.PASTE, raw_text=text)
    )


def _assert_legal(pkg: ScriptPackage, analysis: TextAnalysis) -> None:
    assert ScriptPackage.model_validate(json.loads(pkg.model_dump_json())) == pkg
    assert validate_all(pkg, analysis) == {
        "structure": [],
        "evidence": [],
        "characters": [],
        "event_order": [],
        "teaching": [],
    }
    key_beats = [b for s in pkg.scenes for b in s.beats if b.is_key_event]
    assert key_beats, "Stage2 关键 beat 不得为空"
    assert all(b.evidence_refs for b in key_beats), "关键 beat 必须带原文证据"


# ===== 1. 多篇叙事课文 → 合法 ScriptPackage =====

_SAMPLE_NARRATIVE = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)
_SAMPLE_DRAMA = (
    "第一幕  茶馆\n\n王利发说：各位，里边请！\n"
    "秦仲义道：王掌柜，生意可好？\n王利发回答：托福，还过得去。"
)


@pytest.mark.parametrize(
    "analysis",
    [
        _load_analysis("text_analysis"),
        _analysis_from_text(_SAMPLE_NARRATIVE),
        _analysis_from_text(_SAMPLE_DRAMA),
    ],
    ids=["背影fixture", "叙事样例", "戏剧样例"],
)
async def test_synthesize_produces_legal_script_package(analysis: TextAnalysis):
    pkg = synthesize_script_package(analysis)
    _assert_legal(pkg, analysis)
    assert pkg.playable_roles
    assert pkg.stage2_ending_beat_id > 0


# ===== 2. LLM 结构化输出 + telemetry =====


async def test_generator_structured_output_and_telemetry():
    analysis = _load_analysis("text_analysis")
    expected_json = synthesize_script_package(analysis).model_dump_json()
    llm = ScriptLLM(expected_json)
    gen = Stage1Generator(llm, model="fake-model")

    outcome = await gen.generate(analysis, session_id="s1")

    assert ScriptPackage.model_validate(
        json.loads(outcome.script_package.model_dump_json())
    ) == outcome.script_package
    t = outcome.telemetry
    assert t.model == "fake-model"
    assert t.prompt_version == PROMPT_VERSION
    assert t.schema_version == outcome.script_package.schema_version
    assert t.latency_ms >= 0
    assert t.token_count > 0
    assert t.retries == 0


# ===== 3. 重试 ≤2 =====


async def test_generator_retries_then_succeeds():
    analysis = _load_analysis("text_analysis")
    valid = synthesize_script_package(analysis).model_dump_json()
    llm = ScriptLLM('{"not": "script"}', valid)
    gen = Stage1Generator(llm, model="m")

    outcome = await gen.generate(analysis)
    assert outcome.telemetry.retries == 1
    assert len(llm.calls) == 2


async def test_generator_fails_after_two_retries():
    analysis = _load_analysis("text_analysis")
    llm = ScriptLLM("bad-json", "bad-json", "bad-json")
    gen = Stage1Generator(llm, model="m")

    with pytest.raises(WJError) as excinfo:
        await gen.generate(analysis)
    assert excinfo.value.code == 6003  # CNT_GENERATION_FAILED
    assert len(llm.calls) == 3, "初始 1 次 + 重试 2 次"


# ===== 4. 纯原文不足 =====


async def test_insufficient_source_raises():
    analysis = TextAnalysis(
        content_hash="h",
        genre={
            "schema_version": "1.0.0",
            "genre": "narrative",
            "is_supported": True,
            "signals": [],
        },
        characters=[],
        key_events=[],
    )
    llm = ScriptLLM("")
    gen = Stage1Generator(llm, model="m")
    with pytest.raises(WJError) as excinfo:
        await gen.generate(analysis)
    assert excinfo.value.code == 6002  # CNT_INSUFFICIENT_SOURCE
    assert len(llm.calls) == 0, "不足时不得调用 LLM"


# ===== 5. 五类校验各自拒收非法剧本 =====


def _good_pkg() -> tuple[ScriptPackage, TextAnalysis]:
    analysis = _load_analysis("text_analysis")
    return synthesize_script_package(analysis), analysis


def test_validator_structure_rejects_missing_ending_beat():
    pkg, analysis = _good_pkg()
    pkg.stage2_ending_beat_id = 9999
    assert validate_all(pkg, analysis)["structure"]


def test_validator_evidence_rejects_key_beat_without_evidence():
    pkg, analysis = _good_pkg()
    pkg.scenes[0].beats[0].is_key_event = True
    pkg.scenes[0].beats[0].evidence_refs = []
    assert validate_all(pkg, analysis)["evidence"]


def test_validator_characters_rejects_fabricated_name():
    pkg, analysis = _good_pkg()
    pkg.characters[0].name = "不存在的人物"
    assert validate_all(pkg, analysis)["characters"]


def test_validator_event_order_rejects_reversed_beats():
    pkg, analysis = _good_pkg()
    pkg.scenes[0].beats = list(reversed(pkg.scenes[0].beats))
    assert validate_all(pkg, analysis)["event_order"]


def test_validator_teaching_rejects_empty_focus():
    pkg, analysis = _good_pkg()
    pkg.teaching_focus = []
    assert validate_all(pkg, analysis)["teaching"]


# ===== 6. 非叙事文本在管线入口被拒 =====


def test_non_narrative_text_rejected_by_pipeline():
    from app.errx import codes

    with pytest.raises(WJError) as excinfo:
        ContentPipeline().analyze(
            MaterialInput(
                source=MaterialSource.PASTE,
                raw_text="赵州桥非常雄伟。这座桥的特点是结构坚固。",
            )
        )
    assert excinfo.value.code == codes.CNT_UNSUPPORTED_GENRE


def test_generator_conforms_to_llm_service_protocol():
    from typing import get_type_hints

    assert Stage1Generator.__init__  # 构造注入 LLMService
    hints = get_type_hints(Stage1Generator.__init__)
    assert hints["llm"] is LLMService
