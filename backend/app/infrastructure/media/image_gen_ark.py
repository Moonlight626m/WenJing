"""火山引擎方舟（Ark）Seedream 文生图 adapter（branch-montage-dm 增补）。

复用 OpenAI Images 兼容骨架（`OpenAIImageGen`）：Ark 数据面就是
`POST {base}/api/v3/images/generations` + Bearer key，响应形状（`data[].url`
/`b64_json`/error）与 OpenAI 同形——传输/解析/SSRF 防护/审核错误形状映射全部
继承（父类 `_looks_like_policy` 已含 Ark 错误码族），本子类只处理 Ark 的
协议差异（2026-10 官方文档与 `arkruntime` SDK 类型核对）：

- **无 `n` 字段**：官方 SDK `CreateImageGenerationRequestParam` 没有它，不发。
- **`watermark` 默认 true**（右下角「AI 生成」标识）：中国 AI 生成内容标识
  合规优先，构造默认**保持水印**，显式传 `watermark=False` 才关。
- **尺寸**：seedream 5.0 接受 `WxH`，总像素下限 921 600（1280x720）、宽高比
  [1/16, 16]。头像/立绘的理想尺寸（512²/768x1024）低于下限，exact 直发会
  400——按 kind 保比例抬到「≥下限、≤261 万像素（pro 低价档）」的档位。
- **重试**：官方 SDK 对 408/429/5xx 退避重试（最多 2 次）；400/401/403/404
  不重试——重复付费或掩盖配置错误。注意 408 重试有「已生成但响应丢失」的
  双计费极小概率，官方 SDK 同样接受。
- **审核失败不计费**（官方价格页原文），BLOCKED 降级安全。

首推 `doubao-seedream-5-0-flash`（0.12 元/张，平面价）；`response_format=b64_json`
绕开产物 URL 的 24 小时有效期与 SSRF 面。接入前置：控制台开通模型 +
「API Key 管理」建 key（实名认证）。
"""

from __future__ import annotations

import asyncio
import base64
import logging
from collections.abc import Sequence

import httpx

from app.domain.game.media import AssetKind, GeneratedImage
from app.infrastructure.errx import codes, new, wrap
from app.infrastructure.media.image_gen_openai import OpenAIImageGen, sniff_image_mime

logger = logging.getLogger("wenjing.media.image_gen_ark")

DEFAULT_ARK_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_ARK_MODEL = "doubao-seedream-5-0-flash-260915"

# per-request 重试上限（408/429/5xx）——对齐官方 SDK DEFAULT_MAX_RETRIES = 2。
_MAX_RETRIES = 2

# seedream 5.0 exact 档位下限与 pro 低价档上限（像素）。
_ARK_MIN_PIXELS = 921_600        # 1280x720
_ARK_PRO_MAX_PIXELS = 2_610_000  # ≤261 万像素按 0.30 元/张计费

# 各 kind 的低保真抬升档（保比例、≥下限、≤261 万）：
# 16:9 用 1424x800（1:1.78 保画幅又压在低价档）；1:1 用 1024x1024；3:4 用 864x1152。
_ARK_LIFT_SIZES: dict[AssetKind, tuple[int, int]] = {
    AssetKind.BACKGROUND: (1424, 800),
    AssetKind.SCENE_MONTAGE: (1424, 800),
    AssetKind.AVATAR: (1024, 1024),
    AssetKind.FULLBODY: (864, 1152),
}

# 参考图张数上限（官方文档：seedream 5.0 pro/flash 最多 10 张）。
_ARK_MAX_REFERENCES = 10


def _data_url(data: bytes) -> str:
    """参考图字节 → base64 data URL（Ark 接受 URL 或 data URL）。"""
    mime = sniff_image_mime(data) or "image/png"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


class ArkImageGen(OpenAIImageGen):
    """`ImageGenPort` 的火山方舟实现：OpenAI 骨架 + Ark 协议差异。"""

    def __init__(
        self,
        *,
        api_key: str,
        client: httpx.AsyncClient | None = None,
        base_url: str = DEFAULT_ARK_BASE_URL,
        model: str = DEFAULT_ARK_MODEL,
        watermark: bool = True,
        read_timeout: float = 300.0,
        size_mode: str = "exact",
        **kwargs: object,
    ) -> None:
        super().__init__(
            api_key=api_key,
            client=client,
            base_url=base_url,
            model=model,
            read_timeout=read_timeout,
            size_mode=size_mode,
            **kwargs,  # type: ignore[arg-type] - 转发父类可选参（response_format 等）
        )
        # AI 生成内容标识合规默认：不显式关闭就保持官方水印。
        self._watermark = watermark
        # `sequential_image_generation` 只被部分 seedream 档支持（组图参数），
        # flash 单图档直接 400 InvalidParameter——只在该模型上报错时才免发，
        # 初始发一次探明，此后记住（一次 400 换后续所有请求干净）。
        self._send_sequential = True

    def _provider_size(
        self, width: int, height: int, *, kind: AssetKind | None = None
    ) -> str:
        """保比例抬到 Ark 合法像素档（低于 921 600 的 kind 直发会 400）。

        请求尺寸已 ≥ 下限（背景/场面 1280x720 恰好触及）则原样发；低于下限
        的 kind 默认（头像 512²、立绘 768x1024）换 `_ARK_LIFT_SIZES` 档位。
        """
        if self._size_mode != "exact":  # 走 OpenAI 三档 preset；1036x1024 等均合法
            return super()._provider_size(width, height, kind=kind)
        if width * height >= _ARK_MIN_PIXELS:
            return f"{width}x{height}"
        lift = _ARK_LIFT_SIZES.get(kind or AssetKind.SCENE_MONTAGE, (1424, 800))
        return f"{lift[0]}x{lift[1]}"

    def _build_payload(
        self,
        prompt: str,
        size: str,
        *,
        reference_images: Sequence[bytes] = (),
    ) -> dict[str, object]:
        """Ark 请求体：无 `n` 字段（官方 SDK 类型无此参数）；显式控水印。

        `image`（参考图，2026-11 官方文档核验 + 实测）：string 或 string[]，
        接受 URL 或 base64 data URL；seedream 5.0 pro/flash 最多 10 张。
        角色一致性靠它：已生成的头像作为后续场面图的参考输入。

        `sequential_image_generation`（组图开关）不是所有 seedream 档都收：
        flash 单图档 400 InvalidParameter。首次命中该错误就记下来不再发
        （并发下可能多张各探一次，各自收敛到同一结论，无害）。
        """
        payload: dict[str, object] = {
            "model": self._model,
            "prompt": prompt,
            "size": size,
            "watermark": self._watermark,
        }
        if reference_images:
            payload["image"] = [
                _data_url(data) for data in reference_images[:_ARK_MAX_REFERENCES]
            ]
        if self._send_sequential:
            payload["sequential_image_generation"] = "disabled"
        if self._response_format:
            payload["response_format"] = self._response_format
        return payload

    async def generate(
        self,
        *,
        prompt: str,
        kind: AssetKind,
        width: int = 0,
        height: int = 0,
        reference_images: Sequence[bytes] = (),
    ) -> GeneratedImage:
        """408/429/5xx 退避重试（≤2 次）；4xx 配置/审核错误立即抛。

        复刻父类 generate 的网络段并把重试插进去——生成前的本地过滤/尺寸
        解析/payload 构造每次重试只算一次。复用父类的 `_status_reason` 与
        `_looks_like_policy`（后者已带 Ark 错误码族）。
        """
        # 延迟避免循环导入：父类模块只依赖 domain，这里复用其内部函数。
        from app.domain.game.media_safety import screen_generation_prompt
        from app.infrastructure.media.image_gen_openai import (
            _status_reason,
            image_dimensions,
            sniff_image_mime,
        )

        screen_generation_prompt(prompt, max_chars=self._max_prompt_chars)
        w, h = self._resolve_size(kind, width, height)
        payload = self._build_payload(
            prompt,
            self._provider_size(w, h, kind=kind),
            reference_images=reference_images,
        )

        last_reason = ""
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self._post(payload)
            except httpx.TimeoutException as exc:
                raise new(
                    codes.MEDIA_IMAGE_GEN_TIMEOUT,
                    extra={"reason": f"timeout ({self._model})"},
                ) from exc
            except httpx.HTTPError as exc:
                raise wrap(exc, codes.MEDIA_IMAGE_GEN_FAILED, extra={"reason": str(exc)}) from exc
            if resp.is_success:
                data = await self._extract_bytes(resp)
                mime = sniff_image_mime(data)
                if mime is None:
                    raise new(
                        codes.MEDIA_IMAGE_GEN_INVALID,
                        extra={"reason": "unrecognised image bytes"},
                    )
                actual_w, actual_h = image_dimensions(data)
                return GeneratedImage(
                    image_bytes=data,
                    content_type=mime,
                    width=actual_w or w,
                    height=actual_h or h,
                )
            # 组图参数不被当前模型支持：去掉该参数立即重试本条请求。
            # 该兜底在 4xx 语义化映射**之前**——InvalidParameter 是「参数
            # 与模型不配」，去掉参数后本条请求仍有希望成功。
            reason_now = _status_reason(resp) or f"http {resp.status_code}"
            if (
                self._send_sequential
                and "sequential_image_generation" in reason_now
            ):
                self._send_sequential = False
                payload.pop("sequential_image_generation", None)
                logger.info(
                    "ark_sequential_param_dropped model=%s", self._model
                )
                continue
            if resp.status_code not in (408, 429) and resp.status_code < 500:
                self._raise_non_retryable(resp)
            last_reason = reason_now
            if attempt < _MAX_RETRIES:
                delay = min(2.0 * (2**attempt), 8.0)  # 指数退避 2s/4s，封顶 8s
                retry_after = resp.headers.get("retry-after")
                if retry_after and retry_after.isdigit():
                    delay = min(max(float(retry_after), delay), 8.0)
                logger.warning(
                    "ark_image_gen_retry attempt=%d status=%d delay=%.1fs",
                    attempt + 1,
                    resp.status_code,
                    delay,
                )
                await asyncio.sleep(delay)
        raise new(
            codes.MEDIA_IMAGE_GEN_FAILED,
            extra={"reason": f"retries exhausted: {last_reason}"},
        )

    @staticmethod
    def _raise_non_retryable(resp: httpx.Response) -> None:
        """4xx 非 408/429 → 语义化失败（审核拒绝 BLOCKED，其余 FAILED）。

        复用父类模块的 `_status_reason`/`_looks_like_policy`（后者已带 Ark
        错误码族关键词）。
        """
        from app.infrastructure.media.image_gen_openai import (
            _looks_like_policy,
            _status_reason,
        )

        reason = _status_reason(resp)
        raise new(
            codes.MEDIA_IMAGE_GEN_BLOCKED
            if _looks_like_policy(reason)
            else codes.MEDIA_IMAGE_GEN_FAILED,
            extra={"reason": reason or f"http {resp.status_code}"},
        )


__all__ = ["DEFAULT_ARK_BASE_URL", "DEFAULT_ARK_MODEL", "ArkImageGen"]
