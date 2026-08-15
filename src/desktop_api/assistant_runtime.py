from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from src.business.agents import run_context
from src.business.agents.config import AgentType, ResultType
from src.business.orchestration.agent import AgentOrchestrator
from src.business.services.chat_service import ChatService
from src.business.services.assistant_failure_service import (
    AssistantFailureService,
    AssistantRetryConflict,
)
from src.business.scheduling.scheduling_confirmation_manager import (
    settle_for_session_stopped as settle_scheduling_confirmations_for_session_stopped,
)
from src.business.task_collaboration.reentry_briefing import (
    build_reentry_briefing,
    filter_pending_entries,
)
from src.desktop_api.clarifications import (
    install_clarification_signal,
    settle_clarifications_for_session_stopped,
)
from src.desktop_api.confirmations import (
    clear_confirmation_session_context,
    fail_closed_confirmations_for_session,
    install_confirmation_signal,
    set_confirmation_session_context,
)
from src.desktop_api.events import event_queue
from src.desktop_api.orchestrator_runtime import build_default_orchestrator

if TYPE_CHECKING:
    from src.business.agents.observability import AssistantObservability

logger = logging.getLogger(__name__)

# 中断型工具中表示"本轮已向用户交付"的那些；其余 NEEDS_USER_INPUT 都当成在等用户答复。
# 见 ``AssistantRuntime._is_report_completion``。
_REPORT_COMPLETION_SIGNALS = frozenset({"reply_to_user"})


@dataclass(frozen=True)
class ContinueSubagentDirective:
    subagent_id: str
    supplemental: str = ""
    initial_return_transition_count: int = 0


@dataclass(frozen=True)
class RetryDirective:
    failure_id: str
    source_message_sequence: int
    reuse_user_message: bool


class AssistantRuntime:
    """Background dispatch adapter for assistant messages in the desktop sidecar."""

    def __init__(
        self,
        orchestrator_factory: Callable[[], AgentOrchestrator] = build_default_orchestrator,
        chat_service: Optional[ChatService] = None,
        failure_service: Optional[AssistantFailureService] = None,
    ) -> None:
        self._orchestrator_factory = orchestrator_factory
        self._chat_service = chat_service or ChatService()
        self._failure_service = failure_service or AssistantFailureService()
        self._orchestrator: AgentOrchestrator | None = None
        self._orchestrator_lock = threading.Lock()
        self._workers: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()
        self._session_reservations: dict[str, str] = {}
        self._reentry_sink = None
        self._observability: Optional["AssistantObservability"] = None
        install_confirmation_signal()
        install_clarification_signal()

    @property
    def _obs(self) -> "AssistantObservability":
        """延迟初始化的可观测读模型单例——避免每次调用重复创建 Repository 实例。"""
        if self._observability is None:
            from src.business.agents.observability import AssistantObservability

            self._observability = AssistantObservability()
        return self._observability

    def _get_orchestrator(self) -> AgentOrchestrator:
        with self._orchestrator_lock:
            orchestrator = self._orchestrator
            if orchestrator is None:
                orchestrator = self._orchestrator_factory()
                self._orchestrator = orchestrator
                self._ensure_planner_specialist()
                orchestrator.task_worker.start()
                self._install_reentry_sink(orchestrator)
                self._ensure_task_scheduler_for_orchestrator(orchestrator)
            return orchestrator

    def ensure_task_scheduler(self) -> None:
        """Ensure the process-level task graph scheduler is wired."""
        self._ensure_task_scheduler_for_orchestrator(self._get_orchestrator())

    def _ensure_task_scheduler_for_orchestrator(self, orchestrator: AgentOrchestrator) -> None:
        try:
            orchestrator._get_task_dispatcher()
        except Exception:
            # 装配失败 = 任务图调度整体不可用：图建好后节点不推进、主助理收不到回流，
            # 前端无提示的静默卡死。必须 ERROR 级暴露后果，不得降级为 warning（硬规则⑥）。
            logger.error(
                "Task graph scheduler 初始化失败：复杂任务图将无法自动推进"
                "（建图后节点停滞、主助理不收回流），请检查 dispatcher/task 装配。",
                exc_info=True,
            )

    def _ensure_planner_specialist(self) -> None:
        """Register the default planner specialist once per runtime startup."""
        try:
            from src.business.brain.specialist_service import SpecialistService

            SpecialistService().ensure_planner_specialist()
        except Exception:
            logger.warning("Failed to ensure planner specialist", exc_info=True)

    def _install_reentry_sink(self, orchestrator: AgentOrchestrator) -> None:
        """创建父侧回流 sink 并注入 orchestrator 的 dispatcher。

        sink 通过本 runtime 的 has_active_worker / kick_reentry_run 与 worker 池协作，
        是 dispatcher 线程池 → 续跑 worker 的受控直连（非 blinker，constitution 原则 I）。
        """
        from src.business.task_collaboration.parent_reentry_sink import ParentReentrySink

        sink = ParentReentrySink(
            has_active_worker=self.has_active_worker,
            kick_reentry_run=self.kick_reentry_run,
        )
        self._reentry_sink = sink
        orchestrator.set_parent_reentry_callback(sink.dispatch)
        set_reentry_sink = getattr(orchestrator, "set_reentry_sink", None)
        if callable(set_reentry_sink):
            set_reentry_sink(sink)

    def has_active_worker(self, session_id: str) -> bool:
        with self._workers_lock:
            worker = self._workers.get(session_id)
            return worker is not None and worker.is_alive()

    def reserve_scheduled_session(self, session_id: str, reservation_id: str) -> bool:
        """预约一个无 worker 的 session；与所有 worker 启动共用 first-wins 锁。"""
        sid = (session_id or "").strip()
        token = (reservation_id or "").strip()
        if not sid or not token:
            return False
        # 预约不仅要排除 worker，还必须能证明父侧回流队列已安装且为空。
        # 初始化 orchestrator 会同步安装 sink；失败时 fail-closed。
        try:
            self._get_orchestrator()
        except Exception:
            logger.error(
                "Cannot initialize reentry sink before reserving scheduled session %s",
                sid,
                exc_info=True,
            )
            return False
        with self._workers_lock:
            worker = self._workers.get(sid)
            if worker is not None and worker.is_alive():
                return False
            if sid in self._session_reservations:
                return False
            self._session_reservations[sid] = token
        if self.has_pending_reentry(sid):
            self.release_scheduled_session_reservation(sid, token)
            return False
        if not self._scheduled_session_graphs_quiescent(sid):
            self.release_scheduled_session_reservation(sid, token)
            return False
        return True

    def release_scheduled_session_reservation(
        self,
        session_id: str,
        reservation_id: str,
    ) -> None:
        """仅预约 owner 可释放，迟到 release 不得清掉新预约。"""
        sid = (session_id or "").strip()
        token = (reservation_id or "").strip()
        with self._workers_lock:
            if self._session_reservations.get(sid) == token:
                self._session_reservations.pop(sid, None)

    def is_scheduled_session_quiescent(self, session_id: str) -> bool:
        """供显式重置使用：证明 session 当前没有运行态或未收口图。"""
        sid = (session_id or "").strip()
        if not sid:
            return False
        try:
            self._get_orchestrator()
        except Exception:
            logger.error(
                "Cannot initialize runtime before checking scheduled session %s",
                sid,
                exc_info=True,
            )
            return False
        with self._workers_lock:
            worker = self._workers.get(sid)
            if worker is not None and worker.is_alive():
                return False
            if sid in self._session_reservations:
                return False
        return not self.has_pending_reentry(sid) and self._scheduled_session_graphs_quiescent(sid)

    @staticmethod
    def _scheduled_session_graphs_quiescent(session_id: str) -> bool:
        """所有历史图执行节点均终态；查询失败时 fail-closed。"""
        try:
            from src.business.task_collaboration.service import TaskCollaborationService

            with TaskCollaborationService() as service:
                return not service.has_nonterminal_execution_tasks(session_id)
        except Exception:
            logger.error(
                "Cannot confirm graph quiescence for scheduled session %s",
                session_id,
                exc_info=True,
            )
            return False

    def has_pending_reentry(
        self,
        session_id: str,
        graph_id: str | None = None,
    ) -> bool:
        """Return whether reentry work is pending, failing closed before sink setup.

        ``RunCompletionMonitor`` treats ``True`` as "not quiescent".  The sink is
        installed lazily with the orchestrator, so an absent sink means the runtime
        cannot yet prove that the queue is empty; it must not be projected as a
        successful scheduled run.
        """
        sink = self._reentry_sink
        if sink is None:
            logger.warning(
                "Reentry sink is not installed; cannot confirm quiescence for session %s",
                session_id,
            )
            return True
        if graph_id is None:
            return bool(sink.has_pending(session_id))
        return bool(sink.has_pending(session_id, graph_id))

    @staticmethod
    def _is_report_completion(result: object) -> bool:
        """收尾是"向用户汇报"而非"向用户提问"时返回 True。

        主助理给用户的回复统一走 ``reply_to_user``，需要用户拍板才走
        ``ask_user_question``；两者都是中断型工具，都让 AgentLoop 返回
        ``NEEDS_USER_INPUT``，但语义相反——前者是"本轮已交付"，后者才是"等你回话"。
        scheduled run 必须按 ``signal_tool`` 区分：主助理架构上没有别的收尾方式
        （``text_as_user_input=False``），不区分就等于每次正常汇报都被记成待接管，
        run 永不结束、占住 per-task active 槽位，后续每轮到点静默 skipped。

        signal 缺失（非工具触发的 ``NEEDS_USER_INPUT``）一律按提问处理：宁可让用户
        多看一眼，也不把无法证明已交付的一轮报成完成。
        """
        name = getattr(getattr(result, "signal_tool", None), "name", None)
        return name in _REPORT_COMPLETION_SIGNALS

    @staticmethod
    def _mark_scheduled_waiting_user(run_id: str | None) -> bool:
        if not run_id:
            return True
        try:
            from src.business.scheduling.run_completion_monitor import (
                get_run_completion_monitor,
            )

            get_run_completion_monitor().mark_waiting_user(run_id)
            return True
        except Exception:
            logger.error(
                "Failed to mark scheduled run %s waiting_user",
                run_id,
                exc_info=True,
            )
            return False

    @staticmethod
    def _mark_scheduled_failed(run_id: str | None) -> bool:
        if not run_id:
            return True
        try:
            from src.business.scheduling.run_completion_monitor import (
                get_run_completion_monitor,
            )

            get_run_completion_monitor().mark_failed(run_id)
            return True
        except Exception:
            logger.error(
                "Failed to mark scheduled run %s failed",
                run_id,
                exc_info=True,
            )
            return False

    @staticmethod
    def _evaluate_scheduled_completion(run_id: str | None) -> None:
        if not run_id:
            return
        try:
            from src.business.scheduling.run_completion_monitor import (
                get_run_completion_monitor,
            )

            get_run_completion_monitor().evaluate_run(run_id)
        except Exception:
            logger.error(
                "Failed to evaluate scheduled completion for run %s",
                run_id,
                exc_info=True,
            )

    def set_auto_approve(self, enabled: bool) -> bool:
        """开启/关闭"全部允许"免确认，并结算挂起确认（router 编排下沉）。

        开启时同时结算当前挂起的确认队列（toast allow-all 来源）；关闭时仅切标志。
        返回切换后的标志当前值。
        """
        from src.business.agents.tools.builtin_general_tools import (
            CONFIRM_SOURCE_TOAST_ALLOW_ALL,
            CONFIRM_SOURCE_TOP_TOGGLE,
            is_auto_approve_enabled,
            set_auto_approve_enabled,
            settle_pending_confirmations,
        )

        if enabled:
            set_auto_approve_enabled(True, CONFIRM_SOURCE_TOAST_ALLOW_ALL)
            settle_pending_confirmations(True, CONFIRM_SOURCE_TOAST_ALLOW_ALL)
        else:
            set_auto_approve_enabled(False, CONFIRM_SOURCE_TOP_TOGGLE)
        return is_auto_approve_enabled()

    def _spawn_session_worker(
        self,
        session_id: str,
        build_worker: "Callable[[], tuple[threading.Thread, Callable[[], None] | None]]",
        *,
        raise_on_conflict: bool = False,
        reservation_id: str | None = None,
    ) -> bool:
        """单会话 worker 的统一 first-wins 启动协议。

        在 ``_workers_lock`` 下守住"查活跃 worker → 注册 → 启动失败回滚"的不变量，
        三个调用方（dispatch / retry / reentry）只提供各自的准备逻辑。``build_worker``
        仅在锁内、确认无活跃 worker 后调用，返回 ``(worker, on_start_failure)``：``worker``
        是待启动的 daemon 线程，``on_start_failure`` 是 ``worker.start()`` 抛错时的额外
        回滚（无则为 ``None``）。已有活跃 worker 时按 ``raise_on_conflict`` 决定返回 False
        还是抛 :class:`AssistantRetryConflict`。
        """
        with self._workers_lock:
            existing = self._workers.get(session_id)
            if existing is not None and existing.is_alive():
                if raise_on_conflict:
                    raise AssistantRetryConflict("assistant session is already running")
                return False
            active_reservation = self._session_reservations.get(session_id)
            if reservation_id is None:
                if active_reservation is not None:
                    if raise_on_conflict:
                        raise AssistantRetryConflict("assistant session is reserved")
                    return False
            elif active_reservation != reservation_id:
                return False
            worker, on_start_failure = build_worker()
            self._workers[session_id] = worker
            if reservation_id is not None:
                self._session_reservations.pop(session_id, None)
            try:
                worker.start()
            except Exception:
                self._workers.pop(session_id, None)
                if reservation_id is not None:
                    # start 失败时预约所有权仍属于 Launcher；恢复 token，让它先把
                    # 已落库 run 终结，再显式 release，避免同 session 窄窗抢入。
                    self._session_reservations[session_id] = reservation_id
                if on_start_failure is not None:
                    on_start_failure()
                raise
        return True

    def kick_reentry_run(self, session_id: str, graph_id: str) -> bool:
        """回流唤醒：起一个续跑 worker 消费 pending 回流结果并驱动父侧裁定。

        与 ``dispatch_message`` 同构（起新 daemon worker），共享 ``_workers`` +
        ``_workers_lock`` first-wins：已有活跃 worker 时返回 False，回流留队列由该
        worker 首轮 drain。
        """

        def build() -> tuple[threading.Thread, None]:
            after_sequence = self._chat_service.get_latest_display_sequence(session_id)
            scheduled_run_id = self._resolve_scheduled_run_id_for_graph(
                session_id,
                graph_id,
            )
            worker = threading.Thread(
                target=self._run_assistant_reentry,
                args=(session_id, graph_id, after_sequence, scheduled_run_id),
                name=f"AssistantReentry-{session_id}",
                daemon=True,
            )
            return worker, None

        return self._spawn_session_worker(session_id, build)

    def _run_assistant_reentry(
        self,
        session_id: str,
        graph_id: str,
        after_sequence: int,
        scheduled_run_id: str | None = None,
    ) -> None:
        """续跑 worker：drain 回流 → 组装摘要注入主助理 → 续跑决策。"""
        set_confirmation_session_context(session_id)
        run_ctx = run_context.begin(session_id)
        event_queue.publish_nowait(
            "assistant.progress",
            {"status": "running", "headline": "正在处理子任务结果", "runId": run_ctx.run_id},
            {"sessionId": session_id},
        )
        entries: list[dict] = []
        re_enqueued = False
        can_evaluate_scheduled_completion = True
        try:
            entries = self._reentry_sink.drain(session_id, graph_id) if self._reentry_sink else []
            # 024: drain 后查一次 graph snapshot 传入 briefing（DEC-H）
            snapshot = None
            if graph_id is not None:
                from src.business.task_collaboration.service import TaskCollaborationService

                try:
                    with TaskCollaborationService() as service:
                        snapshot = service.get_graph_snapshot(
                            session_id=session_id, graph_id=graph_id
                        )
                except Exception:
                    logger.debug("graph snapshot query failed for briefing, degrading gracefully")
            # 024: 从 snapshot 的 pending adjudications 派生 pending_ids，省一次独立 DB 查询；
            # 无 snapshot 时退回旧路径（service 查询）
            if snapshot is not None:
                pending_ids = {a.adjudication_id for a in snapshot.adjudications}
                entries = filter_pending_entries(entries, pending_ids)
            elif entries and graph_id:
                from src.business.task_collaboration.service import TaskCollaborationService

                with TaskCollaborationService() as service:
                    entries = self._drop_decided_entries(graph_id, entries, service)
            summary = build_reentry_briefing(entries, snapshot=snapshot)
            result = self._get_orchestrator().run_agent(
                AgentType.ASSISTANT,
                {"role": "program", "content": summary},
                session_id=session_id,
            )
            self._publish_display_messages(session_id, after_sequence)
            if result is not None and result.result_type == ResultType.COMPLETED:
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "succeeded", "headline": "子任务结果已处理"},
                    {"sessionId": session_id},
                )
            elif result is not None and result.result_type == ResultType.NEEDS_USER_INPUT:
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "waiting_for_user", "headline": result.question or ""},
                    {"sessionId": session_id},
                )
                # 与主路径同口径：汇报收尾不是在等用户答复，见 _is_report_completion。
                if not self._is_report_completion(result):
                    can_evaluate_scheduled_completion = self._mark_scheduled_waiting_user(
                        scheduled_run_id
                    )
            else:
                # ERROR / 异常结果：续跑未成功，必须发 failed（不能照发 succeeded 让
                # 前端卡在成功）。reentry 失败不接 AssistantFailureService——它没有
                # 自然归属的用户消息回合，重试靠下次 dispatch 回流或用户新消息。
                logger.warning(
                    "[reentry] session %s reentry run ended with %s",
                    session_id,
                    result.result_type if result else None,
                )
                self._publish_reentry_failure(session_id)
                # ERROR 终态同样会让 drained 回流搁浅（has_pending=False → tail-kick
                # 不触发），须像 except 分支一样回填，防 pending adjudication 永久卡在
                # DB；本次不 tail-kick 以免失败立即重试死循环，留待下次 dispatch/新消息。
                if entries and self._reentry_sink is not None:
                    self._reentry_sink.re_enqueue(session_id, entries)
                    re_enqueued = True
                can_evaluate_scheduled_completion = self._mark_scheduled_failed(scheduled_run_id)
        except Exception:
            logger.error("[reentry] session %s reentry run failed", session_id, exc_info=True)
            # drain 已取走的回流回填队列，避免 run_agent 异常导致条目永久丢失。
            # 下次 dispatch（新子任务完成）会重新消费；本次不 tail-kick 以免失败
            # 立即重试死循环。
            if entries and self._reentry_sink is not None:
                self._reentry_sink.re_enqueue(session_id, entries)
                re_enqueued = True
            self._publish_reentry_failure(session_id)
            can_evaluate_scheduled_completion = self._mark_scheduled_failed(scheduled_run_id)
        finally:
            run_context.end()
            clear_confirmation_session_context()
            with self._workers_lock:
                if self._workers.get(session_id) is threading.current_thread():
                    self._workers.pop(session_id, None)
            # tail-kick：续跑期间到达的回流（当时 has_active=True 未 kick）现在补 kick。
            # 但 except 回填的回流不立即重试（re_enqueued），留待下次 dispatch。
            if not re_enqueued and self._reentry_sink is not None:
                next_graph_id = self._reentry_sink.next_pending_graph(session_id)
                if next_graph_id is not None:
                    self.kick_reentry_run(session_id, next_graph_id)
            # ``mark_failed`` / ``mark_waiting_user`` 写入失败时绝不能继续走静默成功
            # 判定，否则简单 scheduled 会话会被误标为 succeeded。保留 running，
            # 等后续权威事件或恢复路径重试，比伪造成功更安全。
            if can_evaluate_scheduled_completion:
                self._evaluate_scheduled_completion(scheduled_run_id)

    def _drop_decided_entries(self, graph_id: str, entries: list[dict], service) -> list[dict]:
        """剔除已决定的回流条目，避免 briefing 重提已 decide 的裁定。

        run_agent 异常回填后，上一轮已 decide 的裁定可能残留队列；不过滤会让 LLM 重复
        裁定撞 LookupError。查询走传入的 business service（adapter 不直接碰 repo）。
        """
        if not entries:
            return entries
        pending_ids = service.pending_adjudication_ids(graph_id)
        return filter_pending_entries(entries, pending_ids)

    def _publish_reentry_failure(self, session_id: str) -> None:
        """续跑失败终态事件（安全 headline，不泄漏内部诊断）。"""
        event_queue.publish_nowait(
            "assistant.progress",
            {"status": "failed", "headline": "处理子任务结果时发生错误，请稍后重试或发新消息。"},
            {"sessionId": session_id},
        )

    @staticmethod
    def _resolve_scheduled_run_id_for_graph(
        session_id: str,
        graph_id: str,
    ) -> str | None:
        try:
            from src.business.scheduling.run_completion_monitor import (
                get_run_completion_monitor,
            )

            return get_run_completion_monitor().resolve_run_id_for_graph(
                session_id=session_id,
                graph_id=graph_id,
            )
        except Exception:
            logger.error(
                "Failed to resolve scheduled run for graph %s in session %s",
                graph_id,
                session_id,
                exc_info=True,
            )
            return None

    @staticmethod
    def _resolve_active_scheduled_run_id(session_id: str) -> str | None:
        try:
            from src.business.scheduling.run_completion_monitor import (
                get_run_completion_monitor,
            )

            return get_run_completion_monitor().get_active_run_id_for_session(session_id)
        except Exception:
            logger.error(
                "Failed to resolve active scheduled run for session %s",
                session_id,
                exc_info=True,
            )
            return None

    def dispatch_message(
        self,
        session_id: str,
        content: str,
        continue_subagent: dict | None = None,
    ) -> bool:
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")
        continue_directive = self._validate_continue_subagent_directive(
            session_id,
            continue_subagent,
        )
        # busy 锁：异步任务在跑期间拒绝新消息（200 + accepted=false，前端进排队态）。
        # 回合正在跑的互斥由 _spawn_session_worker 兜底；这里补"回合空闲但任务在跑"。
        # suspended（等用户回答/额度停）不算 busy——用户此刻该能说话。
        from src.business.task_collaboration.service import TaskCollaborationService

        try:
            with TaskCollaborationService() as service:
                busy = service.has_active_execution_tasks(session_id)
        except Exception:
            logging.warning(
                "[dispatch_message] busy check failed for session=%s; allow message",
                session_id,
                exc_info=True,
            )
            busy = False
        if busy:
            return False
        scheduled_run_id = self._resolve_active_scheduled_run_id(session_id)

        def build() -> tuple[threading.Thread, None]:
            resolved_sequence = self._failure_service.resolve_current_for_new_message(session_id)
            if resolved_sequence is not None:
                self._publish_display_message(session_id, resolved_sequence)
            after_sequence = self._chat_service.get_latest_display_sequence(session_id)
            worker = threading.Thread(
                target=self._run_assistant,
                args=(
                    session_id,
                    content,
                    after_sequence,
                    continue_directive,
                    None,
                    scheduled_run_id,
                ),
                name=f"AssistantRuntime-{session_id}",
                daemon=True,
            )
            return worker, None

        return self._spawn_session_worker(session_id, build)

    def dispatch_reserved_message(
        self,
        session_id: str,
        content: str,
        *,
        scheduled_run_id: str,
        reservation_id: str,
    ) -> bool:
        """把 scheduled session 预约原子转换成携带 ``run_id`` 的 worker。"""
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")
        run_id = (scheduled_run_id or "").strip()
        token = (reservation_id or "").strip()
        if not run_id or not token:
            return False

        def build() -> tuple[threading.Thread, None]:
            resolved_sequence = self._failure_service.resolve_current_for_new_message(session_id)
            if resolved_sequence is not None:
                self._publish_display_message(session_id, resolved_sequence)
            after_sequence = self._chat_service.get_latest_display_sequence(session_id)
            worker = threading.Thread(
                target=self._run_assistant,
                args=(session_id, content, after_sequence, None, None, run_id),
                name=f"AssistantRuntime-{session_id}",
                daemon=True,
            )
            return worker, None

        return self._spawn_session_worker(
            session_id,
            build,
            reservation_id=token,
        )

    def retry_message(
        self,
        session_id: str,
        message_sequence: int,
        content: str | None = None,
    ) -> bool:
        scheduled_run_id = self._resolve_active_scheduled_run_id(session_id)

        def build() -> tuple[threading.Thread, Callable[[], None]]:
            preparation = self._failure_service.prepare_retry(
                session_id,
                message_sequence,
                content,
            )
            after_sequence = self._chat_service.get_latest_display_sequence(session_id)
            directive = RetryDirective(
                failure_id=preparation.failure_id,
                source_message_sequence=preparation.source_message_sequence,
                reuse_user_message=preparation.reuse_user_message,
            )
            worker = threading.Thread(
                target=self._run_assistant,
                args=(
                    session_id,
                    preparation.content,
                    after_sequence,
                    None,
                    directive,
                    scheduled_run_id,
                ),
                name=f"AssistantRuntime-{session_id}",
                daemon=True,
            )
            return worker, lambda: self._failure_service.restore_failed(preparation.failure_id)

        return self._spawn_session_worker(session_id, build, raise_on_conflict=True)

    def _validate_continue_subagent_directive(
        self,
        session_id: str,
        raw: dict | None,
    ) -> ContinueSubagentDirective | None:
        if raw is None:
            return None
        subagent_id = str(raw.get("subagentId") or "").strip()
        if not subagent_id:
            raise ValueError("continueSubagent.subagentId must not be empty")
        supplemental = str(raw.get("supplemental") or "").strip()

        observability = self._obs
        summary = observability.find_subagent_summary(session_id, subagent_id)
        if summary is None:
            raise ValueError("找不到属于当前对话的暂停子任务")
        if summary.status == "running":
            raise ValueError("该子任务仍在运行中，不能重复继续")
        if summary.status != "suspended":
            raise ValueError("只有已暂停的子任务可以继续")
        return ContinueSubagentDirective(
            subagent_id=subagent_id,
            supplemental=supplemental,
            initial_return_transition_count=observability.count_subagent_return_transitions(
                session_id,
                subagent_id,
            ),
        )

    def cancel_session(self, session_id: str, run_id: str | None = None) -> bool:
        """对会话发出协作式停止信号（014）。

        返回 accepted：是否对一个运行中的回合发出了取消（true）/ 当前无运行回合（false）。
        深度穿透由 run_context 的 ContextVar 在同线程同步子 loop 内生效，停止一次父子皆停。
        run_id 来自 assistant.progress 的当前运行令牌；带令牌时拒绝迟到的旧停止请求误停新运行。
        """
        sid = (session_id or "").strip()
        if not sid:
            return False
        expected_run_id = (run_id or "").strip() or None
        accepted = run_context.request_cancel(
            sid,
            expected_run_id=expected_run_id,
            reason=run_context.CancelReason.USER_CANCEL,
        )
        if not accepted:
            with self._workers_lock:
                worker = self._workers.get(sid)
                has_worker = worker is not None and worker.is_alive()
            if has_worker and expected_run_id is None:
                # 停止早于 begin() 登记 Event（早停竞态 C2-E3）：记待停止意图，begin 命中即取消。
                run_context.mark_pending_cancel(
                    sid,
                    reason=run_context.CancelReason.USER_CANCEL,
                )
                accepted = True
        # 若回合此刻阻塞在 pending 高危确认等待中，fail-closed 当拒绝并唤醒回合到下一取消检查点
        # （FR-006b / C2-X1）；CC-001 同步确认协议 first-decision-wins / expires_at 不被破坏。
        if accepted:
            fail_closed_confirmations_for_session(sid)
            # 同理结算该会话仍 pending 的澄清为 stopped 并唤醒阻塞 worker（FR-013）。
            settle_clarifications_for_session_stopped(sid)
            # 033 创建确认卡同样遵守“停止即 fail-closed”：停止后迟到 confirm 不得落库。
            settle_scheduling_confirmations_for_session_stopped(sid)
        return accepted

    def stop_session_all(self, session_id: str, run_id: str | None = None) -> bool:
        """方块停止 = 全停：取消当前回合 + 停掉该会话所有在办用户任务。

        回合取消与任务停止无条件都做——回合可能已结束（cancel 返回 False）但
        异步执行体仍在 dispatcher 线程跑，session 取消信号穿不透异步边界，
        只有 stop_user_task 的图级取消信号能停到它们。
        """
        accepted = self.cancel_session(session_id, run_id=run_id)
        from src.business.user_tasks import UserTaskService

        try:
            with UserTaskService() as service:
                # open = active + cooling：冷却的任务底下也可能有执行在跑，全停不漏
                active_tasks = service.list_for_session(
                    session_id, status_filter="open"
                )
            for task in active_tasks:
                task_id = task.get("taskId") or task.get("task_id")
                if not task_id:
                    continue
                try:
                    self.stop_user_task(session_id, task_id)
                except Exception:
                    logging.warning(
                        "[stop_session_all] stop_user_task failed for %s", task_id,
                        exc_info=True,
                    )
        except Exception:
            logging.warning(
                "[stop_session_all] list active user tasks failed for session=%s",
                session_id,
                exc_info=True,
            )
        return accepted

    def continue_user_task(self, session_id: str, user_task_id: str) -> dict:
        """用户对一件事点「继续」：遍历这件事底下所有图，推得动的都推。

        返回结构化报告（几摊动了/几摊没动/原因）。

        ③ §2.4 原子化：每个任务走 continue_task_atomically（不经过 PENDING_DISPATCH，
        scheduler 不可能抢跑）。
        """
        from src.business.task_collaboration.service import TaskCollaborationService

        with TaskCollaborationService() as service:
            report = service.continue_user_task(
                session_id=session_id,
                user_task_id=user_task_id,
            )
        # 对每个推得动的任务走原子化 continue（跳过 PENDING_DISPATCH）
        orch = self._get_orchestrator()
        actual_pushed: list[dict] = []
        still_finishing: list[dict] = []
        for item in report.get("pushed", []):
            task_id = item.get("task_id")
            if not task_id:
                continue
            try:
                # §2.5 有界等待：如果旧 attempt 还 active（刚 stop），等它停稳。
                # 超时返回 False → 不调 atomic continue，标"正在收尾"。
                settled = orch.wait_for_active_attempt(task_id, timeout_seconds=5.0)
                if not settled:
                    still_finishing.append({"title": item.get("title", ""), "reason": "正在收尾，尚未重新开工"})
                    continue
                # §2.4 规则三：capability_scope 为空时 fail-closed，不续跑
                success = orch.continue_task_atomically(task_id=task_id)
                if success:
                    actual_pushed.append(item)
                else:
                    report.setdefault("not_pushed", []).append(
                        {"title": item.get("title", ""), "reason": "无法续跑（容量冲突或无续跑目标）"}
                    )
            except Exception:
                logging.warning(
                    "continue_user_task: atomic continue failed for task %s",
                    task_id,
                    exc_info=True,
                )
                report.setdefault("not_pushed", []).append(
                    {"title": item.get("title", ""), "reason": "续跑时发生内部错误"}
                )
        # 用实际结果替换 service 层的预判
        report["pushed"] = actual_pushed
        report["still_finishing"] = still_finishing
        report["success"] = len(actual_pushed) > 0 or (
            len(report.get("not_pushed", [])) == 0 and len(still_finishing) == 0
        )
        return report

    def stop_user_task(self, session_id: str, user_task_id: str) -> dict:
        """用户对一件事点「停止」：遍历这件事底下所有图，把正在跑的都停了。

        返回结构化报告（跟 continue_user_task 对称）。
        """
        from src.business.task_collaboration.service import TaskCollaborationService

        with TaskCollaborationService() as service:
            report = service.stop_user_task(
                session_id=session_id,
                user_task_id=user_task_id,
            )
        # side effects（跟 stop_task_graph 一致）
        if report.get("total", 0) > 0:
            fail_closed_confirmations_for_session(session_id)
            settle_clarifications_for_session_stopped(session_id)
            settle_scheduling_confirmations_for_session_stopped(session_id)
        return report

    def resume_recovered_task(self, task_id: str, checkpoint_ref: str) -> bool:
        """Background recovery callback for checkpoint-backed tasks."""
        return self._get_orchestrator().resume_recovered_task(
            task_id=task_id,
            checkpoint_ref=checkpoint_ref,
        )

    def get_transcript(
        self,
        session_id: str,
        subagent_id: str | None = None,
        *,
        after_sequence: int | None = None,
        before_sequence: int | None = None,
    ) -> dict:
        """过程时间线读模型 facade（014）：subagent_id 给定则取该子任务自身过程，否则取主助理过程。

        router 经此 facade 调业务读模型，不直连 Repository。
        """
        observability = self._obs
        target = (subagent_id or "").strip()
        if target:
            summary = observability.find_subagent_summary(session_id, target)
            if summary is None:
                raise LookupError("subagent transcript not found for this session")
        else:
            target = session_id
        result = observability.build_transcript(
            target,
            after_sequence=after_sequence,
            before_sequence=before_sequence,
        )
        return {
            "steps": [
                {
                    "kind": step.kind,
                    "toolName": step.tool_name,
                    "text": step.text,
                    "seq": step.seq,
                    "redacted": step.redacted,
                }
                for step in result.steps
            ],
            "compressed": result.compressed,
        }

    def list_subagents(self, session_id: str) -> dict:
        """Legacy 子任务卡片读模型 facade。

        新的统一任务图 UI/API 读取 `TaskCollaborationService` 快照；此方法只服务
        `/subagents` 兼容端点和旧过程观察面，不能作为 Task 图事实来源。
        """
        items = self._obs.build_subagent_list(session_id)
        # 批量下发 task_id：执行体卡片正面要展示它自己的 todolist，而 todo 按
        # task_id 存，卡片手上只有执行会话 id。一次聚合查询，不做 N+1。
        task_id_map: dict[str, str] = {}
        try:
            from src.data.repos import AssistantTaskAttemptRepository

            with AssistantTaskAttemptRepository() as attempts:
                task_id_map = attempts.latest_tasks_for_sessions(
                    [item.subagent_id for item in items]
                )
        except Exception:
            logging.warning(
                "[subagents] task_id 反查失败，卡片将无 todolist session=%s",
                session_id,
                exc_info=True,
            )
        return {
            "items": [
                {
                    "subagentId": item.subagent_id,
                    "label": item.label,
                    "task": item.task,
                    "status": item.status,
                    "lastOutput": item.last_output,
                    "turnStartSequence": item.turn_start_sequence,
                    "taskId": task_id_map.get(item.subagent_id),
                }
                for item in items
            ]
        }

    def get_executor_detail(
        self, session_id: str, executor_session_id: str
    ) -> dict:
        """执行体详情聚合 facade（⑦ 递归抽屉用）：一次返回某执行体会话的 summary +
        transcript + children（它派出去的子执行体）。

        - summary: ``find_subagent_summary(session_id, executor_session_id)``；
          找不到（如直接以 session_id 取根执行体）时回退用 session_id 造最小 summary。
        - transcript: ``build_transcript(executor_session_id)`` —— 该执行体自己的过程。
        - children: ``build_subagent_list(executor_session_id)`` —— 它委派的下一层执行体。
        """
        observability = self._obs
        target = executor_session_id.strip()
        if not target:
            raise LookupError("executor_session_id required")

        summary_obj = observability.find_subagent_summary(session_id, target)
        if summary_obj is not None:
            summary = {
                "subagentId": summary_obj.subagent_id,
                "label": summary_obj.label,
                "task": summary_obj.task,
                "status": summary_obj.status,
                "lastOutput": summary_obj.last_output,
                "turnStartSequence": summary_obj.turn_start_sequence,
                "taskId": None,
            }
        else:
            # 回退：直接查该 session 取 label/lastOutput（同样包含执行体文本消息）
            transcript_result = observability.build_transcript(
                target, include_final_text=True
            )
            summary = {
                "subagentId": target,
                "label": target,
                "task": "",
                "status": "done",
                "lastOutput": None,
                "turnStartSequence": None,
                "taskId": None,
            }
            return {
                "summary": summary,
                "steps": [
                    {
                        "kind": step.kind,
                        "toolName": step.tool_name,
                        "text": step.text,
                        "seq": step.seq,
                        "redacted": step.redacted,
                    }
                    for step in transcript_result.steps
                ],
                "children": [],
            }

        # 执行体详情：过程步骤 + 它的文本消息（结论只在这一个展示面，必须带上）
        transcript_result = observability.build_transcript(
            target, include_final_text=True
        )
        children = observability.build_subagent_list(target)
        # 批量建立 session→task_id 映射，让前端能按 task_id 加载 todo（⑦ 递归规则）
        all_session_ids = [target] + [c.subagent_id for c in children]
        task_id_map: dict[str, str] = {}
        try:
            from src.data.repos import AssistantTaskAttemptRepository

            with AssistantTaskAttemptRepository() as attempts:
                task_id_map = attempts.latest_tasks_for_sessions(all_session_ids)
        except Exception:
            pass
        summary["taskId"] = task_id_map.get(target)
        return {
            "summary": summary,
            "steps": [
                {
                    "kind": step.kind,
                    "toolName": step.tool_name,
                    "text": step.text,
                    "seq": step.seq,
                    "redacted": step.redacted,
                }
                for step in transcript_result.steps
            ],
            "children": [
                {
                    "subagentId": child.subagent_id,
                    "label": child.label,
                    "task": child.task,
                    "status": child.status,
                    "lastOutput": child.last_output,
                    "turnStartSequence": child.turn_start_sequence,
                    "taskId": task_id_map.get(child.subagent_id),
                }
                for child in children
            ],
        }

    def _publish_display_messages(self, session_id: str, after_sequence: int) -> None:
        """把回合新增的可展示消息按序补发到前端（停止/完成/反问后保证已产内容不丢）。"""
        for message in self._chat_service.get_display_messages_after(session_id, after_sequence):
            self._publish_message(session_id, message)

    def _publish_display_message(self, session_id: str, sequence: int) -> None:
        message = self._chat_service.get_display_message(session_id, sequence)
        if message is not None:
            self._publish_message(session_id, message)

    @staticmethod
    def _publish_message(session_id: str, message) -> None:
        payload = {
            "sequence": message.sequence,
            "role": message.role,
            "content": message.content,
            "createdAt": (message.created_at.isoformat() if message.created_at else None),
            "rendering": (
                "safe_markdown" if message.role in ("assistant", "summary") else "plain_text"
            ),
        }
        if message.failure is not None:
            payload["failure"] = message.failure.to_public_dict()
        event_queue.publish_nowait(
            "assistant.message",
            payload,
            {"sessionId": session_id},
        )

    def _latest_user_sequence_after(self, session_id: str, after_sequence: int) -> int | None:
        messages = self._chat_service.get_display_messages_after(session_id, after_sequence)
        for message in reversed(messages):
            if message.role == "user":
                return message.sequence
        return None

    def _publish_terminal_failure(
        self,
        *,
        session_id: str,
        after_sequence: int,
        result_type: ResultType | None,
        error: str | None,
        exception: BaseException | None,
        retry_directive: RetryDirective | None,
    ) -> None:
        message_sequence = (
            retry_directive.source_message_sequence
            if retry_directive is not None and retry_directive.reuse_user_message
            else self._latest_user_sequence_after(session_id, after_sequence)
        )
        if message_sequence is None:
            if retry_directive is not None:
                self._failure_service.restore_failed(retry_directive.failure_id)
                self._publish_display_message(
                    session_id,
                    retry_directive.source_message_sequence,
                )
            logger.error(
                "Assistant terminal failure has no user message",
                extra={"session_id": session_id},
            )
            safe_headline = "处理这条消息时发生了内部错误。"
        else:
            summary = self._failure_service.record_terminal_failure(
                session_id=session_id,
                message_sequence=message_sequence,
                result_type=result_type,
                error=error,
                exception=exception,
                source_failure_id=(
                    retry_directive.failure_id if retry_directive is not None else None
                ),
            )
            safe_headline = summary.message
            if retry_directive is not None:
                self._publish_display_message(
                    session_id,
                    retry_directive.source_message_sequence,
                )
            self._publish_display_messages(session_id, after_sequence)
        event_queue.publish_nowait(
            "assistant.progress",
            {"status": "failed", "headline": safe_headline},
            {"sessionId": session_id},
        )

    def _resolve_retry(self, session_id: str, retry_directive: RetryDirective) -> None:
        self._failure_service.resolve(retry_directive.failure_id)
        self._publish_display_message(
            session_id,
            retry_directive.source_message_sequence,
        )

    def _restore_cancelled_retry(
        self,
        session_id: str,
        retry_directive: RetryDirective,
    ) -> None:
        self._failure_service.restore_failed(retry_directive.failure_id)
        self._publish_display_message(
            session_id,
            retry_directive.source_message_sequence,
        )

    def _publish_continue_fallback_if_needed(
        self,
        session_id: str,
        directive: ContinueSubagentDirective | None,
    ) -> None:
        if directive is None:
            return
        started = self._obs.continue_subagent_started(
            session_id,
            directive.subagent_id,
            directive.initial_return_transition_count,
        )
        if started:
            return
        event_queue.publish_nowait(
            "assistant.error",
            {
                "message": "这次没有成功唤醒该子任务，请再次点击继续任务，或补充说明后重试。",
                "type": "continue_subagent_not_started",
            },
            {"sessionId": session_id},
        )

    def _run_assistant(
        self,
        session_id: str,
        content: str,
        after_sequence: int,
        continue_directive: ContinueSubagentDirective | None = None,
        retry_directive: RetryDirective | None = None,
        scheduled_run_id: str | None = None,
    ) -> None:
        set_confirmation_session_context(session_id)
        # 在 worker 线程入口登记取消上下文（ContextVar + session→Event）；同线程同步派出的
        # 子代理/专员子 loop 自动继承，深度取消生效。begin() 会命中早到的"待停止"意图（C2-E3）。
        run_ctx = run_context.begin(session_id)
        event_queue.publish_nowait(
            "assistant.progress",
            {"status": "running", "headline": "Assistant is working", "runId": run_ctx.run_id},
            {"sessionId": session_id},
        )
        can_evaluate_scheduled_completion = True
        try:
            result = self._get_orchestrator().run_agent(
                AgentType.ASSISTANT,
                content,
                session_id=session_id,
                assistant_continue_intent=(
                    {
                        "subagent_id": continue_directive.subagent_id,
                        "instruction": continue_directive.supplemental,
                    }
                    if continue_directive is not None
                    else None
                ),
                assistant_reuse_user_message=(
                    retry_directive.reuse_user_message if retry_directive is not None else False
                ),
            )
            if result is None or result.result_type == ResultType.MAX_ITERATIONS_REACHED:
                message = result.error if result is not None else "Assistant did not complete."
                self._publish_terminal_failure(
                    session_id=session_id,
                    after_sequence=after_sequence,
                    result_type=(result.result_type if result is not None else ResultType.ERROR),
                    error=message,
                    exception=None,
                    retry_directive=retry_directive,
                )
                can_evaluate_scheduled_completion = self._mark_scheduled_failed(scheduled_run_id)
                self._publish_continue_fallback_if_needed(session_id, continue_directive)
                return
            if result.result_type == ResultType.ERROR:
                self._publish_terminal_failure(
                    session_id=session_id,
                    after_sequence=after_sequence,
                    result_type=result.result_type,
                    error=result.error,
                    exception=None,
                    retry_directive=retry_directive,
                )
                can_evaluate_scheduled_completion = self._mark_scheduled_failed(scheduled_run_id)
                self._publish_continue_fallback_if_needed(session_id, continue_directive)
                return
            if result.result_type == ResultType.CANCELLED:
                # 用户主动停止（014）：flush 已产增量消息（已产内容不丢，FR-008），发"已停止"进度。
                if retry_directive is not None:
                    self._restore_cancelled_retry(session_id, retry_directive)
                self._publish_display_messages(session_id, after_sequence)
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "cancelled", "headline": "已停止"},
                    {"sessionId": session_id},
                )
                can_evaluate_scheduled_completion = self._mark_scheduled_failed(scheduled_run_id)
                return
            if result.result_type == ResultType.NEEDS_USER_INPUT:
                if retry_directive is not None:
                    self._resolve_retry(session_id, retry_directive)
                self._publish_display_messages(session_id, after_sequence)
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "waiting_for_user", "headline": result.question or ""},
                    {"sessionId": session_id},
                )
                # 汇报收尾对 scheduled run 是"本轮已交付"，不落 waiting_user：终态交给
                # finally 的静默判定（worker 退出 ∧ 无 pending 回流 ∧ 图全终态）裁决。
                # 普通会话的进度事件语义不变，仍是等用户接着说。
                if not self._is_report_completion(result):
                    can_evaluate_scheduled_completion = self._mark_scheduled_waiting_user(
                        scheduled_run_id
                    )
                self._publish_continue_fallback_if_needed(session_id, continue_directive)
                return
            if retry_directive is not None:
                self._resolve_retry(session_id, retry_directive)
            self._publish_display_messages(session_id, after_sequence)
            event_queue.publish_nowait(
                "assistant.progress",
                {"status": "succeeded", "headline": "Assistant response ready"},
                {"sessionId": session_id},
            )
            self._publish_continue_fallback_if_needed(session_id, continue_directive)
        except Exception as exc:
            logger.error(
                "Assistant runtime failed",
                extra={"session_id": session_id, "exception_type": type(exc).__name__},
            )
            self._publish_terminal_failure(
                session_id=session_id,
                after_sequence=after_sequence,
                result_type=ResultType.ERROR,
                error=None,
                exception=exc,
                retry_directive=retry_directive,
            )
            can_evaluate_scheduled_completion = self._mark_scheduled_failed(scheduled_run_id)
        finally:
            run_context.end()
            clear_confirmation_session_context()
            with self._workers_lock:
                if self._workers.get(session_id) is threading.current_thread():
                    self._workers.pop(session_id, None)
            if can_evaluate_scheduled_completion:
                self._evaluate_scheduled_completion(scheduled_run_id)
