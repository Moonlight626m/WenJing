"""进程级组合根：把配置与适配器组装到各接缝。

这是**唯一**的依赖装配点（原先散落在各 controller 的模块级单例）。lifespan 调用
`get_container().open()` 建立事件循环绑定资源（LangGraph checkpointer），请求期各
controller 经 `get_container()` 取已组装的用例/服务。

分层：本模块位于 controllers 之上、services/infrastructure 之下——只 import
services/domain/infrastructure，不 import controllers/main，故不破坏 `lint-arch`。
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.game.image_review import ImageReviewAgent
from app.domain.game.media import MediaKind, SceneDesigner
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.diagnostics.logging import exc_reason
from app.infrastructure.llm.factory import ModelServiceFactory
from app.infrastructure.llm.fake import DeterministicAgentLLM
from app.infrastructure.media import (
    ImageProcessor,
    MediaQuotaService,
    MediaUsageRecorder,
    SqlAssetRepository,
    build_image_gen,
    build_image_search,
    build_object_storage,
)
from app.infrastructure.rag.service import RagService, build_search_provider
from app.infrastructure.usage import UsageRecorder
from app.services.admin import AdminService
from app.services.assets import AssetAccessService
from app.services.auth import AuthService
from app.services.script_library import ScriptLibrary
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
        self._asset_access: AssetAccessService | None = None
        self._scene_designer: SceneDesigner | None = None

    # ===== 生命周期（lifespan 调用）=====

    async def open(self) -> None:
        """建立事件循环绑定资源（重复调用会先释放旧 pool）。失败降级不阻断启动。"""
        if self._checkpoint_pool is not None:
            await self._checkpoint_pool.close()
        self.checkpointer, self._checkpoint_pool = await self._open_checkpointer()
        # checkpointer 若在建库前已被访问过，丢弃缓存以纳入新 saver
        self._script_library = None

    async def close(self) -> None:
        if self._checkpoint_pool is not None:
            await self._checkpoint_pool.close()
        self._checkpoint_pool = None
        self.checkpointer = None
        # 关闭后再次访问需以无 checkpointer 重建，避免绑定已关闭的 saver
        self._script_library = None
        # 检索/生图端口各自持有自建 httpx 连接池；不关会在长跑进程与多轮 lifespan
        # 下持续泄漏 socket/fd（空实现无 close，走 hasattr 守卫）。置空以便重建。
        await self._aclose_port("_image_search")
        await self._aclose_port("_image_gen")
        # 编排器持有上面两个端口（可能已被关闭），一并丢弃以便按新端口重建。
        self._scene_designer = None

    async def _aclose_port(self, attr: str) -> None:
        port = getattr(self, attr, None)
        if port is not None and hasattr(port, "close"):
            await port.close()
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
    def session_application(self) -> SessionApplication:
        if self._session_application is None:
            self._session_application = SessionApplication(
                session_factory=self.session_factory,
                agent_llm=self._build_agent_llm(),
                usage_recorder=UsageRecorder(session_factory=self.session_factory),
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
    def asset_access(self) -> AssetAccessService:
        """资产访问服务（ADR-0005 §3 / #42）：鉴权 + 预签名 URL。"""
        if self._asset_access is None:
            self._asset_access = AssetAccessService(
                assets=SqlAssetRepository(session_factory=self.session_factory),
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
                assets=SqlAssetRepository(session_factory=self.session_factory),
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
