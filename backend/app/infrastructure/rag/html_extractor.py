"""HtmlDocumentExtractor：网页清洗与不可信文本标记（issue #10 验收标准 4）。

- 去除 script/style/注释/隐藏内容，只保留可见文本。
- 提取标题（<title> / <h1>）。
- 网页文本永远标记为 `untrusted=True`：后续作为「网络补充」证据而非事实来源；
  以显式隔离标签包裹指令类内容（如网页中的「忽略以上指示…」），供 LLM 侧防注入。
"""

from __future__ import annotations

import re
from html import unescape

from app.infrastructure.rag.providers import ExtractedDocument, FetchedPage

_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(script|style|noscript|template)\b[^>]*>.*?</\1\s*>"
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_H1_RE = re.compile(r"(?is)<h1[^>]*>(.*?)</h1>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")


class HtmlDocumentExtractor:
    """DocumentExtractor 首个实现：正则清洗 HTML 为纯文本。"""

    def extract(self, page: FetchedPage) -> ExtractedDocument:
        text = page.body_bytes.decode("utf-8", errors="replace")
        title = self._extract_title(text)
        cleaned = self._clean(text)
        return ExtractedDocument(
            url=page.final_url,
            title=title,
            text=cleaned,
            content_hash=page.content_hash,
            fetched_at=page.fetched_at,
            untrusted=True,
        )

    def _extract_title(self, html: str) -> str:
        for pattern in (_TITLE_RE, _H1_RE):
            match = pattern.search(html)
            if match:
                return _collapse_ws(unescape(match.group(1)))
        return ""

    def _clean(self, html: str) -> str:
        text = _SCRIPT_STYLE_RE.sub(" ", html)
        text = _COMMENT_RE.sub(" ", text)
        text = _TAG_RE.sub("\n", text)
        text = unescape(text)
        text = _WS_RE.sub(" ", text)
        text = _BLANK_RE.sub("\n\n", text)
        return text.strip()


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()
