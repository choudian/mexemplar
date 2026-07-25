"""执行体工具把自己的会话带到归属校验。

服务层已经以"active attempt 绑定的会话"为准，但工具 handler 不把会话传下去的话，
生产路径仍然只剩显式指派那条永远为空的判定——修了服务层等于没修。
"""

from __future__ import annotations

import json
from datetime import timedelta

from src.business.agents.tools.assistant_tools import (
    create_ask_parent_handler,
    create_todo_update_handler,
)
from src.data.repos import AssistantTaskAttemptRepository, AssistantTaskRepository
from src.utils.timezone import utc_now_naive

EXECUTOR_SESSION = "sess_exec_tool"


def _bound_graph_node(task_id: str) -> str:
    repo = AssistantTaskRepository()
    root = repo.create_task(
        graph_id="tg_tool",
        session_id="ast_tool",
        task_id=f"{task_id}_root",
        title="root",
        description="root",
        owner_session_id="ast_tool",
        status="running",
    )
    repo.create_task(
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
    attempts = AssistantTaskAttemptRepository()
    attempts.start_attempt(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="graph_scheduler",
        lease_expires_at=utc_now_naive() + timedelta(minutes=2),
    )
    attempts.bind_session(task_id=task_id, executor_session_id=EXECUTOR_SESSION)
    return task_id


def _payload(result) -> dict:
    return json.loads(result if isinstance(result, str) else result.payload)


def test_ask_parent_handler_passes_executor_session_to_the_guard() -> None:
    task_id = _bound_graph_node("tsk_tool_ask")
    handler = create_ask_parent_handler(
        executor_type="ephemeral_subagent",
        executor_id=EXECUTOR_SESSION,
        executor_session_id=EXECUTOR_SESSION,
        bound_task_id=task_id,
    )

    payload = _payload(handler(question="我需要写权限", kind="clarification"))

    assert payload["success"] is True
    assert payload["taskId"] == task_id


def test_todo_update_handler_passes_executor_session_to_the_guard() -> None:
    task_id = _bound_graph_node("tsk_tool_todo")
    handler = create_todo_update_handler(
        executor_type="ephemeral_subagent",
        executor_id=EXECUTOR_SESSION,
        executor_session_id=EXECUTOR_SESSION,
        bound_task_id=task_id,
    )

    payload = _payload(handler(items=[{"text": "先读现有组件"}]))

    assert payload["success"] is True


def test_delegated_executor_tools_wire_the_child_session_into_ask_parent(
    mock_config, in_memory_db
) -> None:
    """注册表必须把执行体会话传给 handler，否则前面几层全白搭。"""
    from unittest.mock import MagicMock

    from src.business.orchestration.agent.orchestrator import AgentOrchestrator

    task_id = _bound_graph_node("tsk_registry_wire")
    orch = AgentOrchestrator(MagicMock(), mock_config)

    tools_factory = orch._build_delegated_executor_tools(
        set(),
        agent_type="ephemeral_subagent",
        executor_id=EXECUTOR_SESSION,
        current_task_id=task_id,
        parent_session_id="ast_tool",
    )
    ask_parent = next(t for t in tools_factory() if t.name == "ask_parent")

    # 绑定了 task 的 ask_parent 是中断型工具，返回信号而非载荷；提问落库才是它做成了事。
    ask_parent.handler(question="我需要写权限", kind="clarification")

    from src.data.repos import AssistantTaskQuestionRepository

    questions = AssistantTaskQuestionRepository().list_open_for_task(task_id)
    assert [row.question_text for row in questions] == ["我需要写权限"]
