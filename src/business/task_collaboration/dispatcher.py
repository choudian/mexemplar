"""Bounded async dispatcher for Assistant task collaboration."""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from collections.abc import Iterator
from typing import Any, Callable

from src.business.agents import run_context
from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    DeliveredStatus,
    OperationStatus,
    SuspendReason,
    TaskStatus,
    WaitingOn,
    safe_preview,
    waiting_on_for_reason,
)
from src.business.task_collaboration.service import (
    TaskCollaborationService,
    increment_task_collaboration_counter,
)
from src.business.task_collaboration.unit_of_work import task_session_scope
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskOperationRepository,
    AssistantTaskRepository,
)
from src.data.repos.workflow_transition_repository import WorkflowTransitionRepository
from src.data.unified_config import get_unified_config

from .attempt_heartbeat import AttemptHeartbeat
from src.utils.helpers import positive_int
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

ExecutorCallback = Callable[[str], str | dict[str, Any] | None]
ParentReentryCallback = Callable[[dict[str, Any]], None]

_TASK_OUTCOME_SUSPENDED = "suspended"

# 租约时长的下界与兜底值，与 unified_config 的 minimum / default 一致。
_MIN_SANE_LEASE_SECONDS = 10
_DEFAULT_LEASE_SECONDS = 120

# 024: 失败自愈动作候选集（确定性，按失败类；FR-010）。advisory——主助理仍可自由裁定，
# 这里只提供"下一步建议"避免开放自由发挥（FR-015）。display_hint 供 briefing 渲染。
# action_name 与 decide/mutate 工具调用语义对齐，是唯一的自愈动作来源。
_HEALING_ACTION_HINTS: dict[str, str] = {
    "retry": '重试该节点 → decide(decision="returned")',
    "swap_executor": '换执行器重试 → 改 assignee 后 decide(decision="returned")',
    "adjust_input": '调整输入后重做 → decide(decision="returned", instruction="…")',
    "skip": "跳过该节点 → mutate_task_graph(skip_node)（若可容忍，下游继续）",
    "replan": "改图绕过 → mutate_task_graph(add_node/remove_dependency)",
    "abandon": '放弃该分支 → decide(decision="abandoned")',
}

_HEALING_ACTIONS_BY_STATUS: dict[str, list[str]] = {
    "stuck": ["retry", "adjust_input", "swap_executor", "skip", "replan"],
    "failed_input": ["adjust_input", "retry", "swap_executor", "skip", "replan"],
}
_DEFAULT_HEALING_ACTIONS: list[str] = [
    "retry",
    "swap_executor",
    "adjust_input",
    "replan",
    "skip",
]
_SAFE_RECOVERY_HINT = (
    "节点执行失败。可先尝试重试、调整输入或更换执行器；若反复失败可改图（增删节点/依赖）"
    "或跳过该节点；确实无法推进时再升级用户。"
)


def _healing_actions_for(delivered_status: str) -> list[str]:
    """024: 按失败类返回确定性自愈动作候选集（advisory，FR-010）。"""
    return list(_HEALING_ACTIONS_BY_STATUS.get(delivered_status, _DEFAULT_HEALING_ACTIONS))


# TaskCollaborationCutoverGuard 已删除：主助理串行保证了简单委派和统一调度不会并发，
# guard 的历史 transition 查询（只看 started 不看 completed）反而误拦已完成的委派，
# 导致统一调度回退 sync + 留下孤儿 root task。原 023 CC-005 设计意图（防双写）
# 由主助理串行保证；unified_dispatch_enabled 开关保留作为统一调度总开关。


def graph_cancel_key(graph_id: str) -> str:
    return f"assistant_task_graph:{graph_id}"


def task_cancel_key(task_id: str) -> str:
    return f"assistant_task:{task_id}"


def attempt_cancel_key(attempt_id: str) -> str:
    return f"assistant_task_attempt:{attempt_id}"


class TaskDispatcher:
    def __init__(
        self,
        *,
        cutover_guard=None,  # legacy: cutover guard 已删，参数保留兼容现有测试
        executor_callback: ExecutorCallback | None = None,
        parent_reentry_callback: ParentReentryCallback | None = None,
        scheduler_callback: Callable | None = None,
    ) -> None:
        self._config = get_unified_config()
        self._cutover_guard = cutover_guard  # legacy: guard 已删，保留兼容测试注入
        self._executor_callback = executor_callback
        self._parent_reentry_callback = parent_reentry_callback
        # 024: GraphScheduler.on_attempt_outcome 回调（松耦合，避免循环依赖）
        self._scheduler_callback = scheduler_callback
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
                # 024 C5: 派发层就绪硬校验兜底（FR-003），独立于 GraphScheduler 装配状态。
                # 无 dependency 的 task（simple delegation / root 容器）直接通过；有
                # dependency 的 task 前置必须全 completed，否则跳过派发——防止任何路径绕过
                # scheduler 乱序派发未就绪节点。未就绪时 return None（不抛错），保护
                # fallback / continue 等批量调用方。
                task_row = service.get_task(task_id)
                if task_row is not None and task_row.graph_id:
                    try:
                        service.assert_dependencies_satisfied(task_row.graph_id, task_id)
                    except ValueError:
                        logger.warning(
                            "[dispatch] task %s dependencies not satisfied; skip attempt",
                            task_id,
                        )
                        return None
                    if (
                        task_row.requires_confirmation
                        and task_row.status == TaskStatus.PENDING_DISPATCH
                        and not service.has_accepted_confirmation(task_id)
                    ):
                        logger.warning(
                            "[dispatch] task %s requires confirmation but has no accepted adjudication; skip attempt",
                            task_id,
                        )
                        return None
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
                # 执行期间持续续租：租约只在创建时写死，不续约的话执行体跑得比
                # 租约长就会被恢复扫描判死重派，而它还活着——重派只是又起一个。
                # 心跳随 executor 返回或抛出立即停止：租约活得比执行体久，正是
                # 恢复机制要抓的那种情况。
                with _lease_heartbeat(attempt_id):
                    result = (
                        self._executor_callback(attempt_id) if self._executor_callback else None
                    )
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
                        result_ref=_result_reference_with_truncation(result)[0],
                        pause_result=result,
                    )
                result_ref, result_ref_truncated = _result_reference_with_truncation(result)
                return self._record_attempt_outcome(
                    attempt_id=attempt_id,
                    fence_token=fence_token,
                    delivered_status=DeliveredStatus.DONE,
                    safe_summary=_safe_result_summary(result),
                    result_ref=result_ref,
                    result_ref_truncated=result_ref_truncated,
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
        result_ref_truncated: bool = False,
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
                "adjudicationId": adjudication.adjudication_id if adjudication else None,
                "deliveredStatus": delivered_status,
                "safeSummary": safe_summary,
                "sessionId": task_row.session_id if task_row else None,
                "graphId": task_row.graph_id if task_row else None,
            }
            if delivered_status == DeliveredStatus.DONE and result_ref:
                payload["deliverablePreview"] = result_ref
                payload["deliverableTruncated"] = bool(result_ref_truncated)
                if adjudication is not None:
                    payload["resultReferenceId"] = adjudication.adjudication_id
            # 024: 失败附自愈动作清单 + 安全恢复提示（FR-010/FR-015），供 briefing 渲染。
            # safeRecoveryHint 是固定安全文案，不携带 provider 原始错误（constitution III）。
            if delivered_status != DeliveredStatus.DONE:
                payload["healingActions"] = _healing_actions_for(delivered_status)
                payload["safeRecoveryHint"] = _SAFE_RECOVERY_HINT
        self._notify_parent_reentry(payload)

        # 024: 通知 GraphScheduler 节点 attempt 完成
        self._notify_scheduler_attempt_outcome(payload)

        return payload

    def _record_attempt_paused(
        self,
        *,
        attempt_id: str,
        fence_token: int,
        suspend_reason: str,
        safe_summary: str,
        result_ref: str | None = None,
        pause_result: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """落库之后才决定通知谁——读的就是刚写进库的 ``waiting_on``。

        顺序不能反：先发通知后落库会留下一个说谎窗口（主助理被叫醒去查这个活，
        库里还写着"正在跑"）。而通知对象若来自另一套独立判断，两边迟早对不上
        ——这正是撞预算暂停从不回流的成因。
        """
        with _worker_scope() as (attempts, service):
            current_attempt = attempts.get_by_id(attempt_id)
            if current_attempt is None or current_attempt.fence_token != fence_token:
                increment_task_collaboration_counter("late_result_rejected")
                return {"accepted": False, "attemptId": attempt_id, "lateResult": True}
            task_row = service.get_task(current_attempt.task_id)
            if task_row is None:
                # attempt 指向的 task 不存在（数据不一致）。必须在把 attempt 翻 paused
                # 之前中止：继续往下走的话，attempt 落了 paused 而 task 无从更新，
                # 通知里的 sessionId / graphId 也全是空的——而回流正是按 sessionId
                # 分队列投递的。早失败，不留半截状态。
                logger.error(
                    "[task reentry] attempt=%s 指向的 task=%s 不存在，暂停收尾中止",
                    attempt_id,
                    current_attempt.task_id,
                )
                return {
                    "accepted": False,
                    "attemptId": attempt_id,
                    "taskId": current_attempt.task_id,
                    "taskMissing": True,
                }
            if task_row.status in TERMINAL_TASK_STATUSES:
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
            if task is None:
                # 落库没成功。通知的前提是**状态已经落库**——这里放行的话，主助理会
                # 被叫醒去查一个账上没记的活，而且 payload 的 sessionId / graphId 都
                # 是空的。抛异常让 _worker_scope 的共享事务整体回滚（attempt 不会停在
                # paused），由上层兜底记为内部错误。这条正常到不了：上面已确认 task
                # 存在，且此处不传 expected_task_version，所以它守的是不变量本身。
                raise RuntimeError(
                    f"暂停落库失败，未发通知：task={resolved.task_id} attempt={attempt_id}"
                )
            persisted_waiting_on = task.waiting_on
            payload = {
                "accepted": True,
                "attemptId": attempt_id,
                "taskId": resolved.task_id,
                "taskStatus": TaskStatus.SUSPENDED,
                "suspendReason": suspend_reason,
                "waitingOn": persisted_waiting_on,
                "safeSummary": safe_summary,
                "sessionId": task.session_id,
                "graphId": task.graph_id,
            }
            reentry_payload = _paused_reentry_payload(
                pause_result if isinstance(pause_result, dict) else {},
                waiting_on=persisted_waiting_on,
            )
            if reentry_payload is not None:
                reentry_payload["taskId"] = resolved.task_id
                if safe_summary:
                    # 外层这份已经过 _safe_result_summary 归一化，优先用它
                    reentry_payload["safeSummary"] = safe_summary
                # 同理：外层这份已过 _suspend_reason_from_result 校验并转成标准值。
                # 让 result 里的原始值盖回去，等于把那道校验绕过去——眼下两份内容
                # 相同看不出差别，但校验哪天开始做实事（清洗、旧写法转新写法），
                # 结果就会被静默丢掉。
                reentry_payload["suspendReason"] = suspend_reason
                payload.update(reentry_payload)
        if reentry_payload is not None:
            self._notify_parent_reentry(payload)
        return payload

    def _notify_parent_reentry(self, payload: dict[str, Any]) -> None:
        if self._parent_reentry_callback is None:
            return
        self._parent_reentry_callback(payload)

    def set_scheduler_callback(self, callback) -> None:
        """024: 注入 GraphScheduler.on_attempt_outcome 回调（装配期注入）。

        与构造参数 ``scheduler_callback`` 等效；orchestrator 先构造 dispatcher，再建
        GraphScheduler（它依赖 dispatcher），最后经此 setter 回填回调，解决 scheduler
        依赖 dispatcher、dispatcher 又要 scheduler 回调的构造循环。
        """
        self._scheduler_callback = callback

    def _notify_scheduler_attempt_outcome(self, payload: dict[str, Any]) -> None:
        """024: 通知 GraphScheduler 节点 attempt 完成。"""
        if self._scheduler_callback is None:
            return
        graph_id = payload.get("graphId")
        task_id = payload.get("taskId")
        if graph_id and task_id:
            try:
                self._scheduler_callback(graph_id, task_id)
            except Exception as e:
                logger.warning(
                    "scheduler_callback failed for graph=%s task=%s: %s",
                    graph_id,
                    task_id,
                    e,
                    exc_info=True,
                )

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
                result_ref=_result_reference_with_truncation(result)[0],
            )
        return result

    def shutdown(self, *, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)


_MAX_RESULT_REF_CHARS = 6000
_RESULT_REFERENCE_TEXT_KEYS = ("result_text", "message")


def _result_reference_with_truncation(
    result: str | dict[str, Any] | None,
) -> tuple[str | None, bool]:
    if result is None:
        return None, False
    if isinstance(result, str):
        text = result
    else:
        for key in _RESULT_REFERENCE_TEXT_KEYS:
            value = result.get(key)
            if isinstance(value, str) and value:
                text = value
                break
        else:
            text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    truncated = len(text) > _MAX_RESULT_REF_CHARS
    return text[:_MAX_RESULT_REF_CHARS], truncated


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


_REENTRY_DEFAULT_SUMMARY = {
    "budget_exhausted": "子任务已用完本轮轮次预算，等待追加预算或改派。",
    "task_question": "子任务正在等待派活方答复。",
    "needs_review": "节点标记为需确认，请裁定是否执行。",
}
_REENTRY_FALLBACK_SUMMARY = "子任务已暂停，等待主助理处理。"


def _paused_reentry_payload(
    result: str | dict[str, Any] | None,
    *,
    waiting_on: str | None = None,
) -> dict[str, Any] | None:
    """按「球在谁手上」决定要不要叫醒主助理，并组出回流 payload。

    只有 ``waiting_on == assistant`` 才发——等用户、等系统各有自己的通知路径，
    不该挤进这一条。

    ``waiting_on`` 缺失时**兜底当 assistant 并记 warning**：认不出的暂停宁可多叫
    醒主助理一次，也绝不静默丢弃。这里原本是一张只认两种 ``reentry_type`` 的白名
    单，于是撞轮次预算暂停的任务状态全部正确落库，却永远没有任何人被告知——主助
    理以为活还在跑，用户在等主助理告知，两边互等。
    """
    if not isinstance(result, dict):
        return None

    resolved = waiting_on or result.get("waiting_on")
    if resolved is None:
        resolved = waiting_on_for_reason(result.get("suspend_reason"))
    if resolved is None:
        logger.warning(
            "[task reentry] 暂停结果既无 waiting_on 也无 suspend_reason，"
            "兜底通知主助理 reentry_type=%s task=%s",
            result.get("reentry_type"),
            result.get("task_id"),
        )
        resolved = WaitingOn.ASSISTANT.value
    if str(resolved) != WaitingOn.ASSISTANT.value:
        return None

    reentry_type = result.get("reentry_type")
    event_type = str(reentry_type or _suspend_reason_from_result(result))
    raw_summary = result.get("safe_summary")
    payload: dict[str, Any] = {
        "eventType": event_type,
        "taskId": result.get("task_id"),
        # 独立调用（如单测）时这里也得走 safe_preview，别把未归一化的长文本带出去；
        # 生产路径上 _record_attempt_paused 会用它已处理过的 safe_summary 覆盖。
        "safeSummary": (
            safe_preview(raw_summary)
            if isinstance(raw_summary, str) and raw_summary.strip()
            else _REENTRY_DEFAULT_SUMMARY.get(event_type, _REENTRY_FALLBACK_SUMMARY)
        ),
    }
    if reentry_type == "task_question":
        payload["questionId"] = result.get("question_id")
        payload["questionKind"] = result.get("question_kind")
    # 主助理要续跑得知道续哪个执行体——没有这个 id，它知道该做什么也做不了。
    if result.get("subagent_id"):
        payload["subagentId"] = result["subagent_id"]
    for src_key, out_key in (
        ("iterations_used", "iterationsUsed"),
        ("max_iterations", "maxIterations"),
        ("suspend_reason", "suspendReason"),
    ):
        if result.get(src_key) is not None:
            payload[out_key] = result[src_key]
    return payload


def _lease_heartbeat(attempt_id: str) -> AttemptHeartbeat:
    """构造该 attempt 的续租心跳。

    每次续约用独立 Repository：心跳跑在执行线程，与 worker 的终态写入、恢复扫描
    的围栏各自独立连接，共用 Session 会踩 SQLAlchemy 的多线程竞态。
    """

    def _renew(target_attempt_id: str, *, lease_expires_at) -> bool:
        with AssistantTaskAttemptRepository() as attempts:
            return attempts.renew_lease(target_attempt_id, lease_expires_at=lease_expires_at)

    return AttemptHeartbeat(
        attempt_id,
        lease_seconds=_sane_lease_seconds(
            get_unified_config().get_assistant_tasks_attempt_lease_seconds()
        ),
        renew=_renew,
    )


def _sane_lease_seconds(value: Any) -> int:
    """把租约时长归一化；荒谬值退回默认。

    续约频率由租约推导，租约被读成 1 秒就会让后台线程每秒打一次库。
    ``UnifiedConfigManager`` 自己有 minimum=10 的下界，但这里还会收到测试替身
    和损坏配置——``int(MagicMock())`` 返回 1，静默把心跳变成忙循环。
    """
    return positive_int(value, default=_DEFAULT_LEASE_SECONDS, minimum=_MIN_SANE_LEASE_SECONDS)


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
        logger.warning(
            "[task attempt] failed to register run context: %s", attempt_id, exc_info=True
        )
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
