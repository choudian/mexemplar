"""tool_gap_detector 脱敏测试（026 C3）。

error_message 可能含已注册 secret（API key 等），不得原样入 gap_report.evidence 或
喂外部 LLM。复用 SecretRedactor（经 get_debug_service().redactor）。
"""

import json
from unittest.mock import MagicMock

from src.business.debug.service import get_debug_service
from src.business.self_improvement.tool_gap_detector import ToolGapDetector
from src.data.repos.self_improvement_repository import SelfImprovementRepository


def test_detect_bug_patterns_redacts_registered_secret_in_evidence(in_memory_db) -> None:
    """error_message 中的已注册 secret 必须在入库 evidence 前脱敏。

    Regression (026 C3): tool_gap_detector 曾把原始 error_message 截断后直接入
    gap_report.evidence，泄漏 secret 到数据库。
    """
    secret = "sk-test-leak-7C9F2A"
    get_debug_service().register_secret(secret)

    with SelfImprovementRepository() as repo:
        detector = ToolGapDetector(repo, MagicMock(), MagicMock())
        transitions = [
            {
                "status": "failed",
                "tool_name": "search_web",
                "error_message": f"upstream 403: key {secret} is invalid",
                "session_id": "sess-a",
            },
            {
                "status": "failed",
                "tool_name": "search_web",
                "error_message": f"upstream 403: key {secret} is invalid",
                "session_id": "sess-b",
            },
        ]
        detector._detect_bug_patterns(transitions, config=MagicMock())

        reports = repo.get_unresolved_gap_reports()
        assert reports, "expected a bug_pattern gap report"
        evidence_blob = json.dumps([r.evidence for r in reports], ensure_ascii=False)
        assert secret not in evidence_blob
        assert "REDACTED" in evidence_blob


def test_generate_tool_proposal_redacts_secret_in_prompt(in_memory_db) -> None:
    """喂 LLM 的 prompt 中 evidence 里的 secret 必须脱敏（覆盖存量库数据）。

    即使存量 gap_report.evidence 含历史泄漏，_generate_tool_proposal 构造 prompt
    前也必须 redact。
    """
    secret = "sk-test-leak-B3D8E1"
    get_debug_service().register_secret(secret)

    with SelfImprovementRepository() as repo:
        detector = ToolGapDetector(repo, MagicMock(), MagicMock())
        report = {
            "gap_type": "bug_pattern",
            "evidence": {"sample_errors": [f"key {secret} rejected"]},
            "occurrence_count": 2,
        }
        captured: dict = {}

        class _LLM:
            def call(self, *, messages, max_tokens, temperature):
                captured["prompt"] = messages[0]["content"]
                return '{"proposed_code": "def x(): pass", "rationale": "r"}'

        detector._generate_tool_proposal(_LLM(), report)

    assert secret not in captured["prompt"]
    assert "REDACTED" in captured["prompt"]
