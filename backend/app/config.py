from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.agents.model_config import KNOWN_PROVIDERS, ModelConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WENJING_", extra="ignore")

    app_name: str = "文境 (Wenjing)"
    debug: bool = False

    # 访问日志是否打印完整 req/resp body（排障用；正式环境可关）
    log_body: bool = True

    # CORS 允许来源（逗号分隔）；默认本地前端 dev server
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    database_url: str = "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"

    # 账号会话（issue #17 / ADR-0002）。生产走 HTTPS 时应置 WENJING_AUTH_COOKIE_SECURE=1。
    auth_cookie_secure: bool = False
    auth_session_ttl_days: int = 14
    auth_csrf_header: str = "X-CSRF-Token"

    llm_provider: str = "openai"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_temperature: float = 0.7

    max_concurrent_llm: int = 5
    # 默认上限需覆盖 Stage1 全剧本生成（实测 DeepSeek 约 100s）；短调用仅受上界约束
    llm_timeout_seconds: int = 150
    player_timeout_seconds: int = 300
    max_events_in_memory: int = 5000
    checkpoint_interval: int = 20
    max_rollback_steps: int = 100
    max_proposal_retries: int = 2

    def llm_model_config(self) -> ModelConfig:
        """根据环境配置构建当前生效的 `ModelConfig`（provider 多路分发）。

        未显式指定 model 时回落到该 provider 的默认模型。
        """
        provider = self.llm_provider.lower()
        default_model = KNOWN_PROVIDERS.get(provider, {}).get("default_model", "")
        return ModelConfig(
            provider=provider,
            model=self.llm_model or default_model or None,
            api_key=self.llm_api_key,
            base_url=self.llm_base_url or None,
            temperature=self.llm_temperature,
            timeout_seconds=self.llm_timeout_seconds,
            max_concurrency=self.max_concurrent_llm,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
