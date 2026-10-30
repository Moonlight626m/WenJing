"""内容管线包（issue #9）：课文导入 / 体裁判断 / 原文证据模型。

对外：
- `ContentPipeline`：导入 → 体裁判断 → 原文分析的一站式入口。
- `MaterialIngestor` / `GenreDetector` / `TextAnalyzer`：可独立使用/注入的步骤。
"""

from app.domain.content.analysis import TextAnalyzer
from app.domain.content.genre import GenreDetector
from app.domain.content.ingestion import (
    ALLOWED_EXTENSIONS,
    DEFAULT_MAX_CHARS,
    MaterialIngestor,
    content_hash,
    normalize_text,
)
from app.domain.content.pipeline import ContentPipeline

__all__ = [
    "ContentPipeline",
    "MaterialIngestor",
    "GenreDetector",
    "TextAnalyzer",
    "ALLOWED_EXTENSIONS",
    "DEFAULT_MAX_CHARS",
    "content_hash",
    "normalize_text",
]
