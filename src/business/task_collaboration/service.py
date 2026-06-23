"""Authoritative Assistant task graph facade."""

from __future__ import annotations

from collections.abc import Callable

from src.business.task_collaboration.events import (
    emit_board_changed,
    emit_graph_changed,
    emit_task_updated,
)
from src.business.task_collaboration.models import (
    TaskAdjudicationSnapshot,
    TaskAssignee,
    TaskEdgeSnapshot,
    TaskGraphSnapshot,
    TaskSnapshot,
    TaskStatus,
    SuspendReason,
    TERMINAL_TASK_STATUSES,
    derive_display_phase,
    safe_public_preview,
    validate_task_transition,
)
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import AssistantTaskAdjudicationRepository, AssistantTaskRepository
from src.data.repos.assistant_task_repository import graph_version_from_tasks
from src.data.repos.base_repository import generate_id

# FR-023：委派拓扑结构上封顶为"枢纽单层 + 一级延伸"——根任务(深度 0) → 一级被委派者(1)
# → 专员的至多一个临时子代理(2)。深度 2 的任务不得再有子任务，结构上杜绝无限/循环委派。
_MAX_DELEGATION_DEPTH = 2
_PENDING_REVIEW_EXPLANATION = "等待上级检查结果"


class TaskCollaborationService(AtomicTaskService):
    def __init__(
        self,
        task_repo: AssistantTaskRepository | None = None,
        adjudication_repo: AssistantTaskAdjudicationRepository | None = None,
    ) -> None:
        # 守卫：task_repo 与 adjudication_repo 必须同时注入或同时省略。只注入一个
        # 时，未注入的 repo 会走 ``repo_cls()`` 自建独立 session，``_atomic`` 只
        # commit ``self._session`` 指向的那个，跨 repo 的原子写（如
        # ``create_parent_adjudication``）会在孤立 session 里未提交。校验注入完整
        # 性而非 session 一致性——因为 ``TaskMeetingService`` 内部组合总是同时传
        # 入两个 repo（即便在 stub 单元测试里它们 session 不同也无害，不触发跨
        # repo 原子写），通用 session 校验会误伤那种合法模式。
        if (task_repo is None) != (adjudication_repo is None):
            raise RuntimeError(
                "TaskCollaborationService requires task_repo and adjudication_repo "
                "to be injected together or both omitted; partial injection splits "
                "the shared session and breaks cross-repository atomicity."
            )
        self._init_repos(
            tasks=(AssistantTaskRepository, task_repo),
            adjudications=(AssistantTaskAdjudicationRepository, adjudication_repo),
        )

    def create_root_graph(
        self,
        *,
        session_id: str,
        title: str,
        description: str,
        user_message_sequence: int | None = None,
        graph_id: str | None = None,
    ) -> str:
        resolved_graph_id = graph_id or generate_id("tg")
        # 根任务的 root_task_id 在创建时一次性写入（指向自身），避免"先建后改"的第二次
        # commit——第二次失败会把 root_task_id 留成 NULL，且业务层直接 commit 仓库 session
        # 越界访问数据层。
        new_task_id = generate_id("tsk")
        with self._atomic():
            task = self._tasks.create_task(
                graph_id=resolved_graph_id,
                session_id=session_id,
                task_id=new_task_id,
                root_task_id=new_task_id,
                title=title,
                description=description,
                user_message_sequence=user_message_sequence,
                owner_session_id=session_id,
            )
            status = task.status
        emit_graph_changed(
            self,
            session_id=session_id,
            graph_id=resolved_graph_id,
            change_type="graph_created",
            task_id=new_task_id,
            status=status,
            display_phase=derive_display_phase(status),
        )
        return resolved_graph_id

    def create_child_task(
        self,
        *,
        graph_id: str,
        session_id: str,
        parent_task_id: str,
        title: str,
        description: str,
        assignee_type: str | None = None,
        assignee_id: str | None = None,
        capability_scope: str | None = None,
    ) -> str:
        parent = self._tasks.get_task(parent_task_id)
        if parent is not None and self._task_depth(parent) >= _MAX_DELEGATION_DEPTH:
            raise ValueError("delegation depth exceeds bounded topology (hub + one extension)")
        # FR-011 / plan：replan 不得在已取消的祖先下新建任务——被取消的方向是终态，
        # 不返工、不复活。cancel_graph 的图版本围栏防并发 replan 插入新下游逃过取消波，
        # 这里防同一波次内显式在已取消的 parent / root 下建子任务。
        if parent is not None:
            if parent.status == TaskStatus.CANCELLED:
                raise ValueError("cannot create task under a cancelled parent")
            root_id_for_check = parent.root_task_id
            if root_id_for_check and root_id_for_check != parent_task_id:
                root_task = self._tasks.get_task(root_id_for_check)
                if root_task is not None and root_task.status == TaskStatus.CANCELLED:
                    raise ValueError("cannot create task under a cancelled root graph")
        from src.data.unified_config import get_unified_config

        max_tasks = get_unified_config().get_assistant_tasks_graph_max_tasks()
        if len(self._tasks.list_graph_tasks(graph_id)) >= max_tasks:
            raise ValueError("task graph exceeds configured task budget")
        root_task_id = parent.root_task_id if parent else parent_task_id
        with self._atomic():
            task = self._tasks.create_task(
                graph_id=graph_id,
                session_id=session_id,
                parent_task_id=parent_task_id,
                root_task_id=root_task_id,
                title=title,
                description=description,
                owner_session_id=session_id,
                assignee_type=assignee_type,
                assignee_id=assignee_id,
                capability_scope=capability_scope,
            )
            self._tasks.add_edge(
                graph_id=graph_id,
                source_task_id=parent_task_id,
                target_task_id=task.task_id,
                edge_type="delegation",
                propagation="blocking",
            )
            new_task_id = task.task_id
            status = task.status
        emit_graph_changed(
            self,
            session_id=session_id,
            graph_id=graph_id,
            change_type="task_created",
            task_id=new_task_id,
            status=status,
            display_phase=derive_display_phase(status),
        )
        if not (assignee_type and assignee_id):
            emit_board_changed(self, task, change_type="opened", claim_status="open")
        return new_task_id

    def _task_depth(self, task) -> int:
        """沿 parent_task_id 链上溯，返回任务在委派树中的深度（根为 0）。"""
        depth = 0
        current = task
        seen: set[str] = set()
        while current is not None and current.parent_task_id is not None:
            if current.task_id in seen:
                break
            seen.add(current.task_id)
            depth += 1
            current = self._tasks.get_task(current.parent_task_id)
        return depth

    def update_task_status(
        self,
        *,
        task_id: str,
        status: str,
        suspend_reason: str | None = None,
        expected_task_version: int | None = None,
        emit: bool = True,
    ):
        current = self._tasks.get_task(task_id)
        if current is None:
            return None
        validate_task_transition(
            current.status,
            status,
            suspend_reason=suspend_reason,
        )
        with self._atomic():
            task = self._tasks.update_status(
                task_id,
                status=status,
                expected_task_version=expected_task_version,
                suspend_reason=suspend_reason,
            )
        if task is not None and emit:
            emit_task_updated(self, task)
        return task

    def get_task(self, task_id: str):
        """Public query for a task row (used by reentry sink to resolve session/graph)."""
        return self._tasks.get_task(task_id)

    def create_parent_adjudication(
        self,
        *,
        task_id: str,
        delivered_status: str,
        safe_summary: str,
        raw_result_ref: str | None = None,
    ):
        task = self._tasks.get_task(task_id)
        if task is None:
            return None
        existing = self._adjudications.get_pending_for_task(task_id)
        if existing is not None:
            return existing
        task_session_id = task.session_id
        task_graph_id = task.graph_id
        task_status = task.status
        with self._atomic():
            adjudication = self._adjudications.create_pending(
                task_id=task.task_id,
                graph_id=task.graph_id,
                parent_session_id=task.owner_session_id or task.session_id,
                delivered_status=delivered_status,
                safe_summary=safe_public_preview(safe_summary, key="safeSummary"),
                raw_result_ref=raw_result_ref,
            )
        emit_graph_changed(
            self,
            session_id=task_session_id,
            graph_id=task_graph_id,
            change_type="adjudication_created",
            task_id=task_id,
            status=task_status,
            display_phase=derive_display_phase(task_status, has_pending_adjudication=True),
            requires_review=True,
            safe_explanation=_PENDING_REVIEW_EXPLANATION,
        )
        return adjudication

    def get_current_graph_snapshot(self, session_id: str) -> TaskGraphSnapshot | None:
        graph_id = self._tasks.get_current_graph_id(session_id)
        if graph_id is None:
            return None
        return self.get_graph_snapshot(session_id=session_id, graph_id=graph_id)

    def get_or_create_request_graph_root(
        self,
        *,
        session_id: str,
        user_message_sequence: int | None,
        title: str,
        description: str,
    ) -> tuple[str, str]:
        """找到本次用户请求的任务图并返回 (graph_id, root_task_id)，没有就新建。

        图按 ``user_message_sequence`` 隔离：同一条用户消息（同一次请求）内的多次委派
        复用同一张图；新的用户消息（新 sequence）开新图，不会把新任务粘到上一条消息
        已完成或被中途放弃的旧图上。``user_message_sequence`` 为 None（无消息上下文）时
        每次都新建，避免误复用会话里的任意旧图。
        """
        if user_message_sequence is not None:
            graph_id = self._tasks.get_current_graph_id(session_id, user_message_sequence)
            if graph_id is not None:
                root = self._tasks.get_graph_root(graph_id)
                if root is not None:
                    return graph_id, root.task_id
        graph_id = self.create_root_graph(
            session_id=session_id,
            title=title,
            description=description,
            user_message_sequence=user_message_sequence,
        )
        root = self._tasks.get_graph_root(graph_id)
        if root is None:
            raise RuntimeError("failed to create unified task graph root")
        return graph_id, root.task_id

    def pending_adjudication_ids(self, graph_id: str) -> set[str]:
        """该图所有仍 pending 的裁定 ID，供续跑 briefing 过滤已决定条目。"""
        return {
            adjudication.adjudication_id
            for adjudication in self._adjudications.list_pending_for_graph(graph_id)
        }

    def get_graph_snapshot(self, *, session_id: str, graph_id: str) -> TaskGraphSnapshot | None:
        tasks = self._tasks.list_graph_tasks(graph_id)
        if not tasks or any(task.session_id != session_id for task in tasks):
            return None
        edges = self._tasks.list_graph_edges(graph_id)
        pending_by_task = {
            adjudication.task_id: adjudication
            for adjudication in self._adjudications.list_pending_for_graph(graph_id)
        }
        snapshots: list[TaskSnapshot] = []
        adjudication_items: list[TaskAdjudicationSnapshot] = []
        for task in tasks:
            pending = pending_by_task.get(task.task_id)
            if pending is not None:
                adjudication_items.append(
                    TaskAdjudicationSnapshot(
                        adjudication_id=pending.adjudication_id,
                        task_id=pending.task_id,
                        safe_summary=pending.safe_summary,
                        delivered_status=pending.delivered_status,
                    )
                )
            snapshots.append(
                TaskSnapshot(
                    task_id=task.task_id,
                    graph_id=task.graph_id,
                    parent_task_id=task.parent_task_id,
                    title=safe_public_preview(task.title, key="title", max_chars=80),
                    description_preview=safe_public_preview(
                        task.description, key="descriptionPreview"
                    ),
                    status=task.status,
                    display_phase=derive_display_phase(
                        task.status,
                        has_pending_adjudication=pending is not None,
                    ),
                    requires_review=pending is not None,
                    safe_explanation=_PENDING_REVIEW_EXPLANATION if pending is not None else "",
                    suspend_reason=task.suspend_reason,
                    assignee=(
                        TaskAssignee(
                            type=task.assignee_type,
                            id=task.assignee_id,
                            label=task.assignee_id,
                        )
                        if task.assignee_type and task.assignee_id
                        else None
                    ),
                    adjudication_id=pending.adjudication_id if pending else None,
                    updated_at=task.updated_at,
                )
            )
        return TaskGraphSnapshot(
            graph_id=graph_id,
            session_id=session_id,
            user_message_sequence=tasks[0].user_message_sequence,
            version=graph_version_from_tasks(tasks),
            tasks=snapshots,
            edges=[
                TaskEdgeSnapshot(
                    source_task_id=edge.source_task_id,
                    target_task_id=edge.target_task_id,
                    type=edge.edge_type,
                )
                for edge in edges
            ],
            adjudications=adjudication_items,
        )

    def _bulk_transition(
        self,
        *,
        session_id: str,
        graph_id: str,
        predicate: Callable[[object], bool],
        target_status: str,
        suspend_reason: str | None = None,
        expected_graph_version: int | None = None,
        change_type: str,
    ) -> int:
        """对图内满足 ``predicate`` 的任务批量翻成 ``target_status``。

        stop/continue/cancel 三个图级动作结构同构：在事务边界内读图、校验 session 归属、按
        predicate 筛选、per-task 校验迁移合法性、批量 update_status，最后发 per-task
        ``task_updated`` 与一次图级 ``graph_changed``。``expected_graph_version`` 仅 cancel
        用作并发围栏。``update_status`` 对 ``suspend_reason=None`` 与不传等价（都清空该列）。
        """
        affected = 0
        updated_tasks: list = []
        with self._atomic():
            # 事务边界内读取任务列表，防止并发写入逃过本次波次
            tasks = self._tasks.list_graph_tasks(graph_id)
            if not tasks or any(task.session_id != session_id for task in tasks):
                raise LookupError("task graph not found")
            if expected_graph_version is not None:
                # FR-011：cancel 必须带图版本围栏，防止并发 replan 插入的新下游逃过取消波。
                current_version = graph_version_from_tasks(tasks)
                if current_version != expected_graph_version:
                    raise ValueError(
                        f"graph version mismatch: expected {expected_graph_version}, "
                        f"current {current_version}; re-fetch snapshot before cancelling"
                    )
            for task in tasks:
                if not predicate(task):
                    continue
                validate_task_transition(
                    task.status, target_status, suspend_reason=suspend_reason
                )
                updated = self._tasks.update_status(
                    task.task_id,
                    status=target_status,
                    suspend_reason=suspend_reason,
                )
                if updated is not None:
                    updated_tasks.append(updated)
                    affected += 1
        for updated in updated_tasks:
            emit_task_updated(self, updated)
        emit_graph_changed(
            self,
            session_id=session_id,
            graph_id=graph_id,
            change_type=change_type,
            display_phase=derive_display_phase(target_status),
        )
        return affected

    def stop_graph(self, *, session_id: str, graph_id: str) -> int:
        return self._bulk_transition(
            session_id=session_id,
            graph_id=graph_id,
            predicate=lambda task: task.status
            in {TaskStatus.PENDING_DISPATCH, TaskStatus.RUNNING},
            target_status=TaskStatus.SUSPENDED,
            suspend_reason=SuspendReason.USER_STOP,
            change_type="graph_stopped",
        )

    def continue_graph(self, *, session_id: str, graph_id: str) -> int:
        return self._bulk_transition(
            session_id=session_id,
            graph_id=graph_id,
            predicate=lambda task: task.status == TaskStatus.SUSPENDED
            and task.suspend_reason == SuspendReason.USER_STOP,
            target_status=TaskStatus.PENDING_DISPATCH,
            change_type="graph_continued",
        )

    def cancel_graph(
        self,
        *,
        session_id: str,
        graph_id: str,
        expected_graph_version: int | None = None,
    ) -> int:
        return self._bulk_transition(
            session_id=session_id,
            graph_id=graph_id,
            predicate=lambda task: task.status not in TERMINAL_TASK_STATUSES,
            target_status=TaskStatus.CANCELLED,
            expected_graph_version=expected_graph_version,
            change_type="graph_cancelled",
        )

    @staticmethod
    def snapshot_to_dict(snapshot: TaskGraphSnapshot) -> dict:
        """显式构建 camelCase dict，不原地修改 asdict 输出，保持不可变风格。"""
        return {
            "graphId": snapshot.graph_id,
            "sessionId": snapshot.session_id,
            "userMessageSequence": snapshot.user_message_sequence,
            "version": snapshot.version,
            "tasks": [
                {
                    "taskId": t.task_id,
                    "graphId": t.graph_id,
                    "parentTaskId": t.parent_task_id,
                    "title": t.title,
                    "descriptionPreview": t.description_preview,
                    "status": t.status,
                    "displayPhase": t.display_phase,
                    "requiresReview": t.requires_review,
                    "safeExplanation": t.safe_explanation,
                    "suspendReason": t.suspend_reason,
                    "assignee": t.assignee,
                    "adjudicationId": t.adjudication_id,
                    "updatedAt": t.updated_at,
                }
                for t in snapshot.tasks
            ],
            "edges": [
                {
                    "sourceTaskId": e.source_task_id,
                    "targetTaskId": e.target_task_id,
                    "type": e.type,
                }
                for e in snapshot.edges
            ],
            "adjudications": [
                {
                    "adjudicationId": a.adjudication_id,
                    "taskId": a.task_id,
                    "safeSummary": a.safe_summary,
                    "deliveredStatus": a.delivered_status,
                }
                for a in snapshot.adjudications
            ],
        }
