"""Bounded async dispatcher for Assistant task collaboration."""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from collections.abc import Iterator
from typing import Any, Callable

from src.business.agents import run_context
from src.business.task_collaboration.cutover import TaskCollaborationCutoverGuard
from src.business.task_collaboration.health import increment_task_collaboration_counter
from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    DeliveredStatus,
    OperationStatus,
    SuspendReason,
    TaskStatus,
    safe_preview,
)
from src.business.task_collaboration.run_control import (
    attempt_cancel_key,
    graph_cancel_key,
    task_cancel_key,
)
from src.business.task_collaboration.service import TaskCollaborationService
from src.business.task_collaboration.unit_of_work import task_session_scope
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskOperationRepository,
    AssistantTaskRepository,
)
from src.data.unified_config import get_unified_config
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

ExecutorCallback = Callable[[str], str | dict[str, Any] | None]
ParentReentryCallback = Callable[[dict[str, Any]], None]

_TASK_OUTCOME_SUSPENDED = "suspended"


class TaskDispatcher:
    def __init__(
        self,
        *,
        cutover_guard: TaskCollaborationCutoverGuard | None = None,
        executor_callback: ExecutorCallback | None = None,
        parent_reentry_callback: ParentReentryCallback | None = None,
    ) -> None:
        self._config = get_unified_config()
        self._cutover_guard = cutover_guard or TaskCollaborationCutoverGuard()
        self._executor_callback = executor_callback
        self._parent_reentry_callback = parent_reentry_callback
        # 写串行锁：start_attempt（建 attempt）与 _record_attempt_outcome（complete/裁定）
        # 在锁内串行，规避 SQLAlchemy Session 多线程并发写竞态；executor_callback（跑
        # LLM/子代理）在锁外并行——即"LLM 并行、写串行"（FR-003）。
        self._write_lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=self._config.get_assistant_tasks_dispatch_max_workers(),
            thread_name_prefix="AssistantTaskDispatcher",
        )

    def delegate_task(
        self,
        *,
        service: TaskCollaborationService,
        graph_id: str,
        session_id: str,
        parent_task_id: str,
        task: str,
        context: str = "",
        assignee_type: str | None = None,
        assignee_id: str | None = None,
        capability_scope: str | None = None,
    ) -> dict:
        self._cutover_guard.assert_can_dispatch()
        task_id = service.create_child_task(
            graph_id=graph_id,
            session_id=session_id,
            parent_task_id=parent_task_id,
            title=task,
            description=context or task,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            capability_scope=capability_scope,
        )
        assignment = "directed" if assignee_type and assignee_id else "board"
        return {"accepted": True, "taskId": task_id, "graphId": graph_id, "assignment": assignment}

    def start_attempt_async(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        lease_owner: str,
        checkpoint_ref: str | None = None,
    ) -> Future | None:
        lease_seconds = self._config.get_assistant_tasks_attempt_lease_seconds()
        # attempt 创建与任务置 running 必须同一事务：否则 attempt=running 而任务仍
        # pending_dispatch，恢复扫描与看板状态会不一致。写锁串行化建 attempt 写。
        with self._write_lock:
            with _worker_scope() as (attempts, service):
                attempt = attempts.start_attempt(
                    task_id=task_id,
                    executor_type=executor_type,
                    executor_id=executor_id,
                    lease_owner=lease_owner,
                    lease_expires_at=utc_now_naive() + timedelta(seconds=lease_seconds),
                    checkpoint_ref=checkpoint_ref,
                )
                if attempt is None:
                    return None
                attempt_id = attempt.attempt_id
                fence_token = attempt.fence_token
                if self._executor_callback is not None:
                    service.update_task_status(task_id=task_id, status=TaskStatus.RUNNING)
                increment_task_collaboration_counter("attempt_started")
        if self._executor_callback is None:
            return None
        return self._pool.submit(
            self._run_attempt_worker,
            attempt_id,
            fence_token,
        )

    def start_fallback_attempts(self, *, session_id: str | None = None) -> int:
        """Start attempts for stale open-board tasks claimed by fallback selection."""
        if self._executor_callback is None:
            return 0
        from src.business.task_collaboration.board import TaskBoardService

        started = 0
        with TaskBoardService() as board:
            task_ids = board.start_fallback_executors(session_id=session_id)
        for task_id in task_ids:
            future = self.start_attempt_async(
                task_id=task_id,
                executor_type="ephemeral_subagent",
                executor_id=task_id,
                lease_owner="fallback_dispatch",
            )
            if future is not None:
                started += 1
                increment_task_collaboration_counter("fallback_executor_started")
        return started

    def start_pending_graph_tasks(self, *, session_id: str, graph_id: str) -> int:
        """Start attempts for already-assigned pending tasks in a graph."""
        if self._executor_callback is None:
            return 0
        with AssistantTaskRepository() as tasks, AssistantTaskAttemptRepository() as attempts:
            rows = tasks.list_graph_tasks(graph_id)
            if not rows or any(task.session_id != session_id for task in rows):
                raise LookupError("task graph not found")
            candidates = [
                task
                for task in rows
                if task.status == TaskStatus.PENDING_DISPATCH
                and task.assignee_type
                and task.assignee_id
            ]
            resume_refs = {
                task.task_id: attempts.latest_resume_ref_for_task(task.task_id)
                for task in candidates
            }
        started = 0
        for task in candidates:
            executor_id = (
                task.assignee_id
                if task.assignee_type == "specialist" and task.assignee_id
                else task.task_id
            )
            future = self.start_attempt_async(
                task_id=task.task_id,
                executor_type=task.assignee_type,
                executor_id=executor_id,
                lease_owner="unified_continue",
                checkpoint_ref=resume_refs.get(task.task_id),
            )
            if future is not None:
                started += 1
        return started

    def _run_attempt_worker(self, attempt_id: str, fence_token: int) -> dict[str, Any]:
        # 整个 worker 体外层兜底：executor 之外（complete/fail/裁定等 DB 操作）的异常
        # 否则会被线程池 Future 静默吞掉，任务永远卡在 running 只能等 lease 过期。
        run_started = _begin_attempt_run_context(attempt_id)
        try:
            try:
                result = self._executor_callback(attempt_id) if self._executor_callback else None
            except Exception as exc:
                # executor 原始异常只进后端日志，不进安全投影（result_ref 只留异常类型名）。
                logger.exception("[task attempt] executor failed attempt=%s", attempt_id)
                with self._write_lock:
                    return self._record_attempt_outcome(
                        attempt_id=attempt_id,
                        fence_token=fence_token,
                        delivered_status=DeliveredStatus.STUCK,
                        safe_summary="任务执行时发生内部错误，需上级检查后决定是否重试。",
                        result_ref=type(exc).__name__,
                    )
            with self._write_lock:
                if _is_suspended_outcome(result):
                    return self._record_attempt_paused(
                        attempt_id=attempt_id,
                        fence_token=fence_token,
                        suspend_reason=_suspend_reason_from_result(result),
                        safe_summary=_safe_result_summary(result),
                        result_ref=_result_reference(result),
                        reentry_payload=_paused_reentry_payload(result),
                    )
                return self._record_attempt_outcome(
                    attempt_id=attempt_id,
                    fence_token=fence_token,
                    delivered_status=DeliveredStatus.DONE,
                    safe_summary=_safe_result_summary(result),
                    result_ref=_result_reference(result),
                )
        except Exception:
            logger.exception("[task attempt] worker crashed attempt=%s", attempt_id)
            raise
        finally:
            if run_started:
                run_context.end()

    def _record_attempt_outcome(
        self,
        *,
        attempt_id: str,
        fence_token: int,
        delivered_status: str,
        safe_summary: str,
        result_ref: str | None = None,
    ) -> dict[str, Any]:
        with _worker_scope() as (attempts, service):
            if delivered_status == DeliveredStatus.DONE:
                resolved = attempts.complete_if_current(
                    attempt_id=attempt_id,
                    fence_token=fence_token,
                    result_ref=result_ref,
                )
            else:
                resolved = attempts.fail_if_current(
                    attempt_id=attempt_id,
                    fence_token=fence_token,
                    error_category="internal",
                    result_ref=result_ref,
                )
            if resolved is None:
                increment_task_collaboration_counter("late_result_rejected")
                return {"accepted": False, "attemptId": attempt_id, "lateResult": True}
            # FR-005/FR-011：如果 Task 已进入终态（cancelled/completed/failed），
            # 迟到的结果必须被拒绝——不创建裁定、不改变 Task 状态、不产生副作用事件。
            task_id = resolved.task_id
            # 一次读取复用于终态判定与回流 payload：原先 get_task_status 与末尾 get_task
            # 命中同一主键两次；create_parent_adjudication 内部仍保留它自己的事务内读取。
            task_row = service.get_task(task_id)
            task_status = task_row.status if task_row else None
            if task_status is not None and task_status in TERMINAL_TASK_STATUSES:
                logger.warning(
                    "[task attempt] late %s rejected: task %s already %s, attempt %s",
                    delivered_status,
                    task_id,
                    task_status,
                    attempt_id,
                )
                increment_task_collaboration_counter("late_result_rejected")
                return {
                    "accepted": False,
                    "attemptId": attempt_id,
                    "lateResult": True,
                    "taskTerminal": task_status,
                }
            adjudication = service.create_parent_adjudication(
                task_id=task_id,
                delivered_status=delivered_status,
                safe_summary=safe_summary,
                raw_result_ref=result_ref,
            )
            # 回流 payload 带足续跑所需信息：父侧 runtime 据此 kick 续跑 worker，续跑首轮
            # drain 后直接用 deliveredStatus/safeSummary 组装回流摘要，无需再查 DB。
            payload = {
                "accepted": True,
                "attemptId": attempt_id,
                "taskId": task_id,
                "adjudicationId": getattr(adjudication, "adjudication_id", None),
                "deliveredStatus": delivered_status,
                "safeSummary": safe_summary,
                "sessionId": task_row.session_id if task_row else None,
                "graphId": task_row.graph_id if task_row else None,
            }
        self._notify_parent_reentry(payload)
        return payload

    def _record_attempt_paused(
        self,
        *,
        attempt_id: str,
        fence_token: int,
        suspend_reason: str,
        safe_summary: str,
        result_ref: str | None = None,
        reentry_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with _worker_scope() as (attempts, service):
            current_attempt = attempts.get_by_id(attempt_id)
            if current_attempt is None or current_attempt.fence_token != fence_token:
                increment_task_collaboration_counter("late_result_rejected")
                return {"accepted": False, "attemptId": attempt_id, "lateResult": True}
            task_row = service.get_task(current_attempt.task_id)
            if task_row is not None and task_row.status in TERMINAL_TASK_STATUSES:
                increment_task_collaboration_counter("late_result_rejected")
                return {
                    "accepted": False,
                    "attemptId": attempt_id,
                    "lateResult": True,
                    "taskTerminal": task_row.status,
                }
            resolved = attempts.pause_if_current(
                attempt_id=attempt_id,
                fence_token=fence_token,
                result_ref=result_ref,
            )
            if resolved is None:
                increment_task_collaboration_counter("late_result_rejected")
                return {"accepted": False, "attemptId": attempt_id, "lateResult": True}
            task = service.update_task_status(
                task_id=resolved.task_id,
                status=TaskStatus.SUSPENDED,
                suspend_reason=suspend_reason,
            )
            payload = {
                "accepted": True,
                "attemptId": attempt_id,
                "taskId": resolved.task_id,
                "taskStatus": TaskStatus.SUSPENDED,
                "suspendReason": suspend_reason,
                "safeSummary": safe_summary,
                "sessionId": task.session_id if task is not None else None,
                "graphId": task.graph_id if task is not None else None,
            }
            if reentry_payload is not None:
                payload.update(reentry_payload)
        if reentry_payload is not None:
            self._notify_parent_reentry(payload)
        return payload

    def _notify_parent_reentry(self, payload: dict[str, Any]) -> None:
        if self._parent_reentry_callback is None:
            return
        self._parent_reentry_callback(payload)

    def run_side_effect(
        self,
        *,
        task_id: str,
        attempt_id: str,
        operation_key: str,
        operation_type: str,
        safe_summary: str,
        execute: Callable[[], str | dict[str, Any] | None],
        idempotency_scope: str = "unknown",
    ) -> str | dict[str, Any] | None:
        with AssistantTaskOperationRepository() as operations:
            existing = operations.get_by_key(task_id, operation_key)
            if existing is not None and existing.status == OperationStatus.COMPLETED:
                return {"skipped": True, "resultRef": existing.result_ref}
            operation = operations.record_planned(
                task_id=task_id,
                attempt_id=attempt_id,
                operation_key=operation_key,
                operation_type=operation_type,
                safe_summary=safe_summary,
                idempotency_scope=idempotency_scope,
            )
            operations.update_status(operation.operation_id, OperationStatus.IN_PROGRESS)
            operation_id = operation.operation_id
        try:
            result = execute()
        except Exception:
            # 副作用执行失败必须把 operation 标 failed：get_by_key/唯一索引都排除 failed，
            # 否则它会永久卡在 in_progress，后续同 operation_key 重入直接撞唯一约束、无法重试。
            try:
                with AssistantTaskOperationRepository() as operations:
                    operations.update_status(operation_id, OperationStatus.FAILED)
            except Exception as mark_err:
                logger.error(
                    "[task side-effect] CRITICAL: failed to mark operation %s as failed: %s",
                    operation_id,
                    mark_err,
                    exc_info=True,
                )
            logger.exception(
                "[task side-effect] operation failed key=%s type=%s task=%s",
                operation_key,
                operation_type,
                task_id,
            )
            raise
        with AssistantTaskOperationRepository() as operations:
            operations.update_status(
                operation_id,
                OperationStatus.COMPLETED,
                result_ref=_result_reference(result),
            )
        return result

    def shutdown(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)


_MAX_RESULT_REF_CHARS = 4000


def _result_reference(result: str | dict[str, Any] | None) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        return result[:_MAX_RESULT_REF_CHARS]
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    return serialized[:_MAX_RESULT_REF_CHARS]


_RESULT_SUMMARY_KEYS = ("safe_summary", "message", "result_text")


def _safe_result_summary(result: str | dict[str, Any] | None) -> str:
    if result is None:
        return "任务已回传结果，等待上级检查。"
    if isinstance(result, str):
        return safe_preview(result)
    if isinstance(result, dict):
        for key in _RESULT_SUMMARY_KEYS:
            value = result.get(key)
            if isinstance(value, str):
                return safe_preview(value)
    return "任务已回传结构化结果，等待上级检查。"


def _is_suspended_outcome(result: str | dict[str, Any] | None) -> bool:
    return isinstance(result, dict) and result.get("task_outcome") == _TASK_OUTCOME_SUSPENDED


def _suspend_reason_from_result(result: str | dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return SuspendReason.WAITING_SYSTEM.value
    value = result.get("suspend_reason") or SuspendReason.WAITING_SYSTEM.value
    return SuspendReason(str(value)).value


def _paused_reentry_payload(result: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(result, dict) or result.get("reentry_type") != "task_question":
        return None
    return {
        "eventType": "task_question",
        "questionId": result.get("question_id"),
        "questionKind": result.get("question_kind"),
    }


def _begin_attempt_run_context(attempt_id: str) -> bool:
    try:
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.get_by_id(attempt_id)
        if attempt is None:
            return False
        with AssistantTaskRepository() as tasks:
            task = tasks.get_task(attempt.task_id)
        if task is None:
            return False
        run_context.begin(
            task.owner_session_id or task.session_id,
            cancel_keys=(
                graph_cancel_key(task.graph_id),
                task_cancel_key(task.task_id),
                attempt_cancel_key(attempt_id),
            ),
        )
        return True
    except Exception:
        logger.warning("[task attempt] failed to register run context: %s", attempt_id, exc_info=True)
        return False


@contextmanager
def _worker_scope() -> Iterator[tuple[AssistantTaskAttemptRepository, TaskCollaborationService]]:
    # 三个 Repository 共享一个 session，让 attempt 收尾（complete/fail）+ 建父侧裁定、或
    # start_attempt + 任务置 running 落在同一事务里；事务生命周期复用 task_session_scope。
    with task_session_scope() as session:
        attempts = AssistantTaskAttemptRepository(session)
        tasks = AssistantTaskRepository(session)
        adjudications = AssistantTaskAdjudicationRepository(session)
        yield attempts, TaskCollaborationService(
            task_repo=tasks,
            adjudication_repo=adjudications,
        )
