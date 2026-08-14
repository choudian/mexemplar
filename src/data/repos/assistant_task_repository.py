"""Repository for Assistant task graph rows."""

from __future__ import annotations

from datetime import datetime, timedelta
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
        user_task_id: str | None = None,
        owner_session_id: str | None = None,
        assignee_type: str | None = None,
        assignee_id: str | None = None,
        capability_scope: str | None = None,
        workspace_root: str | None = None,
        requires_confirmation: bool = False,
        status: str = "pending_dispatch",
        graph_control_status: str | None = None,
    ) -> AssistantTask:
        self.ensure_immediate_transaction()
        row = AssistantTask(
            task_id=task_id or generate_id("tsk"),
            graph_id=graph_id,
            root_task_id=root_task_id,
            parent_task_id=parent_task_id,
            session_id=session_id,
            user_message_sequence=user_message_sequence,
            user_task_id=user_task_id,
            title=title,
            description=description,
            owner_session_id=owner_session_id,
            assignee_type=assignee_type,
            assignee_id=assignee_id,
            capability_scope=capability_scope,
            workspace_root=workspace_root,
            requires_confirmation=requires_confirmation,
            status=status,
            graph_control_status=graph_control_status,
        )
        if row.root_task_id is None and row.parent_task_id is not None:
            row.root_task_id = row.parent_task_id
        return self._add_and_flush(row)

    def get_graph_control_status(self, graph_id: str) -> str | None:
        """读图根的控制状态（draft/running/stopped/cancelled）。图不存在返回 None。"""
        row = (
            self.session.query(AssistantTask.graph_control_status)
            .filter(
                AssistantTask.graph_id == graph_id,
                AssistantTask.parent_task_id.is_(None),
            )
            .first()
        )
        return row.graph_control_status if row is not None else None

    def set_graph_control_status(self, graph_id: str, status: str) -> bool:
        """翻图根的控制状态。只改图根行；图不存在返回 False。

        只允许显式操作调用（build/start_graph/stop/cancel/continue 续跑），
        不做节点状态推导。
        """
        if status not in ("draft", "running", "stopped", "cancelled"):
            raise ValueError(f"invalid graph control status: {status!r}")
        self.ensure_immediate_transaction()
        updated = (
            self.session.query(AssistantTask)
            .filter(
                AssistantTask.graph_id == graph_id,
                AssistantTask.parent_task_id.is_(None),
            )
            .update(
                {"graph_control_status": status}, synchronize_session=False
            )
        )
        return updated > 0

    def get_task(self, task_id: str) -> AssistantTask | None:
        return self.session.get(AssistantTask, task_id)

    def resolve_user_task_id(self, task: AssistantTask) -> str | None:
        """解析一个执行节点归属的用户任务 id。

        图根节点直接返回自身 ``user_task_id``；子节点（按设计不冗余写）沿
        ``graph_id`` 上溯到图根取归属。图根也没有时返回 None（proposal 等场景）。
        """
        if task.user_task_id is not None:
            return task.user_task_id
        root = self.get_graph_root(task.graph_id)
        return getattr(root, "user_task_id", None) if root else None

    def list_graph_tasks(self, graph_id: str) -> list[AssistantTask]:
        rows = self.session.query(AssistantTask).filter(AssistantTask.graph_id == graph_id).all()
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

    def resolve_graph_id_for_run(
        self,
        session_id: str,
        *,
        after_sequence: int,
        started_at: datetime,
    ) -> tuple[bool, str | None]:
        """解析 run 窗口内的当前图，返回 ``(known, graph_id)``。"""
        unscoped = (
            self.session.query(AssistantTask.task_id)
            .filter(
                AssistantTask.session_id == session_id,
                AssistantTask.parent_task_id.is_(None),
                AssistantTask.user_message_sequence.is_(None),
                # SQLite CURRENT_TIMESTAMP may truncate fractional seconds while
                # run.started_at comes from Python. One-second conservative overlap
                # keeps an unscoped graph fail-closed instead of misclassifying it
                # as an older graph and falling through to tool evidence success.
                AssistantTask.created_at >= started_at - timedelta(seconds=1),
            )
            .first()
        )
        if unscoped is not None:
            return False, None
        row = (
            self.session.query(AssistantTask.graph_id)
            .filter(
                AssistantTask.session_id == session_id,
                AssistantTask.parent_task_id.is_(None),
                AssistantTask.user_message_sequence > int(after_sequence),
            )
            .order_by(AssistantTask.created_at.desc())
            .first()
        )
        return True, (row[0] if row else None)

    def get_graph_user_message_sequence(self, graph_id: str) -> int | None:
        """返回图根绑定的 user message sequence；缺失/未标记均返回 None。"""
        row = (
            self.session.query(AssistantTask.user_message_sequence)
            .filter(
                AssistantTask.graph_id == graph_id,
                AssistantTask.parent_task_id.is_(None),
            )
            .order_by(AssistantTask.created_at.asc())
            .first()
        )
        return row[0] if row else None

    def list_graph_roots_for_user_task(self, user_task_id: str) -> list[AssistantTask]:
        """返回某用户任务下的所有图根（parent_task_id IS NULL）。

        供界面层（⑦）和"继续一件事"用：遍历一件事底下所有图，逐个推进。
        """
        return (
            self.session.query(AssistantTask)
            .filter(
                AssistantTask.user_task_id == user_task_id,
                AssistantTask.parent_task_id.is_(None),
            )
            .order_by(AssistantTask.created_at)
            .all()
        )

    def status_distribution_for_user_task(self, user_task_id: str) -> dict[str, int]:
        """返回用户任务下所有执行节点的状态分布（供界面画分布条）。

        遍历 user_task 下所有图的节点，按 status + suspend_reason 聚合。
        返回 key 形如 ``done``, ``skipped``, ``delivered``, ``running``,
        ``pending_dispatch``, ``suspended:user_stop``, ``suspended:interrupted``,
        ``suspended:quota_exhausted``, ``suspended:waiting_user``,
        ``suspended:blocked_by_defect`` 等。

        用 ``suspend_reason`` 而非 ``waiting_on`` 做 key：前者精确到每种暂停
        原因，前端可以区分「等用户回答」（``waiting_user``，不可继续）和
        「用户手动停」（``user_stop``，可继续）；后者把它们合进同一个 key
        ``suspended:user``，无法区分（问题 7）。
        """
        from sqlalchemy import func

        roots = self.list_graph_roots_for_user_task(user_task_id)
        if not roots:
            return {}
        graph_ids = [root.graph_id for root in roots]

        # 先查每张图有没有子节点（区分多节点图的根容器 vs 单节点图的根=执行节点）
        child_counts: dict[str, int] = {}
        for graph_id in graph_ids:
            child_counts[graph_id] = (
                self.session.query(AssistantTask.task_id)
                .filter(
                    AssistantTask.graph_id == graph_id,
                    AssistantTask.parent_task_id.is_not(None),
                )
                .count()
            )

        rows = (
            self.session.query(
                AssistantTask.status,
                AssistantTask.suspend_reason,
                AssistantTask.parent_task_id,
                AssistantTask.graph_id,
                func.count(AssistantTask.task_id),
            )
            .filter(AssistantTask.graph_id.in_(graph_ids))
            .group_by(
                AssistantTask.status,
                AssistantTask.suspend_reason,
                AssistantTask.parent_task_id,
                AssistantTask.graph_id,
            )
            .all()
        )
        distribution: dict[str, int] = {}
        for status, suspend_reason, parent_task_id, graph_id, count in rows:
            # 多节点图跳过根容器；单节点图（同步委派）的根就是执行节点
            if parent_task_id is None and child_counts.get(graph_id, 0) > 0:
                continue
            if status == "suspended" and suspend_reason:
                key = f"suspended:{suspend_reason}"
            else:
                key = status
            distribution[key] = distribution.get(key, 0) + count
        return distribution

    def has_active_execution_tasks(self, session_id: str) -> bool:
        """会话是否仍有真正在跑/将跑的执行节点（busy 判据）。

        只算 ``running / pending_dispatch`` 且所属图 ``graph_control_status='running'``：
        - suspended（等用户回答/额度停）不算——用户此刻该能说话（回答/改方向）；
        - delivered（等主助理裁定）不算——回流链路自己处理；
        - draft 图的 pending 不算——图未启动，系统没在干活。
        """
        running_graphs = (
            self.session.query(AssistantTask.graph_id)
            .filter(
                AssistantTask.session_id == session_id,
                AssistantTask.parent_task_id.is_(None),
                AssistantTask.graph_control_status == "running",
            )
            .subquery()
        )
        row = (
            self.session.query(AssistantTask.task_id)
            .filter(
                AssistantTask.parent_task_id.is_not(None),
                AssistantTask.status.in_(("running", "pending_dispatch")),
                AssistantTask.graph_id.in_(running_graphs),
            )
            .first()
        )
        return row is not None

    def has_nonterminal_execution_tasks(self, session_id: str) -> bool:
        """返回 session 内是否仍有未终态执行节点；root 容器不参与判定。"""
        row = (
            self.session.query(AssistantTask.task_id)
            .filter(
                AssistantTask.session_id == session_id,
                AssistantTask.parent_task_id.is_not(None),
                # ⚠️ 手抄的 TERMINAL_TASK_STATUSES 副本（数据层不 import 业务枚举）。
                # 改枚举时这里不会报错，只会静默把某个终态当成"还在跑"。
                AssistantTask.status.notin_(("done", "skipped", "abandoned", "cancelled")),
            )
            .first()
        )
        return row is not None

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

    def remove_edge(
        self,
        *,
        graph_id: str,
        source_task_id: str,
        target_task_id: str,
        edge_type: str,
    ) -> bool:
        """删除一条边并 bump graph_version（与 ``add_edge`` 对称的 cancel 并发围栏）。

        返回是否实际删除了一条边。按 (graph, source, target, type) 精确定位，避免
        「列全图边 + 循环匹配」的 O(E) 扫描，也把 ORM 删除收敛在 Repository 层。
        """
        self.ensure_immediate_transaction()
        edge = (
            self.session.query(AssistantTaskEdge)
            .filter(
                AssistantTaskEdge.graph_id == graph_id,
                AssistantTaskEdge.source_task_id == source_task_id,
                AssistantTaskEdge.target_task_id == target_task_id,
                AssistantTaskEdge.edge_type == edge_type,
            )
            .first()
        )
        if edge is None:
            return False
        self.session.delete(edge)
        self.session.flush()
        # 删边同样改变图拓扑，bump root graph_version 维持 cancel fence（与 add_edge 对称）
        source = self.get_task(source_task_id)
        root_id = (source.root_task_id if source is not None else None) or source_task_id
        root = self.get_task(root_id) if root_id else None
        if root is not None:
            root.graph_version += 1
        return True

    def update_status(
        self,
        task_id: str,
        *,
        status: str,
        expected_task_version: int | None = None,
        suspend_reason: str | None = None,
        waiting_on: str | None = None,
    ) -> AssistantTask | None:
        """``waiting_on`` 与 ``suspend_reason`` 同生同灭，由 DB CHECK 约束保证。

        本层不从 ``suspend_reason`` 推导 ``waiting_on``——那是业务语义，数据层不反
        调业务层。调用方用 ``models.waiting_on_for_reason()`` 算好了传进来；漏传会
        直接撞 ``ck_assistant_tasks_waiting_on_required`` 当场报错，不会静默落一行
        "停了却不知道等谁"的记录。
        """
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
        row.waiting_on = waiting_on
        row.task_version += 1
        row.updated_at = now
        if status in ("done", "skipped"):
            row.completed_at = now
        elif status == "abandoned":
            # 列名仍是 failed_at：它没有任何读取方，改列名要动 5 段迁移历史 DDL 和
            # 3 份测试期望字典，换不来任何东西。这里记的就是"这个活终结的时刻"。
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

    def assert_dependencies_satisfied(self, graph_id: str, task_id: str) -> None:
        """就绪硬校验：所有 edge_type='dependency' 且 propagation='blocking' 的前置节点必须 status='completed'。

        派发/认领前在数据层强制校验，前置未完成则 raise ValueError。
        这是 scheduler 就绪扫描的底层兜底：即便 scheduler 扫描有遗漏，claim 层也挡住乱序。
        """
        edges = self.list_graph_edges(graph_id)
        blocking_predecessor_ids = [
            e.source_task_id
            for e in edges
            if e.target_task_id == task_id
            and e.edge_type == "dependency"
            and e.propagation == "blocking"
        ]
        if not blocking_predecessor_ids:
            return
        # 批量查询所有前置节点（避免 N+1）
        rows = (
            self.session.query(AssistantTask.task_id, AssistantTask.status)
            .filter(AssistantTask.task_id.in_(blocking_predecessor_ids))
            .all()
        )
        found_ids = {r.task_id for r in rows}
        for pred_id in blocking_predecessor_ids:
            if pred_id not in found_ids:
                raise ValueError(f"dependency predecessor {pred_id} not found for task {task_id}")
        for r in rows:
            if r.status != "done":
                raise ValueError(
                    f"dependency not satisfied: predecessor {r.task_id} "
                    f"is {r.status}, expected done (task {task_id})"
                )

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
