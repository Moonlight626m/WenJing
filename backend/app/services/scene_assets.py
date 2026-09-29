"""运行期场景配图调度（ADR-0005 §5 / issue #56）。

引擎（`GameRuntime`）只**发起意图**：新场景缺图时把 `{scene_key, description}`
放进 `StepResult.asset_requests`，自己不调用任何 provider。命令事务提交后，
`SessionApplication` 把意图补齐成 `SceneAssetRequest`（绑上 session/branch/org/script）
交给本模块派后台任务——**任务只捕获纯值，不持有 GameRuntime**：运行时的无状态
约定（#21 每次命令从 DB 重建）不能被后台任务拖回常驻内存，请求期绑定也让
「回溯后放弃的分支」能被 `report_asset_ready` 的 branch 校验挡住。

三条性质：

- **失败即占位**：`design_scene` 的 FAILED 与任何异常都不抛回游玩路径，只是这一场
  没有图（叙事照常跑、前端降级为渐变）。
- **不重复付费**：同一 `(session, scene_key)` 在途或**已失败**都不再发起。已失败也
  拦，是因为 `SceneDesigner` 的去重键只命中 `READY` 资产——不拦的话每次命令都会
  为一个注定失败的场景再付一次生成费。
- **不阻塞命令**：`schedule()` 只创建任务就返回，命令响应不等生成。

每会话生图上限、安全过滤、崩溃恢复（`asset_jobs` 表）与跨会话缓存是 #57。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.domain.game.media import (
    AssetKind,
    AssetRecord,
    AssetStatus,
    SceneDesigner,
)

logger = logging.getLogger("wenjing.session.scene_assets")

#: 就绪回调：把已落库的资产交给 Session 层（写事件 + 推 WS）。
OnReady = Callable[["SceneAssetRequest", AssetRecord], Awaitable[None]]


def _brief(exc: BaseException, *, limit: int = 200) -> str:
    """异常 → 单行短日志（换行会污染结构化日志，长栈会淹没它）。"""
    return str(exc).replace("\n", " ")[:limit]


@dataclass(frozen=True)
class SceneAssetRequest:
    """一次运行期配图请求：请求期绑定的全部上下文（后台任务只拿到它）。"""

    session_id: uuid.UUID
    #: 请求发起时的活动分支；落库前据此校验分支是否已被回溯放弃。
    branch_id: uuid.UUID
    scene_key: str
    description: str
    org_id: uuid.UUID
    script_id: int | None = None
    user_id: uuid.UUID | None = None


class SceneAssetScheduler:
    """去重 + 派发运行期配图后台任务。

    `designer` 是延迟求值的 callable（与 `ScriptLibrary` 的注入方式一致）：
    无媒体配置的环境里组合根仍会构建 `SceneDesigner`，其 provider 是安全空实现，
    失败会被降级成 FAILED 记录——不在这里判空，是为了让「降级」只有一条路径。
    """

    def __init__(self, *, designer: Callable[[], SceneDesigner | None]) -> None:
        self._designer = designer
        #: 在途任务：既作去重闸，也作强引用（不持有引用的话 Task 可能被 GC 回收）
        self._inflight: dict[tuple[str, str], asyncio.Task[None]] = {}
        #: 已发起过的键（含失败）：跨命令存活，防重复付费
        self._attempted: set[tuple[str, str]] = set()

    def schedule(self, request: SceneAssetRequest, *, on_ready: OnReady) -> bool:
        """派发一次后台生成；返回是否真的派了（False = 去重拦下）。

        同步方法、无 await 点：在命令事务提交后的同一次事件循环调度里完成登记，
        同一拍内不会出现两个任务抢同一个 scene_key。
        """
        key = (str(request.session_id), request.scene_key)
        if key in self._inflight or key in self._attempted:
            return False
        self._attempted.add(key)
        task = asyncio.create_task(self._run(request, on_ready))
        self._inflight[key] = task
        task.add_done_callback(lambda _t, k=key: self._inflight.pop(k, None))
        return True

    async def drain(self) -> None:
        """等待在途任务结束（优雅停机 / 测试用）。"""
        while self._inflight:
            await asyncio.gather(*list(self._inflight.values()), return_exceptions=True)

    async def _run(self, request: SceneAssetRequest, on_ready: OnReady) -> None:
        """后台任务主体：生成 → 就绪则回调。任何失败都只记日志。"""
        designer = self._designer()
        if designer is None:
            logger.info(
                "scene_asset_skipped",
                extra={"session_id": str(request.session_id), "reason": "no designer"},
            )
            return
        try:
            record = await designer.design_scene(
                org_id=request.org_id,
                subject_key=request.scene_key,
                scene_key=request.scene_key,
                description=request.description,
                kind=AssetKind.BACKGROUND,
                script_id=request.script_id,
                session_id=request.session_id,
                user_id=request.user_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 配图失败不得打断游玩
            logger.warning(
                "scene_asset_design_error",
                extra={
                    "session_id": str(request.session_id),
                    "scene_key": request.scene_key,
                    "reason": _brief(exc),
                },
            )
            return

        if record.status is not AssetStatus.READY:
            # 失败/未就绪 → 保持占位（纯文本/渐变），不写事件、不推送
            logger.warning(
                "scene_asset_not_ready",
                extra={
                    "session_id": str(request.session_id),
                    "scene_key": request.scene_key,
                    "status": record.status.value,
                },
            )
            return

        try:
            await on_ready(request, record)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 落库/推送失败同样不打断游玩
            logger.warning(
                "scene_asset_report_error",
                extra={
                    "session_id": str(request.session_id),
                    "scene_key": request.scene_key,
                    "reason": _brief(exc),
                },
            )


__all__ = ["OnReady", "SceneAssetRequest", "SceneAssetScheduler"]
