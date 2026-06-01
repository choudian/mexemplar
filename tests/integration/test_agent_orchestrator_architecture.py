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
    from src.business.orchestration.agent.teaching_failure_tracker import (
        TeachingFailureTracker,
    )
    from src.business.orchestration.agent.workflow_retry_coordinator import (
        WorkflowRetryCoordinator,
    )

    assert AgentSessionStore is not None
    assert AssistantPromptBuilder is not None
    assert AssistantTaskWorker is not None
    assert TeachingFailureTracker is not None
    assert WorkflowRetryCoordinator is not None


def test_old_import_path_builds_new_collaborators(mock_config):
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.business.orchestration.agent.assistant_prompt_builder import AssistantPromptBuilder
    from src.business.orchestration.agent.assistant_task_worker import AssistantTaskWorker
    from src.business.orchestration.agent.teaching_failure_tracker import (
        TeachingFailureTracker,
    )
    from src.business.orchestration.agent.workflow_retry_coordinator import (
        WorkflowRetryCoordinator,
    )

    orchestrator = _build_orchestrator(mock_config)

    assert isinstance(orchestrator._session_store, AgentSessionStore)
    assert isinstance(orchestrator._failure_tracker, TeachingFailureTracker)
    assert isinstance(orchestrator._retry_coordinator, WorkflowRetryCoordinator)
    assert isinstance(orchestrator._task_worker, AssistantTaskWorker)
    assert isinstance(orchestrator._prompt_builder, AssistantPromptBuilder)


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


def test_agent_execution_adapter_returns_delegate_result():
    from src.business.agents.config import AgentResult, ResultType
    from src.business.orchestration.agent.orchestrator import _AgentExecutionAdapter

    expected = AgentResult(result_type=ResultType.COMPLETED)
    calls = []

    def run_agent(agent_type, user_input, workflow_id=None, session_id=None):
        calls.append((agent_type, user_input, workflow_id, session_id))
        return expected

    adapter = _AgentExecutionAdapter(run_agent, start_analysis=lambda *_: None)

    result = adapter.run_agent("pm", "input", workflow_id="wf_1", session_id="sess_1")

    assert result is expected
    assert calls == [("pm", "input", "wf_1", "sess_1")]


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


def test_old_shim_import_path_removed():
    """门卫测试：旧兼容入口 agent_orchestrator.py 已被移除"""
    import importlib

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("src.business.orchestration.agent_orchestrator")
