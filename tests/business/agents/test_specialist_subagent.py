from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.business.agents.config import AgentType, ResultType, ToolDefinition, ToolSignal
from src.business.orchestration.agent import AgentOrchestrator
from src.data.repos import AssistantTaskRepository, AssistantTodoRepository


def _orchestrator_for_tools() -> AgentOrchestrator:
    orch = AgentOrchestrator.__new__(AgentOrchestrator)
    orch._make_load_skill_tool = MagicMock(
        return_value=ToolDefinition(
            name="load_skill_methodology",
            schema={"function": {"name": "load_skill_methodology"}},
            handler=lambda **_kwargs: "",
        )
    )
    return orch


def test_specialist_gets_single_use_delegate_to_subagent() -> None:
    # FR-019：专员可起"至多一个"临时子代理用于隔离上下文
    orch = _orchestrator_for_tools()
    orch._run_sync_ephemeral_subagent = MagicMock(
        return_value={
            "success": True,
            "result_text": "干净结果",
            "delegation_type": "ephemeral_subagent",
        }
    )

    factory = orch._build_delegated_executor_tools(
        {"tool-a"},
        agent_type=AgentType.SPECIALIST,
        executor_id="spec-session",
        specialist_id="spec-1",
    )
    tools = factory()
    names = {tool.name for tool in tools}
    assert "delegate_to_subagent" in names

    handler = next(tool.handler for tool in tools if tool.name == "delegate_to_subagent")
    first = json.loads(handler(task_description="OCR 这沓扫描件，只回干净清单"))
    second = json.loads(handler(task_description="再起一个"))

    assert first["success"] is True
    assert second["success"] is False  # 至多一个：第二次被单实例门卫拒
    assert orch._run_sync_ephemeral_subagent.call_count == 1


def test_ephemeral_subagent_cannot_delegate_to_subagent() -> None:
    # 防深度封顶失效：普通被委派者（临时子代理）不得获得 delegate_to_subagent
    orch = _orchestrator_for_tools()

    factory = orch._build_delegated_executor_tools(
        {"tool-a"},
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        executor_id="sub-session",
    )
    names = {tool.name for tool in factory()}
    assert "delegate_to_subagent" not in names


def test_ephemeral_todo_update_handler_aligns_executor_id_with_task_assignee() -> None:
    # 临时子代理 task.assignee_id 是 dispatch 时设的类型占位 'ephemeral_subagent'
    # （非 child session）。_build_delegated_executor_tools 给 ephemeral 构造的
    # todo_update handler 必须用对齐 assignee_id 的 executor_id，否则 todos.py
    # 归属校验（assignee_id == executor_id）抛 PermissionError。
    task = AssistantTaskRepository().create_task(
        graph_id="tg_eph_tools",
        session_id="ast_eph",
        task_id="tsk_eph_tools",
        title="ephemeral task",
        description="d",
        owner_session_id="ast_eph",
        assignee_type="ephemeral_subagent",
        assignee_id="ephemeral_subagent",
        status="running",
    )
    orch = _orchestrator_for_tools()
    factory = orch._build_delegated_executor_tools(
        {"todo_update"},
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        executor_id="child_session_xyz",  # 模拟 unified dispatch 传入的 child session
    )
    todo_tool = next(tool for tool in factory() if tool.name == "todo_update")

    result = json.loads(
        todo_tool.handler(
            taskId=task.task_id,
            items=[{"todoId": "todo_1", "text": "step", "status": "todo", "sortOrder": 1}],
        )
    )

    assert result["success"] is True
    assert len(AssistantTodoRepository().list_for_task(task.task_id)) == 1


def test_bound_task_collaboration_tools_do_not_require_model_task_id() -> None:
    task = AssistantTaskRepository().create_task(
        graph_id="tg_bound_tools",
        session_id="ast_bound",
        task_id="tsk_bound_tools",
        title="bound task",
        description="d",
        owner_session_id="ast_bound",
        assignee_type="ephemeral_subagent",
        assignee_id="ephemeral_subagent",
        status="running",
    )
    orch = _orchestrator_for_tools()
    factory = orch._build_delegated_executor_tools(
        {"todo_update"},
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        executor_id="child_session_xyz",
        current_task_id=task.task_id,
    )
    tools = {tool.name: tool for tool in factory()}

    ask_required = tools["ask_parent"].schema["function"]["parameters"]["required"]
    todo_required = tools["todo_update"].schema["function"]["parameters"]["required"]
    assert "taskId" not in ask_required
    assert "taskId" not in todo_required
    assert tools["ask_parent"].is_interrupting is True

    result = json.loads(
        tools["todo_update"].handler(
            items=[{"todoId": "todo_1", "text": "step", "status": "todo", "sortOrder": 1}],
        )
    )

    assert result["success"] is True
    assert result["taskId"] == task.task_id

    signal = tools["ask_parent"].handler(question="Need parent input.", kind="clarification")
    assert isinstance(signal, ToolSignal)
    assert signal.result_type == ResultType.NEEDS_USER_INPUT
    payload = json.loads(signal.display_text)
    assert payload["success"] is True
    assert payload["taskId"] == task.task_id
