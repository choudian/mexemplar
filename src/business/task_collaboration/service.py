"""Authoritative Assistant task graph facade."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from threading import Lock

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
from src.utils.events import emit

# FR-023：委派拓扑结构上封顶为"枢纽单层 + 一级延伸"——根任务(深度 0) → 一级被委派者(1)
# → 专员的至多一个临时子代理(2)。深度 2 的任务不得再有子任务，结构上杜绝无限/循环委派。
_MAX_DELEGATION_DEPTH = 2
_PENDING_REVIEW_EXPLANATION = "等待上级检查结果"

_COUNTERS: Counter[str] = Counter()
_COUNTER_LOCK = Lock()
_KNOWN_COUNTERS = frozenset(
    {
        "task_created",
        "attempt_started",
        "attempt_fenced",
        "late_result_rejected",
        "claim_conflict",
        "adjudication_decided",
        "graph_stopped",
        "graph_cancelled",
        "root_graph_failed",
        "root_failure_bridge_failed",
        "fallback_executor_started",
    }
)


def _encode_capability_scope(raw: object) -> str | None:
    """Persist capability scope in the JSON format consumed by TaskExecutorAdapter."""
    if not raw:
        return None
    if not isinstance(raw, list):
        raise ValueError("capabilityScope must be an array of tool identifiers")
    values = [str(item).strip() for item in raw if str(item).strip()]
    return json.dumps(values, ensure_ascii=False) if values else None


def _resolve_node_assignment(node: dict) -> tuple[str | None, str | None]:
    """Resolve model-facing assignee hints into executable assignment fields.

    ``assigneeHint="specialist"`` is advisory unless a concrete assigneeId is
    provided; persisting specialist without an id makes the executor adapter fail
    with "specialist unavailable". Unresolved hints fall back to normal ephemeral
    dispatch in GraphScheduler.
    """
    hint = node.get("assigneeHint")
    assignee_id = str(node.get("assigneeId") or "").strip()
    if hint == "specialist":
        return ("specialist", assignee_id) if assignee_id else (None, None)
    if hint == "ephemeral_subagent":
        return "ephemeral_subagent", None
    return None, None


def increment_task_collaboration_counter(name: str, value: int = 1) -> None:
    """Increment a known collaboration counter."""
    if name not in _KNOWN_COUNTERS or value <= 0:
        return
    with _COUNTER_LOCK:
        _COUNTERS[name] += value


def get_task_collaboration_counters() -> dict[str, int]:
    with _COUNTER_LOCK:
        return {name: _COUNTERS.get(name, 0) for name in sorted(_KNOWN_COUNTERS)}


def reset_task_collaboration_counters() -> None:
    """Testing hook."""
    with _COUNTER_LOCK:
        _COUNTERS.clear()


def emit_task_updated(sender, task) -> None:
    """单条任务状态变更 → assistant_task_graph_changed(change_type=task_updated)。"""
    emit(
        "assistant_task_graph_changed",
        sender=sender,
        session_id=task.session_id,
        graph_id=task.graph_id,
        task_id=task.task_id,
        status=task.status,
        change_type="task_updated",
        display_phase=derive_display_phase(task.status),
        suspend_reason=task.suspend_reason,
    )


def emit_board_changed(sender, task, *, change_type: str, claim_status: str) -> None:
    """看板认领状态变更 → assistant_task_board_changed。"""
    emit(
        "assistant_task_board_changed",
        sender=sender,
        change_type=change_type,
        claim_status=claim_status,
        session_id=task.session_id,
        graph_id=task.graph_id,
        task_id=task.task_id,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


def emit_meeting_changed(
    sender,
    task,
    channel,
    *,
    change_type: str,
    status: str,
    sequence: int | None = None,
) -> None:
    """会议通道变更 → assistant_meeting_changed。"""
    emit(
        "assistant_meeting_changed",
        sender=sender,
        session_id=task.session_id if task is not None else "",
        graph_id=channel.graph_id,
        task_id=channel.parent_task_id,
        channel_id=channel.channel_id,
        change_type=change_type,
        status=status,
        sequence=sequence,
    )


def emit_graph_changed(
    sender,
    *,
    session_id: str,
    graph_id: str,
    change_type: str,
    task_id: str | None = None,
    status: str | None = None,
    display_phase: str | None = None,
    requires_review: bool | None = None,
    safe_explanation: str | None = None,
    suspend_reason: str | None = None,
) -> None:
    """图级生命周期变更 → assistant_task_graph_changed。"""
    emit(
        "assistant_task_graph_changed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        change_type=change_type,
        status=status,
        display_phase=display_phase,
        requires_review=requires_review,
        safe_explanation=safe_explanation,
        suspend_reason=suspend_reason,
    )
    if change_type in {"task_created", "graph_stopped", "graph_cancelled"}:
        increment_task_collaboration_counter(change_type)


def emit_question_changed(
    sender,
    *,
    session_id: str,
    graph_id: str,
    task_id: str,
    question_id: str,
    kind: str,
    status: str,
    change_type: str,
) -> None:
    """问答/资源请求路由变更 → assistant_task_question_changed。"""
    emit(
        "assistant_task_question_changed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        question_id=question_id,
        kind=kind,
        status=status,
        change_type=change_type,
    )


def emit_todo_changed(
    sender,
    *,
    session_id: str,
    task_id: str,
    todo_id: str,
    change_type: str,
    status: str,
    sort_order: int,
) -> None:
    """executor 私人 Todo 变更 → assistant_todo_changed。"""
    emit(
        "assistant_todo_changed",
        sender=sender,
        session_id=session_id,
        task_id=task_id,
        todo_id=todo_id,
        change_type=change_type,
        status=status,
        sort_order=sort_order,
    )


def emit_adjudication_decided(
    sender,
    *,
    session_id: str,
    graph_id: str,
    task_id: str,
    status: str,
) -> None:
    """父侧裁定决策落定 → assistant_task_adjudication_changed(adjudication_decided)。"""
    emit(
        "assistant_task_adjudication_changed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        change_type="adjudication_decided",
        status=status,
        display_phase=derive_display_phase(status),
        requires_review=False,
        safe_explanation="",
    )
    increment_task_collaboration_counter("adjudication_decided")


def emit_root_failed(
    sender,
    *,
    session_id: str,
    graph_id: str,
    task_id: str,
    status: str,
    safe_explanation: str,
) -> None:
    """根任务失败 → assistant_task_root_failed。"""
    emit(
        "assistant_task_root_failed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        change_type="root_failed",
        status=status,
        display_phase=derive_display_phase(status),
        safe_explanation=safe_explanation,
    )
    increment_task_collaboration_counter("root_graph_failed")


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

    def build_task_graph(
        self,
        *,
        session_id: str,
        nodes: list[dict],
        dependencies: list[dict] | None = None,
        user_message_sequence: int | None = None,
    ) -> dict:
        """原子建图：创建根任务 + N 个节点任务 + M 条 dependency 边。

        024 task-graph-scheduling 核心：把复杂任务分解成带依赖的 DAG 并原子落库。
        复用 _atomic UoW 保证全原子；add_edge 自动过 _assert_no_cycle。
        graph_version 按 DEC-F 接受 per-edge 递增。

        Args:
            session_id: 会话 ID
            nodes: 节点列表，每项含 nodeId/title/description，可选
                   assigneeHint/capabilityScope/needsConfirmation
            dependencies: 依赖列表，每项含 from/to（引用 nodeId）
            user_message_sequence: 用户消息序号

        Returns:
            dict 含 graphId, nodeTaskIds, confirmationRequired, readyNodeCount
        """
        from src.data.unified_config import get_unified_config

        dependencies = dependencies or []

        # 预算校验
        max_tasks = get_unified_config().get_assistant_tasks_graph_max_tasks()
        if len(nodes) > max_tasks:
            raise ValueError(
                f"task graph exceeds configured task budget ({len(nodes)} > {max_tasks})"
            )

        resolved_graph_id = generate_id("tg")
        root_task_id = generate_id("tsk")

        # nodeId → 真实 task_id 映射
        node_task_ids: dict[str, str] = {}
        confirmation_required = False

        with self._atomic():
            # 1. 创建根任务（图的容器）
            self._tasks.create_task(
                graph_id=resolved_graph_id,
                session_id=session_id,
                task_id=root_task_id,
                root_task_id=root_task_id,
                title="任务图根节点",
                description="DAG 任务图容器节点，不直接执行",
                user_message_sequence=user_message_sequence,
                owner_session_id=session_id,
            )

            # 2. 逐节点创建任务
            for node in nodes:
                node_id = node["nodeId"]
                task_id = generate_id("tsk")
                node_task_ids[node_id] = task_id

                needs_confirm = bool(node.get("needsConfirmation", False))
                if needs_confirm:
                    confirmation_required = True
                assignee_type, assignee_id = _resolve_node_assignment(node)

                self._tasks.create_task(
                    graph_id=resolved_graph_id,
                    session_id=session_id,
                    task_id=task_id,
                    root_task_id=root_task_id,
                    parent_task_id=root_task_id,
                    title=node["title"],
                    description=node["description"],
                    owner_session_id=session_id,
                    user_message_sequence=user_message_sequence,
                    assignee_type=assignee_type,
                    assignee_id=assignee_id,
                    capability_scope=_encode_capability_scope(node.get("capabilityScope")),
                    requires_confirmation=1 if needs_confirm else 0,
                )

            # 3. 逐依赖添加边（自动过 _assert_no_cycle）
            for dep in dependencies:
                from_node_id = dep["from"]
                to_node_id = dep["to"]
                from_task_id = node_task_ids.get(from_node_id)
                to_task_id = node_task_ids.get(to_node_id)
                if from_task_id is None or to_task_id is None:
                    raise ValueError(
                        f"dependency references unknown nodeId: {from_node_id} -> {to_node_id}"
                    )
                self._tasks.add_edge(
                    graph_id=resolved_graph_id,
                    source_task_id=from_task_id,
                    target_task_id=to_task_id,
                    edge_type="dependency",
                    propagation="blocking",
                )

        # 事务外发事件
        emit_graph_changed(
            self,
            session_id=session_id,
            graph_id=resolved_graph_id,
            change_type="graph_created",
            task_id=root_task_id,
            status="pending_dispatch",
            display_phase=derive_display_phase("pending_dispatch"),
        )

        # 计算就绪节点数（无前置依赖的节点）
        has_predecessor: set[str] = set()
        for dep in dependencies:
            has_predecessor.add(dep["to"])
        ready_node_count = sum(1 for n in nodes if n["nodeId"] not in has_predecessor)

        return {
            "graphId": resolved_graph_id,
            "nodeTaskIds": node_task_ids,
            "confirmationRequired": confirmation_required,
            "readyNodeCount": ready_node_count,
        }

    def mutate_task_graph(
        self,
        *,
        graph_id: str,
        session_id: str,
        changes: list[dict],
        reason: str = "",
    ) -> dict:
        """自愈改图：add_node / skip_node / add_dependency / remove_dependency。

        每次变更 bump graph_version 并重新过无环校验。
        skip_node 的下游处理规则见 data-model.md §3。
        """
        applied: list[dict] = []
        rejected: list[dict] = []

        root = self._tasks.get_graph_root(graph_id)
        if root is None:
            return {"applied": [], "rejected": changes, "graphVersion": 0, "rescanned": False}

        root_task_id = root.task_id

        with self._atomic():
            for change in changes:
                op = change.get("op")
                try:
                    if op == "add_node":
                        node_id = change.get("nodeId", generate_id("n"))
                        task_id = generate_id("tsk")
                        assignee_type, assignee_id = _resolve_node_assignment(change)
                        self._tasks.create_task(
                            graph_id=graph_id,
                            session_id=session_id,
                            task_id=task_id,
                            root_task_id=root_task_id,
                            parent_task_id=root_task_id,
                            title=change.get("title", ""),
                            description=change.get("description", ""),
                            owner_session_id=session_id,
                            user_message_sequence=root.user_message_sequence,
                            assignee_type=assignee_type,
                            assignee_id=assignee_id,
                            capability_scope=_encode_capability_scope(
                                change.get("capabilityScope")
                            ),
                            requires_confirmation=1 if change.get("needsConfirmation") else 0,
                        )
                        applied.append({"op": op, "nodeId": node_id, "taskId": task_id})

                    elif op == "skip_node":
                        task_id = change.get("taskId", "")
                        task = self._tasks.get_task(task_id)
                        if task is None or task.graph_id != graph_id:
                            rejected.append({"op": op, "reason": "task not found or wrong graph"})
                            continue
                        # 跳过一个 blocking predecessor 时，下游子图已无法满足完成依赖；
                        # 级联取消防止后续节点永久停在 pending_dispatch。
                        candidate_ids = {
                            task_id,
                            *self._blocking_dependency_descendants(graph_id, task_id),
                        }
                        cancelled_ids: list[str] = []
                        for candidate_id in sorted(candidate_ids):
                            candidate = self._tasks.get_task(candidate_id)
                            if candidate is None or candidate.graph_id != graph_id:
                                continue
                            if candidate.status in TERMINAL_TASK_STATUSES:
                                continue
                            self._tasks.update_status(candidate_id, status="cancelled")
                            cancelled_ids.append(candidate_id)
                        applied.append(
                            {
                                "op": op,
                                "taskId": task_id,
                                "cancelledTaskIds": cancelled_ids,
                            }
                        )

                    elif op == "add_dependency":
                        from_id = change.get("from", "")
                        to_id = change.get("to", "")
                        if not from_id or not to_id:
                            rejected.append({"op": op, "reason": "missing from/to"})
                            continue
                        # from/to 可能是 nodeId 或 taskId
                        from_task_id = from_id
                        to_task_id = to_id
                        self._tasks.add_edge(
                            graph_id=graph_id,
                            source_task_id=from_task_id,
                            target_task_id=to_task_id,
                            edge_type="dependency",
                            propagation="blocking",
                        )
                        applied.append({"op": op, "from": from_id, "to": to_id})

                    elif op == "remove_dependency":
                        from_id = change.get("from", "")
                        to_id = change.get("to", "")
                        if not from_id or not to_id:
                            rejected.append({"op": op, "reason": "missing from/to"})
                            continue
                        # 精确删边 + bump graph_version 由 repo 负责（消除 session 直操作与全图边扫描）
                        self._tasks.remove_edge(
                            graph_id=graph_id,
                            source_task_id=from_id,
                            target_task_id=to_id,
                            edge_type="dependency",
                        )
                        applied.append({"op": op, "from": from_id, "to": to_id})

                    else:
                        rejected.append({"op": op, "reason": "unknown op"})
                except ValueError as e:
                    rejected.append({"op": op, "reason": str(e)})

        # 获取当前 graph_version
        root_refreshed = self._tasks.get_task(root_task_id)
        current_version = root_refreshed.graph_version if root_refreshed else 0

        return {
            "applied": applied,
            "rejected": rejected,
            "graphVersion": current_version,
            "rescanned": len(applied) > 0,
        }

    def _blocking_dependency_descendants(self, graph_id: str, task_id: str) -> set[str]:
        edges = self._tasks.list_graph_edges(graph_id)
        adjacency: dict[str, set[str]] = {}
        for edge in edges:
            if edge.edge_type == "dependency" and edge.propagation == "blocking":
                adjacency.setdefault(edge.source_task_id, set()).add(edge.target_task_id)

        descendants: set[str] = set()
        stack = list(adjacency.get(task_id, ()))
        while stack:
            current = stack.pop()
            if current in descendants:
                continue
            descendants.add(current)
            stack.extend(adjacency.get(current, ()))
        return descendants

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

    def create_needs_confirmation_pause(self, *, task_id: str, title: str):
        """为「需确认」节点原子地建 pending adjudication 并挂起（FR-009，SC-002）。

        在单个 ``_atomic`` 内完成 ``create_pending`` + ``update_status(suspended/waiting_user)``，
        避免两步非原子导致「adjudication 已建但节点未挂起」——那会让高风险节点停在
        ``pending_dispatch`` 既不执行也不暂停，违反「高风险节点执行前必须暂停」。
        幂等：已有 pending adjudication 则跳过。title 由 scheduler 从 snapshot 传入。
        """
        task = self._tasks.get_task(task_id)
        if task is None:
            return None
        existing = self._adjudications.get_pending_for_task(task_id)
        if existing is not None:
            return existing
        task_session_id = task.session_id
        task_graph_id = task.graph_id
        safe_summary = safe_public_preview(
            f"节点「{title}」标记为需确认，请裁定是否执行。（高风险/不可逆操作）",
            key="safeSummary",
        )
        with self._atomic():
            adjudication = self._adjudications.create_pending(
                task_id=task.task_id,
                graph_id=task.graph_id,
                parent_session_id=task.owner_session_id or task.session_id,
                delivered_status="done",  # 占位：不是真正的执行结果
                safe_summary=safe_summary,
                raw_result_ref=None,
            )
            updated = self._tasks.update_status(
                task_id,
                status="suspended",
                suspend_reason="waiting_user",
            )
        emit_graph_changed(
            self,
            session_id=task_session_id,
            graph_id=task_graph_id,
            change_type="adjudication_created",
            task_id=task_id,
            status="suspended",
            display_phase=derive_display_phase("suspended", has_pending_adjudication=True),
            requires_review=True,
            safe_explanation=_PENDING_REVIEW_EXPLANATION,
        )
        if updated is not None:
            emit_task_updated(self, updated)
        return adjudication

    def assert_dependencies_satisfied(self, graph_id: str, task_id: str) -> None:
        """就绪硬校验公共入口：所有 blocking dependency 前置必须 completed，否则 raise ValueError。

        scheduler 与 dispatcher 复用同一份数据层判定，避免调度器直接访问仓库私有方法
        （分层硬边界：scheduler 经 service 公共表面进入）。
        """
        self._tasks._assert_dependencies_satisfied(graph_id, task_id)

    def has_accepted_confirmation(self, task_id: str) -> bool:
        """该 task 是否已有 accepted 裁定（requires_confirmation 节点的派发闸门）。"""
        return self._adjudications.has_decided_for_task(task_id, decision="accepted")

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
                    requires_confirmation=bool(task.requires_confirmation),
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
                validate_task_transition(task.status, target_status, suspend_reason=suspend_reason)
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
            predicate=lambda task: task.status in {TaskStatus.PENDING_DISPATCH, TaskStatus.RUNNING},
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
                    "requiresConfirmation": t.requires_confirmation,
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
