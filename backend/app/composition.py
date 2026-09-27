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

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.diagnostics.logging import exc_reason
from app.infrastructure.llm.factory import ModelServiceFactory
from app.infrastructure.llm.fake import DeterministicAgentLLM
from app.infrastructure.rag.service import RagService, build_search_provider
from app.infrastructure.usage import UsageRecorder
from app.services.admin import AdminService
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
