"""门卫：ask_user_question 仅暴露给主助理，不进委派执行器（subagent/specialist）工具集（FR-008）。"""

from types import SimpleNamespace

from src.business.orchestration.agent import AgentOrchestrator


def _orchestrator(mock_config):
    return AgentOrchestrator(
        llm_client=SimpleNamespace(),
        config=mock_config,
        llm_reviewer=SimpleNamespace(),
    )


def _tool_names(factory):
    return {t.name for t in factory()}


def test_ask_user_question_in_assistant_tools(in_memory_db, mock_config):
    orch = _orchestrator(mock_config)
    names = _tool_names(orch._build_assistant_tools("sess-guard"))
    assert "ask_user_question" in names


def test_ask_user_question_exclusive_flag_set(in_memory_db, mock_config):
    orch = _orchestrator(mock_config)
    tools = orch._build_assistant_tools("sess-guard")()
    ask = next(t for t in tools if t.name == "ask_user_question")
    assert ask.requires_exclusive_call is True
    assert ask.is_interrupting is False


def test_ask_user_question_not_in_delegated_executor_tools(in_memory_db, mock_config):
    orch = _orchestrator(mock_config)
    names = _tool_names(orch._build_delegated_executor_tools(None))
    assert "ask_user_question" not in names


def test_ask_user_question_not_in_specialist_tools(in_memory_db, mock_config):
    orch = _orchestrator(mock_config)
    from src.business.agents.config import AgentType

    names = _tool_names(
        orch._build_delegated_executor_tools(
            None, agent_type=AgentType.SPECIALIST, specialist_id="spec-1"
        )
    )
    assert "ask_user_question" not in names
