"""Recovery routines for Assistant task attempts."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    ClaimStatus,
    OperationStatus,
    SuspendReason,
    TaskStatus,
    WaitingOn,
    waiting_on_for_reason,
)
from src.business.task_collaboration.service import (
    emit_task_updated,
    increment_task_collaboration_counter,
)
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskClaimRepository,
    AssistantTaskOperationRepository,
    AssistantTaskRepository,
    SessionRepository,
)
from src.utils.events import emit
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class TaskRecoveryService(AtomicTaskService):
    def __init__(
        self,
        attempt_repo: AssistantTaskAttemptRepository | None = None,
        task_repo: AssistantTaskRepository | None = None,
        adjudication_repo: AssistantTaskAdjudicationRepository | None = None,
        claim_repo: AssistantTaskClaimRepository | None = None,
        operation_repo: AssistantTaskOperationRepository | None = None,
        session_repo: SessionRepository | None = None,
        resume_callback: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._init_repos(
            attempts=(AssistantTaskAttemptRepository, attempt_repo),
            tasks=(AssistantTaskRepository, task_repo),
            adjudications=(AssistantTaskAdjudicationRepository, adjudication_repo),
            claims=(AssistantTaskClaimRepository, claim_repo),
            operations=(AssistantTaskOperationRepository, operation_repo),
            sessions=(SessionRepository, session_repo),
        )
        self._resume_callback = resume_callback

    def fence_expired_attempts(self, now: datetime | None = None) -> int:
        current = now or utc_now_naive()
        count = 0
        updated_tasks: list = []
        scheduler_tasks: list = []
        resume_requests: list[tuple[str, str]] = []
        for attempt in self._attempts.scan_expired_active(current):
            # 单个 attempt 的恢复（fence + 任务回到可派发）必须同一事务：fence 成功但
            # 任务仍 running 会让下一轮恢复扫描抓不到它。
            # 单点失败（如终态 task 的 transition 校验、竞态下 attempt 已终态）用
            # try/except 隔离，不得中止整个循环让后续 attempt 永久漏处理。
            try:
                with self._atomic():
                    fenced = self._attempts.fence(attempt.attempt_id)
                    if fenced is None:
                        # attempt 已终态/已围栏/不存在（多见于 worker 完成的竞态）：
                        # 不再把 task 翻 suspended 或建裁定，整段跳过。
                        continue
                    increment_task_collaboration_counter("attempt_fenced")
                    current_task = self._tasks.get_task(attempt.task_id)
                    if current_task is not None and current_task.status in TERMINAL_TASK_STATUSES:
                        # task 已达终态（被 cancel/stop 等）：只 fence attempt 清 lease，
                        # 不转 pending 也不建裁定——终态 task 不应被恢复翻回可派发。
                        continue
                    task = self._tasks.update_status(
                        attempt.task_id,
                        status=TaskStatus.PENDING_DISPATCH,
                    )
                    if task is not None:
                        updated_tasks.append(task)
                        if attempt.checkpoint_ref and self._resume_callback is not None:
                            resume_requests.append((task.task_id, attempt.checkpoint_ref))
                        else:
                            scheduler_tasks.append(task)
                count += 1
            except Exception:
                logger.exception(
                    "[recovery] fence attempt %s failed; skipping rest of this attempt",
                    attempt.attempt_id,
                )
                continue
        for task in updated_tasks:
            emit_task_updated(self, task)
        for task_id, checkpoint_ref in resume_requests:
            try:
                if self._resume_callback is not None and self._resume_callback(
                    task_id, checkpoint_ref
                ):
                    continue
            except Exception:
                logger.exception("[recovery] checkpoint resume callback failed for %s", task_id)
            task = self._tasks.get_task(task_id)
            if task is not None and task.status not in TERMINAL_TASK_STATUSES:
                scheduler_tasks.append(task)
        # 024: 通知 scheduler executor 已恢复，重扫受影响 graph（FR-008 装配）。
        self._notify_scheduler_recovered(scheduler_tasks)
        return count

    def mark_interrupted_after_restart(self) -> int:
        """sidecar 重启后：把上一代进程遗留的假状态一次性对齐（状态对齐半，⑤）。

        判据是进程级全局事实——重启 = 上一代进程的所有执行体线程物理全死，不需要逐条
        PID 校验（普通 attempt 执行体是进程内线程，``dispatcher.py`` 的 ThreadPoolExecutor）。
        必须在 ``TaskCollaborationBackgroundWorker.start()`` **之前**同步跑完（启动栅栏），
        否则 worker 第一 tick 的 fence 会撞到死 attempt 盲目重派。

        四摊一次性清：
        ① 任务执行：遗留 running attempt → fenced（复用原子 ``fence``），task → SUSPENDED+INTERRUPTED。
        ② 会话状态：所有 active session → suspended（含主助理根会话，不依赖 attempt 绑定）。
        ③ 看板认领：所有 claimed → expired（释放 partial unique index）。
        ④ 副作用：所有 in_progress operation → failed（释放唯一约束，允许重试）。

        返回处理过的 attempt 条数（摊①）。幂等：终态行被各 repo 的状态守卫跳过。
        逐条 try/except 隔离——单条失败不阻断其余（照 ``fence_expired_attempts`` 的结构）。
        """
        count = 0
        updated_tasks: list = []

        # 摊①：遗留 active attempt → fenced + task → SUSPENDED+INTERRUPTED。
        # 与 fence_expired_attempts 的关键区别：落 SUSPENDED 等用户点继续，而非 PENDING_DISPATCH
        # （后者会被 scheduler 立即重派——断电后用户得自己拍板要不要继续，不能自动烧 token）。
        for attempt in self._attempts.scan_all_active():
            try:
                with self._atomic():
                    fenced = self._attempts.fence(attempt.attempt_id)
                    if fenced is None:
                        continue  # 竞态下已终态，跳过
                    increment_task_collaboration_counter("attempt_interrupted_restart")
                    count += 1  # attempt 已处理（fenced 成功），无论 task 是否也转 suspended
                    current_task = self._tasks.get_task(attempt.task_id)
                    if current_task is None or current_task.status in TERMINAL_TASK_STATUSES:
                        continue  # task 已终态/不存在，只 fence attempt
                    task = self._tasks.update_status(
                        attempt.task_id,
                        status=TaskStatus.SUSPENDED,
                        suspend_reason=SuspendReason.INTERRUPTED.value,
                        waiting_on=waiting_on_for_reason(SuspendReason.INTERRUPTED).value,
                    )
                    if task is not None:
                        updated_tasks.append(task)
            except Exception:
                logger.exception(
                    "[recovery] mark interrupted attempt %s failed; skipping",
                    attempt.attempt_id,
                )
                continue

        # 摊②：所有 active session → suspended。
        # 不依赖 attempt 绑定——主助理根会话不挂在任何 attempt 上，按绑定清会漏掉它。
        # 重启后无执行体活着，所有 active 一律是假；用户下次发消息时 AgentLoop 会复活。
        try:
            with self._atomic():
                cleared = self._sessions.clear_all_active()
            if cleared:
                logger.info(
                    "[recovery] cleared %d active sessions after restart", cleared
                )
        except Exception:
            logger.warning("[recovery] clear active sessions failed", exc_info=True)

        # 摊③：所有 claimed → expired。
        # claim 状态更新与 assignee 解除分两个 _atomic：``unassign_if_assignee`` 在
        # 找不到匹配 assignee 时调 ``_abort_conflict``（回滚整个工作单元），若合在一个
        # _atomic 里会把已写的 claim 更新也回滚。断电后 claim 的 assignee 可能本就为空
        # （认领了但任务 assignee 字段没同步），不应因此丢掉 claim 状态更新。
        for claim in self._claims.scan_all_active_claims():
            try:
                with self._atomic():
                    if self._claims.update_status(claim.claim_id, ClaimStatus.EXPIRED) is None:
                        continue
                # assignee 解除 best-effort：失败只留残余 assignee（不影响 claim 释放）
                with self._atomic():
                    self._tasks.unassign_if_assignee(
                        claim.task_id,
                        assignee_type=claim.claimer_type,
                        assignee_id=claim.claimer_id,
                    )
            except Exception:
                logger.warning(
                    "[recovery] expire claimed task %s after restart failed",
                    claim.task_id,
                    exc_info=True,
                )
                continue

        # 摊④：所有 in_progress operation → failed（与 dispatcher.run_side_effect 的异常路径一致）。
        for operation in self._operations.scan_in_progress():
            try:
                with self._atomic():
                    self._operations.update_status(operation.operation_id, OperationStatus.FAILED)
            except Exception:
                logger.warning(
                    "[recovery] fail in-progress operation %s after restart failed",
                    operation.operation_id,
                    exc_info=True,
                )
                continue

        # 摊①的 task 变更统一 emit（循环内 emit=False 避免重复/乱序）。
        for task in updated_tasks:
            emit_task_updated(self, task)
        return count

    def _notify_scheduler_recovered(self, tasks: list) -> None:
        """024: fence 恢复后通知 GraphScheduler 重扫（FR-008）。

        已回到 pending_dispatch 的 task 由 scheduler 重扫后重派；带 checkpoint 且已被
        resume_callback 接管的 task 不再通知 scheduler，避免被无 checkpoint 的路径抢先派发。
        scheduler 未装配时跳过（优雅降级）。

        按 graph_id 去重：同图多 task 恢复只触发一次 on_executor_recovered（scheduler 的
        _advance 会扫全图就绪节点），避免冗余 service 创建和 snapshot 查询。

        I13: 逐图独立 try/except，单图通知失败不阻断其余图。

        事件驱动：通过 blinker 事件 ``graph_scheduler_recovery_completed`` 解耦
        recovery 与 scheduler 单例，调用方不再直接 import get_graph_scheduler。
        """
        seen_graphs: set[str] = set()
        for task in tasks:
            graph_id = getattr(task, "graph_id", None)
            if not graph_id or graph_id in seen_graphs:
                continue
            seen_graphs.add(graph_id)
            try:
                emit(
                    "graph_scheduler_recovery_completed",
                    sender=self,
                    graph_id=graph_id,
                    task_id=getattr(task, "task_id", ""),
                )
            except Exception:
                logger.warning(
                    "[recovery] graph_scheduler_recovery_completed emit failed for graph=%s",
                    graph_id,
                    exc_info=True,
                )
