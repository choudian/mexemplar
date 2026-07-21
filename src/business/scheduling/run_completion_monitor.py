"""``RunCompletionMonitor`` —— run-scoped 静默判定 + 终态写入（034）。

订阅后端 blinker 事件，在 scheduled 会话「真正静默」后把对应 run 置终态并发
``scheduler_run_terminal``（由 projector 转 ``scheduled_task.completed`` /
``.needs_takeover`` 公开事件）。

静默三条件（缺一不可——首 run 的 durable accepted ≠ 完成）：

1. ``not has_active_worker(session_id)``：主助理 worker 已退出。
2. ``not has_pending_reentry(session_id)``：无未消费回流。
3. 图全终态；简单任务无图时，必须存在成功的同步委派工具结果。

静默后按图终态分流：

- all_terminal ∧ all_completed → ``succeeded``（summary = 最后一条 assistant 展示消息截取）；
- all_terminal ∧ not all_completed → ``failed``（failure_reason 安全投影，无敏感诊断）；
- 主助理返回需补充信息时，``mark_waiting_user`` 原子转换并单次 emit；
  后续评估遇到稳定 ``waiting_user`` 不覆盖、不重复通知。

业务层不 import desktop_api：``has_active_worker`` callback 由 desktop lifespan 注入；
``has_pending_reentry`` / ``get_graph_snapshot`` 走 task_collaboration 既有 API。
Blinker receiver 只是同步 observer：图根消息序号先映射到 ``run_id``，评估异常在 receiver
边界记录并隔离，不得反向打断 task collaboration 发送方；runtime 必须主动调用
``evaluate_run(run_id)``，session 入口只作兼容。
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import nullcontext
from typing import Any, Callable, Optional

from src.business.task_collaboration.graph_terminal import compute_graph_terminal_state
from src.data.models_sqlite import ScheduledTaskRun
from src.data.repos.message_repository import MessageRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.scheduling_types import (
    RUN_ACTIVE_STATUS_VALUES,
    RUN_EVENT_DELIVERABLE_STATUS_VALUES,
    RUN_TERMINAL_STATUS_VALUES,
)

logger = logging.getLogger(__name__)

SUMMARY_MAX_CHARS = 500
FAILURE_REASON_SAFE = "scheduled session failed to complete successfully"
_SYNC_EXECUTION_TOOL_NAMES = frozenset(
    {
        "delegate_to_subagent",
        "delegate_to_specialist",
        "continue_subagent",
    }
)


class RunCompletionMonitor:
    """订阅事件 → 判静默 → 写 run 终态 + emit ``scheduler_run_terminal``。

    生产接线要求 desktop lifespan 注入前两个 runtime callback：

    - ``has_active_worker(session_id) -> bool``：**必须由 desktop 注入**（business 不能
      import ``AssistantRuntime``）；未注入时视为「无法确认静默」，evaluate 跳过并记 warning。
    - ``has_pending_reentry(session_id) -> bool``：**必须由 desktop 注入**；未注入或查询
      失败时 fail-closed，不能把未知状态误报成静默。
    - ``get_graph_snapshot(session_id) -> TaskGraphSnapshot | None``：兼容测试注入；生产走
      run 水位线限定的 ``AssistantTaskRepository`` + ``TaskCollaborationService`` 权威查询。
    """

    def __init__(
        self,
        *,
        has_active_worker: Callable[[str], bool] | None = None,
        has_pending_reentry: Callable[..., bool] | None = None,
        get_graph_snapshot: Callable[[str], Any] | None = None,
        run_repo: ScheduledTaskRunRepository | None = None,
        message_repo: MessageRepository | None = None,
        task_repo: ScheduledTaskRepository | None = None,
    ) -> None:
        self._has_active_worker = has_active_worker
        self._has_pending_reentry_callback = has_pending_reentry
        self._get_graph_snapshot = get_graph_snapshot
        # 注入 repo 仅供单线程单元测试；生产不长期持有 SQLAlchemy Session，
        # 每次评估在回调线程内创建 fresh Repository。
        self._run_repo = run_repo
        self._message_repo = message_repo
        self._task_repo = task_repo
        self._evaluation_lock = threading.RLock()
        self._connected = False

    def close(self) -> None:
        # 注入的 Repository 归调用方；生产 Repository 均为单次 scope 自动关闭。
        return None

    # -- wiring ---------------------------------------------------------------

    def connect(self) -> None:
        """订阅 blinker 事件（idempotent）。"""
        if self._connected:
            return
        from src.utils.events import connect

        connect("graph_scheduler_terminal", self._on_graph_terminal, weak=False)
        connect("assistant_subagent_finished", self._on_session_activity, weak=False)
        connect("assistant_task_root_failed", self._on_session_activity, weak=False)
        self._connected = True
        # 进程上次可能在业务终态提交后、UI 投影确认前退出。连接建立后先补投；
        # 失败项继续留在 SQLite，后续 SchedulerWorker tick 再试。
        self.retry_pending_terminal_events()
        logger.info("RunCompletionMonitor connected")

    def disconnect(self) -> None:
        if not self._connected:
            return
        from src.utils.events import disconnect

        subscriptions = (
            ("graph_scheduler_terminal", self._on_graph_terminal),
            ("assistant_subagent_finished", self._on_session_activity),
            ("assistant_task_root_failed", self._on_session_activity),
        )
        for event_name, receiver in subscriptions:
            try:
                disconnect(event_name, receiver)
            except Exception:  # pragma: no cover - blinker 防御
                logger.warning(
                    "RunCompletionMonitor: disconnect %s failed",
                    event_name,
                    exc_info=True,
                )
        self._connected = False

    # -- 事件回调 -------------------------------------------------------------

    def _on_graph_terminal(self, _sender, **kwargs) -> None:
        graph_id = kwargs.get("graph_id")
        session_id = kwargs.get("session_id")
        if not session_id or not graph_id:
            return
        run_id = self.resolve_run_id_for_graph(
            session_id=session_id,
            graph_id=graph_id,
        )
        if run_id is None:
            return
        self._evaluate_run_from_event(
            run_id,
            event_name=str(kwargs.get("event_name") or "graph_scheduler_terminal"),
        )

    def _on_session_activity(self, _sender, **kwargs) -> None:
        session_id = kwargs.get("session_id")
        graph_id = kwargs.get("graph_id")
        if not session_id or not graph_id:
            return
        run_id = self.resolve_run_id_for_graph(
            session_id=session_id,
            graph_id=graph_id,
        )
        if run_id is None:
            return
        self._evaluate_run_from_event(
            run_id,
            event_name=str(kwargs.get("event_name") or "assistant_session_activity"),
        )

    def _evaluate_run_from_event(self, run_id: str, *, event_name: str) -> None:
        """Best-effort observer 边界；绝不把评估异常抛回核心事件发送方。"""
        try:
            self.evaluate_run(run_id)
        except Exception:
            logger.error(
                "RunCompletionMonitor: %s evaluation failed for run %s",
                event_name,
                run_id,
                exc_info=True,
            )

    def resolve_run_id_for_graph(
        self,
        *,
        session_id: str,
        graph_id: str,
    ) -> str | None:
        """通过图根消息序号把 graph 精确映射到所属 run 窗口。"""
        try:
            from src.data.repos.assistant_task_repository import (
                AssistantTaskRepository,
            )

            with AssistantTaskRepository() as task_repo:
                sequence = task_repo.get_graph_user_message_sequence(graph_id)
            if sequence is None:
                return None
            with self._run_repo_scope() as run_repo:
                run = run_repo.get_for_message_sequence(session_id, sequence)
            return run.run_id if run is not None else None
        except Exception:
            logger.error(
                "RunCompletionMonitor: failed to map graph %s in session %s to run",
                graph_id,
                session_id,
                exc_info=True,
            )
            return None

    def get_active_run_id_for_session(self, session_id: str) -> str | None:
        """仅供 takeover/user dispatch 入场时固定一次 run owner。"""
        try:
            with self._run_repo_scope() as run_repo:
                run = run_repo.get_active_by_session(session_id)
            return run.run_id if run is not None else None
        except Exception:
            logger.error(
                "RunCompletionMonitor: active run lookup failed for session %s",
                session_id,
                exc_info=True,
            )
            return None

    # -- 主入口 ---------------------------------------------------------------

    def evaluate_run(self, run_id: str) -> Optional[dict[str, Any]]:
        """按唯一 ``run_id`` 判静默并写终态。"""
        normalized_run_id = (run_id or "").strip()
        if not normalized_run_id:
            return None
        with self._evaluation_lock:
            with self._run_repo_scope() as run_repo:
                run = run_repo.get_fresh(normalized_run_id)
                if run is None:
                    return None
                return self._evaluate_run_locked(run, run_repo)

    def evaluate_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """兼容观察入口：只解析该 session 唯一 active run，再委托 ``run_id``。

        runtime worker 不得使用本入口；它必须携带并调用 ``evaluate_run(run_id)``。
        """
        sid = (session_id or "").strip()
        if not sid:
            return None
        with self._evaluation_lock:
            with self._run_repo_scope() as run_repo:
                run = run_repo.get_active_by_session(sid)
                if run is None:
                    # 仅给旧终态投影补投；不得选择一条 nonterminal 历史 run 继续推进。
                    latest = run_repo.get_by_session(sid)
                    if latest is not None and latest.status in RUN_EVENT_DELIVERABLE_STATUS_VALUES:
                        self._emit_terminal(latest, run_repo=run_repo)
                    return None
                return self._evaluate_run_locked(run, run_repo)

    def _evaluate_run_locked(
        self,
        run: ScheduledTaskRun,
        run_repo: ScheduledTaskRunRepository,
    ) -> Optional[dict[str, Any]]:
        # 终态业务事实不再推进，但其通知可能在上一次 emit 后仍待确认。
        if run.status in RUN_TERMINAL_STATUS_VALUES:
            if run.status in RUN_EVENT_DELIVERABLE_STATUS_VALUES:
                self._emit_terminal(run, run_repo=run_repo)
            return None
        # waiting_user 是稳定等待态，等用户接管后由 takeover 回 running 再评估
        if run.status == "waiting_user":
            self._emit_terminal(run, run_repo=run_repo)
            return None

        graph_state = self._quiescent_graph_state(run)
        if graph_state is None:
            return None
        _, all_completed = graph_state

        if all_completed:
            summary = self._extract_summary(run)
            updated = run_repo.cas_transition(
                run.run_id,
                from_status="running",
                to_status="succeeded",
                summary=summary,
            )
        else:
            updated = run_repo.cas_transition(
                run.run_id,
                from_status="running",
                to_status="failed",
                failure_reason=FAILURE_REASON_SAFE,
                clear_trigger_message_sequence=self._can_release_trigger_slot(run),
            )
        if updated is None:
            # 并发已置终态 / waiting_user；不重复 emit
            return None
        self._emit_terminal(updated, run_repo=run_repo)
        return {
            "runId": updated.run_id,
            "status": updated.status,
            "summary": updated.summary,
        }

    def mark_waiting_user(self, run_id: str) -> Optional[dict[str, Any]]:
        """scheduled 主助理反问时按 ``run_id`` 原子落 ``waiting_user``。"""
        normalized_run_id = (run_id or "").strip()
        if not normalized_run_id:
            return None
        with self._evaluation_lock:
            with self._run_repo_scope() as run_repo:
                run = run_repo.get_fresh(normalized_run_id)
                if run is None or run.status != "running":
                    return None
                updated = run_repo.cas_transition(
                    run.run_id,
                    from_status="running",
                    to_status="waiting_user",
                )
                if updated is None:
                    return None
                self._emit_terminal(updated, run_repo=run_repo)
                return {"runId": updated.run_id, "status": updated.status}

    def mark_failed(
        self,
        run_id: str,
        *,
        failure_reason: str = FAILURE_REASON_SAFE,
    ) -> Optional[dict[str, Any]]:
        """明确的 assistant 失败/停止结果按 ``run_id`` 结束 scheduled run。"""
        normalized_run_id = (run_id or "").strip()
        if not normalized_run_id:
            return None
        with self._evaluation_lock:
            with self._run_repo_scope() as run_repo:
                run = run_repo.get_fresh(normalized_run_id)
                if run is None or run.status not in RUN_ACTIVE_STATUS_VALUES:
                    return None
                clear_trigger = self._can_release_trigger_slot(run)
                updated = run_repo.cas_transition(
                    run.run_id,
                    from_status=RUN_ACTIVE_STATUS_VALUES,
                    to_status="failed",
                    failure_reason=failure_reason,
                    clear_trigger_message_sequence=clear_trigger,
                )
                if updated is None:
                    return None
                self._emit_terminal(updated, run_repo=run_repo)
                return {"runId": updated.run_id, "status": updated.status}

    def _trigger_message_is_missing(self, run: ScheduledTaskRun) -> bool:
        """仅在能证明预留 trigger 尚未持久化时释放唯一序号。"""
        sequence = run.trigger_message_sequence
        if sequence is None:
            return False
        try:
            with self._message_repo_scope() as message_repo:
                return message_repo.get_by_sequence(run.session_id, sequence) is None
        except Exception:
            # 查询未知时保留 trigger 归属，避免把真实消息重新分给后续 run。
            logger.error(
                "RunCompletionMonitor: trigger message lookup failed for run %s",
                run.run_id,
                exc_info=True,
            )
            return False

    def _can_release_trigger_slot(self, run: ScheduledTaskRun) -> bool:
        """仅在消息缺失且没有图认领该 run 窗口时释放 trigger 序号。"""
        if not self._trigger_message_is_missing(run):
            return False
        try:
            from src.data.repos.assistant_task_repository import (
                AssistantTaskRepository,
            )

            with AssistantTaskRepository() as task_repo:
                known, graph_id = task_repo.resolve_graph_id_for_run(
                    run.session_id,
                    after_sequence=run.baseline_message_sequence,
                    started_at=run.started_at,
                )
            # 已有精确图或未标序号图时都保留 trigger，避免后续 run 复用同一
            # message sequence 后把旧图误映射给新 owner。
            return known and graph_id is None
        except Exception:
            logger.error(
                "RunCompletionMonitor: graph ownership lookup failed before releasing "
                "trigger slot for run %s",
                run.run_id,
                exc_info=True,
            )
            return False

    def is_session_quiescent(self, session_id: str) -> bool:
        """静默三条件：无 worker ∧ 无回流 ∧ 图终态/无图同步委派已结束。"""
        with self._run_repo_scope() as run_repo:
            run = run_repo.get_active_by_session(session_id)
            return run is not None and self._quiescent_graph_state(run) is not None

    def _quiescent_graph_state(
        self,
        run: ScheduledTaskRun,
    ) -> tuple[bool, bool] | None:
        """一次性判静默并返回本次读取的图终态，避免判定与落账重复查询。"""
        sid = (run.session_id or "").strip()
        if not sid:
            return None
        has_active_worker = self._has_active_worker
        if has_active_worker is None:
            logger.warning(
                "RunCompletionMonitor: has_active_worker callback not injected; "
                "cannot confirm quiescence for session %s",
                sid,
            )
            return None
        try:
            if has_active_worker(sid):
                return None
        except Exception:
            logger.error(
                "RunCompletionMonitor: has_active_worker callback failed for session %s",
                sid,
                exc_info=True,
            )
            return None
        known, graph_id, snapshot = self._get_snapshot(run)
        if not known:
            return None
        if self._has_pending_reentry_now(sid, graph_id):
            return None
        graph_state = self._compute_graph_state(run, snapshot)
        if graph_state is None:
            return None
        all_terminal, _ = graph_state
        return graph_state if all_terminal else None

    # -- 内部 -----------------------------------------------------------------

    def _has_pending_reentry_now(
        self,
        session_id: str,
        graph_id: str | None,
    ) -> bool:
        if self._has_pending_reentry_callback is not None:
            try:
                if graph_id is None:
                    return bool(self._has_pending_reentry_callback(session_id))
                return bool(self._has_pending_reentry_callback(session_id, graph_id))
            except Exception:
                logger.error(
                    "RunCompletionMonitor: has_pending_reentry callback failed for session %s",
                    session_id,
                    exc_info=True,
                )
                return True
        # business 层不得反向 import desktop runtime；未注入时无法证明静默。
        logger.warning(
            "RunCompletionMonitor: has_pending_reentry callback not injected; "
            "cannot confirm quiescence for session %s",
            session_id,
        )
        return True

    def _compute_graph_state(
        self,
        run: ScheduledTaskRun,
        snapshot: Any | None,
    ) -> tuple[bool, bool] | None:
        session_id = run.session_id
        if snapshot is None:
            # 无图只允许来自 100% 调度规则中的简单同步委派。仅凭主助理 worker
            # 退出不能证明任务做过，否则“误调用别的工具后结束”会被记成成功。
            delegated = self._has_successful_sync_execution(run)
            if delegated is None:
                return None
            if not delegated:
                logger.warning(
                    "RunCompletionMonitor: scheduled session %s has no graph and "
                    "no successful synchronous delegation evidence",
                    session_id,
                )
            return True, delegated
        tasks = getattr(snapshot, "tasks", None) or []
        try:
            from src.business.task_collaboration.models import (
                TERMINAL_TASK_STATUSES,
                TaskStatus,
            )
        except Exception:  # pragma: no cover - task_collaboration 应可 import
            logger.error(
                "RunCompletionMonitor: task collaboration status types unavailable",
                exc_info=True,
            )
            return None
        return compute_graph_terminal_state(
            tasks,
            terminal_statuses=TERMINAL_TASK_STATUSES,
            completed_status=str(TaskStatus.COMPLETED),
        )

    def _has_successful_sync_execution(self, run: ScheduledTaskRun) -> bool | None:
        """读取持久工具结果；查询未知时 fail-closed，避免误报终态。"""
        session_id = run.session_id
        try:
            with self._message_repo_scope() as message_repo:
                messages = message_repo.list_tool_messages_after(
                    session_id,
                    after_sequence=run.baseline_message_sequence,
                    tool_names=_SYNC_EXECUTION_TOOL_NAMES,
                )
        except Exception:
            logger.error(
                "RunCompletionMonitor: delegation evidence lookup failed for session %s",
                session_id,
                exc_info=True,
            )
            return None

        return any(
            self._tool_result_succeeded(getattr(message, "content", None)) for message in messages
        )

    @staticmethod
    def _tool_result_succeeded(content: Any) -> bool:
        """兼容原始 handler JSON 与 output-governance envelope。"""
        if not isinstance(content, str) or not content.strip():
            return False
        try:
            payload = json.loads(content)
        except (TypeError, ValueError):
            return False
        if not isinstance(payload, dict):
            return False

        direct_success = payload.get("success")
        if isinstance(direct_success, bool):
            return direct_success

        if str(payload.get("outcome") or "").lower() != "success":
            return False

        # 普通自定义工具的小结果会被 governance 包在 payload.content 中。
        # 若其中保留了显式 success=false，以内层业务结果为准。
        envelope_payload = payload.get("payload")
        if isinstance(envelope_payload, dict):
            nested_content = envelope_payload.get("content")
            if isinstance(nested_content, str):
                try:
                    nested = json.loads(nested_content)
                except (TypeError, ValueError):
                    nested = None
                if isinstance(nested, dict) and isinstance(nested.get("success"), bool):
                    return nested["success"]
        return True

    def _get_snapshot(
        self,
        run: ScheduledTaskRun,
    ) -> tuple[bool, str | None, Any | None]:
        """返回 ``(known, graph_id, snapshot)``；查询失败与“无图”严格区分。"""
        session_id = run.session_id
        if self._get_graph_snapshot is not None:
            try:
                snapshot = self._get_graph_snapshot(session_id)
                graph_id = getattr(snapshot, "graph_id", None) if snapshot is not None else None
                return True, graph_id, snapshot
            except Exception:
                logger.error(
                    "RunCompletionMonitor: get_graph_snapshot callback failed for session %s",
                    session_id,
                    exc_info=True,
                )
                return False, None, None
        # 默认：TaskCollaborationService.get_graph_snapshot(session_id, graph_id)
        graph_id_known, graph_id = self._lookup_current_graph_id(run)
        if not graph_id_known:
            return False, None, None
        if graph_id is None:
            return True, None, None
        try:
            from src.business.task_collaboration.service import TaskCollaborationService

            with TaskCollaborationService() as service:
                snapshot = service.get_graph_snapshot(
                    session_id=session_id,
                    graph_id=graph_id,
                )
            if snapshot is None:
                logger.error(
                    "RunCompletionMonitor: graph %s exists but snapshot is unavailable "
                    "for session %s",
                    graph_id,
                    session_id,
                )
                return False, graph_id, None
            return True, graph_id, snapshot
        except Exception:
            logger.error(
                "RunCompletionMonitor: graph snapshot lookup failed for session %s",
                session_id,
                exc_info=True,
            )
            return False, graph_id, None

    def _lookup_current_graph_id(
        self,
        run: ScheduledTaskRun,
    ) -> tuple[bool, Optional[str]]:
        session_id = run.session_id
        try:
            from src.data.repos.assistant_task_repository import (
                AssistantTaskRepository,
            )

            with AssistantTaskRepository() as repo:
                return repo.resolve_graph_id_for_run(
                    session_id,
                    after_sequence=run.baseline_message_sequence,
                    started_at=run.started_at,
                )
        except Exception:
            logger.error(
                "RunCompletionMonitor: current graph id lookup failed for session %s",
                session_id,
                exc_info=True,
            )
            return False, None

    def _extract_summary(self, run: ScheduledTaskRun) -> str:
        session_id = run.session_id
        try:
            with self._message_repo_scope() as message_repo:
                text = message_repo.get_latest_assistant_text(
                    session_id,
                    max_length=SUMMARY_MAX_CHARS,
                    after_sequence=run.baseline_message_sequence,
                )
            return text or ""
        except Exception:
            logger.warning(
                "RunCompletionMonitor: summary extraction failed for session %s",
                session_id,
                exc_info=True,
            )
            return ""

    def _emit_terminal(
        self,
        run: ScheduledTaskRun,
        *,
        run_repo: ScheduledTaskRunRepository,
    ) -> bool:
        from src.business.scheduling.terminal_event_delivery import deliver_terminal_event

        return deliver_terminal_event(
            run.run_id,
            run_repo=run_repo,
            task_repo=self._task_repo,
        )

    def retry_pending_terminal_events(self, *, limit: int = 100) -> int:
        """Replay a bounded durable batch (startup + every scheduler tick)."""
        from src.business.scheduling.terminal_event_delivery import (
            retry_pending_terminal_events,
        )

        return retry_pending_terminal_events(
            limit=limit,
            run_repo=self._run_repo,
            task_repo=self._task_repo,
        )

    def _run_repo_scope(self):
        if self._run_repo is not None:
            return nullcontext(self._run_repo)
        return ScheduledTaskRunRepository()

    def _message_repo_scope(self):
        if self._message_repo is not None:
            return nullcontext(self._message_repo)
        return MessageRepository()


# =============================================================================
# 模块级单例
# =============================================================================

_monitor: RunCompletionMonitor | None = None


def get_run_completion_monitor() -> RunCompletionMonitor:
    global _monitor
    if _monitor is None:
        _monitor = RunCompletionMonitor()
    return _monitor


def install_run_completion_monitor(
    *,
    has_active_worker: Callable[[str], bool] | None,
    has_pending_reentry: Callable[..., bool] | None = None,
    get_graph_snapshot: Callable[[str], Any] | None = None,
) -> RunCompletionMonitor:
    """desktop lifespan 注入：构造 + connect 单例，返回它供 shutdown disconnect。"""
    global _monitor
    if _monitor is not None:
        _monitor.disconnect()
        _monitor.close()
    _monitor = RunCompletionMonitor(
        has_active_worker=has_active_worker,
        has_pending_reentry=has_pending_reentry,
        get_graph_snapshot=get_graph_snapshot,
    )
    _monitor.connect()
    return _monitor


def shutdown_run_completion_monitor() -> None:
    global _monitor
    if _monitor is not None:
        _monitor.disconnect()
        _monitor.close()
        _monitor = None
