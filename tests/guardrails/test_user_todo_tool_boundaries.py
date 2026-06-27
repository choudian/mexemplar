from __future__ import annotations

import json
from types import SimpleNamespace

from src.business.agents.config import AgentType
from src.business.agents.tools.assistant_tools import (
    create_complete_user_todo_handler,
    create_list_user_todos_handler,
    create_user_todo_handler,
)
from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager
from src.business.orchestration.agent.tool_registry import ToolRegistry


USER_TODO_TOOL_NAMES = {
    "create_user_todo",
    "list_user_todos",
    "update_user_todo",
    "complete_user_todo",
    "delete_user_todo",
}


class _DynamicManagerCache:
    def get_or_create_dynamic_manager(self, session_id, allowed_ids):
        return DynamicToolManager(allowed_tool_ids=allowed_ids)


def _registry() -> ToolRegistry:
    return ToolRegistry(
        session_store=SimpleNamespace(get_session=lambda _session_id: None),
        dynamic_manager_cache=_DynamicManagerCache(),
        delegation_orchestrator=SimpleNamespace(
            delegate_to_subagent=lambda **_: {},
            continue_subagent=lambda **_: {},
            inspect_subagent=lambda **_: {},
            delegate_to_specialist=lambda **_: {},
            run_sync_ephemeral_subagent=lambda **_: {},
        ),
        resolve_recording_mode=lambda _workflow_id: "browser",
        redispatch_answered_task=lambda _task_id: False,
    )


def _tool_names(factory):
    return {tool.name for tool in factory()}


def test_user_todo_tools_are_executor_only() -> None:
    registry = _registry()

    executor_names = _tool_names(
        registry.build_delegated_executor_tools(
            None,
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            executor_id="sub_1",
        )
    )
    planner_names = _tool_names(
        registry.build_delegated_executor_tools(
            None,
            agent_type=AgentType.SPECIALIST,
            specialist_id="planner",
            role_kind="planner",
        )
    )
    assistant_names = _tool_names(registry.build_assistant_tools("ast_1"))

    assert USER_TODO_TOOL_NAMES.issubset(executor_names)
    assert not USER_TODO_TOOL_NAMES & planner_names
    assert not USER_TODO_TOOL_NAMES & assistant_names


def test_user_todo_tool_handlers_use_service_projection() -> None:
    created = json.loads(create_user_todo_handler()(title="买牛奶", priority="high"))
    todo_id = created["todo"]["todoId"]
    listed = json.loads(create_list_user_todos_handler()(statusFilter="open", query="牛奶"))
    completed = json.loads(create_complete_user_todo_handler()(todoId=todo_id))

    assert created["success"] is True
    assert listed["items"][0]["title"] == "买牛奶"
    assert completed["todo"]["status"] == "done"
