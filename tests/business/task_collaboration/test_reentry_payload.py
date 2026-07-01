"""Tests for _paused_reentry_payload pure function (024 C2)."""

from __future__ import annotations

from src.business.task_collaboration.dispatcher import _paused_reentry_payload


class TestPausedReentryPayloadNeedsReview:
    """C2: needs_review reentry_type produces correct payload."""

    def test_needs_review_payload_has_event_type(self) -> None:
        result = _paused_reentry_payload(
            {"reentry_type": "needs_review", "task_id": "t-1", "safe_summary": "review me"}
        )
        assert result is not None
        assert result["eventType"] == "needs_review"

    def test_needs_review_payload_has_task_id(self) -> None:
        result = _paused_reentry_payload({"reentry_type": "needs_review", "task_id": "t-42"})
        assert result is not None
        assert result["taskId"] == "t-42"

    def test_needs_review_payload_has_safe_summary(self) -> None:
        result = _paused_reentry_payload(
            {"reentry_type": "needs_review", "task_id": "t-1", "safe_summary": "custom summary"}
        )
        assert result is not None
        assert result["safeSummary"] == "custom summary"

    def test_needs_review_safe_summary_defaults(self) -> None:
        """When safe_summary is missing, the Chinese default message is used."""
        result = _paused_reentry_payload({"reentry_type": "needs_review", "task_id": "t-1"})
        assert result is not None
        assert result["safeSummary"] == "节点标记为需确认，请裁定是否执行。"

    def test_needs_review_empty_safe_summary_passes_through(self) -> None:
        """Empty string safe_summary is truthy for dict.get — passes through as-is."""
        result = _paused_reentry_payload(
            {"reentry_type": "needs_review", "task_id": "t-1", "safe_summary": ""}
        )
        assert result is not None
        # dict.get returns "" for existing key (not the default) — this is correct behavior
        assert result["safeSummary"] == ""


class TestPausedReentryPayloadUnknownType:
    """C2: Unknown reentry_type returns None."""

    def test_unknown_reentry_type_returns_none(self) -> None:
        result = _paused_reentry_payload({"reentry_type": "something_else"})
        assert result is None

    def test_no_reentry_type_returns_none(self) -> None:
        result = _paused_reentry_payload({"other_key": "value"})
        assert result is None

    def test_non_dict_returns_none(self) -> None:
        assert _paused_reentry_payload(None) is None
        assert _paused_reentry_payload("string") is None
        assert _paused_reentry_payload(42) is None


class TestPausedReentryPayloadTaskQuestionRegression:
    """C2: task_question branch still works (regression)."""

    def test_task_question_payload(self) -> None:
        result = _paused_reentry_payload(
            {
                "reentry_type": "task_question",
                "question_id": "q-1",
                "question_kind": "clarification",
            }
        )
        assert result is not None
        assert result["eventType"] == "task_question"
        assert result["questionId"] == "q-1"
        assert result["questionKind"] == "clarification"
