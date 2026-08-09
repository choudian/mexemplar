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

# 撞上确定性代码缺陷时给主助理的动作候选。**刻意不含 retry / swap_executor /
# adjust_input** —— 代码不改，重试多少次、换谁来、换什么输入，都是同一个错。
#
# 这是"不再重试"的**确定性保证**：不是靠主助理读懂文案自觉，是它手里根本没有
# 那个选项。7/28 实跑里它照着"需上级检查后决定是否重试"重试了 7 次，1 小时 13
# 分钟、0 产出——它没做错任何事，是那句建议在骗它。
_DEFECT_HEALING_ACTIONS: list[str] = ["skip", "replan", "abandon"]

_DEFECT_RECOVERY_HINT = (
    "这一步撞上程序缺陷，重试不会改变结果（换执行器、改输入也一样）。"
    "请判断能否跳过该节点让下游继续，或改图绕过；确实绕不开就放弃该分支并告知用户。"
)

# 记账崩溃时的固定摘要。**必须是常量**：那次崩溃很可能正是因为某个动态值有问题，
# 收尾时再去拼一个新的只会再崩一次。
_DEFECT_RECORDING_SUMMARY = "记录这一步的结果时撞上程序缺陷，重试不会改变结果。"
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

    def start_pending_graph_tasks(
        self,
        *,
        session_id: str,
        graph_id: str,
        use_resume_target: bool = False,
    ) -> int:
        """Start attempts for already-assigned pending tasks in a graph.

        ``use_resume_target=True`` 时用 ``latest_resume_target_for_task``（三条硬规则
        + has_progress + executor 匹配）选续跑目标，供用户点继续路径使用；
        ``False``（默认，fresh 派发/recovery）用 ``latest_resume_ref_for_task``
        （粗粒度"有没有旧会话"信号）。
        """
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
            if use_resume_target:
                resume_refs: dict[str, str | None] = {}
                for task in candidates:
                    target = attempts.latest_resume_target_for_task(
                        task.task_id,
                        assignee_type=task.assignee_type,
                        assignee_id=task.assignee_id,
                    )
                    if target:
                        import json as _json

                        resume_refs[task.task_id] = _json.dumps({
                            "executor_session_id": target["session_id"],
                        })
                    else:
                        resume_refs[task.task_id] = None
            else:
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

    def continue_task_atomically(
        self,
        *,
        task_id: str,
    ) -> Future | None:
        """③ §2.4 原子化 continue：不经过 PENDING_DISPATCH 中间态。

        在一个 ``_worker_scope`` 事务内完成：选续跑目标 → 建 attempt（带 checkpoint_ref）
        → task 从 SUSPENDED 直接翻 RUNNING。scheduler 扫的是 PENDING_DISPATCH，从头到尾
        看不到这个节点——不存在并发抢跑的缝。

        返回 Future（已提交到线程池）或 None（无 executor / 无续跑目标 / 容量冲突）。
        """
        if self._executor_callback is None:
            return None
        lease_seconds = self._config.get_assistant_tasks_attempt_lease_seconds()
        with self._write_lock:
            with _worker_scope() as (attempts, service):
                task_row = service.get_task(task_id)
                if task_row is None:
                    logger.warning("[atomic_continue] task %s not found", task_id)
                    return None
                if task_row.status != TaskStatus.SUSPENDED:
                    logger.warning(
                        "[atomic_continue] task %s is %s, not suspended; skip",
                        task_id,
                        task_row.status,
                    )
                    return None
                if not task_row.assignee_type or not task_row.assignee_id:
                    logger.warning(
                        "[atomic_continue] task %s has no assignee; skip", task_id
                    )
                    return None
                # 选续跑目标（三条硬规则：paused/fenced 都续跑 + executor 匹配 + has_progress）
                target = attempts.latest_resume_target_for_task(
                    task_id,
                    assignee_type=task_row.assignee_type,
                    assignee_id=task_row.assignee_id,
                )
                checkpoint_ref = None
                if target:
                    checkpoint_ref = json.dumps(
                        {"executor_session_id": target["session_id"]}
                    )
                # 建 attempt（start_attempt 内部有容量=1 守卫 + 唯一索引兜底）
                executor_id = (
                    task_row.assignee_id
                    if task_row.assignee_type == "specialist" and task_row.assignee_id
                    else task_id
                )
                attempt = attempts.start_attempt(
                    task_id=task_id,
                    executor_type=task_row.assignee_type,
                    executor_id=executor_id,
                    lease_owner="atomic_continue",
                    lease_expires_at=utc_now_naive() + timedelta(seconds=lease_seconds),
                    checkpoint_ref=checkpoint_ref,
                )
                if attempt is None:
                    logger.warning(
                        "[atomic_continue] start_attempt returned None (capacity conflict): task=%s",
                        task_id,
                    )
                    return None
                attempt_id = attempt.attempt_id
                fence_token = attempt.fence_token
                # task 从 SUSPENDED 直接翻 RUNNING（不经过 PENDING_DISPATCH）
                service.update_task_status(
                    task_id=task_id,
                    status=TaskStatus.RUNNING,
                )
                increment_task_collaboration_counter("attempt_started")
        return self._pool.submit(
            self._run_attempt_worker,
            attempt_id,
            fence_token,
        )

    def wait_for_active_attempt(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.2,
    ) -> bool:
        """③ §2.5 有界等待：等 task 的 active attempt 停稳。

        stop→continue 场景：用户点了停止后立刻点继续，旧 attempt 可能还 running。
        新 attempt 会撞唯一索引。此方法轮询等旧 attempt 变非 active。

        返回 True（已停稳，可以建新 attempt）或 False（超时，旧 attempt 仍 active）。
        """
        import time

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with AssistantTaskAttemptRepository() as attempts:
                active = attempts._active_attempt_for_task(task_id)
            if active is None:
                return True
            time.sleep(poll_interval_seconds)
        return False

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
        except Exception as exc:
            # 记账本身崩了（落库被约束拒、result 里有不可序列化的对象…）。
            #
            # 这里原本是裸 raise —— 而 worker 跑在线程池里，没有人 .result()，
            # 于是异常被 Future 整个吞掉：只剩一行日志，活停在「运行中」，两分钟
            # 租约过期后被当成失联重派，再跑一遍、记账时再崩，**无限循环**。
            # 7/28 那 7 次重试至少还是主助理照建议做的；这一类连它都不知道。
            #
            # 所以不再往上抛：把活钉死在一个终态，让它退出重派循环。
            return self._force_defect_terminal(attempt_id, fence_token, exc)
        finally:
            if run_started:
                run_context.end()

    def _force_defect_terminal(
        self, attempt_id: str, fence_token: int, exc: BaseException
    ) -> dict[str, Any]:
        """记账崩溃后的收尾：用最小字段集把活钉在「撞上程序缺陷」。

        **只写内置常量字段**（status / suspend_reason / waiting_on / 固定摘要），
        绕开任何可能就是崩溃原因的东西——原来那次失败很可能正是因为某个值违约
        或某个对象序列化不了，带着它再写一次只会再崩一次。

        这一步再失败就只剩日志了。那意味着数据库整体写不进去（磁盘满、库损坏），
        系统已经不可用，不是这里能补救的——但**至少不会递归重试**。
        """
        from src.business.services.assistant_failure_classifier import (
            classify_assistant_failure,
        )

        classified = classify_assistant_failure(exception=exc)
        logger.error(
            "[task defect] 记账失败 attempt=%s class=%s type=%s",
            attempt_id,
            classified.category,
            classified.exception_type,
            exc_info=True,
        )
        try:
            with self._write_lock:
                return self._record_attempt_paused(
                    attempt_id=attempt_id,
                    fence_token=fence_token,
                    suspend_reason=SuspendReason.BLOCKED_BY_DEFECT.value,
                    safe_summary=_DEFECT_RECORDING_SUMMARY,
                    pause_result={
                        "suspend_reason": SuspendReason.BLOCKED_BY_DEFECT.value,
                        "reentry_type": "blocked_by_defect",
                        "failure_exception_type": classified.exception_type,
                    },
                )
        except Exception:
            logger.exception(
                "[task defect] 最小字段集收尾也失败 attempt=%s，只能靠租约扫描兜底",
                attempt_id,
            )

        # 收尾写不进 task 表，至少让 attempt 让出执行者槽——否则它一直占着
        # 「活跃」名额，恢复扫描会把它当失联重派，又回到那个循环里。
        try:
            with self._write_lock, _worker_scope() as (attempts, _service):
                attempts.fail_if_current(
                    attempt_id=attempt_id,
                    fence_token=fence_token,
                    error_category=classified.category,
                    result_ref=classified.exception_type,
                )
        except Exception:
            logger.exception("[task defect] attempt 收尾也失败 attempt=%s", attempt_id)

        return {
            "accepted": False,
            "attemptId": attempt_id,
            "recordingFailed": True,
            "failureClass": classified.category,
        }

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
            # ⑥ 执行体交了活——task 从 running 落 delivered（显式"等裁定"状态）。
            # 必须在 create_parent_adjudication 之后写：先建裁定再标 delivered，
            # 崩在中间留下"delivered 但无 pending 裁定"的死格子。
            service.update_task_status(task_id=task_id, status=TaskStatus.DELIVERED)
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
            # ③ 第二阶段：checkpoint_ref 存 executor_session_id，供续跑路径解析。
            # result_ref 继续做它本职（给主助理看的产出预览），两者不再混用。
            checkpoint_json = None
            if current_attempt.executor_session_id:
                import json as _json

                checkpoint_json = _json.dumps(
                    {"executor_session_id": current_attempt.executor_session_id}
                )
            resolved = attempts.pause_if_current(
                attempt_id=attempt_id,
                fence_token=fence_token,
                result_ref=result_ref,
                checkpoint_ref=checkpoint_json,
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
    if result.get("suspend_reason") == SuspendReason.BLOCKED_BY_DEFECT.value:
        # 撞上缺陷时**必须**给出动作候选，而且这组里没有 retry —— 见
        # _DEFECT_HEALING_ACTIONS 的说明。这是"不再重试"的确定性保证：
        # 主助理想重试也没这个选项，不靠它读懂文案自觉。
        payload["healingActions"] = list(_DEFECT_HEALING_ACTIONS)
        payload["safeRecoveryHint"] = _DEFECT_RECOVERY_HINT
        if result.get("failure_exception_type"):
            # 只带类型名，给主助理一点判断依据；完整现场在 ERROR 日志里。
            payload["failureExceptionType"] = result["failure_exception_type"]
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
