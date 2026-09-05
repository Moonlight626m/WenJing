"""内容管线（issue #9）：导入 → 体裁判断 → 原文分析。

对外唯一入口 `ContentPipeline.analyze()`：
- 导入校验/规范化/hash（ingestion）
- 体裁判断；非叙事体裁抛 CONTENT_UNSUPPORTED_GENRE（genre）
- 原文分析（analysis，确定性）
#11 在此输出（TextAnalysis）之上做 Schema-first Stage1 生成。
"""

from __future__ import annotations

from app.content.analysis import TextAnalyzer
from app.content.genre import GenreDetector
from app.content.ingestion import DEFAULT_MAX_CHARS, MaterialIngestor
from app.contracts.content import TextAnalysis
from app.contracts.material import MaterialInput
from app.errx import codes, new


class ContentPipeline:
    """内容管线门面；各步骤可替换（依赖注入），默认确定性实现。"""

    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self.ingestor = MaterialIngestor(max_chars=max_chars)
        self.detector = GenreDetector()
        self.analyzer = TextAnalyzer()

    def analyze(self, inp: MaterialInput, *, raw_bytes: bytes | None = None) -> TextAnalysis:
        material = self.ingestor.ingest(inp, raw_bytes=raw_bytes)
        genre = self.detector.classify(material)
        if not genre.is_supported:
            raise new(codes.CNT_UNSUPPORTED_GENRE, extra={"genre": genre.genre.value})
        return self.analyzer.analyze(material, genre)
