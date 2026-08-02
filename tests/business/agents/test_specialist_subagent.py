from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.business.agents.config import AgentType, ResultType, ToolSignal
from src.business.agents.tools.assistant_tools import (
    CONTINUE_SUBAGENT_SCHEMA,
    DELEGATE_TO_SUBAGENT_SCHEMA,
    INSPECT_SUBAGENT_SCHEMA,
)
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.business.orchestration.agent.delegation_orchestrator import DelegationOrchestrator
from src.business.orchestration.agent.subagent_scope import (
    EffectiveSubagentScope,
    ScopeCaptureState,
)
from src.business.orchestration.agent.tool_registry import ToolRegistry
from src.data.repos import AssistantTaskRepository, AssistantTodoRepository


def _tool_registry(*, run_sync_ephemeral_subagent=None, delegation=None) -> ToolRegistry:
    """构造 ToolRegistry + fake 依赖(依赖注入改造后无需 bare orchestrator)。

    specialist 分支把 delegation.run_sync_ephemeral_subagent 绑进委派闭包;
    需要断言它时显式传入。
    """
    delegation = delegation or MagicMock()
    if run_sync_ephemeral_subagent is not None:
        delegation.run_sync_ephemeral_subagent = run_sync_ephemeral_subagent
    return ToolRegistry(
        session_store=MagicMock(),
        dynamic_manager_cache=MagicMock(),
        delegation_orchestrator=delegation,
        resolve_recording_mode=MagicMock(),
        redispatch_answered_task=MagicMock(),
    )


def test_specialist_gets_continue_and_inspect_bound_to_executor_session() -> None:
    delegation = MagicMock()
    delegation.inspect_subagent.return_value = {
        "success": True,
        "subagent_id": "child-session",
    }
    registry = _tool_registry(delegation=delegation)

    tools = {
        tool.name: tool
        for tool in registry.build_delegated_executor_tools(
            {"tool-a"},
            agent_type=AgentType.SPECIALIST,
            executor_id="spec-session",
            specialist_id="spec-1",
        )()
    }

    assert {"continue_subagent", "inspect_subagent"}.issubset(tools)
    assert tools["inspect_subagent"].has_side_effects is False
    assert tools["inspect_subagent"].is_concurrency_safe is False

    result = json.loads(tools["inspect_subagent"].handler(subagent_id="child-session"))

    assert result["success"] is True
    delegation.inspect_subagent.assert_called_once_with(
        parent_session_id="spec-session",
        subagent_id="child-session",
    )


def test_specialist_gets_single_use_delegate_to_subagent() -> None:
    # FR-019：专员可起"至多一个"临时子代理用于隔离上下文
    run_sync = MagicMock(
        return_value={
            "success": True,
            "result_text": "干净结果",
            "delegation_type": "ephemeral_subagent",
        }
    )
    registry = _tool_registry(run_sync_ephemeral_subagent=run_sync)

    factory = registry.build_delegated_executor_tools(
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
    assert run_sync.call_count == 1


def test_specialist_continuation_reuses_scope_bound_to_child_id() -> None:
    delegation = MagicMock()
    effective_scope = EffectiveSubagentScope(
        dynamic_tool_ids=frozenset({"allowed-tool"}),
        builtin_names=frozenset({"read_file"}),
        composition_ids=frozenset({"composition-a"}),
        workspace_root="E:/isolated-worktree",
    )
    delegation.prepare_specialist_subagent_scope.return_value = effective_scope
    delegation.run_sync_ephemeral_subagent.return_value = {
        "success": False,
        "paused": True,
        "subagent_id": "child-session",
    }
    delegation.continue_subagent.return_value = {
        "success": True,
        "subagent_id": "child-session",
    }
    registry = _tool_registry(delegation=delegation)
    tools = {
        tool.name: tool
        for tool in registry.build_delegated_executor_tools(
            {"allowed-tool"},
            tool_whitelist=["read_file"],
            agent_type=AgentType.SPECIALIST,
            executor_id="spec-session",
            specialist_id="spec-1",
            allowed_composition_ids={"composition-a"},
            workspace_root="E:/isolated-worktree",
        )()
    }

    paused = json.loads(
        tools["delegate_to_subagent"].handler(
            task_description="继续查完",
            tool_whitelist=["read_file", "forbidden-tool", "composition-a"],
        )
    )
    resumed = json.loads(
        tools["continue_subagent"].handler(
            subagent_id=paused["subagent_id"],
            instruction="从断点继续",
        )
    )

    assert resumed["success"] is True
    delegation.prepare_specialist_subagent_scope.assert_called_once_with(
        requested_tool_whitelist=["read_file", "forbidden-tool", "composition-a"],
        specialist_allowed_tool_ids={"allowed-tool"},
        specialist_builtin_names={"read_file"},
        specialist_allowed_composition_ids={"composition-a"},
        workspace_root="E:/isolated-worktree",
    )
    delegation.run_sync_ephemeral_subagent.assert_called_once_with(
        parent_session_id="spec-session",
        task="继续查完",
        execution_context="",
        tool_whitelist=["read_file", "forbidden-tool", "composition-a"],
        workspace_root="E:/isolated-worktree",
        effective_scope=effective_scope,
    )
    delegation.continue_subagent.assert_called_once_with(
        parent_session_id="spec-session",
        subagent_id="child-session",
        instruction="从断点继续",
        extra_iterations=20,
        effective_scope=effective_scope,
    )

    missing = json.loads(tools["continue_subagent"].handler(subagent_id="different-child-session"))
    assert missing["success"] is False
    assert "ask_parent" in missing["error"]
    assert delegation.continue_subagent.call_count == 1

    second_delegate = json.loads(tools["delegate_to_subagent"].handler(task_description="再起一个"))
    assert second_delegate["success"] is False
    assert delegation.run_sync_ephemeral_subagent.call_count == 1


def test_specialist_control_schemas_are_deep_copies() -> None:
    registry = _tool_registry()
    tools = {
        tool.name: tool
        for tool in registry.build_delegated_executor_tools(
            set(),
            agent_type=AgentType.SPECIALIST,
            executor_id="spec-session",
            specialist_id="spec-1",
        )()
    }
    specialist_continue = tools["continue_subagent"].schema
    specialist_inspect = tools["inspect_subagent"].schema
    specialist_delegate = tools["delegate_to_subagent"].schema
    assistant_continue_description = CONTINUE_SUBAGENT_SCHEMA["function"]["parameters"][
        "properties"
    ]["subagent_id"]["description"]
    assistant_inspect_description = INSPECT_SUBAGENT_SCHEMA["function"]["parameters"]["properties"][
        "subagent_id"
    ]["description"]

    assert specialist_continue is not CONTINUE_SUBAGENT_SCHEMA
    assert specialist_inspect is not INSPECT_SUBAGENT_SCHEMA
    assert specialist_delegate is not DELEGATE_TO_SUBAGENT_SCHEMA
    assert (
        "组合 ID"
        in specialist_delegate["function"]["parameters"]["properties"]["tool_whitelist"][
            "description"
        ]
    )
    assert "quota_exhausted" in specialist_continue["function"]["description"]
    assert "新开" not in specialist_inspect["function"]["description"]
    specialist_continue["function"]["parameters"]["properties"]["subagent_id"][
        "description"
    ] = "mutated"
    specialist_inspect["function"]["parameters"]["properties"]["subagent_id"][
        "description"
    ] = "mutated"

    assert (
        CONTINUE_SUBAGENT_SCHEMA["function"]["parameters"]["properties"]["subagent_id"][
            "description"
        ]
        == assistant_continue_description
    )
    assert (
        INSPECT_SUBAGENT_SCHEMA["function"]["parameters"]["properties"]["subagent_id"][
            "description"
        ]
        == assistant_inspect_description
    )


def test_effective_scope_intersects_child_request_with_specialist_authority(
    mock_config, in_memory_db
) -> None:
    orchestrator = AgentOrchestrator(MagicMock(), mock_config)
    published_allowed = SimpleNamespace(tool_id="tool-allowed", status="published")
    published_forbidden = SimpleNamespace(tool_id="tool-forbidden", status="published")
    tools_by_id = {
        "tool-allowed": published_allowed,
        "tool-forbidden": published_forbidden,
    }
    orchestrator._tool_repo = MagicMock()
    orchestrator._tool_repo.get_by_id.side_effect = tools_by_id.get
    orchestrator._tool_repo.get_by_name.return_value = None
    orchestrator._composition_service = MagicMock()
    orchestrator._composition_service.get_execution_snapshot.side_effect = lambda composition_id: (
        object() if composition_id == "composition-a" else None
    )

    scope = orchestrator.delegation_orchestrator.prepare_specialist_subagent_scope(
        requested_tool_whitelist=[
            "tool-allowed",
            "tool-forbidden",
            "read_file",
            "write_file",
            "composition-a",
            "composition-withdrawn",
        ],
        specialist_allowed_tool_ids={"tool-allowed"},
        specialist_builtin_names={"read_file"},
        specialist_allowed_composition_ids={"composition-a", "composition-withdrawn"},
        workspace_root="E:/isolated-worktree",
    )

    assert scope.dynamic_tool_ids == frozenset({"tool-allowed"})
    assert scope.builtin_names == frozenset({"read_file"})
    assert scope.composition_ids == frozenset({"composition-a"})
    assert scope.workspace_root == "E:/isolated-worktree"
    assert scope.capture_state is ScopeCaptureState.BOUNDED


def test_effective_scope_does_not_inherit_unrequested_compositions(
    mock_config, in_memory_db
) -> None:
    orchestrator = AgentOrchestrator(MagicMock(), mock_config)
    orchestrator._tool_repo = MagicMock()
    orchestrator._tool_repo.get_by_id.return_value = None
    orchestrator._tool_repo.get_by_name.return_value = None
    orchestrator._composition_service = MagicMock()
    orchestrator._composition_service.get_execution_snapshot.return_value = object()

    scope = orchestrator.delegation_orchestrator.prepare_specialist_subagent_scope(
        requested_tool_whitelist=["read_file"],
        specialist_allowed_tool_ids=set(),
        specialist_builtin_names={"read_file"},
        specialist_allowed_composition_ids={"composition-a"},
        workspace_root=None,
    )

    assert scope.composition_ids == frozenset()


def test_unrestricted_effective_scope_is_materialized_at_capture(mock_config, in_memory_db) -> None:
    orchestrator = AgentOrchestrator(MagicMock(), mock_config)
    orchestrator._tool_repo = MagicMock()
    orchestrator._tool_repo.get_all_published.return_value = [
        SimpleNamespace(tool_id="tool-a"),
        SimpleNamespace(tool_id="tool-b"),
    ]
    orchestrator._composition_service = MagicMock()
    orchestrator._composition_service.list_compositions.return_value = [
        SimpleNamespace(composition_id="composition-a")
    ]
    orchestrator._composition_service.get_execution_snapshot.return_value = object()

    scope = orchestrator.delegation_orchestrator.prepare_specialist_subagent_scope(
        requested_tool_whitelist=None,
        specialist_allowed_tool_ids=None,
        specialist_builtin_names={"read_file", "search_files"},
        specialist_allowed_composition_ids=None,
        workspace_root=None,
    )

    assert scope.dynamic_tool_ids == frozenset({"tool-a", "tool-b"})
    assert scope.composition_ids == frozenset({"composition-a"})
    assert scope.capture_state is ScopeCaptureState.UNRESTRICTED_AT_CAPTURE


def test_inherited_specialist_tool_ids_are_revalidated_at_capture(
    mock_config, in_memory_db
) -> None:
    orchestrator = AgentOrchestrator(MagicMock(), mock_config)
    tools_by_id = {
        "tool-live": SimpleNamespace(tool_id="tool-live", status="published"),
        "tool-withdrawn": SimpleNamespace(tool_id="tool-withdrawn", status="draft"),
    }
    orchestrator._tool_repo = MagicMock()
    orchestrator._tool_repo.get_by_id.side_effect = tools_by_id.get
    orchestrator._tool_repo.get_by_name.return_value = None
    orchestrator._composition_service = MagicMock()

    scope = orchestrator.delegation_orchestrator.prepare_specialist_subagent_scope(
        requested_tool_whitelist=None,
        specialist_allowed_tool_ids={"tool-live", "tool-withdrawn"},
        specialist_builtin_names={"read_file"},
        specialist_allowed_composition_ids=set(),
        workspace_root=None,
    )

    assert scope.dynamic_tool_ids == frozenset({"tool-live"})


def test_first_launch_consumes_captured_scope_and_workspace() -> None:
    owner = MagicMock()
    owner._prompt_builder.format_capability_catalog.return_value = "catalog"
    owner._build_ephemeral_subagent_prompt.return_value = "system prompt"
    owner._new_delegation_workflow_id.return_value = "workflow-1"
    owner._session_store.create_session.return_value = "child-session"
    owner._format_delegated_task_input.return_value = "delegated input"
    owner._run_delegated_executor.return_value = {
        "success": False,
        "paused": True,
        "subagent_id": "child-session",
    }
    scope = EffectiveSubagentScope(
        dynamic_tool_ids=frozenset({"tool-a"}),
        builtin_names=frozenset({"read_file"}),
        composition_ids=frozenset({"composition-a"}),
        workspace_root="E:/isolated-worktree",
    )

    result = DelegationOrchestrator(owner).run_sync_ephemeral_subagent(
        parent_session_id="spec-session",
        task="查完这批文件",
        tool_whitelist=["read_file", "tool-a", "composition-a"],
        workspace_root="E:/wrong-root-must-not-win",
        effective_scope=scope,
    )

    assert result["subagent_id"] == "child-session"
    owner._run_delegated_executor.assert_called_once_with(
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        session_id="child-session",
        workflow_id="workflow-1",
        parent_session_id="spec-session",
        user_input="delegated input",
        system_prompt="system prompt",
        allowed_tool_ids={"tool-a"},
        tool_whitelist=["read_file", "tool-a", "composition-a"],
        current_task_id=None,
        workspace_root="E:/isolated-worktree",
        allowed_composition_ids={"composition-a"},
        allowed_builtin_tool_names={"read_file"},
    )


def test_ephemeral_subagent_cannot_delegate_to_subagent() -> None:
    # 防深度封顶失效：普通被委派者（临时子代理）不得获得 delegate_to_subagent
    registry = _tool_registry()

    factory = registry.build_delegated_executor_tools(
        {"tool-a"},
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        executor_id="sub-session",
    )
    names = {tool.name for tool in factory()}
    assert {
        "delegate_to_subagent",
        "continue_subagent",
        "inspect_subagent",
    }.isdisjoint(names)


def test_delegated_executor_filters_builtin_tools_when_capability_scope_names_builtins() -> None:
    registry = _tool_registry()

    planner_factory = registry.build_delegated_executor_tools(
        set(),
        tool_whitelist=["read_file", "search_files"],
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        executor_id="proposal-plan-session",
    )
    tester_factory = registry.build_delegated_executor_tools(
        set(),
        tool_whitelist=["exec", "read_file", "search_files"],
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        executor_id="proposal-test-session",
    )

    planner_names = {tool.name for tool in planner_factory()}
    tester_names = {tool.name for tool in tester_factory()}

    assert {"read_file", "search_files"}.issubset(planner_names)
    assert "write_file" not in planner_names
    assert "edit_file" not in planner_names
    assert "apply_patch" not in planner_names
    assert "exec" not in planner_names

    assert {"exec", "read_file", "search_files"}.issubset(tester_names)
    assert "write_file" not in tester_names
    assert "edit_file" not in tester_names
    assert "apply_patch" not in tester_names


def test_ephemeral_todo_update_handler_aligns_executor_id_with_task_assignee() -> None:
    # 临时子代理 task.assignee_id 是 dispatch 时设的类型占位 'ephemeral_subagent'
    # （非 child session）。build_delegated_executor_tools 给 ephemeral 构造的
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
    registry = _tool_registry()
    factory = registry.build_delegated_executor_tools(
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
    registry = _tool_registry()
    factory = registry.build_delegated_executor_tools(
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
