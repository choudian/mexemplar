"""Recovery routines for Assistant task attempts."""

from __future__ import annotations

import logging

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
    ) -> None:
        self._init_repos(
            attempts=(AssistantTaskAttemptRepository, attempt_repo),
            tasks=(AssistantTaskRepository, task_repo),
            adjudications=(AssistantTaskAdjudicationRepository, adjudication_repo),
            claims=(AssistantTaskClaimRepository, claim_repo),
            operations=(AssistantTaskOperationRepository, operation_repo),
            sessions=(SessionRepository, session_repo),
        )

    def mark_interrupted_after_restart(self) -> int:
        """sidecar 重启后：把上一代进程遗留的假状态一次性对齐（状态对齐半，⑤）。

        判据是进程级全局事实——重启 = 上一代进程的所有执行体线程物理全死，不需要逐条
        PID 校验（普通 attempt 执行体是进程内线程，``dispatcher.py`` 的 ThreadPoolExecutor）。
        租约超时扫描废除后，这里是遗留 running attempt 的**唯一**回收路径，必须在
        ``TaskCollaborationBackgroundWorker.start()`` **之前**同步跑完（启动栅栏）。

        四摊一次性清：
        ① 任务执行：遗留 running attempt → fenced（复用原子 ``fence``），task → SUSPENDED+INTERRUPTED。
        ② 会话状态：所有 active session → suspended（含主助理根会话，不依赖 attempt 绑定）。
        ③ 看板认领：所有 claimed → expired（释放 partial unique index）。
        ④ 副作用：所有 in_progress operation → failed（释放唯一约束，允许重试）。

        落 SUSPENDED 而非 PENDING_DISPATCH：后者会被 scheduler 立即重派——断电后用户
        得自己拍板要不要继续，不能自动烧 token。

        返回处理过的 attempt 条数（摊①）。幂等：终态行被各 repo 的状态守卫跳过。
        逐条 try/except 隔离——单条失败不阻断其余。
        """
        count = 0
        updated_tasks: list = []
        interrupted_graph_ids: set[str] = set()

        # 摊①：遗留 active attempt → fenced + task → SUSPENDED+INTERRUPTED。
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
                        if task.graph_id:
                            interrupted_graph_ids.add(task.graph_id)
            except Exception:
                logger.exception(
                    "[recovery] mark interrupted attempt %s failed; skipping",
                    attempt.attempt_id,
                )
                continue

        # 摊①b：图控制状态对齐——节点已被打断全停，图还遗留 running 是假状态，
        # 会让 mutate 校验误拒（"运行中先停止"）并误导展示。running → stopped；
        # 用户点继续时 atomic continue 会翻回 running。启动栅栏期间无并发，先查后写安全。
        for graph_id in interrupted_graph_ids:
            try:
                if self._tasks.get_graph_control_status(graph_id) == "running":
                    self._tasks.set_graph_control_status(graph_id, "stopped")
            except Exception:
                logger.warning(
                    "[recovery] align graph control status failed for %s", graph_id,
                    exc_info=True,
                )

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

