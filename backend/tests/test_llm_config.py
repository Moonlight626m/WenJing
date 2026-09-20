"""ModelConfig 与多 provider 支持的单测。

验证：
- ModelConfig 按 provider 回落默认 model / base_url
- 未知 provider 抛 CFG_UNKNOWN_PROVIDER
- ModelServiceFactory 构造出 ChatLLMService 并透传采样参数
- Settings.llm_model_config() 从环境配置分发到对应 provider
"""

from __future__ import annotations

import pytest

from app.infrastructure.config import Settings
from app.infrastructure.errx import codes, match_code
from app.infrastructure.llm.chat import ChatLLMService
from app.infrastructure.llm.factory import (
    KNOWN_PROVIDERS,
    ModelConfig,
    ModelServiceFactory,
)


def test_openai_defaults_and_factory():
    cfg = ModelConfig(provider="openai", api_key="k")
    assert cfg.base_url is None  # OpenAI 官方默认
    assert cfg.model == KNOWN_PROVIDERS["openai"]["default_model"]

    service = ModelServiceFactory.build(cfg)
    assert isinstance(service, ChatLLMService)
    assert service.provider == "openai"
    assert service.model == cfg.model


def test_deepseek_default_base_url_and_model():
    cfg = ModelConfig(provider="deepseek", api_key="k")
    assert cfg.base_url == KNOWN_PROVIDERS["deepseek"]["base_url"]
    assert cfg.model == KNOWN_PROVIDERS["deepseek"]["default_model"]


def test_explicit_base_url_overrides_provider_default():
    cfg = ModelConfig(provider="deepseek", api_key="k", base_url="http://localhost:9999/v1")
    assert cfg.base_url == "http://localhost:9999/v1"


def test_unknown_provider_raises_errx():
    with pytest.raises(Exception) as excinfo:
        ModelConfig(provider="not-a-provider")
    assert match_code(excinfo.value, codes.CFG_UNKNOWN_PROVIDER)


def test_temperature_and_max_tokens_pass_through():
    cfg = ModelConfig(provider="openai", api_key="k", temperature=0.2, max_tokens=64)
    service = ModelServiceFactory.build(cfg)
    assert service._temperature == 0.2
    assert service._max_tokens == 64


def test_settings_llm_model_config_deepseek():
    settings = Settings(llm_provider="deepseek", llm_api_key="k", llm_model="")
    cfg = settings.llm_model_config()
    assert cfg.provider == "deepseek"
    assert cfg.api_key == "k"
    assert cfg.base_url == KNOWN_PROVIDERS["deepseek"]["base_url"]
    assert cfg.model == KNOWN_PROVIDERS["deepseek"]["default_model"]
