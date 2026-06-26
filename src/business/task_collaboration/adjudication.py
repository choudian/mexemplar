"""Parent-side adjudication for Assistant task collaboration."""

from __future__ import annotations

import logging

from src.business.task_collaboration.board import TaskBoardService
from src.business.task_collaboration.models import (
    AdjudicationDecision,
    AdjudicationStatus,
    TERMINAL_TASK_STATUSES,
    TaskStatus,
)
from src.business.task_collaboration.service import (
    TaskCollaborationService,
    emit_adjudication_decided,
    emit_root_failed,
    increment_task_collaboration_counter,
)
from src.business.services.assistant_failure_service import AssistantFailureService
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskClaimRepository,
    AssistantTaskRepository,
)

logger = logging.getLogger(__name__)


class TaskFailureBridge:
    """Bridge failed root task graphs to Assistant run failure cards."""

    def __init__(
        self,
        task_repo: AssistantTaskRepository | None = None,
        failure_service: AssistantFailureService | None = None,
    ) -> None:
        self._tasks = task_repo or AssistantTaskRepository()
        self._failure_service = failure_service or AssistantFailureService()

    def bridge_root_failure(self, *, task_id: str, safe_summary: str) -> object | None:
        task = self._tasks.get_task(task_id)
        if task is None or task.parent_task_id is not None or task.status != TaskStatus.FAILED:
            return None
        if task.user_message_sequence is None:
            return None
        summary = self._failure_service.record_task_root_failure(
            session_id=task.session_id,
            message_sequence=task.user_message_sequence,
            safe_summary=safe_summary,
        )
        emit_root_failed(
            self,
            session_id=task.session_id,
            graph_id=task.graph_id,
            task_id=task.task_id,
            status=task.status,
            safe_explanation=summary.message,
        )
        return summary


class TaskAdjudicationService(AtomicTaskService):
    def __init__(
        self,
        adjudication_repo: AssistantTaskAdjudicationRepository | None = None,
        task_repo: AssistantTaskRepository | None = None,
        claim_repo: AssistantTaskClaimRepository | None = None,
        graph_service: TaskCollaborationService | None = None,
        failure_bridge: TaskFailureBridge | None = None,
        scheduler_callback=None,
    ) -> None:
        # 024: GraphScheduler.on_adjudication_decided 回调
        # 未显式传入时自动从进程级单例解析，避免各调用方独立注入遗忘导致静默退化
        if scheduler_callback is None:
            from src.business.task_collaboration.graph_scheduler import get_graph_scheduler
            scheduler = get_graph_scheduler()
            scheduler_callback = scheduler.on_adjudication_decided if scheduler else None
        self._scheduler_callback = scheduler_callback
        if claim_repo is None and task_repo is not None:
            claim_repo = AssistantTaskClaimRepository(task_repo.session)
        self._init_repos(
            tasks=(AssistantTaskRepository, task_repo),
            adjudications=(AssistantTaskAdjudicationRepository, adjudication_repo),
            claims=(AssistantTaskClaimRepository, claim_repo),
        )
        # graph_service 复用同一对 Repository（同一 session），裁定决策与任务状态翻转在
        # decide() 的同一事务里原子完成。failure_bridge 故意使用独立 session，作为提交后的
        # 旁路副作用在 _atomic() 外执行（见下方 bridge_root_failure 调用），不在裁定事务内。
        self._graph_service = graph_service or TaskCollaborationService(
            task_repo=self._tasks,
            adjudication_repo=self._adjudications,
        )
        self._board_service = TaskBoardService(
            task_repo=self._tasks,
            claim_repo=self._claims,
        )
        self._failure_bridge = failure_bridge or TaskFailureBridge(task_repo=self._tasks)

    def decide(
        self,
        *,
        adjudication_id: str,
        decision: str,
        decided_by: str = "agent",
        instruction: str | None = None,
        session_id: str | None = None,
    ) -> dict:
        resolved_decision = AdjudicationDecision(decision)
        if resolved_decision == AdjudicationDecision.RETURNED and not (instruction or "").strip():
            raise ValueError("instruction is required when returning a task")

        pending = self._adjudications.get_by_id(adjudication_id)
        if pending is None or pending.status != AdjudicationStatus.PENDING:
            raise LookupError("pending adjudication not found")
        task = self._tasks.get_task(pending.task_id)
        if task is None:
            raise LookupError("adjudicated task not found")
        if session_id is not None and task.session_id != session_id:
            raise LookupError("pending adjudication not found")

        # 024 needs_confirmation 节点执行前暂停的放行：ACCEPTED 翻 pending_dispatch 让
        # scheduler 派发执行，而非 completed（节点尚未执行，不能算完成）。与普通结果裁定
        # （执行后回流，ACCEPTED=采纳结果→completed）按 task.requires_confirmation +
        # 当前 suspended 态区分，无需 schema 改（data-model §2.1 kind 字段的等效落地）。
        if (
            resolved_decision == AdjudicationDecision.ACCEPTED
            and task.requires_confirmation
            and task.status == TaskStatus.SUSPENDED
        ):
            target_status = TaskStatus.PENDING_DISPATCH
        else:
            target_status = {
                AdjudicationDecision.ACCEPTED: TaskStatus.COMPLETED,
                AdjudicationDecision.RETURNED: TaskStatus.PENDING_DISPATCH,
                AdjudicationDecision.ABANDONED: TaskStatus.FAILED,
            }[resolved_decision]
        task_session_id = task.session_id
        task_graph_id = task.graph_id
        task_id_value = task.task_id
        # 决策落库 + 任务状态翻转必须同一事务：否则裁定记为 decided 但任务状态
        # 未变时无法重试，看板/任务图陷入半完成态。
        bridge_needed = False
        bridge_task_id = ""
        bridge_safe_summary = ""
        complete_claim = False
        with self._atomic():
            decided = self._adjudications.decide(
                adjudication_id,
                decision=resolved_decision.value,
                decided_by=decided_by,
                instruction=instruction,
            )
            if decided is None:
                raise LookupError("pending adjudication not found")
            updated_task = self._graph_service.update_task_status(
                task_id=task.task_id,
                status=target_status,
                emit=False,
            )
            # FR-007/FR-008：放弃裁定必须级联取消/失败子任务——失败沿链向上冒泡，
            # 下游不应继续执行。子任务取消是终态，不会被 replan 复活。
            if resolved_decision == AdjudicationDecision.ABANDONED:
                self._cascade_cancel_children(
                    parent_task_id=task.task_id,
                    graph_id=task.graph_id,
                )
                # 失败桥接使用独立 session，必须在 _atomic() 外调用以避免跨 session 写入
                # 破坏事务原子性。裁定+状态翻转已在上面原子完成，失败记录是旁路通知。
                bridge_needed = True
                bridge_task_id = task.task_id
                bridge_safe_summary = pending.safe_summary
            elif (
                resolved_decision == AdjudicationDecision.ACCEPTED
                and target_status == TaskStatus.COMPLETED
            ):
                # 仅普通结果采纳（→completed）收尾 claim；needs_confirmation 放行
                # （→pending_dispatch）节点尚未执行、无 claim 可收。
                complete_claim = True
            # I14: update_task_status 返回 None 表示状态翻转失败，final_status 应反映 DB 实际状态
            # 而非期望的目标状态，否则事件发出的 status 与 DB 不一致。
            final_status = updated_task.status if updated_task is not None else task.status

        # I1：失败桥接 / 看板收尾在事务外用独立 session 执行，是裁定提交后的旁路副作用。
        # 各自 try/except 隔离：副作用失败不得回滚已提交的裁定、不得把成功的决策冒泡成
        # 500、不得阻断另一个副作用或后续 emit；失败升 ERROR + 堆栈供排查。claim 失败由
        # lease 过期回收兜底；根失败桥接失败目前无自动兜底，只能靠日志告警。
        if bridge_needed:
            try:
                self._failure_bridge.bridge_root_failure(
                    task_id=bridge_task_id,
                    safe_summary=bridge_safe_summary,
                )
            except Exception:
                increment_task_collaboration_counter("root_failure_bridge_failed")
                logger.error(
                    "[adjudication] root failure bridge failed after decision committed; "
                    "task=%s already failed but failure was not surfaced",
                    bridge_task_id,
                    exc_info=True,
                )
        if complete_claim:
            try:
                self._board_service.complete_active_claim(task_id_value)
            except Exception:
                logger.error(
                    "[adjudication] board claim completion failed after decision committed; "
                    "task=%s claim will be reclaimed by lease expiry",
                    task_id_value,
                    exc_info=True,
                )

        emit_adjudication_decided(
            self,
            session_id=task_session_id,
            graph_id=task_graph_id,
            task_id=task_id_value,
            status=final_status,
        )

        # 024: 通知 GraphScheduler 裁定落定
        self._notify_scheduler_adjudication_decided(
            graph_id=task_graph_id,
            task_id=task_id_value,
            decision=resolved_decision.value,
        )

        return {
            "accepted": True,
            "adjudicationId": adjudication_id,
            "taskId": task_id_value,
            "graphId": task_graph_id,
            "decision": resolved_decision.value,
            "taskStatus": final_status,
        }

    def _notify_scheduler_adjudication_decided(
        self, *, graph_id: str, task_id: str, decision: str
    ) -> None:
        """024: 通知 GraphScheduler 裁定落定。"""
        if self._scheduler_callback is None:
            return
        try:
            self._scheduler_callback(graph_id, task_id, decision)
        except Exception as e:
            logger.warning(
                "scheduler_callback failed for adjudication decide graph=%s task=%s: %s",
                graph_id,
                task_id,
                e,
                exc_info=True,
            )

    def fail_root_graph(
        self,
        *,
        session_id: str,
        safe_summary: str,
    ) -> dict:
        """主助理显式放弃整个用户请求：root task 翻 FAILED + 级联取消下游 + 桥接 run 卡。

        FR-008/CC-004：失败冒到顶 → 桥接 run 级失败。``decide(abandoned)`` 处理的是"有
        pending adjudication 的子任务"，其 bridge 调用因被裁定 task 必有 parent 而从不命中
        ``bridge_root_failure`` 的 root-only 守卫；本方法直接定位当前请求的 root
        （``parent_task_id is None``）翻 FAILED，让 bridge 真正触发，补上"整图放弃 → run 卡"
        这一跳。由主助理在 reentry briefing 判断"子失败导致整个请求无法完成"后显式调用。
        """
        graph_id = self._tasks.get_current_graph_id(session_id)
        if graph_id is None:
            raise LookupError("no active task graph for session")
        root = self._tasks.get_graph_root(graph_id)
        if root is None or root.session_id != session_id:
            raise LookupError("task graph root not found")
        root_task_id = root.task_id
        graph_id_value = root.graph_id
        with self._atomic():
            updated_root = self._graph_service.update_task_status(
                task_id=root_task_id,
                status=TaskStatus.FAILED,
                emit=False,
            )
            # 级联取消下游：失败沿链向下终止，下游不继续执行、不被 replan 复活
            # （与 abandon 裁定同语义，复用 _cascade_cancel_children）。
            self._cascade_cancel_children(
                parent_task_id=root_task_id,
                graph_id=graph_id_value,
            )
            final_status = updated_root.status if updated_root is not None else root.status
        # bridge 用独立 session 在 _atomic() 外执行（与 decide() 同模式）；失败只告警不回滚
        # 已提交的 root FAILED。root.user_message_sequence 为 None 时 bridge 不桥接（无消息
        # 回合可挂失败卡），root 仍 FAILED，由 task_updated 让前端感知。
        try:
            self._failure_bridge.bridge_root_failure(
                task_id=root_task_id,
                safe_summary=safe_summary,
            )
        except Exception:
            increment_task_collaboration_counter("root_failure_bridge_failed")
            logger.error(
                "[adjudication] root failure bridge failed after fail_root_graph committed; "
                "root=%s already failed but failure was not surfaced",
                root_task_id,
                exc_info=True,
            )
        return {
            "abandoned": True,
            "graphId": graph_id_value,
            "rootTaskId": root_task_id,
            "taskStatus": final_status,
        }

    def _cascade_cancel_children(
        self,
        *,
        parent_task_id: str,
        graph_id: str,
    ) -> int:
        """Cancel all non-terminal children of the given parent task.

        FR-007/FR-008: When a task is abandoned, its children must be cancelled
        (terminal, not revivable). This prevents orphaned child tasks from
        continuing to execute after their parent has been declared failed.
        """
        # 顶层一次读取全图任务与边，建 task 字典 + parent→children 邻接，递归复用，
        # 避免每层重读全图、每个子任务单独 get_task（N+1）。
        tasks_by_id = {task.task_id: task for task in self._tasks.list_graph_tasks(graph_id)}
        children_by_parent: dict[str, list[str]] = {}
        for task in tasks_by_id.values():
            if task.parent_task_id:
                children_by_parent.setdefault(task.parent_task_id, []).append(task.task_id)
        for edge in self._tasks.list_graph_edges(graph_id):
            # I2: 仅 dependency 和 delegation 边参与级联取消；
            # question/meeting_channel/resource_request 边的目标节点不应被取消。
            if edge.edge_type in ("dependency", "delegation"):
                children = children_by_parent.setdefault(edge.source_task_id, [])
                if edge.target_task_id not in children:
                    children.append(edge.target_task_id)
        return self._cancel_subtree(parent_task_id, children_by_parent, tasks_by_id)

    def _cancel_subtree(
        self,
        parent_task_id: str,
        children_by_parent: dict[str, list[str]],
        tasks_by_id: dict[str, object],
    ) -> int:
        cancelled = 0
        for child_id in children_by_parent.get(parent_task_id, []):
            child = tasks_by_id.get(child_id)
            if child is not None and child.status not in TERMINAL_TASK_STATUSES:
                result = self._graph_service.update_task_status(
                    task_id=child_id,
                    status=TaskStatus.CANCELLED,
                )
                if result is not None:
                    cancelled += 1
                    # Recursively cancel grandchildren (bounded by _MAX_DELEGATION_DEPTH)
                    cancelled += self._cancel_subtree(child_id, children_by_parent, tasks_by_id)
        return cancelled
