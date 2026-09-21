"""原文分析（issue #9 验收标准 3）：确定性启发式提取。

零 LLM、零随机：基于对白归属、称谓共现、场景标记与事件动词做启发式抽取，
每条结论附 OriginalEvidence（文档级 char 区间 + paragraph_index）。
#11 可在此基础上用 LLM 深加工；本模块保证"同输入 → 同输出"。

证据坐标约定：char_start/char_end 为规范化全文（Material.normalized_text）中的
绝对偏移（左闭右开）；paragraph_index 为该段落序号（0 起）。
"""

from __future__ import annotations

import re

from app.contracts.content import (
    CharacterMention,
    GenreClassification,
    KeyEvent,
    RelationshipEdge,
    SceneSetting,
    TextAnalysis,
)
from app.contracts.material import Material, OriginalEvidence

# 常见称谓/身份词（确定性识别为人物）；"我" 视为叙述视角人物
_CHAR_TERMS = (
    "父亲", "母亲", "儿子", "女儿", "祖母", "祖父", "奶奶", "爷爷",
    "哥哥", "弟弟", "姐姐", "妹妹", "朋友", "老师", "同学", "妻子",
    "丈夫", "先生", "师傅", "徒弟", "叔叔", "阿姨", "我",
)
# 自定义人名的对白归属："（名字）说/道/问/答/喊："
_ATTR_RE = re.compile(r"([\u4e00-\u9fa5]{2,4})(?:对[\u4e00-\u9fa5]{2,4})?(?:说|道|问|答|喊)[：:]")
_QUOTE_RE = re.compile(r"[“「]([^”」]{1,80})[”」]([\u4e00-\u9fa5]{2,4})(?:说|道|问|答|喊)")
_EVENT_VERBS = (
    "说", "道", "问", "答", "喊", "哭", "笑", "走", "买", "送", "死", "到",
    "离开", "回到", "来到", "走到", "见到", "看见", "想起", "流下", "交卸",
    "分别", "告别", "回来", "坐下", "爬上", "去世",
)
_LOCATION_RE = re.compile(
    r"(?:来到|走到|到了|到)([\u4e00-\u9fa5]{2,3})(?=[见看说问，。、；！？\s]|\Z)"
)
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？；])")

_TITLE_MAX = 20
_AUTHOR_RE = re.compile(r"^(?:作者|author)[：:]\s*(.+)$", re.IGNORECASE)


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """切分为 [(文档级起始偏移, 段落文本)]，段落文本已 strip 两端空白。"""
    result: list[tuple[int, str]] = []
    pos = 0
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped:
            start = pos + (len(raw) - len(raw.lstrip()))
            result.append((start, stripped))
        pos += len(raw) + 1
    return result


def _evidence(
    para_start: int, para_index: int, text: str, start: int, end: int
) -> OriginalEvidence:
    return OriginalEvidence(
        excerpt=text[start:end],
        paragraph_index=para_index,
        char_start=para_start + start,
        char_end=para_start + end,
    )


def _find_terms(text: str, terms: tuple[str, ...]) -> list[tuple[str, int, int]]:
    """返回 [(term, start, end)]，start/end 为 text 内偏移。"""
    hits: list[tuple[str, int, int]] = []
    for term in terms:
        idx = text.find(term)
        while idx != -1:
            hits.append((term, idx, idx + len(term)))
            idx = text.find(term, idx + 1)
    return hits


class TextAnalyzer:
    """确定性原文分析器：人物 / 关系 / 场景 / 关键事件。"""

    def analyze(self, material: Material, genre: GenreClassification) -> TextAnalysis:
        text = material.normalized_text
        paras = _paragraphs(text)

        characters, char_names = self._extract_characters(text, paras)
        relationships = self._extract_relationships(paras, char_names)
        scenes = self._extract_scenes(paras, char_names)
        key_events = self._extract_key_events(paras, char_names)

        return TextAnalysis(
            content_hash=material.content_hash,
            title=self._extract_title(text),
            author=self._extract_author(text),
            genre=genre,
            characters=characters,
            relationships=relationships,
            scenes=scenes,
            key_events=key_events,
        )

    # ===== 人物 =====

    def _extract_characters(
        self, text: str, paras: list[tuple[int, str]]
    ) -> tuple[list[CharacterMention], set[str]]:
        mentions: dict[str, CharacterMention] = {}

        def add_evidence(name: str, ev: OriginalEvidence) -> None:
            if name not in mentions:
                mentions[name] = CharacterMention(name=name)
            mentions[name].evidence_refs.append(ev)

        for para_start, para in paras:
            para_index = _paragraph_index(paras, para_start)
            for term, s, e in _find_terms(para, _CHAR_TERMS):
                add_evidence(term, _evidence(para_start, para_index, para, s, e))
            for match in _ATTR_RE.finditer(para):
                speaker = match.group(1)
                if speaker in _CHAR_TERMS:
                    continue  # 称谓词已被扫描覆盖
                add_evidence(
                    speaker,
                    _evidence(para_start, para_index, para, match.start(), match.end()),
                )
            for match in _QUOTE_RE.finditer(para):
                speaker = match.group(2)
                if speaker in _CHAR_TERMS:
                    continue
                add_evidence(
                    speaker,
                    _evidence(para_start, para_index, para, match.start(), match.end()),
                )

        ordered = sorted(mentions.values(), key=lambda m: m.name)
        return ordered, set(mentions.keys())

    # ===== 关系（同一段落共现）=====

    def _extract_relationships(
        self, paras: list[tuple[int, str]], char_names: set[str]
    ) -> list[RelationshipEdge]:
        edges: dict[tuple[str, str], RelationshipEdge] = {}

        def _register(a: str, b: str, ev: OriginalEvidence) -> None:
            key = tuple(sorted((a, b)))
            if key not in edges:
                edges[key] = RelationshipEdge(source=key[0], target=key[1], nature="共同出场")
            edges[key].evidence_refs.append(ev)

        for para_start, para in paras:
            para_index = _paragraph_index(paras, para_start)
            present = sorted({name for name in char_names if name in para})
            if len(present) < 2:
                continue
            ev = _evidence(para_start, para_index, para, 0, len(para))
            for i, a in enumerate(present):
                for b in present[i + 1:]:
                    _register(a, b, ev)

        return list(edges.values())

    # ===== 场景（地点/时间标记段落）=====

    def _extract_scenes(
        self, paras: list[tuple[int, str]], char_names: set[str]
    ) -> list[SceneSetting]:
        scenes: list[SceneSetting] = []
        for para_start, para in paras:
            para_index = _paragraph_index(paras, para_start)
            loc_match = _LOCATION_RE.search(para)
            time_marker = re.search(
                r"^(?:那年|那年冬天|次日|第二天|第二天清晨|晚上|白天|清晨|傍晚)", para
            )
            if loc_match is None and time_marker is None:
                continue
            location = loc_match.group(1) if loc_match else None
            participants = sorted({name for name in char_names if name in para})
            scenes.append(
                SceneSetting(
                    title=location or (time_marker.group(0) if time_marker else para[:8]),
                    location=location,
                    participants=participants,
                    core_event=para[:40],
                    significance=None,
                    evidence_refs=[_evidence(para_start, para_index, para, 0, len(para))],
                )
            )
        return scenes

    # ===== 关键事件（含人物 + 事件动词的句子）=====

    def _extract_key_events(
        self, paras: list[tuple[int, str]], char_names: set[str]
    ) -> list[KeyEvent]:
        events: list[KeyEvent] = []
        order = 0
        for para_start, para in paras:
            para_index = _paragraph_index(paras, para_start)
            cursor = 0
            for raw_sentence in _SENT_SPLIT_RE.split(para):
                sentence = raw_sentence.strip()
                if not sentence:
                    cursor += len(raw_sentence)
                    continue
                start = para.index(raw_sentence, cursor)
                cursor = start + len(raw_sentence)
                participants = sorted({name for name in char_names if name in sentence})
                if not participants or not any(v in sentence for v in _EVENT_VERBS):
                    continue
                order += 1
                events.append(
                    KeyEvent(
                        title=sentence,
                        description=sentence,
                        participants=participants,
                        order=order,
                        evidence_refs=[
                            _evidence(
                                para_start,
                                para_index,
                                para,
                                start,
                                start + len(raw_sentence),
                            )
                        ],
                    )
                )
        return events

    # ===== 标题 / 作者 =====

    def _extract_title(self, text: str) -> str | None:
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if 0 < len(first) <= _TITLE_MAX and not re.search(r"[。！？；，、]", first):
            return first
        return None

    def _extract_author(self, text: str) -> str | None:
        for line in text.splitlines()[:5]:
            match = _AUTHOR_RE.match(line.strip())
            if match:
                return match.group(1).strip()
        return None


def _paragraph_index(paras: list[tuple[int, str]], para_start: int) -> int:
    for i, (start, _) in enumerate(paras):
        if start == para_start:
            return i
    return 0
