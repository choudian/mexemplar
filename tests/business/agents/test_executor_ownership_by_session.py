"""执行体归属校验以"当前 active attempt 绑定的会话"为准。

`build_task_graph` 建出的节点 ``assignee_type``/``assignee_id`` 恒为空（认领制，
不预先指派），而两个守卫都在比对这两列，于是图节点上的执行体 100% 喊不出话：
``ask_parent`` 报 "requires the assigned executor"，``todo_update`` 报
"requires assigned executor ownership"。真正的"此刻谁在干"在执行记录里。

显式指派路径（assignee 两列都有值）保持原样放行，零回归。
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from src.business.task_collaboration.questions import TaskQuestionService
from src.business.task_collaboration.todos import TaskTodoService
from src.data.repos import AssistantTaskAttemptRepository, AssistantTaskRepository
from src.utils.timezone import utc_now_naive

EXECUTOR_SESSION = "sess_executor"
OTHER_SESSION = "sess_someone_else"


def _graph_node_without_assignee(task_id: str = "tsk_node") -> str:
    """复刻 build_task_graph 建出的真实形态：assignee 两列都是空。"""
    repo = AssistantTaskRepository()
    root = repo.create_task(
        graph_id="tg_own",
        session_id="ast_own",
        task_id="tsk_root_own",
        title="root",
        description="root",
        owner_session_id="ast_own",
        capability_scope=json.dumps(["tool.read", "tool.write"]),
        status="running",
    )
    child = repo.create_task(
        graph_id=root.graph_id,
        session_id=root.session_id,
        task_id=task_id,
        root_task_id=root.task_id,
        parent_task_id=root.task_id,
        title="child",
        description="child",
        owner_session_id=root.session_id,
        status="running",
    )
    assert child.assignee_type is None and child.assignee_id is None
    return child.task_id


def _bind_active_attempt(task_id: str, session_id: str) -> None:
    attempts = AssistantTaskAttemptRepository()
    attempts.start_attempt(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="graph_scheduler",
        lease_expires_at=utc_now_naive() + timedelta(minutes=2),
    )
    assert attempts.bind_session(task_id=task_id, executor_session_id=session_id) is True


def test_ask_parent_allows_executor_bound_to_active_attempt() -> None:
    task_id = _graph_node_without_assignee()
    _bind_active_attempt(task_id, EXECUTOR_SESSION)

    row = TaskQuestionService().ask_parent(
        task_id=task_id,
        asker_type="ephemeral_subagent",
        asker_id=EXECUTOR_SESSION,
        asker_session_id=EXECUTOR_SESSION,
        kind="clarification",
        question="我需要写目标仓库的权限",
    )

    assert row.task_id == task_id


def test_ask_parent_rejects_session_not_bound_to_active_attempt() -> None:
    task_id = _graph_node_without_assignee("tsk_node_wrong")
    _bind_active_attempt(task_id, EXECUTOR_SESSION)

    with pytest.raises(PermissionError):
        TaskQuestionService().ask_parent(
            task_id=task_id,
            asker_type="ephemeral_subagent",
            asker_id=OTHER_SESSION,
            asker_session_id=OTHER_SESSION,
            kind="clarification",
            question="我是别的会话",
        )


def test_todo_update_allows_executor_bound_to_active_attempt() -> None:
    task_id = _graph_node_without_assignee("tsk_node_todo")
    _bind_active_attempt(task_id, EXECUTOR_SESSION)

    rows = TaskTodoService().update_todos(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=EXECUTOR_SESSION,
        executor_session_id=EXECUTOR_SESSION,
        items=[{"text": "先读现有组件"}],
    )

    assert [row["text"] for row in rows] == ["先读现有组件"]


def test_todo_update_rejects_session_not_bound_to_active_attempt() -> None:
    task_id = _graph_node_without_assignee("tsk_node_todo_wrong")
    _bind_active_attempt(task_id, EXECUTOR_SESSION)

    with pytest.raises(PermissionError):
        TaskTodoService().update_todos(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=OTHER_SESSION,
            executor_session_id=OTHER_SESSION,
            items=[{"text": "越权"}],
        )


def test_unbound_attempt_still_rejects_so_missing_wiring_never_opens_the_gate() -> None:
    """attempt 未绑定会话时不得放行——否则接线漏掉就等于守卫失效。"""
    task_id = _graph_node_without_assignee("tsk_node_unbound")
    AssistantTaskAttemptRepository().start_attempt(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="graph_scheduler",
        lease_expires_at=utc_now_naive() + timedelta(minutes=2),
    )

    with pytest.raises(PermissionError):
        TaskQuestionService().ask_parent(
            task_id=task_id,
            asker_type="ephemeral_subagent",
            asker_id=EXECUTOR_SESSION,
            asker_session_id=EXECUTOR_SESSION,
            kind="clarification",
            question="没绑定就不该放行",
        )
