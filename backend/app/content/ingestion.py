"""材料导入（issue #9 验收标准 1）：校验 + 规范化 + 内容 hash。

- 粘贴：接收已解码文本；上传：字节按 UTF-8 → GB18030 顺序尝试解码，
  失败报 INPUT_INVALID_ENCODING。
- 扩展名仅允许 .txt/.md；空/纯空白报 INPUT_EMPTY_MATERIAL；超长报 INPUT_TOO_LARGE。
- 规范化：去 BOM、统一换行、NFC、压缩连续空行、strip 首尾空白。
- content_hash = SHA-256(normalized_text)，是去重与证据引用的锚点。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from app.contracts.material import Material, MaterialInput, MaterialSource
from app.errx import codes, new

ALLOWED_EXTENSIONS: tuple[str, ...] = (".txt", ".md")
DEFAULT_MAX_CHARS: int = 200_000

_BLANK_RUN_RE = re.compile(r"\n{3,}")


def normalize_text(raw: str) -> str:
    """规范化原始文本（确定性、幂等）。"""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\ufeff", "")
    text = unicodedata.normalize("NFC", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def content_hash(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise new(codes.INP_INVALID_ENCODING, extra={"reason": "not utf-8/gb18030"})


class MaterialIngestor:
    """导入校验 + 规范化入口。"""

    def __init__(self, *, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        self.max_chars = max_chars

    def ingest(self, inp: MaterialInput, *, raw_bytes: bytes | None = None) -> Material:
        raw = self._resolve_raw(inp, raw_bytes)
        normalized = normalize_text(raw)
        if not normalized:
            raise new(codes.INP_EMPTY_MATERIAL)
        if len(normalized) > self.max_chars:
            raise new(codes.INP_TOO_LARGE, extra={"max_chars": str(self.max_chars)})
        return Material(
            content_hash=content_hash(normalized),
            normalized_text=normalized,
            char_count=len(normalized),
            created_at=datetime.now(UTC),
        )

    def _resolve_raw(self, inp: MaterialInput, raw_bytes: bytes | None) -> str:
        if inp.source != MaterialSource.UPLOAD:
            return inp.raw_text
        ext = Path(inp.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise new(codes.INP_UNSUPPORTED_EXTENSION, extra={"ext": ext or "(none)"})
        if raw_bytes is None:
            # 调用方已自行解码：仅做扩展名校验后沿用 raw_text
            return inp.raw_text
        return _decode_bytes(raw_bytes)
