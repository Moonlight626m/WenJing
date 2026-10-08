"""媒体契约（ADR-0005 §3/§11，issue #42 / #64）。

- `AssetUrlResponse`：鉴权端点 `GET /api/assets/{id}/url` 的响应——短时效预签名 URL。
  契约保持 URL-free 的投影（`AssetRef`）不受影响；URL 只在物化响应里出现。
- `TranscribeResponse`：学生语音识别端点 `POST /api/sessions/{id}/transcribe` 的响应。
  **只回文本**：录音字节是临时输入，不落库、不回传，也就不进契约。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.contracts.base import VersionedContract


class AssetUrlResponse(VersionedContract):
    """资产预签名 URL 物化响应。"""

    asset_id: uuid.UUID
    url: str
    expires_at: datetime


class TranscribeResponse(VersionedContract):
    """语音识别结果（#64）。

    前端拿到 `text` 后当作普通 `free_input` 命令提交——**不**由服务端代劳：
    `POST /api/sessions/{id}/commands` 是契约里明写的唯一游戏输入入口，
    给语音开旁路会绕开幂等、乐观锁与事件同事务持久化。
    """

    text: str = Field(min_length=1, description="识别出的文本（学生说的话）")
    duration_ms: int = Field(default=0, ge=0, description="音频时长（毫秒）；0=未知")


__all__ = ["AssetUrlResponse", "TranscribeResponse"]
