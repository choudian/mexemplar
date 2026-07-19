"""DAG scheduler：确定性、非 LLM 的「按依赖推进器」。

只负责「谁该跑了」；「结果行不行 / 失败咋办 / 高风险放不放行」由主助理裁定。
不替代主助理裁定职责。

核心循环：
1. 扫就绪节点（status=pending_dispatch 且所有 dependency 前置=completed）
2. requires_confirmation=1 → 建裁定暂停，不 dispatch
3. dispatcher.start_attempt_async(node) → running（capacity=1，复用 023）
4. attempt 完成 → 重扫激活下游
5. 全图完成 → 通知主助理汇报

装配：GraphScheduler 由 orchestrator 构造为进程级单例（``set_graph_scheduler``），
dispatcher 经 ``scheduler_callback`` 回调 ``on_attempt_outcome``；其余触发点
（build_task_graph 建图、adjudication decide、background_worker 恢复）通过
blinker 事件 ``graph_scheduler_start_requested`` /
``graph_scheduler_recovery_completed`` 触发，不再由调用方直接取单例。
每次推进用临时 TaskCollaborationService（per-operation session），避免长生命周期
service 的 identity-map stale，与 dispatcher/adjudication 的 per-operation service
模式一致。
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Callable

from src.business.task_collaboration.graph_terminal import compute_graph_terminal_state
from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    AdjudicationDecision,
    TaskEdgeType,
    TaskStatus,
)

if TYPE_CHECKING:
    from src.business.task_collaboration.dispatcher import TaskDispatcher
    from src.business.task_collaboration.parent_reentry_sink import ParentReentrySink
    from src.business.task_collaboration.service import TaskCollaborationService

logger = logging.getLogger(__name__)


class GraphScheduler:
    """DAG 调度器：按依赖关系自动推进任务图中的节点。

    确定性、非 LLM。消费 task/edge 表，通过 dispatcher 派发，
    通过 reentry_sink 通知主助理。
    """

    def __init__(
        self,
        *,
        dispatcher: "TaskDispatcher",
        reentry_sink: "ParentReentrySink | None" = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._reentry_sink = reentry_sink
        self._terminal_observation_lock = threading.Lock()
        self._terminal_observation_versions: dict[str, int] = {}

    def set_reentry_sink(self, sink: "ParentReentrySink | None") -> None:
        """后续注入 reentry_sink（runtime 安装 sink 晚于 scheduler 构造时用）。"""
        self._reentry_sink = sink

    def start_graph(self, graph_id: str) -> None:
        """建图后触发；扫就绪节点开始推进。幂等。"""
        logger.info("GraphScheduler.start_graph: graph_id=%s", graph_id)
        self._run(graph_id, lambda svc: self._advance(svc, graph_id))

    def on_attempt_outcome(self, graph_id: str, task_id: str) -> None:
        """节点 attempt 完成后调；重扫就绪、激活下游、判定全图完成。"""
        logger.info(
            "GraphScheduler.on_attempt_outcome: graph_id=%s task_id=%s",
            graph_id,
            task_id,
        )
        self._run(graph_id, lambda svc: self._advance(svc, graph_id))

    def on_adjudication_decided(
        self, graph_id: str, task_id: str, decision: str | "AdjudicationDecision"
    ) -> None:
        """主助理裁定落定后调。

        accepted(需确认放行)→dispatch；returned/abandoned→重扫(_advance)。
        abandoned 的下游收口由 adjudication.decide 状态机(task→failed 后下游边处理)承担,不在本层。
        """
        logger.info(
            "GraphScheduler.on_adjudication_decided: graph_id=%s task_id=%s decision=%s",
            graph_id,
            task_id,
            decision,
        )

        def _apply(svc: "TaskCollaborationService") -> None:
            if decision == AdjudicationDecision.ACCEPTED:
                # 需确认放行 → dispatch 该节点
                self._dispatch_node(svc, graph_id, task_id)
            else:
                # returned（打回重做，重入就绪扫描）与 abandoned（放弃，重扫下游）都触发重扫
                self._advance(svc, graph_id)

        self._run(graph_id, _apply)

    def on_executor_recovered(self, graph_id: str, task_id: str) -> None:
        """executor lease 过期/崩溃恢复后调；重入就绪重派。"""
        logger.info(
            "GraphScheduler.on_executor_recovered: graph_id=%s task_id=%s",
            graph_id,
            task_id,
        )
        self._run(graph_id, lambda svc: self._advance(svc, graph_id))

    # === 内部方法 ===

    def _run(self, graph_id: str, fn: Callable[["TaskCollaborationService"], None]) -> None:
        """每次推进用临时 service（fresh session）。异常不外泄（调度静默失败只记日志）。"""
        try:
            from src.business.task_collaboration.service import (
                TaskCollaborationService,
                increment_task_collaboration_counter,
            )

            with TaskCollaborationService() as svc:
                fn(svc)
        except Exception as e:
            from src.business.task_collaboration.service import (
                increment_task_collaboration_counter,
            )

            increment_task_collaboration_counter("scheduler_advance_failed")
            logger.error("GraphScheduler._run failed for graph=%s: %s", graph_id, e, exc_info=True)

    def _advance(self, svc: "TaskCollaborationService", graph_id: str) -> None:
        """核心推进循环：扫就绪→判定确认→派发→检查全图完成。

        root 容器节点（``parent_task_id is None``）不参与派发；全图完成 = 所有执行节点
        completed，此时把 root 标 completed（容器收口）并通知主助理汇报。
        """
        snapshot = svc.get_graph_snapshot(
            session_id=self._resolve_session_id(svc, graph_id),
            graph_id=graph_id,
        )
        if snapshot is None:
            logger.warning("GraphScheduler._advance: snapshot not found for %s", graph_id)
            return

        # 单次遍历：区分 root / 执行节点 + 收集 completed_ids（终态统计已抽到公共函数）
        root = None
        real_nodes: list = []
        completed_ids: set[str] = set()
        for t in snapshot.tasks:
            if t.parent_task_id is None:
                root = t
            else:
                real_nodes.append(t)
            if t.status == TaskStatus.COMPLETED:
                completed_ids.add(t.task_id)

        # 全图终态判定（只看执行节点，root 容器不参与）——抽到
        # task_collaboration.graph_terminal.compute_graph_terminal_state 统一复用。
        all_terminal, all_completed = compute_graph_terminal_state(
            snapshot.tasks,
            terminal_statuses=TERMINAL_TASK_STATUSES,
            completed_status=TaskStatus.COMPLETED,
        )

        # 全图完成判定：所有执行节点已终态（全成功 或 含失败/取消）。
        # 契约 §2 规定 all_nodes_terminal → notify：含失败/取消也必须通知主助理裁定后续，
        # 否则自愈跳过/失败收口后整图静默停滞（FR-015/SC-003, constitution IV）。
        # real_nodes 为空（仅 root 容器的退化图）时 all([])=True，也走完成收口，避免空图停滞
        if all_terminal:
            # root 已终态 = 图已收口通知过 → 不重复唤醒主助理
            already_closed = root is not None and root.status in TERMINAL_TASK_STATUSES
            if not already_closed:
                if all_completed and root is not None:
                    # 全成功 → root 容器收口 completed
                    # 必须先完成原有状态副作用，再 claim 新增 observer；否则瞬时 DB
                    # 失败会消费 claim，后续推进永久失去收口重试机会（CC-003）。
                    svc.update_task_status(task_id=root.task_id, status=TaskStatus.COMPLETED)
                # 含失败/取消时不收口 root（保留非终态供主助理裁定 replan/abandon）；
                # 父侧回流保持原有可重试语义，其 sink 自己负责已入队通知的幂等。
                logger.info(
                    "GraphScheduler: graph %s terminal (all_completed=%s)",
                    graph_id,
                    all_completed,
                )
                if self._claim_terminal_observation(graph_id, snapshot.version):
                    try:
                        from src.utils.events import emit

                        emit(
                            "graph_scheduler_terminal",
                            self,
                            graph_id=graph_id,
                            session_id=snapshot.session_id,
                            all_terminal=True,
                            all_completed=all_completed,
                        )
                    except Exception:
                        # 完成监视是观察者，绝不能因其回调失败阻断父侧回流收口。
                        logger.error(
                            "GraphScheduler: graph terminal event failed for %s",
                            graph_id,
                            exc_info=True,
                        )
                self._notify_graph_complete(svc, graph_id, snapshot.session_id)
            return

        # 依赖前置映射（O(E)，非 O(T×E)）
        predecessors: dict[str, list[str]] = {}
        for edge in snapshot.edges:
            if edge.type == TaskEdgeType.DEPENDENCY:
                predecessors.setdefault(edge.target_task_id, []).append(edge.source_task_id)

        for task in real_nodes:
            if task.status != TaskStatus.PENDING_DISPATCH:
                continue

            # 就绪校验：所有 dependency 前置必须 completed
            if any(src not in completed_ids for src in predecessors.get(task.task_id, [])):
                continue

            # requires_confirmation：建裁定暂停等待主助理放行（幂等，已有 pending 则跳过）
            if task.requires_confirmation:
                self._ensure_needs_confirmation_adjudication(
                    svc, graph_id, task.task_id, task.title
                )
                continue

            # 派发就绪节点
            self._dispatch_node(svc, graph_id, task.task_id)

    def _dispatch_node(self, svc: "TaskCollaborationService", graph_id: str, task_id: str) -> None:
        """派发一个就绪节点。"""
        try:
            task = svc.get_task(task_id)
            if task is None:
                logger.warning("GraphScheduler: task %s not found, skip dispatch", task_id)
                return
            if task.status != TaskStatus.PENDING_DISPATCH:
                logger.debug("GraphScheduler: task %s is %s, skip dispatch", task_id, task.status)
                return

            # 就绪硬校验（双层校验的第一层；第二层兜底在 dispatcher.start_attempt_async 派发临界点）
            svc.assert_dependencies_satisfied(graph_id, task_id)

            if task.requires_confirmation and not svc.has_accepted_confirmation(task_id):
                self._ensure_needs_confirmation_adjudication(
                    svc,
                    graph_id,
                    task.task_id,
                    task.title,
                )
                return

            # 确定执行器
            if task.assignee_type == "specialist" and task.assignee_id:
                executor_type = "specialist"
                executor_id = task.assignee_id
            else:
                executor_type = "ephemeral_subagent"
                executor_id = task.task_id

            self._dispatcher.start_attempt_async(
                task_id=task_id,
                executor_type=executor_type,
                executor_id=executor_id,
                lease_owner="graph_scheduler",
            )
            logger.info(
                "GraphScheduler: dispatched task %s (executor=%s/%s)",
                task_id,
                executor_type,
                executor_id,
            )
        except ValueError as e:
            # 就绪硬校验拒绝或派发失败
            logger.warning("GraphScheduler: dispatch failed for task %s: %s", task_id, e)
        except Exception as e:
            logger.error(
                "GraphScheduler: unexpected error dispatching task %s: %s",
                task_id,
                e,
                exc_info=True,
            )

    def _ensure_needs_confirmation_adjudication(
        self,
        svc: "TaskCollaborationService",
        graph_id: str,
        task_id: str,
        title: str,
    ) -> None:
        """为需确认节点原子地建 pending adjudication + 挂起（FR-009，SC-002）。

        委托 ``service.create_needs_confirmation_pause`` 在单个事务内完成 create_pending +
        suspend，避免两步非原子导致「adjudication 已建但节点未挂起」让高风险节点逃过暂停。
        幂等性、title 透传由 service 方法负责。
        """
        try:
            svc.create_needs_confirmation_pause(task_id=task_id, title=title)
            logger.info("GraphScheduler: created needs_confirmation pause for task %s", task_id)
        except Exception as e:
            from src.business.task_collaboration.service import (
                increment_task_collaboration_counter,
            )

            increment_task_collaboration_counter("needs_confirmation_pause_failed")
            logger.warning(
                "GraphScheduler: failed to create needs_confirmation pause for %s (will retry on next advance): %s",
                task_id,
                e,
                exc_info=True,
            )

    def _notify_graph_complete(
        self,
        svc: "TaskCollaborationService",
        graph_id: str,
        session_id: str,
    ) -> None:
        """全图完成 → 通知主助理向用户汇报。

        session_id 由调用方从 snapshot 传入（snapshot 已携带），避免再查一次 get_graph_root。
        """
        if self._reentry_sink is not None:
            try:
                self._reentry_sink.notify_graph_complete(graph_id, session_id)
            except Exception as e:
                logger.error(
                    "GraphScheduler: failed to notify graph complete for %s: %s",
                    graph_id,
                    e,
                    exc_info=True,
                )
        logger.info("GraphScheduler: graph %s complete notification sent", graph_id)

    def _claim_terminal_observation(self, graph_id: str, graph_version: int) -> bool:
        """同一进程内对 ``(graph_id, graph_version)`` 做 first-wins 终态观察。

        graph scheduler 是进程级单例；内部 blinker 事件本身也是进程内观察接缝，因此
        这里用锁只保证新增 observer event 在并发 ``_advance`` 中 emit 一次。它不得
        门控 root 收口或父侧 reentry：这些既有副作用必须保留瞬时失败后的重试语义。
        replan 会 bump ``graph_version``，新的图形态可再次产生一次终态观察。
        """
        with self._terminal_observation_lock:
            if self._terminal_observation_versions.get(graph_id) == graph_version:
                return False
            self._terminal_observation_versions[graph_id] = graph_version
            return True

    def _resolve_session_id(self, svc: "TaskCollaborationService", graph_id: str) -> str:
        """从 graph_id 解析 session_id（经 service 公共表面，不访问私有属性）。"""
        return svc.get_graph_session_id(graph_id)


# === 进程级单例（orchestrator 装配；tool handler / background_worker 经此触发）===

_scheduler_instance: GraphScheduler | None = None


def set_graph_scheduler(scheduler: GraphScheduler | None) -> None:
    """注册/清除进程级 GraphScheduler 单例（orchestrator 装配时调）。"""
    global _scheduler_instance, _subscriptions_installed
    _scheduler_instance = scheduler
    # 拆卸时重置订阅守卫，允许下次装配时重新安装
    if scheduler is None:
        _subscriptions_installed = False


def get_graph_scheduler() -> GraphScheduler | None:
    """取进程级 GraphScheduler 单例（未装配返回 None，调用方优雅降级）。"""
    return _scheduler_instance


def _on_graph_scheduler_start_requested(sender, *, graph_id: str, **_kwargs) -> None:
    """订阅 graph_scheduler_start_requested 事件，触发 scheduler.start_graph。

    scheduler 未装配时静默跳过（图已持久化，后续 dispatch/recovery 兜底）。
    """
    scheduler = get_graph_scheduler()
    if scheduler is None:
        logger.debug(
            "graph_scheduler_start_requested: scheduler not installed, graph_id=%s",
            graph_id,
        )
        return
    try:
        scheduler.start_graph(graph_id)
    except Exception:
        logger.warning(
            "graph_scheduler_start_requested: start_graph failed for %s",
            graph_id,
            exc_info=True,
        )


def _on_graph_scheduler_recovery_completed(
    sender, *, graph_id: str, task_id: str = "", **_kwargs
) -> None:
    """订阅 graph_scheduler_recovery_completed 事件，触发 scheduler.on_executor_recovered。

    scheduler 未装配时静默跳过。
    """
    scheduler = get_graph_scheduler()
    if scheduler is None:
        return
    try:
        scheduler.on_executor_recovered(graph_id, task_id)
    except Exception:
        logger.warning(
            "graph_scheduler_recovery_completed: on_executor_recovered failed for graph=%s",
            graph_id,
            exc_info=True,
        )


_subscriptions_installed = False


def install_graph_scheduler_event_subscriptions() -> None:
    """安装 scheduler 的 blinker 事件订阅。

    由 orchestrator 在装配 scheduler 后调用一次。事件订阅让调用方
    （assistant_tools / recovery）不再需要直接取 scheduler 单例。
    幂等：重复调用不会重复注册。
    """
    global _subscriptions_installed
    if _subscriptions_installed:
        return
    _subscriptions_installed = True
    from src.utils.events import connect

    connect("graph_scheduler_start_requested", _on_graph_scheduler_start_requested)
    connect("graph_scheduler_recovery_completed", _on_graph_scheduler_recovery_completed)
