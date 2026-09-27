from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.infrastructure.llm.factory import KNOWN_PROVIDERS, ModelConfig

# 绝对锚定 backend/.env：不随启动 cwd 漂移（从仓库根/IDE 启动也能读到配置）
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="WENJING_", extra="ignore")

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

    # RAG 搜索 provider：null=不搜索（降级为纯原文）；ddgs=DuckDuckGo 网络搜索（无需 key）。
    # Literal 校验：非法值启动即报错，不静默回落（避免复刻"持续静默降级"）。
    rag_search_provider: Literal["null", "ddgs"] = "null"

    # --- 媒体与对象存储（ADR-0005 / M0 #39 配置项；M1 起接入真实实现）---
    # 存储 provider：null=不落盘空实现；s3=S3 兼容（MinIO 开发 / OSS 生产，M1 #40）。
    media_storage_provider: Literal["null", "s3"] = "null"
    # 内网 endpoint（backend 访问对象存储）与浏览器可达的 public endpoint 分离：
    # 预签名 URL 必须用 public endpoint 重写，否则浏览器拿到容器内主机名不可达。
    media_storage_endpoint: str = ""
    media_storage_public_endpoint: str = ""
    media_storage_region: str = ""
    media_storage_bucket: str = "wenjing-media"
    media_storage_access_key: str = ""
    media_storage_secret_key: str = ""
    media_storage_presign_ttl: int = 900

    # 生图 provider（M2 #46 接入）；检索 provider（M2 #44 接入）。
    media_image_gen_provider: Literal["null"] = "null"
    media_image_search_provider: Literal["null", "openverse", "wikimedia"] = "null"
    # 每会话运行期生图上限（ADR-0005 §7 成本控制）。
    media_max_images_per_session: int = 20

    # org 级媒体配额预算（付费调用前 check+consume，ADR-0005 §12）；0=不限额。
    media_org_image_budget: int = 0
    media_org_tts_budget: int = 0
    media_org_asr_budget: int = 0

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
