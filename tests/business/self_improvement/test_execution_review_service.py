from src.business.self_improvement.execution_review_service import (
    ExecutionReviewService,
    REVIEWER_TOOLS,
)


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


def test_normalize_findings_clamps_unknown_severity_to_low() -> None:
    """LLM 输出非 high/med/low 的 severity 归一化为 low（026 I6）。

    prompt 声明 severity 只能 high/med/low，但 LLM 可能输出 ``critical`` / 大小写
    混用 / 空。``_normalize_findings`` 必须把非法值收敛到 low，避免脏值透传到
    proposal 与 UI event。
    """
    service = ExecutionReviewService()
    findings = service._normalize_findings(
        [
            {"severity": "critical"},
            {"severity": "HIGH"},
            {"severity": ""},
            {"severity": None},
        ]
    )
    assert [f["severity"] for f in findings] == ["low", "high", "low", "low"]


def test_normalize_findings_preserves_valid_severities() -> None:
    service = ExecutionReviewService()
    findings = service._normalize_findings(
        [{"severity": "high"}, {"severity": "med"}, {"severity": "low"}]
    )
    assert [f["severity"] for f in findings] == ["high", "med", "low"]
