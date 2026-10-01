"""进程级组合根：把配置与适配器组装到各接缝。

这是**唯一**的依赖装配点（原先散落在各 controller 的模块级单例）。lifespan 调用
`get_container().open()` 建立事件循环绑定资源（LangGraph checkpointer），请求期各
controller 经 `get_container()` 取已组装的用例/服务。

分层：本模块位于 controllers 之上、services/infrastructure 之下——只 import
services/domain/infrastructure，不 import controllers/main，故不破坏 `lint-arch`。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.domain.game.asr import AsrTranscriber
from app.domain.game.image_review import ImageReviewAgent
from app.domain.game.media import MediaKind, SceneDesigner
from app.domain.game.tts import VoiceMap
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db.session import SessionLocal, engine
from app.infrastructure.diagnostics.logging import exc_reason
from app.infrastructure.llm.factory import ModelServiceFactory
from app.infrastructure.llm.fake import DeterministicAgentLLM
from app.infrastructure.media import (
    ImageProcessor,
    MediaQuotaService,
    MediaUsageRecorder,
    SqlAssetJobStore,
    SqlAssetRepository,
    build_asr,
    build_image_gen,
    build_image_search,
    build_object_storage,
    build_tts,
    build_voice_map,
)
from app.infrastructure.rag.service import RagService, build_search_provider
from app.infrastructure.usage import UsageRecorder
from app.services.admin import AdminService
from app.services.assets import AssetAccessService
from app.services.auth import AuthService
from app.services.scene_assets import SceneAssetScheduler
from app.services.script_library import ScriptLibrary
from app.services.session_events import SessionEventHub
from app.services.session_runtime import SessionApplication

logger = logging.getLogger("wenjing.composition")


class Container:
    """装配后的进程级依赖集合；各服务惰性构建并按需缓存。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.session_factory = SessionLocal
        self.checkpointer: Any | None = None
        self._checkpoint_pool: Any | None = None
        self._session_application: SessionApplication | None = None
        self._script_library: ScriptLibrary | None = None
        self._auth_service: AuthService | None = None
        self._admin_service: AdminService | None = None
        self._object_storage: Any | None = None
        self._image_search: Any | None = None
        self._image_gen: Any | None = None
        self._tts: Any | None = None
        self._asr: Any | None = None
        self._asr_transcriber: AsrTranscriber | None = None
        self._tts_factory: Callable[..., Any] | None = None
        self._voice_map: VoiceMap | None = None
        self._asset_access: AssetAccessService | None = None
        self._asset_repo: SqlAssetRepository | None = None
        self._asset_jobs: SqlAssetJobStore | None = None
        self._scene_designer: SceneDesigner | None = None
        self._event_hub: SessionEventHub | None = None
        self._asset_scheduler: SceneAssetScheduler | None = None

    # ===== 生命周期（lifespan 调用）=====

    async def open(self) -> None:
        """建立事件循环绑定资源（重复调用会先释放旧 pool）。失败降级不阻断启动。"""
        if self._checkpoint_pool is not None:
            await self._checkpoint_pool.close()
        # DB 连接池同样是事件循环绑定资源：asyncpg 连接只属于创建它的那个 loop，
        # 换一个 loop 再取出来用会报 "another operation is in progress"，而且那条
        # 坏连接会被还回池子里继续毒害后续请求。启动恢复（#57）是 open() 里第一个
        # 碰 DB 的动作，不先丢弃旧连接就轮到它踩。生产只 open 一次，这里是空操作。
        # close=False：只丢池子不逐条关闭——在**新** loop 里关闭旧 loop 的连接，
        # 正是我们要避免的那件事。
        await engine.dispose(close=False)
        self.checkpointer, self._checkpoint_pool = await self._open_checkpointer()
        # checkpointer 若在建库前已被访问过，丢弃缓存以纳入新 saver
        self._script_library = None
        await self._recover_asset_jobs()

    async def _recover_asset_jobs(self) -> None:
        """启动时的在途配图恢复（ADR-0005 §5 / issue #57）。

        恢复失败**不阻断启动**：它只是把上次崩溃欠下的账收一收，收不动也不该
        让整个服务起不来（与 checkpointer 建不起来时的降级同一个取舍）。
        """
        try:
            report = await self.session_application.recover_asset_jobs()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "asset_jobs_recovery_failed",
                extra={"wj_extra": {"reason": exc_reason(exc)}},
            )
            return
        if report.requeued or report.expired:
            logger.info(
                "asset_jobs_recovery_done",
                extra={
                    "wj_extra": {
                        "requeued": report.requeued,
                        "expired": report.expired,
                    }
                },
            )

    async def close(self) -> None:
        # 在途运行期配图先收尾：任务已经付过费，等它把 asset_ready 落库再走，
        # 否则每次重启都会丢掉一张刚生成好的图（崩溃恢复是 #57 的 asset_jobs）。
        if self._asset_scheduler is not None:
            await self._asset_scheduler.drain()
        if self._checkpoint_pool is not None:
            await self._checkpoint_pool.close()
        self._checkpoint_pool = None
        self.checkpointer = None
        # 关闭后再次访问需以无 checkpointer 重建，避免绑定已关闭的 saver
        self._script_library = None
        # 检索/生图/TTS 端口各自持有自建 httpx 连接池；不关会在长跑进程与多轮
        # lifespan 下持续泄漏 socket/fd（空实现无 close，走 hasattr 守卫）。置空以便重建。
        await self._aclose_port("_image_search")
        await self._aclose_port("_image_gen")
        await self._aclose_port("_tts")
        await self._aclose_port("_asr")
        # 编排器持有上面两个端口（可能已被关闭），一并丢弃以便按新端口重建。
        self._scene_designer = None
        # 工厂闭包 / 编排器持有配额实例（进程内计数 + 已种子集合），随端口一起重建，
        # 否则新一轮 lifespan 会拿着上一轮的内存计数继续扣。
        self._tts_factory = None
        self._asr_transcriber = None

    async def _aclose_port(self, attr: str) -> None:
        port = getattr(self, attr, None)
        if port is not None:
            # 端口自建的 httpx 池可能挂在 `close` 或 `aclose` 上——`TtsPort` 用后者
            # （协议里就叫 `aclose`），两个都认，免得新增端口时又漏一个。
            closer = getattr(port, "close", None) or getattr(port, "aclose", None)
            if closer is not None:
                await closer()
        setattr(self, attr, None)

    async def _open_checkpointer(self) -> tuple[Any | None, Any | None]:
        """async 创建 AsyncPostgresSaver；只捕连接/建表异常（配置错误显式暴露）。"""
        if not self.settings.llm_api_key:
            return None, None
        pool = None
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool

            conninfo = self.settings.database_url.replace("+asyncpg", "")
            pool = AsyncConnectionPool(conninfo=conninfo, open=False, min_size=1)
            saver = AsyncPostgresSaver(pool)
            await pool.open()
            await saver.setup()
            return saver, pool
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "generation_checkpointer_setup_failed_degraded reason=%s", exc
            )
            if pool is not None:
                await pool.close()
            return None, None

    # ===== 服务（惰性 + 缓存）=====

    @property
    def event_hub(self) -> SessionEventHub:
        """命令外事件的进程内投递点（#56）；WS 路由与 SessionApplication 共用同一个。"""
        if self._event_hub is None:
            self._event_hub = SessionEventHub()
        return self._event_hub

    @property
    def asset_repo(self) -> SqlAssetRepository:
        """资产元数据仓库（ADR-0005 §4）。无状态，进程内共用一个即可。"""
        if self._asset_repo is None:
            self._asset_repo = SqlAssetRepository(session_factory=self.session_factory)
        return self._asset_repo

    @property
    def asset_jobs(self) -> SqlAssetJobStore:
        """运行期配图任务台账（#57）：每会话上限与崩溃恢复都建在它上面。"""
        if self._asset_jobs is None:
            self._asset_jobs = SqlAssetJobStore(session_factory=self.session_factory)
        return self._asset_jobs

    @property
    def asset_scheduler(self) -> SceneAssetScheduler:
        """运行期配图调度（#56）：`scene_designer` 以 lambda 延迟求值，
        避免在没有生成任务时也构建整套媒体栈。"""
        if self._asset_scheduler is None:
            self._asset_scheduler = SceneAssetScheduler(
                designer=lambda: self.scene_designer,
                jobs=self.asset_jobs,
                max_images_per_session=self.settings.media_max_images_per_session,
                job_ttl_seconds=self.settings.media_asset_job_ttl_seconds,
            )
        return self._asset_scheduler

    @property
    def session_application(self) -> SessionApplication:
        if self._session_application is None:
            self._session_application = SessionApplication(
                session_factory=self.session_factory,
                agent_llm=self._build_agent_llm(),
                usage_recorder=UsageRecorder(session_factory=self.session_factory),
                asset_scheduler=self.asset_scheduler,
                event_hub=self.event_hub,
                assets=self.asset_repo,
            )
        return self._session_application

    @property
    def script_library(self) -> ScriptLibrary:
        if self._script_library is None:
            script_llm = self._build_script_llm()
            self._script_library = ScriptLibrary(
                session_factory=self.session_factory,
                script_llm=script_llm,
                rag=RagService(
                    search_provider=build_search_provider(
                        self.settings.rag_search_provider
                    )
                ),
                model_name=self.settings.llm_model,
                usage_recorder=UsageRecorder(session_factory=self.session_factory),
                workflow_checkpointer=self.checkpointer,
                workflow_enabled=script_llm is not None,
                # 生成期配图（#48）：design_assets 节点经此编排检索→审核→回退生成。
                # 传 lambda 延迟到首次生成才构建媒体栈（ScriptLibrary 可能在
                # 无媒体配置的测试桩下被构造）。
                scene_designer=lambda: self.scene_designer,
            )
        return self._script_library

    @property
    def auth_service(self) -> AuthService:
        if self._auth_service is None:
            self._auth_service = AuthService()
        return self._auth_service

    @property
    def admin_service(self) -> AdminService:
        if self._admin_service is None:
            self._admin_service = AdminService(session_factory=self.session_factory)
        return self._admin_service

    @property
    def object_storage(self) -> Any:
        """对象存储端口（ADR-0005 §4）；provider=null 时为安全空实现。"""
        if self._object_storage is None:
            self._object_storage = build_object_storage(self.settings)
        return self._object_storage

    @property
    def image_search(self) -> Any:
        """开放版权图片检索端口（ADR-0005 §6 / #44）；provider=null 时为安全空实现。"""
        if self._image_search is None:
            self._image_search = build_image_search(self.settings)
        return self._image_search

    @property
    def image_gen(self) -> Any:
        """文生图端口（ADR-0005 §2/§6 / #46）；provider=null 时为安全空实现。"""
        if self._image_gen is None:
            self._image_gen = build_image_gen(self.settings)
        return self._image_gen

    @property
    def tts(self) -> Any:
        """语音合成端口（ADR-0005 §11 / #63）；provider=null 时为安全空实现。"""
        if self._tts is None:
            self._tts = build_tts(self.settings)
        return self._tts

    @property
    def asr(self) -> Any:
        """语音识别端口（ADR-0005 §11 / #64）；provider=null 时为安全空实现。"""
        if self._asr is None:
            self._asr = build_asr(self.settings)
        return self._asr

    @property
    def asr_transcriber(self) -> AsrTranscriber:
        """识别编排（#64）。

        与 `scene_designer` 一样**整体缓存**：它持有 `MediaQuotaService`，而配额的
        语义是"种子后按进程内计数推进"——每次访问都重建等于计数逐请求清零，
        配了 `media_org_asr_budget` 时闸门形同不限（#63 审查抓到的同类问题）。
        """
        if self._asr_transcriber is None:
            self._asr_transcriber = AsrTranscriber(
                port=self.asr,
                meter=MediaUsageRecorder(session_factory=self.session_factory),
                quota=MediaQuotaService(
                    session_factory=self.session_factory,
                    limits={MediaKind.ASR: self.settings.media_org_asr_budget},
                ),
                max_audio_bytes=self.settings.media_asr_max_bytes,
                max_seconds=self.settings.media_asr_max_seconds,
            )
        return self._asr_transcriber

    @property
    def voice_map(self) -> VoiceMap:
        """角色 → 音色映射（#63）。领域策略，与 provider 选型解耦。"""
        if self._voice_map is None:
            self._voice_map = build_voice_map(self.settings)
        return self._voice_map

    @property
    def tts_synthesizer_factory(self) -> Callable[[Any], Any]:
        """按连接造 `TtsSynthesizer` 的工厂（音轨出口是 per-connection 的）。

        出口（`AudioTrackChannel`）随连接生灭，所以合成器也必须 per-connection；
        端口、音色表、计量、配额这些**进程级**依赖在这里绑好，路由只管传出口。

        **工厂本身必须缓存**（`self._tts_factory`）：属性每次访问都新建的话，
        `MediaQuotaService` 会被逐命令重建，而它的语义是「首次触达某 (org,kind) 时
        从 `media_usage` 聚合种子，此后按**进程内计数**推进」——重建等于每条命令都把
        计数丢掉并从 DB 重种子，预算形同不限。默认 `media_org_tts_budget=0`（不限）
        时看不出来，配了预算才咬人。同文件 `scene_designer` 是正确先例。
        """
        if self._tts_factory is None:
            from app.domain.game.tts import TtsSynthesizer

            meter = MediaUsageRecorder(session_factory=self.session_factory)
            quota = MediaQuotaService(
                session_factory=self.session_factory,
                limits={MediaKind.TTS: self.settings.media_org_tts_budget},
            )

            def build(sink: Any, *, session_id: Any, org_id: Any, user_id: Any,
                      script_id: Any = None) -> TtsSynthesizer:
                return TtsSynthesizer(
                    port=self.tts,
                    voices=self.voice_map,
                    sink=sink,
                    meter=meter,
                    quota=quota,
                    session_id=session_id,
                    org_id=org_id,
                    user_id=user_id,
                    script_id=script_id,
                    max_sentence_chars=self.settings.media_tts_max_sentence_chars,
                )

            self._tts_factory = build
        return self._tts_factory

    @property
    def asset_access(self) -> AssetAccessService:
        """资产访问服务（ADR-0005 §3 / #42）：鉴权 + 预签名 URL。"""
        if self._asset_access is None:
            self._asset_access = AssetAccessService(
                assets=self.asset_repo,
                storage=self.object_storage,
                session_factory=self.session_factory,
                presign_ttl=self.settings.media_storage_presign_ttl,
            )
        return self._asset_access

    @property
    def scene_designer(self) -> SceneDesigner:
        """场景资产编排（ADR-0005 §6 / #47）：检索→审核→回退生成→存储。

        转码以 `ImageProcessor().process` 注入（domain 不 import infra，故不形式化成端口）；
        审核用 agent 侧 LLM，其失败在 `ImageReviewAgent` 内部降级为「拒绝候选」，
        不会打断编排。配额为 0 表示不限额（`MediaQuotaService` 语义）。
        """
        if self._scene_designer is None:
            self._scene_designer = SceneDesigner(
                storage=self.object_storage,
                image_gen=self.image_gen,
                image_search=self.image_search,
                assets=self.asset_repo,
                reviewer=ImageReviewAgent(llm=self._build_agent_llm()),
                transcode=ImageProcessor().process,
                # 参与去重键：换 model 等于换画风，历史资产不能继续命中缓存。
                generation_model=self.settings.media_image_gen_model,
                meter=MediaUsageRecorder(session_factory=self.session_factory),
                quota=MediaQuotaService(
                    session_factory=self.session_factory,
                    limits={MediaKind.IMAGE: self.settings.media_org_image_budget},
                ),
            )
        return self._scene_designer

    # ===== LLM 构建（含降级日志）=====

    def _build_provider_llm(self, fallback_log: str):
        """真实 provider LLM；无 key 或构建失败时落 warning 并返回 None。"""
        if not self.settings.llm_api_key:
            return None
        try:
            return ModelServiceFactory.build(self.settings.llm_model_config())
        except Exception as exc:
            logger.warning(
                fallback_log, extra={"wj_extra": {"reason": exc_reason(exc)}}
            )
            return None

    def _build_agent_llm(self):
        """运行期 agent LLM：真实 provider；构建失败或无 key 回落确定性 fake。"""
        llm = self._build_provider_llm("llm_factory_build_failed_fallback_fake")
        return llm if llm is not None else DeterministicAgentLLM()

    def _build_script_llm(self):
        """剧本生成 LLM：真实 provider；构建失败或无 key 返回 None（降级路径）。"""
        return self._build_provider_llm("script_llm_build_failed_fallback_degraded")


_container: Container | None = None


def get_container() -> Container:
    """进程级组合根单例。"""
    global _container
    if _container is None:
        _container = Container()
    return _container


def reset_container() -> None:
    """丢弃当前组合根（测试用）。"""
    global _container
    _container = None


__all__ = ["Container", "get_container", "reset_container"]
