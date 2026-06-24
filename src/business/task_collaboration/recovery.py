"""Recovery routines for Assistant task attempts."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from src.business.task_collaboration.models import (
    SuspendReason,
    TERMINAL_TASK_STATUSES,
    TaskStatus,
    validate_task_transition,
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
        resumable: list[tuple[str, str]] = []
        for attempt in self._attempts.scan_expired_active(current):
            # 单个 attempt 的恢复（fence + 任务挂起 + 建裁定）必须同一事务：fence 成功但
            # 挂起失败会让 attempt=fenced 而任务仍 running，下一轮恢复扫描也抓不到它。
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
                    if (
                        current_task is not None
                        and current_task.status in TERMINAL_TASK_STATUSES
                    ):
                        # task 已达终态（被 cancel/stop 等）：只 fence attempt 清 lease，
                        # 不转 suspended 也不建裁定——终态 task 不应被恢复翻成 suspended。
                        continue
                    if current_task is not None:
                        validate_task_transition(
                            current_task.status,
                            TaskStatus.SUSPENDED,
                            suspend_reason=SuspendReason.WAITING_SYSTEM,
                        )
                    task = self._tasks.update_status(
                        attempt.task_id,
                        status=TaskStatus.SUSPENDED,
                        suspend_reason=SuspendReason.WAITING_SYSTEM,
                    )
                    if task is not None:
                        updated_tasks.append(task)
                        if attempt.checkpoint_ref:
                            resumable.append((task.task_id, attempt.checkpoint_ref))
                        else:
                            existing = self._adjudications.get_pending_for_task(task.task_id)
                            if existing is None:
                                self._adjudications.create_pending(
                                    task_id=task.task_id,
                                    graph_id=task.graph_id,
                                    parent_session_id=task.owner_session_id or task.session_id,
                                    delivered_status="stuck",
                                    safe_summary="任务在恢复时需要上级检查后继续。",
                                )
                count += 1
            except Exception:
                logger.exception(
                    "[recovery] fence attempt %s failed; skipping rest of this attempt",
                    attempt.attempt_id,
                )
                continue
        for task in updated_tasks:
            emit_task_updated(self, task)
        for task_id, checkpoint_ref in resumable:
            if self._resume_callback is None:
                self._create_resume_failed_adjudication(task_id)
                continue
            try:
                if not self._resume_callback(task_id, checkpoint_ref):
                    self._create_resume_failed_adjudication(task_id)
            except Exception:
                logger.exception("[recovery] checkpoint resume callback failed for %s", task_id)
                self._create_resume_failed_adjudication(task_id)
        return count

    def _create_resume_failed_adjudication(self, task_id: str) -> None:
        try:
            task = self._tasks.get_task(task_id)
            if task is None:
                return
            existing = self._adjudications.get_pending_for_task(task.task_id)
            if existing is not None:
                return
            with self._atomic():
                self._adjudications.create_pending(
                    task_id=task.task_id,
                    graph_id=task.graph_id,
                    parent_session_id=task.owner_session_id or task.session_id,
                    delivered_status="stuck",
                    safe_summary="任务有检查点但未能自动恢复，等待上级检查后继续。",
                )
        except Exception:
            logger.exception("[recovery] failed to create resume-failed adjudication for %s", task_id)
