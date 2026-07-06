"""proposal_context 序列化单一来源的行为测试（028 T006）。"""

from __future__ import annotations

from types import SimpleNamespace

from src.business.self_improvement.proposal_context import (
    format_discussion_opening_message,
    format_proposal_finding_text,
)


def _proposal(**overrides):
    base = dict(
        status="pending_review",
        what="重复抓取同一 URL",
        evidence="两次读取同一页面",
        suggestion="增加请求级缓存",
        severity="med",
        finding_type="efficiency",
        user_supplement=None,
        branch_name=None,
        result_summary=None,
        result_tests_passed=None,
        error=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestFindingText:
    def test_basic_fields_present(self):
        text = format_proposal_finding_text(_proposal())
        assert "问题：重复抓取同一 URL" in text
        assert "证据：两次读取同一页面" in text
        assert "建议：增加请求级缓存" in text
        assert "严重度：中" in text
        assert "类型：efficiency" in text

    def test_empty_fields_omitted(self):
        text = format_proposal_finding_text(_proposal(evidence=None, severity=""))
        assert "证据" not in text
        assert "严重度" not in text

    def test_supplement_included_when_present(self):
        text = format_proposal_finding_text(_proposal(user_supplement="优先覆盖缓存层"))
        assert "用户补充说明：优先覆盖缓存层" in text

    def test_outcome_excluded_by_default(self):
        text = format_proposal_finding_text(
            _proposal(result_summary="已完成", result_tests_passed=True)
        )
        assert "实施结果" not in text
        assert "测试结论" not in text

    def test_outcome_included_when_requested(self):
        text = format_proposal_finding_text(
            _proposal(
                branch_name="improvement/prop-1",
                result_summary="已加缓存，12 个测试通过",
                result_tests_passed=True,
            ),
            include_outcome=True,
        )
        assert "实施分支：improvement/prop-1" in text
        assert "实施结果：已加缓存，12 个测试通过" in text
        assert "测试结论：通过" in text

    def test_failed_outcome_and_error(self):
        text = format_proposal_finding_text(
            _proposal(result_tests_passed=False, error="执行体越界被拒"),
            include_outcome=True,
        )
        assert "测试结论：未通过" in text
        assert "失败原因：执行体越界被拒" in text

    def test_no_outcome_fields_no_outcome_block(self):
        with_outcome = format_proposal_finding_text(_proposal(), include_outcome=True)
        without = format_proposal_finding_text(_proposal(), include_outcome=False)
        assert with_outcome == without


class TestOpeningMessage:
    def test_contains_status_and_finding(self):
        message = format_discussion_opening_message(_proposal(status="done", result_summary="完成"))
        assert "改进提案讨论" in message
        assert "已完成" in message
        assert "问题：重复抓取同一 URL" in message
        assert "实施结果：完成" in message

    def test_mentions_approval_stays_on_proposal_page(self):
        message = format_discussion_opening_message(_proposal())
        assert "批准或拒绝仍在提案页面完成" in message
