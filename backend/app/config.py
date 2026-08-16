from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="WENJING_", extra="ignore")

    app_name: str = "文境 (Wenjing)"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str = ""

    max_concurrent_llm: int = 5
    llm_timeout_seconds: int = 30
    player_timeout_seconds: int = 300
    max_events_in_memory: int = 5000
    checkpoint_interval: int = 20
    max_rollback_steps: int = 100
    max_proposal_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
