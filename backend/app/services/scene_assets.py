"""运行期场景配图调度（ADR-0005 §5 / issue #56；持久台账与上限 #57）。

引擎（`GameRuntime`）只**发起意图**：新场景缺图时把 `{scene_key, description}`
放进 `StepResult.asset_requests`，自己不调用任何 provider。命令事务提交后，
`SessionApplication` 把意图补齐成 `SceneAssetRequest`（绑上 session/branch/org/script）
交给本模块派后台任务——**任务只捕获纯值，不持有 GameRuntime**：运行时的无状态
约定（#21 每次命令从 DB 重建）不能被后台任务拖回常驻内存，请求期绑定也让
「回溯后放弃的分支」能被 `report_asset_ready` 的 branch 校验挡住。

四条性质：

- **失败即占位**：`design_scene` 的 FAILED 与任何异常都不抛回游玩路径，只是这一场
  没有图（叙事照常跑、前端降级为渐变）。
- **不重复付费**：同一 `(session, scene_key)` 只发起一次，进程内集合 + `asset_jobs`
  唯一约束各管一半——只靠进程内集合的话，一重启就全忘了。
- **不阻塞命令**：`schedule()` 只创建任务就返回，命令响应不等生成。
- **可恢复**：每次尝试先在 `asset_jobs` 留一行 `pending`（#57），进程崩了也不至于
  「谁都不知道曾经有这么一次生成」。重启时 `recover()` 按 TTL 重排或判死。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.game.media import (
    AssetJob,
    AssetJobPort,
    AssetJobStatus,
    AssetKind,
    AssetRecord,
    AssetStatus,
    SceneAssetRequest,
    SceneDesigner,
)

logger = logging.getLogger("wenjing.session.scene_assets")

#: 就绪回调：把已落库的资产交给 Session 层（写事件 + 推 WS）。
OnReady = Callable[[SceneAssetRequest, AssetRecord], Awaitable[None]]

#: 崩溃后仍愿意重排的在途任务年龄上限（秒）。生成本身 10–40s，给足余量；
#: 再久就没人等着看了，重排等于为一张没人看的图付费。
DEFAULT_JOB_TTL_SECONDS = 900


def _brief(exc: BaseException, *, limit: int = 200) -> str:
    """异常 → 单行短日志（换行会污染结构化日志，长栈会淹没它）。"""
    return str(exc).replace("\n", " ")[:limit]


@dataclass(frozen=True)
class RecoveryReport:
    """一次启动重排的结果（日志与测试用）。"""

    requeued: int = 0
    expired: int = 0


class SceneAssetScheduler:
    """去重 + 派发运行期配图后台任务，并在 `asset_jobs` 上留台账。

    `designer` 是延迟求值的 callable（与 `ScriptLibrary` 的注入方式一致）：
    无媒体配置的环境里组合根仍会构建 `SceneDesigner`，其 provider 是安全空实现，
    失败会被降级成 FAILED 记录——不在这里判空，是为了让「降级」只有一条路径。

    `jobs` 是台账端口，**必传**：每会话生图上限与崩溃恢复都建在它上面，
    给它一个「忘了接线就静默失效」的默认值等于把这两条保障变成可选项。
    """

    def __init__(
        self,
        *,
        designer: Callable[[], SceneDesigner | None],
        jobs: AssetJobPort,
        max_images_per_session: int = 0,
        job_ttl_seconds: int = DEFAULT_JOB_TTL_SECONDS,
    ) -> None:
        self._designer = designer
        self._jobs = jobs
        #: <=0 表示不限额（与 `MediaQuotaService` 的语义一致）
        self._max_images_per_session = max_images_per_session
        self._job_ttl = timedelta(seconds=job_ttl_seconds)
        #: 在途任务：既作进程内去重闸，也作强引用（不持有引用的话 Task 可能被 GC 回收）
        self._inflight: dict[tuple[str, str], asyncio.Task[None]] = {}
        #: 已发起过的键（含失败）：跨命令存活，防重复付费。持久的那一半在 `asset_jobs`
        #: 的唯一约束上——这里只是为了不必为一次重复请求多跑一趟 DB。
        self._attempted: set[tuple[str, str]] = set()

    def schedule(self, request: SceneAssetRequest, *, on_ready: OnReady) -> bool:
        """派发一次后台生成；返回是否真的派了（False = 去重拦下）。

        同步方法、无 await 点：在命令事务提交后的同一次事件循环调度里完成登记，
        同一拍内不会出现两个任务抢同一个 scene_key。
        """
        key = self._key(request)
        if key in self._inflight or key in self._attempted:
            return False
        self._attempted.add(key)
        self._spawn(request, on_ready, job=None)
        return True

    async def recover(self, *, on_ready: OnReady) -> RecoveryReport:
        """启动重排（#57）：把上次进程崩溃时留在 `pending` 的任务收掉。

        - **TTL 之外**：判死。崩溃循环（起来就挂）会把同一个场景一次次重排、
          一次次付费，而那份产出多半没人看得到；判死留下原因，也让 `assets` 表
          里那行永远 `pending` 的票据有了解释。
        - **TTL 之内**：重新派发。进程刚刚重启，玩家很可能还等着这张图。
        """
        now = datetime.now(UTC)
        expired = await self._jobs.expire(before=now - self._job_ttl)
        requeued = 0
        for job in await self._jobs.pending(since=now - self._job_ttl):
            key = self._key(job.request)
            if key in self._inflight or key in self._attempted:
                continue
            self._attempted.add(key)
            self._spawn(job.request, on_ready, job=job)
            requeued += 1
        if requeued or expired:
            logger.warning(
                "scene_asset_jobs_recovered",
                extra={"requeued": requeued, "expired": expired},
            )
        return RecoveryReport(requeued=requeued, expired=expired)

    async def drain(self) -> None:
        """等待在途任务结束（优雅停机 / 测试用）。"""
        while self._inflight:
            await asyncio.gather(*list(self._inflight.values()), return_exceptions=True)

    # ===== 内部 =====

    @staticmethod
    def _key(request: SceneAssetRequest) -> tuple[str, str]:
        return (str(request.session_id), request.scene_key)

    def _spawn(
        self, request: SceneAssetRequest, on_ready: OnReady, *, job: AssetJob | None
    ) -> None:
        key = self._key(request)
        task = asyncio.create_task(self._run(request, on_ready, job=job))
        self._inflight[key] = task
        task.add_done_callback(lambda _t, k=key: self._inflight.pop(k, None))

    async def _run(
        self, request: SceneAssetRequest, on_ready: OnReady, *, job: AssetJob | None
    ) -> None:
        """后台任务主体：立账 → 生成 → 就绪则回调 → 收口。任何失败都只记日志。

        `job` 非空表示这是重排（台账行已存在，别再立一条）。
        """
        if job is None:
            job = await self._jobs.open(
                request, limit=self._max_images_per_session
            )
            if job is None:
                # 同一场景已发起过，或这个会话的生成张数已达上限：两种原因由台账
                # 实现各自记日志（`asset_job_deduped` / `asset_job_session_cap_reached`）。
                return
        designer = self._designer()
        if designer is None:
            await self._finish(
                job, AssetJobStatus.FAILED, reason="no designer configured"
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
            # 任务留在 pending：停机时由 `drain()` 先等它跑完，真被硬取消则留给
            # 下次启动的 `recover()` 收尾——绝不能留一条谁都不知道的记录。
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
            await self._finish(job, AssetJobStatus.FAILED, reason=_brief(exc))
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
            await self._finish(
                job,
                AssetJobStatus.FAILED,
                reason=record.reason or f"designer returned {record.status.value}",
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
        # 产出已是 READY 就算这次尝试成功：投递是否被采纳（分支已被回溯放弃、
        # 玩家不在线）是另一回事，图本身在缓存里，后续会话还能免费复用。
        await self._finish(job, AssetJobStatus.READY, asset_id=record.asset_id)

    async def _finish(
        self,
        job: AssetJob,
        status: AssetJobStatus,
        *,
        asset_id: uuid.UUID | None = None,
        reason: str = "",
    ) -> None:
        """收口台账。台账是诊断用的旁路，写不进去也绝不能把异常丢回事件循环。"""
        try:
            await self._jobs.finish(
                job.job_id, status=status, asset_id=asset_id, reason=reason
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "asset_job_finish_failed",
                extra={"job_id": str(job.job_id), "reason": _brief(exc)},
            )


__all__ = [
    "DEFAULT_JOB_TTL_SECONDS",
    "OnReady",
    "RecoveryReport",
    "SceneAssetScheduler",
]
