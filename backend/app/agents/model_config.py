"""LLM 模型配置与多 provider 支持。

统一抽象出 `ModelConfig`（provider / model / api_key / base_url / 采样参数），
由一个 `ModelRegistry` 管理已知 provider 的默认端点，通过 `ChatLLMService` 构造
对应 provider 的客户端。

当前支持 OpenAI 与 DeepSeek，二者均走 OpenAI-compatible chat completions，仅
base_url 与默认 model 不同；新增 provider（Qwen/GLM 等）只需在 `KNOWN_PROVIDERS`
登记即可。

用法::

    cfg = ModelConfig(provider="deepseek", model="deepseek-chat", api_key="...")
    llm = cfg.build_service()           # 由 ModelConfig 直接构造
    llm = ModelServiceFactory.build(config)  # 或走工厂
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.errx import codes, new

logger = logging.getLogger("wenjing.agents.model_config")

# OpenAI-compatible 各 provider 默认端点（base_url 为 None 时用 OpenAI 官方默认）。
KNOWN_PROVIDERS: Mapping[str, Any] = {
    "openai": {"base_url": None, "default_model": "gpt-4o-mini"},
    "deepseek": {"base_url": "https://api.deepseek.com", "default_model": "deepseek-chat"},
}


class UnknownProviderError(RuntimeError):
    """请求了未在 KNOWN_PROVIDERS 登记的 provider。"""


@dataclass
class ModelConfig:
    """单个模型的完整配置，可据此构造对应的 LLM service。

    `provider` 必须是 `KNOWN_PROVIDERS` 中的键；`base_url` 缺省时取该 provider
    的默认端点。`temperature` / `max_tokens` 为采样参数。
    """

    provider: str = "openai"
    model: str | None = None
    api_key: str = ""
    base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider = self.provider.lower()
        if self.provider not in KNOWN_PROVIDERS:
            raise new(codes.CFG_UNKNOWN_PROVIDER, extra={"provider": self.provider})
        if not self.model:
            self.model = KNOWN_PROVIDERS[self.provider]["default_model"]
        if self.base_url is None:
            self.base_url = KNOWN_PROVIDERS[self.provider]["base_url"]


class ModelServiceFactory:
    """根据 `ModelConfig` 构建对应 provider 的 `LLMService`（懒导入避免不必要依赖）。"""

    @staticmethod
    def build(config: ModelConfig) -> Any:
        from app.agents.llm_service import ChatLLMService

        return ChatLLMService(
            model=config.model or "",
            api_key=config.api_key,
            base_url=config.base_url,
            provider=config.provider,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
