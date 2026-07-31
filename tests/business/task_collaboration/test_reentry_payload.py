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

    def test_needs_review_empty_safe_summary_falls_back_to_the_default(self) -> None:
        """空摘要发给主助理等于没信息，回退到默认文案。

        这条原本断言空字符串原样传出，理由是"dict.get 对已存在的键返回 ''"——
        那是在固化 Python 的取值行为，不是在描述期望的业务行为。
        """
        result = _paused_reentry_payload(
            {"reentry_type": "needs_review", "task_id": "t-1", "safe_summary": ""}
        )
        assert result is not None
        assert result["safeSummary"] == "节点标记为需确认，请裁定是否执行。"


class TestPausedReentryPayloadFallback:
    """认不出的暂停一律兜底通知主助理，绝不静默丢弃。

    这个 class 原名 ``TestPausedReentryPayloadUnknownType``，断言"未知 reentry_type
    返回 None"。那是白名单设计的产物：认不出就什么都不做——于是撞轮次预算暂停的任务
    状态全部正确落库，却永远没有人被告知。现在改成默认通知 + 显式排除。
    """

    def test_unknown_reentry_type_still_wakes_the_assistant(self) -> None:
        result = _paused_reentry_payload({"reentry_type": "something_else"})
        assert result is not None
        assert result["eventType"] == "something_else"
        assert result["safeSummary"]

    def test_missing_reentry_type_still_wakes_the_assistant(self) -> None:
        result = _paused_reentry_payload({"other_key": "value"})
        assert result is not None
        assert result["safeSummary"]

    def test_non_dict_returns_none(self) -> None:
        """输入不是 dict 属于调用错误，跟"认不出的暂停"是两回事，仍然返回 None。"""
        assert _paused_reentry_payload(None) is None
        assert _paused_reentry_payload("string") is None
        assert _paused_reentry_payload(42) is None


class TestPausedReentryPayloadWaitingOn:
    """只有球在主助理手上才叫醒它——等用户、等系统各有自己的通知路径。"""

    def test_waiting_on_user_does_not_wake_the_assistant(self) -> None:
        result = _paused_reentry_payload(
            {"reentry_type": "budget_exhausted", "task_id": "t-1"},
            waiting_on="user",
        )
        assert result is None

    def test_waiting_on_system_does_not_wake_the_assistant(self) -> None:
        result = _paused_reentry_payload(
            {"reentry_type": "budget_exhausted", "task_id": "t-1"},
            waiting_on="system",
        )
        assert result is None

    def test_waiting_on_assistant_wakes_it(self) -> None:
        result = _paused_reentry_payload(
            {"reentry_type": "budget_exhausted", "task_id": "t-1"},
            waiting_on="assistant",
        )
        assert result is not None
        assert result["taskId"] == "t-1"

    def test_suspend_reason_decides_when_waiting_on_is_absent(self) -> None:
        """没有显式 waiting_on 时按 suspend_reason 推——user_stop 是等用户，不叫主助理。"""
        assert (
            _paused_reentry_payload({"suspend_reason": "user_stop", "task_id": "t-1"})
            is None
        )
        assert (
            _paused_reentry_payload({"suspend_reason": "budget_exhausted", "task_id": "t-1"})
            is not None
        )


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
