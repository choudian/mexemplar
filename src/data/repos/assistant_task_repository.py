"""Repository for Assistant task graph rows."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from src.data.models_sqlite import AssistantTask, AssistantTaskEdge
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class AssistantTaskRepository(BaseRepository):
    def create_task(
        self,
        *,
        graph_id: str,
        session_id: str,
        title: str,
        description: str,
        task_id: str | None = None,
        root_task_id: str | None = None,
        parent_task_id: str | None = None,
        user_message_sequence: int | None = None,
        owner_session_id: str | None = None,
        assignee_type: str | None = None,
        assignee_id: str | None = None,
        capability_scope: str | None = None,
        status: str = "pending_dispatch",
    ) -> AssistantTask:
        self.ensure_immediate_transaction()
        row = AssistantTask(
            task_id=task_id or generate_id("tsk"),
            graph_id=graph_id,
            root_task_id=root_task_id,
            parent_task_id=parent_task_id,
            session_id=session_id,
            user_message_sequence=user_message_sequence,
            title=title,
            description=description,
            owner_session_id=owner_session_id,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            capability_scope=capability_scope,
            status=status,
        )
        if row.root_task_id is None and row.parent_task_id is not None:
            row.root_task_id = row.parent_task_id
        return self._add_and_flush(row)

    def get_task(self, task_id: str) -> AssistantTask | None:
        return self.session.get(AssistantTask, task_id)

    def list_graph_tasks(self, graph_id: str) -> list[AssistantTask]:
        rows = (
            self.session.query(AssistantTask)
            .filter(AssistantTask.graph_id == graph_id)
            .all()
        )
        return sorted(
            rows,
            key=lambda task: (
                task.parent_task_id is not None,
                task.created_at or datetime.min,
                task.task_id,
            ),
        )

    def get_graph_root(self, graph_id: str) -> AssistantTask | None:
        """返回图的根任务（``parent_task_id`` 为空）。

        只需 root task id 时用它，避免为取一个 id 去 ``list_graph_tasks`` + ``list_graph_edges``
        + pending adjudication 构建整张图 snapshot。
        """
        return (
            self.session.query(AssistantTask)
            .filter(
                AssistantTask.graph_id == graph_id,
                AssistantTask.parent_task_id.is_(None),
            )
            .order_by(AssistantTask.created_at)
            .first()
        )

    def get_current_graph_id(
        self, session_id: str, user_message_sequence: int | None = None
    ) -> str | None:
        query = self.session.query(AssistantTask.graph_id).filter(
            AssistantTask.session_id == session_id,
            AssistantTask.parent_task_id.is_(None),
        )
        if user_message_sequence is not None:
            query = query.filter(AssistantTask.user_message_sequence == user_message_sequence)
        row = query.order_by(AssistantTask.created_at.desc()).first()
        return row[0] if row else None

    def add_edge(
        self,
        *,
        graph_id: str,
        source_task_id: str,
        target_task_id: str,
        edge_type: str,
        propagation: str = "none",
        edge_id: str | None = None,
    ) -> AssistantTaskEdge:
        self.ensure_immediate_transaction()
        self._assert_no_cycle(graph_id, source_task_id, target_task_id)
        # FR-011：每次加边（replan/扩展下游）递增 root 的 graph_version，作为 cancel 的并发围栏——
        # 否则 graph_version 恒为 1，cancel 的版本校验形同虚设，并发 replan 插入的新下游会逃过取消。
        source = self.get_task(source_task_id)
        root_id = (source.root_task_id if source is not None else None) or source_task_id
        root = self.get_task(root_id) if root_id else None
        if root is not None:
            root.graph_version += 1
        row = AssistantTaskEdge(
            edge_id=edge_id or generate_id("edge"),
            graph_id=graph_id,
            source_task_id=source_task_id,
            target_task_id=target_task_id,
            edge_type=edge_type,
            propagation=propagation,
        )
        return self._add_and_flush(row)

    def list_graph_edges(self, graph_id: str) -> list[AssistantTaskEdge]:
        return (
            self.session.query(AssistantTaskEdge)
            .filter(AssistantTaskEdge.graph_id == graph_id)
            .order_by(AssistantTaskEdge.created_at, AssistantTaskEdge.edge_id)
            .all()
        )

    def update_status(
        self,
        task_id: str,
        *,
        status: str,
        expected_task_version: int | None = None,
        suspend_reason: str | None = None,
    ) -> AssistantTask | None:
        self.ensure_immediate_transaction()
        row = self.get_task(task_id)
        if row is None:
            self._abort_conflict()
            return None
        if expected_task_version is not None and row.task_version != expected_task_version:
            self._abort_conflict()
            return None
        now = utc_now_naive()
        row.status = status
        row.suspend_reason = suspend_reason
        row.task_version += 1
        row.updated_at = now
        if status == "completed":
            row.completed_at = now
        elif status == "failed":
            row.failed_at = now
        elif status == "cancelled":
            row.cancelled_at = now
        return self._update_and_flush(row)

    def update_capability_scope(self, task_id: str, capability_scope: str) -> AssistantTask | None:
        self.ensure_immediate_transaction()
        row = self.get_task(task_id)
        if row is None:
            self._abort_conflict()
            return None
        row.capability_scope = capability_scope
        row.task_version += 1
        row.updated_at = utc_now_naive()
        return self._update_and_flush(row)

    def _refetch_task(self, task_id: str) -> AssistantTask | None:
        """条件 UPDATE（``synchronize_session=False``）后只刷新本行的权威态。

        ``populate_existing`` 比 ``expire_all`` 窄，不殃及共享 session 里已加载的 claim 等对象。
        """
        return (
            self.session.query(AssistantTask)
            .populate_existing()
            .filter(AssistantTask.task_id == task_id)
            .one_or_none()
        )

    def assign_if_version(
        self,
        task_id: str,
        *,
        assignee_type: str,
        assignee_id: str,
        expected_task_version: int,
    ) -> AssistantTask | None:
        # 原子条件 UPDATE：task_version + 未占用守卫进 SQL。看板认领跑在独立连接、不共用
        # _write_lock；ORM read-check-write 在并发下两双都能过守卫并盲写 -> 双认领、assignee
        # 被后写覆盖。条件 UPDATE 让第二笔匹配 0 行返回 None（认领冲突）。
        self.ensure_immediate_transaction()
        updated = (
            self.session.query(AssistantTask)
            .filter(
                AssistantTask.task_id == task_id,
                AssistantTask.task_version == expected_task_version,
                AssistantTask.assignee_type.is_(None),
                AssistantTask.assignee_id.is_(None),
            )
            .update(
                {
                    "assignee_type": assignee_type,
                    "assignee_id": assignee_id,
                    "task_version": AssistantTask.task_version + 1,
                    "updated_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        if updated == 0:
            self._abort_conflict()
            return None
        self._commit()
        return self._refetch_task(task_id)

    def unassign_if_assignee(
        self,
        task_id: str,
        *,
        assignee_type: str,
        assignee_id: str,
    ) -> AssistantTask | None:
        self.ensure_immediate_transaction()
        updated = (
            self.session.query(AssistantTask)
            .filter(
                AssistantTask.task_id == task_id,
                AssistantTask.assignee_type == assignee_type,
                AssistantTask.assignee_id == assignee_id,
            )
            .update(
                {
                    "assignee_type": None,
                    "assignee_id": None,
                    "task_version": AssistantTask.task_version + 1,
                    "updated_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        if updated == 0:
            self._abort_conflict()
            return None
        self._commit()
        return self._refetch_task(task_id)

    def list_board_tasks(self, session_id: str) -> list[AssistantTask]:
        return (
            self.session.query(AssistantTask)
            .filter(
                AssistantTask.session_id == session_id,
                AssistantTask.status == "pending_dispatch",
                AssistantTask.parent_task_id.is_not(None),
            )
            .order_by(AssistantTask.updated_at.desc(), AssistantTask.task_id)
            .all()
        )

    def list_open_board_tasks_for_fallback(
        self,
        cutoff,
        *,
        limit: int,
        session_id: str | None = None,
    ) -> list[AssistantTask]:
        query = self.session.query(AssistantTask).filter(
            AssistantTask.status == "pending_dispatch",
            AssistantTask.parent_task_id.is_not(None),
            AssistantTask.assignee_type.is_(None),
            AssistantTask.assignee_id.is_(None),
            AssistantTask.updated_at <= cutoff,
        )
        if session_id is not None:
            query = query.filter(AssistantTask.session_id == session_id)
        return query.order_by(AssistantTask.updated_at, AssistantTask.task_id).limit(limit).all()

    def _assert_no_cycle(self, graph_id: str, source_task_id: str, target_task_id: str) -> None:
        if source_task_id == target_task_id:
            raise ValueError("task edge cannot target itself")
        edges = self.list_graph_edges(graph_id)
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            adjacency.setdefault(edge.source_task_id, set()).add(edge.target_task_id)
        adjacency.setdefault(source_task_id, set()).add(target_task_id)
        if _can_reach(adjacency, target_task_id, source_task_id):
            raise ValueError("task edge would create a cycle")


def _can_reach(adjacency: dict[str, set[str]], start: str, target: str) -> bool:
    seen: set[str] = set()
    stack: list[str] = [start]
    while stack:
        current = stack.pop()
        if current == target:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, ()))
    return False


def graph_version_from_tasks(tasks: Iterable[AssistantTask]) -> int:
    return max((task.graph_version for task in tasks), default=0)
