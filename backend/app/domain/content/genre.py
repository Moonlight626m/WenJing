"""叙事体裁判断（issue #9 验收标准 2）。

纯启发式、确定性、零外部依赖（同输入 → 同输出）：
- 诗歌：出现诗词强标记，或行数较多且单行极短。
- 戏剧：幕/场/旁白/舞台指示等标记，或"人物名：台词"逐行格式 + 对白。
- 说明文 / 议论文：各自标记词占优且无对白。
- 其余：有对白或叙事动词 → 叙事类（按章回/传记标记细分为小说/人物故事，
  否则叙事文）；无任何叙事信号 → 纯写景；无中文内容 → unknown。
"""

from __future__ import annotations

import re

from app.contracts.content import (
    SUPPORTED_GENRES,
    GenreClassification,
    GenreType,
)
from app.contracts.material import Material

_POETRY_MARKERS = (
    "七言", "五言", "绝句", "律诗", "词牌", "沁园春", "水调歌头",
    "卜算子", "浣溪沙", "念奴娇", "如梦令",
)
_DRAMA_MARKERS = ("幕", "旁白", "舞台", "上场", "下场", "幕落", "人物表", "场景")
_EXPOSITORY_MARKERS = (
    "说明", "介绍", "特点", "功能", "原理", "方法", "步骤",
    "用途", "分为", "主要", "例如", "比如",
)
_ARGUMENTATIVE_MARKERS = (
    "论点", "论证", "观点", "因此", "所以", "综上所述",
    "我认为", "证明了", "可见", "总之", "显然",
)
_NARRATIVE_VERBS = (
    "说", "道", "问", "答", "喊", "哭", "笑", "想", "觉得",
    "来到", "走到", "见到", "看见", "离开", "回到", "送", "买", "走了", "去了",
)
_BIO_MARKERS = ("生于", "卒于", "原名", "字", "号", "又名", "一生", "年轻时", "少年")
_CHAPTER_RE = re.compile(r"第[一二三四五六七八九十百千\d]+[章节回]")
_DIALOGUE_RE = re.compile(r"[“「][^”」]{1,80}[”」]")
_SPEECH_ATTR_RE = re.compile(r"[\u4e00-\u9fa5]{1,6}(?:说|道|问|答|喊)[：:]")
_CJK_RE = re.compile(r"[\u4e00-\u9fa5]")


def _result(genre: GenreType, signals: list[str]) -> GenreClassification:
    return GenreClassification(
        genre=genre,
        is_supported=genre in SUPPORTED_GENRES,
        signals=signals,
    )


def _line_stats(text: str) -> tuple[int, float]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 0, 0.0
    return len(lines), sum(len(ln) for ln in lines) / len(lines)


class GenreDetector:
    """确定性体裁分类器。"""

    def classify(self, material: Material) -> GenreClassification:
        text = material.normalized_text
        signals: list[str] = []

        if not _CJK_RE.search(text) or len(text) < 10:
            return _result(GenreType.UNKNOWN, ["no cjk content or too short"])

        n_lines, avg_len = _line_stats(text)
        poetry_hits = sum(1 for m in _POETRY_MARKERS if m in text)
        if poetry_hits >= 1 or (n_lines >= 3 and avg_len <= 8):
            signals.append(f"poetry markers={poetry_hits} lines={n_lines} avg_len={avg_len:.1f}")
            return _result(GenreType.POETRY, signals)

        drama_hits = sum(1 for m in _DRAMA_MARKERS if m in text)
        colon_attr = len(
            re.findall(r"^[\u4e00-\u9fa5A-Za-z]{1,6}：", text, flags=re.M)
        )
        dialogue = len(_DIALOGUE_RE.findall(text))
        if drama_hits >= 2 or (colon_attr >= 3 and dialogue >= 1):
            signals.append(
                f"drama markers={drama_hits} colon_attr={colon_attr} dialogue={dialogue}"
            )
            return _result(GenreType.DRAMA, signals)

        expo_hits = sum(1 for m in _EXPOSITORY_MARKERS if m in text)
        arg_hits = sum(1 for m in _ARGUMENTATIVE_MARKERS if m in text)
        if expo_hits >= 3 and dialogue == 0:
            signals.append(f"expository markers={expo_hits}")
            return _result(GenreType.EXPOSITORY, signals)
        if arg_hits >= 3 and dialogue == 0:
            signals.append(f"argumentative markers={arg_hits}")
            return _result(GenreType.ARGUMENTATIVE, signals)

        narrative_hits = sum(1 for v in _NARRATIVE_VERBS if v in text)
        speech = len(_SPEECH_ATTR_RE.findall(text))
        if dialogue == 0 and speech == 0 and narrative_hits == 0:
            return _result(GenreType.SCENERY, ["no dialogue or narrative signal"])

        chapter_hits = len(_CHAPTER_RE.findall(text))
        if chapter_hits >= 1:
            signals.append(f"novel chapters={chapter_hits}")
            return _result(GenreType.NOVEL, signals)

        bio_hits = sum(1 for m in _BIO_MARKERS if m in text)
        if bio_hits >= 2:
            signals.append(f"character_story bio_markers={bio_hits}")
            return _result(GenreType.CHARACTER_STORY, signals)

        signals.append(f"narrative dialogue={dialogue} speech={speech} verbs={narrative_hits}")
        return _result(GenreType.NARRATIVE, signals)
