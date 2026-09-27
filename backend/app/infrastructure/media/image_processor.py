"""图片多规格处理（ADR-0005 §4，issue #42）。

生成/上传时产出 `thumb` / `medium` / `original` 三档，各编码为 WebP（及 AVIF，
Pillow 支持时）。不塞进 `ObjectStoragePort`——出现第二个后端再抽象。
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from app.infrastructure.errx import codes, new, wrap


@dataclass(frozen=True)
class ImageVariant:
    """一个规格的产出：名称（含格式后缀）、字节、内容类型与像素尺寸。"""

    name: str
    data: bytes
    content_type: str
    width: int
    height: int


# (规格名, 长边上限；0=原尺寸)
_SIZES: tuple[tuple[str, int], ...] = (("thumb", 256), ("medium", 1024), ("original", 0))
# (后缀, Pillow 格式, content-type)
_FORMATS: tuple[tuple[str, str, str], ...] = (
    ("webp", "WEBP", "image/webp"),
    ("avif", "AVIF", "image/avif"),
)


class ImageProcessor:
    """Pillow 多规格转码；AVIF 不可用时自动跳过该格式。

    `max_pixels` 限制输入像素总量（防解压炸弹/内存放大，M2 接入后台链路前的护栏）。
    """

    def __init__(self, *, quality: int = 82, max_pixels: int = 40_000_000) -> None:
        self._quality = quality
        self._max_pixels = max_pixels

    def process(self, data: bytes) -> list[ImageVariant]:
        from PIL import Image, features

        try:
            source = Image.open(BytesIO(data))
        except Exception as exc:  # noqa: BLE001 - 统一媒体错误域
            raise wrap(
                exc, codes.MEDIA_IMAGE_INVALID, extra={"reason": str(exc)}
            ) from exc
        if source.width * source.height > self._max_pixels:
            raise new(
                codes.MEDIA_IMAGE_INVALID,
                extra={"reason": f"image too large ({source.width}x{source.height})"},
            )
        try:
            source.load()
        except Exception as exc:  # noqa: BLE001 - 统一媒体错误域
            raise wrap(
                exc, codes.MEDIA_IMAGE_INVALID, extra={"reason": str(exc)}
            ) from exc

        base = (
            source.convert("RGBA")
            if source.mode in ("RGBA", "LA", "P")
            else source.convert("RGB")
        )

        variants: list[ImageVariant] = []
        for name, max_edge in _SIZES:
            image = base.copy()
            if max_edge:
                image.thumbnail((max_edge, max_edge), Image.LANCZOS)
            for ext, fmt, content_type in _FORMATS:
                if fmt == "AVIF" and not features.check("avif"):
                    continue
                buffer = BytesIO()
                try:
                    image.save(buffer, format=fmt, quality=self._quality)
                except Exception:  # noqa: BLE001 - 该格式不可用则跳过
                    continue
                variants.append(
                    ImageVariant(
                        name=f"{name}.{ext}",
                        data=buffer.getvalue(),
                        content_type=content_type,
                        width=image.width,
                        height=image.height,
                    )
                )
        return variants


__all__ = ["ImageProcessor", "ImageVariant"]
