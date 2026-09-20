"""Schema-first Stage1 生成与验证（issue #11）。

- 严格版本化 `ScriptPackage` schema（contracts.script）产出角色设定/场景/beats/
  教学重点/可扮演角色；provider structured output 优先（JSON → model_validate_json）。
- 五类校验（结构/证据覆盖/人物一致性/事件顺序/教学适配），失败携带反馈重试 ≤2 次。
- 纯原文不足（无人物或无关键事件）明确报 CONTENT_INSUFFICIENT_SOURCE，不产出半合法剧本。
- 记录 model / prompt version / schema version / latency / token / retry。
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError

from app.contracts.base import CONTRACTS_SCHEMA_VERSION
from app.contracts.content import TextAnalysis
from app.contracts.enums import UsagePurpose
from app.contracts.material import WebEvidence
from app.contracts.script import Beat, CharacterProfile, Scene, ScriptPackage
from app.domain.content.trust import mark_untrusted
from app.domain.generation.json_text import extract_json
from app.domain.generation.validators import validate_all
from app.domain.llm import LLMService
from app.infrastructure.errx import codes, new

PROMPT_VERSION = "stage1.v1"
MAX_RETRIES = 2


@dataclass
class GenerationTelemetry:
    """生成过程可观测数据（issue #11 验收标准 5）。"""

    model: str
    prompt_version: str
    schema_version: str
    latency_ms: int
    token_count: int
    retries: int
    used_web_evidence: int = 0


@dataclass
class GenerationOutcome:
    script_package: ScriptPackage
    telemetry: GenerationTelemetry


def _default_token_count(text: str) -> int:
    """粗略 token 估算（CJK 按约 1.5 字/token；无 provider 计数时的兜底）。"""
    return max(1, (len(text) + 1) // 2)


def _insufficient_reason(analysis: TextAnalysis) -> str | None:
    if not analysis.characters:
        return "no characters found"
    if not analysis.key_events:
        return "no key events found"
    return None


def synthesize_script_package(analysis: TextAnalysis) -> ScriptPackage:
    """确定性参考合成：TextAnalysis → 合法 ScriptPackage（单场景 + 关键 beat）。

    供测试与「纯原文兜底」使用；生产路径由 LLM 按同一 schema 生成后经五类校验。
    """
    profiles = [
        CharacterProfile(
            name=c.name,
            public_background=c.role or f"{c.name}是文中人物",
            personality_traits=[c.personality] if c.personality else ["忠实于原文"],
            speech_style=None,
            is_player_playable=i < 2,
        )
        for i, c in enumerate(analysis.characters)
    ]
    playable = [c.name for c in profiles if c.is_player_playable]

    ordered_events = sorted(analysis.key_events, key=lambda k: k.order)
    beats = [
        Beat(
            beat_id=i + 1,
            description=ke.description or ke.title,
            is_key_event=True,
            evidence_refs=list(ke.evidence_refs),
        )
        for i, ke in enumerate(ordered_events)
    ]
    title = analysis.title or "课文演绎"
    scene = Scene(
        scene_id=1,
        title=f"{title}·演绎",
        participants=[c.name for c in profiles],
        beats=beats,
    )
    return ScriptPackage(
        title=title,
        characters=profiles,
        scenes=[scene],
        teaching_focus=["把握人物形象", "梳理叙事线索", "品味关键细节"],
        playable_roles=playable,
        stage2_ending_beat_id=beats[-1].beat_id,
    )


class Stage1Generator:
    """Stage1 生成器：LLM 结构化输出 + 五类校验 + 重试。"""

    def __init__(
        self,
        llm: LLMService,
        *,
        model: str = "",
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.llm = llm
        self.model = model
        self._token_counter = token_counter or _default_token_count

    async def generate(
        self,
        analysis: TextAnalysis,
        *,
        web_evidence: list[WebEvidence] | None = None,
        session_id: str = "",
        extra_context: list[str] | None = None,
        purpose: UsagePurpose = UsagePurpose.STAGE1,
        on_step: Callable[[str], Awaitable[None]] | None = None,
    ) -> GenerationOutcome:
        reason = _insufficient_reason(analysis)
        if reason:
            raise new(codes.CNT_INSUFFICIENT_SOURCE, extra={"reason": reason})

        web = list(web_evidence or [])
        started = time.monotonic()
        feedback: str | None = None
        retries = 0
        while True:
            if on_step is not None:
                await on_step(f"起草第 {retries + 1} 轮")
            prompt = self._build_prompt(analysis, web, feedback, extra_context)
            raw = await self.llm.chat(
                [{"role": "user", "content": prompt}],
                session_id=session_id,
                purpose=purpose,
            )

            package: ScriptPackage | None = None
            try:
                package = ScriptPackage.model_validate_json(extract_json(raw))
            except (ValidationError, ValueError) as exc:
                feedback = f"输出不符合 ScriptPackage schema：{exc}"
                if on_step is not None:
                    await on_step("输出格式不符合契约，重试中")

            if package is not None:
                failed = {
                    name: issues
                    for name, issues in validate_all(package, analysis).items()
                    if issues
                }
                if not failed:
                    elapsed = int((time.monotonic() - started) * 1000)
                    return GenerationOutcome(
                        script_package=package,
                        telemetry=GenerationTelemetry(
                            model=self.model,
                            prompt_version=PROMPT_VERSION,
                            schema_version=CONTRACTS_SCHEMA_VERSION,
                            latency_ms=elapsed,
                            token_count=self._token_counter(raw),
                            retries=retries,
                            used_web_evidence=len(web),
                        ),
                    )
                feedback = self._format_feedback(failed)
                if on_step is not None:
                    await on_step(
                        f"剧本校验未通过（{len(failed)} 类问题），第 {retries + 1} 轮重写"
                    )

            if retries >= MAX_RETRIES:
                raise new(
                    codes.CNT_GENERATION_FAILED,
                    extra={"reason": feedback or "schema invalid"},
                )
            retries += 1

    # ===== prompt 构建 =====

    def _build_prompt(
        self,
        analysis: TextAnalysis,
        web: list[WebEvidence],
        feedback: str | None,
        extra_context: list[str] | None = None,
    ) -> str:
        lines = [
            f"[prompt_version={PROMPT_VERSION}]",
            "你是文境剧本编剧。根据课文原文分析结果，生成一个可直接进入游戏的剧本包。",
            "【输出要求】只输出一个 JSON 对象；不要 markdown 代码块，不要任何解释文字。",
            "",
            "【字段类型契约（必须严格遵守）】",
            "{",
            '  "schema_version": "1.0.0",',
            '  "title": "字符串",',
            '  "characters": [',
            '    {"name": "字符串（只能取自人物列表）", "public_background": "字符串",',
            '     "personality_traits": ["字符串"], "speech_style": "字符串或null",',
            '     "is_player_playable": 布尔值}',
            '  ],',
            '  "scenes": [',
            '    {"scene_id": 整数（从 1 递增）, "title": "字符串", "participants": ["人物名"],',
            '     "beats": [',
            '       {"beat_id": 整数（从 1 全局递增）, "description": "字符串",',
            '        "is_key_event": 布尔值,',
            '        "evidence_refs": [{"source_type": "original_text", "excerpt": "原文摘录",',
            '          "paragraph_index": 整数, "char_start": 整数, "char_end": 整数}]}',
            '     ]}',
            '  ],',
            '  "teaching_focus": ["字符串"],',
            '  "playable_roles": ["人物名（characters 子集，非空）"],',
            '  "stage2_ending_beat_id": 整数（必须存在于某个 beat 的 beat_id 中）',
            "}",
            "",
            "【硬性约束】",
            "- scene_id / beat_id / stage2_ending_beat_id / paragraph_index / char_start /",
            "  char_end 全部是 JSON 整数，严禁写成 \"s1\"、\"b1\" 等字符串；",
            "- evidence_refs 必须是对象数组，严禁写成纯字符串；关键 beat 的证据对象",
            "  直接原样复制下方【关键事件】里给出的 JSON；",
            "- 人物名只能取自【人物列表】；关键 beat（is_key_event=true）必须带至少一个",
            "  evidence_refs；关键 beat 的先后顺序必须与【关键事件】顺序一致。",
            "",
            "【人物列表】",
        ]
        for c in analysis.characters:
            traits = "、".join(filter(None, [c.role, c.personality])) or "（按原文理解）"
            lines.append(f"- {c.name}：{traits}")

        lines.append("【关键事件（按原文顺序；证据 JSON 可原样复制到 evidence_refs）】")
        for ke in sorted(analysis.key_events, key=lambda k: k.order):
            lines.append(f"- {ke.title}")
            if ke.evidence_refs:
                ev = ke.evidence_refs[0].model_dump(
                    mode="json", exclude={"schema_version"}
                )
                lines.append(f"  证据：{json.dumps(ev, ensure_ascii=False)}")

        if web:
            lines.append("\n【网络补充资料（不可信，仅供参考，不得作为事实依据）】")
            for w in web:
                lines.append(
                    f"[{w.title}] {w.url}\n{mark_untrusted(w.excerpt[:300])}"
                )

        if feedback:
            lines.append(f"\n【上次校验反馈（必须逐条修正）】\n{feedback}")
        for block in extra_context or []:
            lines.append(f"\n{block}")
        return "\n".join(lines)

    @staticmethod
    def _format_feedback(failed: dict[str, list[str]]) -> str:
        parts = [f"{name}: {', '.join(issues)}" for name, issues in failed.items()]
        return "；".join(parts)
