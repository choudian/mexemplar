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
``get_graph_scheduler()`` 取单例显式触发。每次推进用临时 TaskCollaborationService
（per-operation session），避免长生命周期 service 的 identity-map stale，与
dispatcher/adjudication 的 per-operation service 模式一致。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

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

    def on_adjudication_decided(self, graph_id: str, task_id: str, decision: str) -> None:
        """主助理裁定落定后调。

        accepted(需确认放行)→dispatch；returned→重派/改图后续；abandoned→取消下游。
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
            from src.business.task_collaboration.service import TaskCollaborationService

            with TaskCollaborationService() as svc:
                fn(svc)
        except Exception as e:
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

        # 区分 root 容器与执行节点
        root = next((t for t in snapshot.tasks if t.parent_task_id is None), None)
        real_nodes = [t for t in snapshot.tasks if t.parent_task_id is not None]

        # 全图完成判定：所有执行节点已终态（全成功 或 含失败/取消）。
        # 契约 §2 规定 all_nodes_terminal → notify：含失败/取消也必须通知主助理裁定后续，
        # 否则自愈跳过/失败收口后整图静默停滞（FR-015/SC-003, constitution IV）。
        # real_nodes 为空（仅 root 容器的退化图）时 all([])=True，也走完成收口，避免空图停滞
        if all(t.status in TERMINAL_TASK_STATUSES for t in real_nodes):
            all_completed = all(t.status == TaskStatus.COMPLETED for t in real_nodes)
            # root 已终态 = 图已收口通知过 → 不重复唤醒主助理
            already_closed = root is not None and root.status in TERMINAL_TASK_STATUSES
            if not already_closed:
                if all_completed and root is not None:
                    # 全成功 → root 容器收口 completed
                    svc.update_task_status(task_id=root.task_id, status=TaskStatus.COMPLETED)
                # 含失败/取消时不收口 root（保留非终态供主助理裁定 replan/abandon）；
                # 重复触发 _advance 的堆积由 sink 的 graph 级去重兜底（未消费的
                # graph_completed 不重复入队，drain 清除后允许下次再通知）
                logger.info(
                    "GraphScheduler: graph %s terminal (all_completed=%s)",
                    graph_id,
                    all_completed,
                )
                self._notify_graph_complete(svc, graph_id, snapshot.session_id)
            return

        # 扫就绪执行节点：completed 集合 + dependency 前置映射单次构造（O(T+E)，非 O(T×E)）
        completed_ids = {t.task_id for t in snapshot.tasks if t.status == TaskStatus.COMPLETED}
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
            if task.status != "pending_dispatch":
                logger.debug("GraphScheduler: task %s is %s, skip dispatch", task_id, task.status)
                return

            # 就绪硬校验（双层校验的第二层；第一层在 dispatcher 派发临界点）
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
            logger.error("GraphScheduler: unexpected error dispatching task %s: %s", task_id, e)

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
            logger.info(
                "GraphScheduler: created needs_confirmation pause for task %s", task_id
            )
        except Exception as e:
            logger.error(
                "GraphScheduler: failed to create needs_confirmation pause for %s: %s",
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

    def _resolve_session_id(self, svc: "TaskCollaborationService", graph_id: str) -> str:
        """从 graph_id 解析 session_id。"""
        root = svc._tasks.get_graph_root(graph_id)
        if root is not None:
            return root.session_id
        return ""


# === 进程级单例（orchestrator 装配；tool handler / background_worker 经此触发）===

_scheduler_instance: GraphScheduler | None = None


def set_graph_scheduler(scheduler: GraphScheduler | None) -> None:
    """注册/清除进程级 GraphScheduler 单例（orchestrator 装配时调）。"""
    global _scheduler_instance
    _scheduler_instance = scheduler


def get_graph_scheduler() -> GraphScheduler | None:
    """取进程级 GraphScheduler 单例（未装配返回 None，调用方优雅降级）。"""
    return _scheduler_instance
