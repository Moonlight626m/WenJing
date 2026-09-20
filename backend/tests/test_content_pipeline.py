"""内容管线测试（issue #9）：导入校验 / 体裁判断 / 原文分析 / 证据区分 / 确定性。

机制测试：验证校验、分类、证据坐标与确定性，不评估提取质量（#14 做质量门禁）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.contracts.content import GenreType, TextAnalysis
from app.contracts.material import (
    Material,
    MaterialInput,
    OriginalEvidence,
    WebEvidence,
)
from app.domain.content import ContentPipeline, MaterialIngestor, content_hash, normalize_text
from app.domain.content.genre import GenreDetector
from app.infrastructure.diagnostics.errors import envelope_for
from app.infrastructure.errx import Error, codes

BEIYING = (
    "背影\n\n"
    "我与父亲不相见已二年余了，我最不能忘记的是他的背影。那年冬天，祖母死了，父亲的差使也交卸了，正是祸不单行的日子。\n"
    "到徐州见着父亲，看见满院狼藉的东西，又想起祖母，不禁簌簌地流下眼泪。父亲说：事已如此，不必难过，好在天无绝人之路！"
)


def _paste(text: str) -> MaterialInput:
    return MaterialInput(source="paste", raw_text=text)


def _material(text: str) -> Material:
    n = normalize_text(text)
    return Material(content_hash=content_hash(n), normalized_text=n, char_count=len(n))


# ===== 1. 导入校验 + 规范化 + hash =====


class TestIngestion:
    def test_paste_normalizes_and_hashes(self):
        raw = "背影\r\n\r\n\r\n我与父亲不相见。\ufeff"
        material = MaterialIngestor().ingest(MaterialInput(source="paste", raw_text=raw))
        assert material.normalized_text == "背影\n\n我与父亲不相见。"
        assert material.char_count == len(material.normalized_text)
        assert material.content_hash == content_hash(material.normalized_text)

    def test_content_hash_is_deterministic(self):
        n = normalize_text(BEIYING)
        assert content_hash(n) == content_hash(n)
        assert len(content_hash(n)) == 64

    def test_empty_and_blank_rejected(self):
        with pytest.raises(Error) as e1:
            MaterialIngestor().ingest(_paste("   \n  "))
        assert e1.value.code == codes.INP_EMPTY_MATERIAL
        # 空串在契约层（raw_text min_length=1）即被拒绝
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            MaterialInput(source="paste", raw_text="")

    def test_too_large_rejected(self):
        ingestor = MaterialIngestor(max_chars=10)
        with pytest.raises(Error) as e:
            ingestor.ingest(_paste("我" * 11))
        assert e.value.code == codes.INP_TOO_LARGE

    def test_unsupported_extension_rejected(self):
        with pytest.raises(Error) as e:
            MaterialIngestor().ingest(
                MaterialInput(source="upload", filename="a.docx", raw_text="正文")
            )
        assert e.value.code == codes.INP_UNSUPPORTED_EXTENSION

    def test_supported_extensions_accepted(self):
        for name in ("a.txt", "b.md", "B.TXT"):
            m = MaterialIngestor().ingest(
                MaterialInput(source="upload", filename=name, raw_text="正文内容")
            )
            assert m.char_count > 0

    def test_invalid_encoding_bytes_rejected(self):
        with pytest.raises(Error) as e:
            MaterialIngestor().ingest(
                MaterialInput(source="upload", filename="a.txt", raw_text="占位"),
                raw_bytes=b"\xff\xfe\x00\x01\xff\xfe",
            )
        assert e.value.code == codes.INP_INVALID_ENCODING

    def test_gb18030_bytes_decoded(self):
        raw = "背影".encode("gb18030")
        m = MaterialIngestor().ingest(
            MaterialInput(source="upload", filename="a.txt", raw_text="占位"), raw_bytes=raw
        )
        assert m.normalized_text == "背影"


# ===== 2. 体裁判断 =====

_NOVEL = "第一章 初遇\n\n傍晚，林小满走进那条老街。她在转角处见到一位老人，老人正慢慢离开。"
_NARRATIVE = "我与父亲不相见已二年余了。父亲说：事已如此，不必难过。"
_DRAMA = (
    "第一幕  茶馆\n\n王利发：（上场）各位，里边请！"
    "\n秦仲义：王掌柜，生意可好？\n常四爷：托福，还过得去。"
)
_CHAR_STORY = "鲁迅原名周树人，生于1881年，卒于1936年。他年轻时离开家乡，来到南京求学。"
_EXPOSITORY = (
    "赵州桥非常雄伟。这座桥的特点是结构坚固。桥的设计方法十分巧妙，"
    "主要介绍了古代工匠的智慧。例如，桥身只有一个大拱。"
)
_ARGUMENTATIVE = (
    "我认为勤奋是成功的关键。勤奋能弥补天赋的不足。"
    "因此，只有勤奋才能成就事业。综上所述，我们应该珍惜时间。"
)
_SCENERY = (
    "湖面平静如镜。柳树的枝条低垂，嫩芽初绽。"
    "远处的山峦连绵起伏，在晨雾中若隐若现。水面上倒映着蓝天白云。"
)
_POETRY = "床前明月光，\n疑是地上霜。\n举头望明月，\n低头思故乡。"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_NOVEL, GenreType.NOVEL),
        (_NARRATIVE, GenreType.NARRATIVE),
        (_DRAMA, GenreType.DRAMA),
        (_CHAR_STORY, GenreType.CHARACTER_STORY),
    ],
)
def test_supported_genres_pass(text: str, expected: GenreType):
    r = GenreDetector().classify(_material(text))
    assert r.genre == expected
    assert r.is_supported is True


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (_EXPOSITORY, GenreType.EXPOSITORY),
        (_ARGUMENTATIVE, GenreType.ARGUMENTATIVE),
        (_SCENERY, GenreType.SCENERY),
        (_POETRY, GenreType.POETRY),
    ],
)
def test_unsupported_genres_rejected(text: str, expected: GenreType):
    r = GenreDetector().classify(_material(text))
    assert r.genre == expected
    assert r.is_supported is False


def test_pipeline_raises_content_unsupported_genre():
    with pytest.raises(Error) as e:
        ContentPipeline().analyze(_paste("湖面平静如镜。柳树低垂。山峦连绵。倒映蓝天。"))
    assert e.value.code == codes.CNT_UNSUPPORTED_GENRE
    envelope = envelope_for(e.value)
    assert envelope.code == "CONTENT_UNSUPPORTED_GENRE"
    assert envelope.domain.value == "content"


# ===== 3. 原文分析（人物/关系/场景/关键事件 + 证据坐标）=====


def test_analysis_extracts_characters_with_evidence():
    analysis = ContentPipeline().analyze(_paste(BEIYING))
    names = {c.name for c in analysis.characters}
    assert {"父亲", "祖母", "我"} <= names

    father = next(c for c in analysis.characters if c.name == "父亲")
    assert father.evidence_refs, "人物必须带原文证据"
    first = father.evidence_refs[0]
    assert first.source_type == "original_text"
    # 文档级 char 区间必须指向原文中的真实片段
    assert BEIYING[first.char_start:first.char_end] == first.excerpt
    assert first.excerpt == "父亲"


def test_analysis_extracts_relationships():
    analysis = ContentPipeline().analyze(_paste(BEIYING))
    pairs = {(r.source, r.target) for r in analysis.relationships}
    assert ("我", "父亲") in pairs
    for r in analysis.relationships:
        assert r.evidence_refs, "关系必须带原文证据"


def test_analysis_extracts_scenes():
    analysis = ContentPipeline().analyze(_paste(BEIYING))
    assert analysis.scenes, "应识别出场景"
    locations = {s.location for s in analysis.scenes}
    assert "徐州" in locations


def test_analysis_extracts_ordered_key_events():
    analysis = ContentPipeline().analyze(_paste(BEIYING))
    assert len(analysis.key_events) >= 2
    orders = [e.order for e in analysis.key_events]
    assert orders == sorted(orders) and orders[0] == 1
    for e in analysis.key_events:
        assert e.evidence_refs
        ev = e.evidence_refs[0]
        assert BEIYING[ev.char_start:ev.char_end] == ev.excerpt


def test_analysis_title_detection():
    analysis = ContentPipeline().analyze(_paste(BEIYING))
    assert analysis.title == "背影"


# ===== 4. EvidenceRef 区分原文证据与网络补充 =====


def test_evidence_ref_discriminates_original_vs_web():
    original = OriginalEvidence(excerpt="父亲说", paragraph_index=1, char_start=0, char_end=3)
    web = WebEvidence(
        url="https://example.com/analysis",
        title="示例解读",
        fetched_at=datetime.now(UTC),
        content_hash="abc",
        excerpt="网络补充片段",
    )
    assert original.source_type == "original_text"
    assert web.source_type == "web"
    assert not hasattr(original, "url")
    assert web.url.scheme == "https"

    dumped = json.loads(original.model_dump_json())
    assert dumped["source_type"] == "original_text"


# ===== 5. 确定性 =====


def test_same_input_yields_identical_output():
    pipeline = ContentPipeline()
    inp = _paste(BEIYING)
    a = pipeline.analyze(inp)
    b = pipeline.analyze(inp)
    assert a.model_dump_json() == b.model_dump_json()

    # 体裁判断同样确定性
    r1 = GenreDetector().classify(_material(BEIYING))
    r2 = GenreDetector().classify(_material(BEIYING))
    assert r1 == r2


def test_analysis_matches_fixture_shape():
    import json as _json
    from pathlib import Path

    fixture = Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "text_analysis.json"
    TextAnalysis.model_validate(_json.loads(fixture.read_text()))
