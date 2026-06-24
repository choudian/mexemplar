from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.business.orchestration.agent import AgentOrchestrator
from src.data.repositories import TeachingFailureRepository
from src.utils.events import clear_all, emit


def _build_orchestrator(mock_config):
    return AgentOrchestrator(
        llm_client=SimpleNamespace(),
        config=mock_config,
        llm_reviewer=SimpleNamespace(),
    )


def test_phase3_split_modules_exist():
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.business.orchestration.agent.assistant_prompt_builder import AssistantPromptBuilder
    from src.business.orchestration.agent.assistant_task_worker import AssistantTaskWorker
    from src.business.orchestration.agent.delegation_orchestrator import (
        DelegationOrchestrator,
    )
    from src.business.orchestration.agent.teaching_orchestrator import TeachingOrchestrator
    from src.business.orchestration.agent.teaching_failure_tracker import (
        TeachingFailureTracker,
    )
    from src.business.orchestration.agent.tool_registry import ToolRegistry
    from src.business.orchestration.agent.workflow_retry_coordinator import (
        WorkflowRetryCoordinator,
    )

    assert AgentSessionStore is not None
    assert AssistantPromptBuilder is not None
    assert AssistantTaskWorker is not None
    assert DelegationOrchestrator is not None
    assert TeachingOrchestrator is not None
    assert TeachingFailureTracker is not None
    assert ToolRegistry is not None
    assert WorkflowRetryCoordinator is not None


def test_old_import_path_builds_new_collaborators(mock_config):
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.business.orchestration.agent.assistant_prompt_builder import AssistantPromptBuilder
    from src.business.orchestration.agent.assistant_task_worker import AssistantTaskWorker
    from src.business.orchestration.agent.delegation_orchestrator import (
        DelegationOrchestrator,
    )
    from src.business.orchestration.agent.teaching_failure_tracker import (
        TeachingFailureTracker,
    )
    from src.business.orchestration.agent.teaching_orchestrator import TeachingOrchestrator
    from src.business.orchestration.agent.tool_registry import ToolRegistry
    from src.business.orchestration.agent.workflow_retry_coordinator import (
        WorkflowRetryCoordinator,
    )

    orchestrator = _build_orchestrator(mock_config)

    assert isinstance(orchestrator._session_store, AgentSessionStore)
    assert isinstance(orchestrator._failure_tracker, TeachingFailureTracker)
    assert isinstance(orchestrator._retry_coordinator, WorkflowRetryCoordinator)
    assert isinstance(orchestrator._task_worker, AssistantTaskWorker)
    assert isinstance(orchestrator._prompt_builder, AssistantPromptBuilder)
    assert isinstance(orchestrator.delegation_orchestrator, DelegationOrchestrator)
    assert isinstance(orchestrator.teaching_orchestrator, TeachingOrchestrator)
    assert isinstance(orchestrator.tool_registry, ToolRegistry)


def test_agent_error_still_records_failure_via_tracker(in_memory_db, mock_config):
    clear_all()
    _build_orchestrator(mock_config)

    emit(
        "agent_error",
        workflow_id="wf_arch_tracker",
        session_id="sess_arch_tracker",
        agent_type="pm",
        error="boom",
        error_type="unit_test",
    )

    record = TeachingFailureRepository().get_by_workflow_id("wf_arch_tracker")
    assert record is not None
    assert record.failed_stage == "pm"
    assert record.error_type == "unit_test"

    clear_all()


def test_retry_coordinator_accessible_via_property(mock_config):
    orchestrator = _build_orchestrator(mock_config)

    with patch.object(orchestrator.retry_coordinator, "retry_teaching") as mock_retry:
        orchestrator.retry_coordinator.retry_teaching("wf_retry_delegate")

    mock_retry.assert_called_once_with("wf_retry_delegate")


def test_retry_coordinator_uses_injected_run_agent_callable():
    from src.business.orchestration.agent.workflow_retry_coordinator import (
        WorkflowRetryCoordinator,
    )

    calls = []

    def run_agent(agent_type, user_input, workflow_id=None, session_id=None):
        calls.append((agent_type, user_input, workflow_id, session_id))

    coordinator = WorkflowRetryCoordinator(
        failure_tracker=SimpleNamespace(),
        session_store=SimpleNamespace(
            find_old_session=lambda workflow_id, stage: "sess_1",
            get_transition_payload=lambda *args, **kwargs: None,
        ),
        run_agent=run_agent,
        start_analysis=lambda *_: None,
        review_counts={},
    )

    coordinator.retry_stage("wf_1", SimpleNamespace(), "pm")

    assert calls == [("pm", None, "wf_1", "sess_1")]


def test_task_worker_accessible_via_property(mock_config):
    orchestrator = _build_orchestrator(mock_config)

    with patch.object(orchestrator.task_worker, "start") as mock_start:
        orchestrator.task_worker.start()

    mock_start.assert_called_once_with()


def test_assistant_prompt_builder_passes_revived_session_signal():
    from src.business.orchestration.agent.assistant_prompt_builder import AssistantPromptBuilder

    session = SimpleNamespace(get_tool_id_set=lambda: None)
    session_store = SimpleNamespace(
        get_session=lambda session_id: session,
        count_messages=lambda session_id: 2,
    )
    tool_repo = SimpleNamespace(get_published_summaries=lambda: [])
    composition_catalog = SimpleNamespace(get_assistant_published_summaries=lambda: [])
    profile_repo = SimpleNamespace(get_default=lambda: None)

    with patch("src.business.brain.context_builder.BrainContextBuilder") as MockBuilder:
        builder_instance = MockBuilder.return_value
        builder_instance.build_context.return_value = MagicMock()
        builder_instance.format_context_for_prompt.return_value = "brain context"

        AssistantPromptBuilder(
            llm_client=SimpleNamespace(),
            session_store=session_store,
            tool_repo=tool_repo,
            composition_catalog=composition_catalog,
            profile_repo=profile_repo,
        ).format_assistant_prompt("sess-existing")

    builder_instance.build_context.assert_called_once_with(
        "sess-existing",
        is_revived_session=True,
    )


def test_assistant_prompt_builder_defers_large_authorized_catalog_without_leaking_names(
    caplog,
):
    from src.business.agents.tools.capability_catalog import CapabilityDiscoveryPolicy
    from src.business.orchestration.agent.assistant_prompt_builder import AssistantPromptBuilder

    session = SimpleNamespace(get_tool_id_set=lambda: {"tool-visible", "tool-hidden"})
    session_store = SimpleNamespace(
        get_session=lambda session_id: session,
        count_messages=lambda session_id: 0,
    )
    tool_repo = SimpleNamespace(
        get_published_summaries=lambda: [
            {
                "tool_id": "tool-visible",
                "tool_name": "不应泄漏技能A",
                "description": "不应泄漏描述A",
            },
            {
                "tool_id": "tool-hidden",
                "tool_name": "不应泄漏技能B",
                "description": "不应泄漏描述B",
            },
            {
                "tool_id": "tool-denied",
                "tool_name": "未授权技能",
                "description": "未授权描述",
            },
        ]
    )
    composition_catalog = SimpleNamespace(get_assistant_published_summaries=lambda: [])
    profile_repo = SimpleNamespace(get_default=lambda: None)
    policy = CapabilityDiscoveryPolicy(1, 6000, 10, 25, 500)
    caplog.set_level("INFO")

    with (
        patch(
            "src.business.orchestration.agent.assistant_prompt_builder."
            "load_capability_discovery_policy",
            return_value=policy,
        ),
        patch("src.business.brain.context_builder.BrainContextBuilder") as MockBuilder,
    ):
        MockBuilder.return_value.build_context.return_value = MagicMock()
        MockBuilder.return_value.format_context_for_prompt.return_value = ""
        prompt = AssistantPromptBuilder(
            llm_client=SimpleNamespace(),
            session_store=session_store,
            tool_repo=tool_repo,
            composition_catalog=composition_catalog,
            profile_repo=profile_repo,
        ).format_assistant_prompt("sess-large")

    assert "共 2 项" in prompt
    assert "search_tools" in prompt
    assert "不应泄漏技能A" not in prompt
    assert "不应泄漏描述A" not in prompt
    assert "未授权技能" not in prompt
    log_text = caplog.text
    assert "agent_type=assistant" in log_text
    assert "item_count=2" in log_text
    assert "rendered_chars=" in log_text
    assert "mode=deferred" in log_text
    assert "不应泄漏技能A" not in log_text
    assert "不应泄漏描述A" not in log_text


def test_assistant_prompt_builder_reloads_runtime_discovery_policy():
    from src.business.agents.tools.capability_catalog import CapabilityDiscoveryPolicy
    from src.business.orchestration.agent.assistant_prompt_builder import AssistantPromptBuilder

    session_store = SimpleNamespace(
        get_session=lambda session_id: SimpleNamespace(get_tool_id_set=lambda: None),
        count_messages=lambda session_id: 0,
    )
    tool_repo = SimpleNamespace(
        get_published_summaries=lambda: [
            {"tool_id": "tool-a", "tool_name": "能力A", "description": "A"},
            {"tool_id": "tool-b", "tool_name": "能力B", "description": "B"},
        ]
    )
    builder = AssistantPromptBuilder(
        llm_client=SimpleNamespace(),
        session_store=session_store,
        tool_repo=tool_repo,
        composition_catalog=SimpleNamespace(get_assistant_published_summaries=lambda: []),
        profile_repo=SimpleNamespace(get_default=lambda: None),
    )
    deferred = CapabilityDiscoveryPolicy(1, 6000, 10, 25, 500)
    full = CapabilityDiscoveryPolicy(10, 6000, 10, 25, 500)

    with patch(
        "src.business.orchestration.agent.assistant_prompt_builder."
        "load_capability_discovery_policy",
        side_effect=[deferred, full],
    ):
        first = builder.format_capability_catalog(
            None,
            agent_type="assistant",
            include_descriptions=True,
        )
        second = builder.format_capability_catalog(
            None,
            agent_type="assistant",
            include_descriptions=True,
        )

    assert "完整目录已延迟加载" in first
    assert "能力A" not in first
    assert "能力A" in second
    assert "能力B" in second


def test_delegated_prompts_accept_shared_catalog_section_without_raw_whitelist():
    deferred_section = (
        "### 用户技能与技能组合\n\n"
        "当前授权目录包含 30 个技能、0 个技能组合（共 30 项），"
        "完整目录已延迟加载。"
    )
    specialist = SimpleNamespace(
        name="测试专员",
        description="描述",
        role_definition="职责",
    )

    subagent_prompt = AgentOrchestrator._build_ephemeral_subagent_prompt(
        ["不应直接出现的技能"],
        capability_catalog_section=deferred_section,
    )
    specialist_prompt = AgentOrchestrator._build_specialist_prompt(
        specialist,
        ["不应直接出现的技能"],
        equipped_skills=[],
        capability_catalog_section=deferred_section,
    )

    assert deferred_section in subagent_prompt
    assert deferred_section in specialist_prompt
    assert "不应直接出现的技能" not in subagent_prompt
    assert "不应直接出现的技能" not in specialist_prompt


def test_subagent_delegation_wires_shared_catalog_before_child_session_creation():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._prompt_builder = MagicMock()
    orchestrator._prompt_builder.format_capability_catalog.return_value = (
        "### 用户技能与技能组合\n\n完整目录已延迟加载。"
    )
    orchestrator._resolve_user_tool_ids = MagicMock(return_value={"tool-a"})
    orchestrator._new_delegation_workflow_id = MagicMock(return_value="wf-child")
    orchestrator._session_store = SimpleNamespace(
        create_session=MagicMock(return_value="child-session")
    )
    orchestrator._run_delegated_executor = MagicMock(return_value={"success": False})

    result = orchestrator._delegate_to_subagent(
        parent_session_id="parent-session",
        task_description="完成任务",
        execution_context="上下文",
        tool_whitelist=["能力A"],
    )

    assert result["delegation_type"] == "ephemeral_subagent"
    orchestrator._prompt_builder.format_capability_catalog.assert_called_once_with(
        {"tool-a"},
        agent_type="ephemeral_subagent",
        include_descriptions=True,
    )
    call = orchestrator._run_delegated_executor.call_args
    assert "完整目录已延迟加载" in call.kwargs["system_prompt"]
    assert "能力A" not in call.kwargs["system_prompt"]
    orchestrator._session_store.create_session.assert_called_once_with(
        "wf-child",
        "ephemeral_subagent",
    )


def test_subagent_delegation_uses_unified_dispatch_without_sync_child_execution():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._dispatch_task_via_unified_model = MagicMock(
        return_value={"accepted": True, "taskId": "tsk_1", "graphId": "tg_1"}
    )
    orchestrator._run_delegated_executor = MagicMock()

    result = orchestrator._delegate_to_subagent(
        parent_session_id="parent-session",
        task_description="完成任务",
        execution_context="上下文",
        tool_whitelist=["tool-a"],
    )

    assert result["accepted"] is True
    assert result["delegation_type"] == "ephemeral_subagent"
    orchestrator._dispatch_task_via_unified_model.assert_called_once_with(
        parent_session_id="parent-session",
        task="完成任务",
        context="上下文",
        assignee_type="ephemeral_subagent",
        assignee_id="ephemeral_subagent",
        capability_scope=["tool-a"],
    )
    orchestrator._run_delegated_executor.assert_not_called()


def test_unified_dispatch_helper_uses_task_dispatcher(monkeypatch):
    from src.business.task_collaboration.service import TaskCollaborationService
    from src.data.repos import AssistantTaskRepository

    class _TaskConfig:
        def get_assistant_tasks_unified_dispatch_enabled(self) -> bool:
            return True

        def get_assistant_tasks_clean_start_guard_enabled(self) -> bool:
            return True

        def get_assistant_tasks_dispatch_max_workers(self) -> int:
            return 2

        def get_assistant_tasks_attempt_lease_seconds(self) -> int:
            return 60

    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _TaskConfig(),
    )
    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _TaskConfig(),
    )
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._config = _TaskConfig()

    result = orchestrator._dispatch_task_via_unified_model(
        parent_session_id="parent-session",
        task="完成任务",
        context="上下文",
        assignee_type="ephemeral_subagent",
        assignee_id="ephemeral_subagent",
        capability_scope=["tool-a"],
    )

    assert result is not None
    assert result["accepted"] is True
    assert result["assignment"] == "directed"
    snapshot = TaskCollaborationService().get_current_graph_snapshot("parent-session")
    assert snapshot is not None
    assert any(task.task_id == result["taskId"] for task in snapshot.tasks)
    assert AssistantTaskRepository().get_task(result["taskId"]) is not None


def test_unified_dispatch_repeated_calls_do_not_invalidate_cached_dispatcher(monkeypatch):
    """Regression: 缓存的 dispatcher 不能持有首次注入、随后被 close 的 service。

    修复前第二次 ``_dispatch_task_via_unified_model`` 会因缓存 dispatcher 持有已关闭
    session 的 service 而静默失败、回退同步路径（返回 None）。dispatcher 无状态化后，
    delegate_task 用当次 service，连续派发都应成功。
    """

    class _TaskConfig:
        def get_assistant_tasks_unified_dispatch_enabled(self) -> bool:
            return True

        def get_assistant_tasks_clean_start_guard_enabled(self) -> bool:
            return True

        def get_assistant_tasks_dispatch_max_workers(self) -> int:
            return 2

        def get_assistant_tasks_attempt_lease_seconds(self) -> int:
            return 60

    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _TaskConfig(),
    )
    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _TaskConfig(),
    )
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._config = _TaskConfig()
    # 本测试关注 dispatcher 缓存不失效（delegate_task 用当次 service）；执行链路由
    # test_assistant_task_reentry_flow 独立覆盖。裸 orchestrator 无法跑真实 executor，
    # 故 no-op 掉 start_attempt_async，避免异步 worker 污染本测试的图/任务状态。
    monkeypatch.setattr(orchestrator, "_start_unified_attempt", lambda *a, **kw: None)

    first = orchestrator._dispatch_task_via_unified_model(
        parent_session_id="parent-session",
        task="第一次任务",
        context="上下文",
        assignee_type="ephemeral_subagent",
        assignee_id="ephemeral_subagent",
        capability_scope=["tool-a"],
    )
    second = orchestrator._dispatch_task_via_unified_model(
        parent_session_id="parent-session",
        task="第二次任务",
        context="上下文",
        assignee_type="ephemeral_subagent",
        assignee_id="ephemeral_subagent",
        capability_scope=["tool-a"],
    )

    assert first is not None and first["accepted"] is True
    assert second is not None and second["accepted"] is True


def test_specialist_delegation_wires_shared_catalog_before_child_session_creation():
    specialist = SimpleNamespace(
        specialist_id="specialist-1",
        name="测试专员",
        description="描述",
        role_definition="职责",
        tool_whitelist='["能力A"]',
        is_active=1,
    )
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._prompt_builder = MagicMock()
    orchestrator._prompt_builder.format_capability_catalog.return_value = (
        "### 用户技能与技能组合\n\n完整目录已延迟加载。"
    )
    orchestrator._resolve_user_tool_ids = MagicMock(return_value={"tool-a"})
    orchestrator._specialist_equipped_skills_snapshot = MagicMock(return_value=[])
    orchestrator._new_delegation_workflow_id = MagicMock(return_value="wf-specialist")
    orchestrator._session_store = SimpleNamespace(
        create_session=MagicMock(return_value="specialist-session")
    )
    orchestrator._run_delegated_executor = MagicMock(return_value={"success": False})

    specialist_repo = MagicMock()
    specialist_repo.get_specialist_by_name.return_value = specialist
    with patch(
        "src.data.repos.specialist_repository.SpecialistRepository"
    ) as MockSpecialistRepository:
        MockSpecialistRepository.return_value.__enter__.return_value = specialist_repo
        result = orchestrator._delegate_to_specialist(
            parent_session_id="parent-session",
            specialist_name="测试专员",
            task="完成任务",
        )

    assert result["delegation_type"] == "specialist"
    orchestrator._prompt_builder.format_capability_catalog.assert_called_once_with(
        {"tool-a"},
        agent_type="specialist",
        include_descriptions=True,
    )
    call = orchestrator._run_delegated_executor.call_args
    assert "完整目录已延迟加载" in call.kwargs["system_prompt"]
    assert "能力A" not in call.kwargs["system_prompt"]
    orchestrator._session_store.create_session.assert_called_once_with(
        "wf-specialist",
        "specialist",
    )


def test_specialist_delegation_uses_unified_dispatch_without_sync_child_execution():
    specialist = SimpleNamespace(
        specialist_id="specialist-1",
        name="测试专员",
        description="描述",
        role_definition="职责",
        tool_whitelist='["能力A"]',
        is_active=1,
    )
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._dispatch_task_via_unified_model = MagicMock(
        return_value={"accepted": True, "taskId": "tsk_1", "graphId": "tg_1"}
    )
    orchestrator._run_delegated_executor = MagicMock()
    specialist_repo = MagicMock()
    specialist_repo.get_specialist_by_name.return_value = specialist

    with patch(
        "src.data.repos.specialist_repository.SpecialistRepository"
    ) as MockSpecialistRepository:
        MockSpecialistRepository.return_value.__enter__.return_value = specialist_repo
        result = orchestrator._delegate_to_specialist(
            parent_session_id="parent-session",
            specialist_name="测试专员",
            task="完成任务",
        )

    assert result["accepted"] is True
    assert result["delegation_type"] == "specialist"
    assert result["specialist_id"] == "specialist-1"
    orchestrator._dispatch_task_via_unified_model.assert_called_once_with(
        parent_session_id="parent-session",
        task="完成任务",
        context="完成任务",
        assignee_type="specialist",
        assignee_id="specialist-1",
        capability_scope=["能力A"],
    )
    orchestrator._run_delegated_executor.assert_not_called()


def test_delegated_executor_tools_include_question_and_message_only_meeting_tools():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)

    tools = orchestrator._build_delegated_executor_tools(
        {"tool-a"},
        agent_type="specialist",
        executor_id="specialist-session",
        specialist_id="specialist-1",
    )()
    by_name = {tool.name: tool for tool in tools}

    assert "ask_parent" in by_name
    assert "meeting_send_message" in by_name
    assert "open_meeting_channel" not in by_name
    assert by_name["ask_parent"].is_concurrency_safe is False
    assert by_name["meeting_send_message"].is_concurrency_safe is False


def test_old_shim_import_path_removed():
    """门卫测试：旧兼容入口 agent_orchestrator.py 已被移除"""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.business.orchestration.agent_orchestrator")
