"""生图 prompt 的本地安全过滤（ADR-0005 §6/§7，issue #46）。

K-12 语文教学场景，生图的本地风险面集中在：真实性内容（真人肖像/照片）、
性内容、自伤与血腥、以及超出教学需要的极端暴力。**provider 侧有自己的审核，
那才是主闸门**；这里是确定性的第二道闸，不额外调用模型、不依赖网络。

判定为**命中即拒**（抛 `MEDIA_IMAGE_GEN_BLOCKED`）而非改写 prompt：改写会让
"最终生成什么"不可预测，也让教师端的"纯生成"开关语义变糊。拒掉后由上层
（#47 SceneDesigner）降级为占位图/纯文本，游玩不阻塞。

非穷举清单：只覆盖明确不可接受的表述，刻意不收录会在课文语境里正常出现的词
（战争、历史、冲突等），避免把《谁是最可爱的人》这类课文误伤。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.infrastructure.errx import codes, new

# prompt 长度上限：provider 侧普遍有上限，过长也容易让"不含人物/统一画风"跑偏。
MAX_PROMPT_CHARS = 1200

# 命中即拒的类别 -> 关键词。ASCII 词按「ASCII 词首边界」匹配——**不能用 `\b`**：
# Python 的 `\w` 把 CJK 也算词字符，`\b` 在「段」与「n」之间不成立，会让
# 「一段nsfw画面」这类中文里紧贴的英文违禁词全部漏检（实测）。改用只看 ASCII 的
# 左向断言 `(?<![A-Za-z0-9_])`，既保住「denuded 不命中 nude」，也保住中文贴合命中。
# 含 CJK 的词直接子串匹配。
BLOCKED_CATEGORIES: dict[str, tuple[str, ...]] = {
    "sexual": (
        "色情",
        "情色",
        "裸露",
        "裸体",
        "性行为",
        "nsfw",
        "nude",
        "nudity",
        "naked",
        "porn",
        "erotic",
        "explicit",
    ),
    "self_harm": ("自杀", "自残", "割腕", "上吊", "suicide", "self-harm", "self harm"),
    "gore": (
        "血腥",
        "血肉模糊",
        "内脏",
        "尸体",
        "残肢",
        "断肢",
        "gore",
        "corpse",
        "mutilat",
        "dismember",
    ),
    "real_person": (
        "真人照片",
        "真实人物照片",
        "真实人物肖像",
        "名人肖像",
        "身份证照片",
        "real person",
        "real photo",
        "celebrity likeness",
    ),
}


@dataclass(frozen=True)
class SafetyVerdict:
    """过滤结论：`ok=False` 时 `category` 与 `matched` 供日志/诊断定位。"""

    ok: bool
    category: str = ""
    matched: str = ""


def _is_ascii(term: str) -> bool:
    return term.isascii()


def _compile(term: str) -> re.Pattern[str]:
    # ASCII 词首边界 + 允许多词连写（real person / real-person / realperson 均命中）。
    # 用 (?<![A-Za-z0-9_]) 而非 \b：后者会把中文当词字符，导致中文紧贴时漏检。
    pattern = r"(?<![A-Za-z0-9_])" + r"[\s_-]*".join(
        re.escape(part) for part in term.split()
    )
    return re.compile(pattern, re.IGNORECASE)


_COMPILED: tuple[tuple[str, str, re.Pattern[str]], ...] = tuple(
    (category, term, _compile(term))
    for category, terms in BLOCKED_CATEGORIES.items()
    for term in terms
)


def inspect_prompt(prompt: str) -> SafetyVerdict:
    """只判定不抛错：命中返回 `ok=False`（供教师端提示/日志用）。"""
    text = (prompt or "").casefold()
    for category, term, pattern in _COMPILED:
        if _is_ascii(term):
            if pattern.search(text):
                return SafetyVerdict(ok=False, category=category, matched=term)
        elif term.casefold() in text:
            return SafetyVerdict(ok=False, category=category, matched=term)
    return SafetyVerdict(ok=True)


def screen_generation_prompt(prompt: str, *, max_chars: int = MAX_PROMPT_CHARS) -> str:
    """生成前过滤：返回原样 prompt，命中违禁或超长则抛 `Error`。

    调用方（adapter 与 #47 编排）应在**付费调用之前**调用本函数。

    超长与命中违禁**共用** `MEDIA_IMAGE_GEN_BLOCKED`（两者都是「不可原样送出」，
    且都不可重试）；具体原因在 `extra["reason"]` 里区分。prompt 由 #47 按已知
    预算拼装，超长属编程/模板问题，不设计成可截断重试的路径。
    """
    if not (prompt or "").strip():
        raise new(codes.MEDIA_IMAGE_GEN_BLOCKED, extra={"reason": "empty prompt"})
    if len(prompt) > max_chars:
        raise new(
            codes.MEDIA_IMAGE_GEN_BLOCKED,
            extra={"reason": f"prompt too long ({len(prompt)}>{max_chars})"},
        )
    verdict = inspect_prompt(prompt)
    if not verdict.ok:
        raise new(
            codes.MEDIA_IMAGE_GEN_BLOCKED,
            extra={"reason": f"{verdict.category}:{verdict.matched}"},
        )
    return prompt


__all__ = [
    "BLOCKED_CATEGORIES",
    "MAX_PROMPT_CHARS",
    "SafetyVerdict",
    "inspect_prompt",
    "screen_generation_prompt",
]
