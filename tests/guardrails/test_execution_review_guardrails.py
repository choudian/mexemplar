from src.business.self_improvement.execution_review_service import ExecutionReviewService, REVIEWER_TOOLS
from src.business.self_improvement.execution_review_trigger import should_review


def test_reviewer_has_no_side_effect_tools():
    assert {tool.name for tool in REVIEWER_TOOLS} == {"load_tool_output"}
    assert all(not tool.has_side_effects for tool in REVIEWER_TOOLS)


def test_switch_off_short_circuits_enqueue():
    assert should_review(
        enabled=False,
        delegated=True,
        tool_executed=True,
        session_count_today=0,
        max_per_session=99,
    ) is False


def test_advisory_is_always_true():
    class _LLM:
        def complete_json(self, *args, **kwargs):
            return {"verdict": "x", "findings": []}

    report = ExecutionReviewService().review(
        {"session_id": "s", "steps": [], "iterations": 0, "delegated": True},
        _LLM(),
    )

    assert report["advisory"] is True
