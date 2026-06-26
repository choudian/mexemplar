"""Recovery routines for Assistant task attempts."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    TaskStatus,
)
from src.business.task_collaboration.service import (
    emit_task_updated,
    increment_task_collaboration_counter,
)
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
)
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class TaskRecoveryService(AtomicTaskService):
    def __init__(
        self,
        attempt_repo: AssistantTaskAttemptRepository | None = None,
        task_repo: AssistantTaskRepository | None = None,
        adjudication_repo: AssistantTaskAdjudicationRepository | None = None,
        resume_callback: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._init_repos(
            attempts=(AssistantTaskAttemptRepository, attempt_repo),
            tasks=(AssistantTaskRepository, task_repo),
            adjudications=(AssistantTaskAdjudicationRepository, adjudication_repo),
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

    def _notify_scheduler_recovered(self, tasks: list) -> None:
        """024: fence 恢复后通知 GraphScheduler 重扫（FR-008）。

        已回到 pending_dispatch 的 task 由 scheduler 重扫后重派；带 checkpoint 且已被
        resume_callback 接管的 task 不再通知 scheduler，避免被无 checkpoint 的路径抢先派发。
        scheduler 未装配时跳过（优雅降级）。

        按 graph_id 去重：同图多 task 恢复只触发一次 on_executor_recovered（scheduler 的
        _advance 会扫全图就绪节点），避免冗余 service 创建和 snapshot 查询。

        I13: 逐图独立 try/except，单图通知失败不阻断其余图。
        """
        from src.business.task_collaboration.graph_scheduler import get_graph_scheduler

        scheduler = get_graph_scheduler()
        if scheduler is None:
            return
        seen_graphs: set[str] = set()
        for task in tasks:
            graph_id = getattr(task, "graph_id", None)
            if not graph_id or graph_id in seen_graphs:
                continue
            seen_graphs.add(graph_id)
            try:
                scheduler.on_executor_recovered(graph_id, getattr(task, "task_id", ""))
            except Exception:
                logger.warning(
                    "[recovery] scheduler on_executor_recovered failed for graph=%s",
                    graph_id,
                    exc_info=True,
                )

