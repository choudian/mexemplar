from src.business.self_improvement.execution_review_service import ExecutionReviewService, REVIEWER_TOOLS


def test_reviewer_toolset_is_read_only():
    assert {tool.name for tool in REVIEWER_TOOLS} == {"load_tool_output"}
    assert all(not tool.has_side_effects for tool in REVIEWER_TOOLS)


class _StubLLM:
    def complete_json(self, *args, **kwargs):
        return {
            "verdict": "重复抓取",
            "findings": [
                {
                    "type": "效率",
                    "what": "同一 URL 两次 web_fetch",
                    "evidence": "step0,step2",
                    "severity": "med",
                    "suggestion": "复用首次结果",
                    "worth_changing": True,
                }
            ],
        }


def test_review_returns_advisory_report():
    service = ExecutionReviewService()
    report = service.review(
        {"session_id": "ast_x", "steps": [], "iterations": 2, "delegated": True},
        llm_client=_StubLLM(),
    )

    assert report["advisory"] is True
    assert report["findings"][0]["type"] == "效率"
