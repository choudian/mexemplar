"""门卫：ask_user_question 仅暴露给主助理，不进委派执行器（subagent/specialist）工具集（FR-008）。"""


def _tool_names(factory):
    return {t.name for t in factory()}


def test_ask_user_question_in_assistant_tools(in_memory_db, orchestrator):
    names = _tool_names(orchestrator._build_assistant_tools("sess-guard"))
    assert "ask_user_question" in names


def test_ask_user_question_exclusive_flag_set(in_memory_db, orchestrator):
    tools = orchestrator._build_assistant_tools("sess-guard")()
    ask = next(t for t in tools if t.name == "ask_user_question")
    assert ask.requires_exclusive_call is True
    assert ask.is_interrupting is False


def test_ask_user_question_not_in_delegated_executor_tools(in_memory_db, orchestrator):
    names = _tool_names(orchestrator._build_delegated_executor_tools(None))
    assert "ask_user_question" not in names


def test_ask_user_question_not_in_specialist_tools(in_memory_db, orchestrator):
    from src.business.agents.config import AgentType

    names = _tool_names(
        orchestrator._build_delegated_executor_tools(
            None, agent_type=AgentType.SPECIALIST, specialist_id="spec-1"
        )
    )
    assert "ask_user_question" not in names
