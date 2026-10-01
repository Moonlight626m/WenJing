from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.infrastructure.llm.factory import KNOWN_PROVIDERS, ModelConfig

# 绝对锚定 backend/.env：不随启动 cwd 漂移（从仓库根/IDE 启动也能读到配置）
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


#: 在途配图任务 TTL 的出厂值。调度器（`services/scene_assets.py`）拿它当默认参数，
#: 这样「配置默认值」与「调度器默认值」只有一个来源，不会各改各的。
MEDIA_ASSET_JOB_TTL_SECONDS_DEFAULT = 900

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

    # 生图 provider（M2 #46 接入）：openai = OpenAI 兼容 Images API（换厂商不改 adapter；
    # provider 选型仍是 ADR-0005 待定项）；null = 不生成，上层降级为无图。
    media_image_gen_provider: Literal["null", "openai"] = "null"
    media_image_gen_base_url: str = "https://api.openai.com/v1"
    media_image_gen_api_key: str = ""
    media_image_gen_model: str = "gpt-image-1"
    media_image_gen_connect_timeout: float = 5.0
    # 生图明显慢于检索（单张 16:9 常见 10–40s），读超时给足但仍设上界。
    media_image_gen_read_timeout: float = 90.0
    media_image_gen_max_bytes: int = 16 * 1024 * 1024
    media_image_gen_max_prompt_chars: int = 1200
    # 多数兼容 provider 认 "b64_json"/"url"；gpt-image-1 不接受该参数，留空即不发。
    media_image_gen_response_format: str = ""
    # 尺寸模式：preset=按宽高比映射到 provider 固定档位（gpt-image-1 只认
    # 1024x1024/1536x1024/1024x1536，发 1280x720 会 400）；exact=直发 WxH，
    # 适合接受任意尺寸的兼容 provider。
    media_image_gen_size_mode: Literal["preset", "exact"] = "preset"

    # 检索 provider（M2 #44 接入）。
    media_image_search_provider: Literal["null", "openverse", "wikimedia"] = "null"
    # 检索下载安全边界（复用 RAG SSRF/DNS 校验）：连接/读取超时与单图字节上限。
    media_image_search_connect_timeout: float = 5.0
    media_image_search_read_timeout: float = 10.0
    media_image_search_max_bytes: int = 8 * 1024 * 1024
    # Openverse 可选访问令牌（匿名可用但限流；配置后走 Bearer）。Wikimedia 无需 key。
    media_image_search_openverse_token: str = ""
    # Wikimedia 要求可识别的 User-Agent（含联系方式更佳）。
    media_image_search_user_agent: str = "Wenjing/1.0 media-search"
    # 每会话运行期生图上限（ADR-0005 §7 成本控制）。
    media_max_images_per_session: int = 20
    # 崩溃后仍愿意重排的在途配图任务年龄上限（秒，ADR-0005 §5）。超龄判死而不重排：
    # 崩溃循环会把同一场景一次次重排队列，那份产出多半没人看得到。
    media_asset_job_ttl_seconds: int = MEDIA_ASSET_JOB_TTL_SECONDS_DEFAULT

    # 语音合成 provider（M6 #63）：openai = OpenAI 兼容 /audio/speech（换厂商不改
    # adapter）；null = 不合成，`TtsSynthesizer` 收到空字节即静默跳过（字幕照滚）。
    media_tts_provider: Literal["null", "openai"] = "null"
    media_tts_base_url: str = "https://api.openai.com/v1"
    media_tts_api_key: str = ""
    media_tts_model: str = "tts-1"
    #: provider 侧默认音色；`media_tts_voices` 为空时全场都用它（角色不可区分）。
    media_tts_default_voice: str = "alloy"
    # 音色池（逗号分隔）：角色按**名字哈希**取模分配，同名角色跨会话恒定。
    # 池子越大越不容易撞嗓；空 = 全场退回 default_voice（角色**不可区分**）。
    # 默认给满 OpenAI 兼容的六个嗓：不给的话「音色可区分角色」（#63 验收）只在
    # 运营显式配置后才成立，而默认配置才是绝大多数部署的样子。
    media_tts_voices: str = "alloy,echo,fable,onyx,nova,shimmer"
    #: 运营钦定的 角色名=音色 覆盖（逗号分隔，如 `母亲=nova,父亲=onyx`）。
    media_tts_voice_overrides: str = ""
    media_tts_connect_timeout: float = 5.0
    media_tts_read_timeout: float = 60.0
    media_tts_max_bytes: int = 16 * 1024 * 1024
    media_tts_max_chars: int = 4096
    #: 单句送合成长度上限（tee 的分句器已按标点切过，这里防超长"一句话"）。
    media_tts_max_sentence_chars: int = 200
    media_tts_response_format: str = "mp3"

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
