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


def test_opencodego_default_base_url_and_model():
    cfg = ModelConfig(provider="opencodego", api_key="k")
    assert cfg.base_url == "https://opencode.ai/zen/go/v1"
    assert cfg.model == "glm-5.3-flash"

    service = ModelServiceFactory.build(cfg)
    assert isinstance(service, ChatLLMService)
    assert service.provider == "opencodego"
    assert service.model == "glm-5.3-flash"


def test_ecnu_default_base_url_and_model():
    """华东师大开放平台：OpenAI 格式，端点/模型由登记表决定（#56 期间接入）。"""
    cfg = ModelConfig(provider="ecnu", api_key="k")
    assert cfg.base_url == "https://chat.ecnu.edu.cn/open/api/v1"
    assert cfg.model == "ecnu-plus"

    service = ModelServiceFactory.build(cfg)
    assert isinstance(service, ChatLLMService)
    assert service.provider == "ecnu"


def test_settings_llm_model_config_ecnu():
    """`.env` 里只写 provider + key 也能起（模型回落登记表默认值）。"""
    settings = Settings(
        llm_provider="ecnu", llm_api_key="k", llm_model="", llm_base_url=""
    )
    cfg = settings.llm_model_config()
    assert cfg.provider == "ecnu"
    assert cfg.base_url == KNOWN_PROVIDERS["ecnu"]["base_url"]
    assert cfg.model == KNOWN_PROVIDERS["ecnu"]["default_model"]


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


def test_sdk_retries_disabled_by_default():
    """SDK 自身的重试必须关闭（缺省 0）。

    回归：`_client` 曾不传 `max_retries`，SDK 缺省值 2 直接生效——它对 429/408/409/5xx
    会自动重试，且带 `Retry-After` 时按 `MAX_RETRY_AFTER_DELAY` 睡最长 120s。整段睡眠
    发生在 `asyncio.wait_for` 预算**之内**，还占着 `_semaphore` 的名额：一条要并发跑
    N 个角色提议 + 若干轮验证的选角命令，能被单个 429 按住数分钟，前端表现为
    「生成首幕中…」永不跳转。而 #65 的既定语义（`_may_retry`）是「4xx 不重试」，
    SDK 这层重试等于把它做废——重试策略必须单源。
    """
    cfg = ModelConfig(provider="openai", api_key="k")
    assert cfg.max_retries is None  # 未显式设置

    service = ModelServiceFactory.build(cfg)
    assert service._max_retries == 0  # 工厂不透传 → ChatLLMService 缺省关闭


async def test_client_passes_max_retries_to_sdk():
    """真正落地的判据：交给 OpenAI 客户端的必须就是 0，而不是「我们以为传了」。"""
    service = ChatLLMService(model="m", api_key="k", provider="openai")
    async with service._client("sess-1") as client:
        assert client.max_retries == 0


def test_sdk_max_retries_can_be_configured():
    """仍可经 ModelConfig 显式调回（排查用），并透传到 service。"""
    cfg = ModelConfig(provider="openai", api_key="k", max_retries=1)
    assert ModelServiceFactory.build(cfg)._max_retries == 1


def test_settings_llm_max_retries_default_zero():
    settings = Settings(llm_api_key="k")
    assert settings.llm_max_retries == 0
    assert settings.llm_model_config().max_retries == 0


def test_settings_llm_model_config_deepseek():
    settings = Settings(
        llm_provider="deepseek", llm_api_key="k", llm_model="", llm_base_url=""
    )
    cfg = settings.llm_model_config()
    assert cfg.provider == "deepseek"
    assert cfg.api_key == "k"
    assert cfg.base_url == KNOWN_PROVIDERS["deepseek"]["base_url"]
    assert cfg.model == KNOWN_PROVIDERS["deepseek"]["default_model"]


def test_opencodego_sends_stable_session_header():
    """OpenCode Go 要求每会话稳定 x-opencode-session 头 + 自有 UA（官方要求）。"""
    from app.infrastructure.llm.chat import ChatLLMService

    service = ChatLLMService(
        model=KNOWN_PROVIDERS["opencodego"]["default_model"], api_key="k", provider="opencodego"
    )
    headers = service._provider_headers("sess-1")
    assert headers is not None
    assert headers["x-opencode-session"] == "sess-1"
    assert headers["User-Agent"].startswith("wenjing/")
    anonymous = service._provider_headers("")
    assert anonymous["x-opencode-session"]  # 空会话回落稳定标识，不发空头

    openai_like = ChatLLMService(model="m", api_key="k", provider="openai")
    assert openai_like._provider_headers("sess-1") is None
