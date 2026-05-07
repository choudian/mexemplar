from types import SimpleNamespace

from src.business.agents.config import AgentResult, ResultType
from src.business.orchestration.agent.desktop_syntax_gate import check_code, should_retry
from src.business.orchestration.agent.orchestrator import AgentOrchestrator, _DesktopSyntaxState


def test_desktop_syntax_gate_accepts_valid_code():
    result = check_code("async def execute() -> dict:\n    return {'ok': True}\n")

    assert result.ok is True
    assert result.feedback is None


def test_desktop_syntax_gate_feedback_hides_offset_and_filename():
    code = "async def execute() -> dict:\n    if True\n        return {}\n"
    result = check_code(code)

    assert result.ok is False
    assert result.lineno == 2
    assert "line 2" in result.feedback
    assert "expected ':'" in result.feedback
    assert "offset" not in result.feedback
    assert "filename" not in result.feedback
    assert should_retry(1) is True
    assert should_retry(2) is True
    assert should_retry(3) is False


def test_desktop_syntax_gate_retries_programmer_before_terminal_failure():
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._desktop_syntax_state = {}
    orchestrator._recording_mode = lambda workflow_id: "desktop"
    calls = []
    errors = []
    orchestrator.run_agent = lambda agent_type, user_input, workflow_id: calls.append(
        (agent_type, user_input, workflow_id)
    )
    orchestrator._emit_agent_error = lambda *args: errors.append(args)
    orchestrator._emit_and_log = lambda *args, **kwargs: None
    orchestrator._run_review = lambda *args, **kwargs: None

    result = AgentResult(
        result_type=ResultType.COMPLETED,
        signal_tool=SimpleNamespace(
            name="submit_code",
            args={"code": "async def execute()\n", "description": "", "parameters": []},
        ),
    )

    orchestrator._on_programmer_completed(result, "session-1", "wf-1")

    assert len(calls) == 1
    assert "语法门卫" in calls[0][1]
    assert errors == []
