from __future__ import annotations

import pytest

from src.business.task_collaboration.models import (
    TaskStatus,
    derive_display_phase,
    safe_preview,
    validate_task_transition,
)

# ── 正向转换：合法路径 ──


class TestValidTransitions:
    def test_pending_dispatch_to_running(self) -> None:
        validate_task_transition(TaskStatus.PENDING_DISPATCH, TaskStatus.RUNNING)

    def test_pending_dispatch_to_cancelled(self) -> None:
        validate_task_transition(TaskStatus.PENDING_DISPATCH, TaskStatus.CANCELLED)

    def test_running_to_suspended_with_reason(self) -> None:
        for reason in ("waiting_user", "waiting_system", "user_stop"):
            validate_task_transition(
                TaskStatus.RUNNING, TaskStatus.SUSPENDED, suspend_reason=reason
            )

    def test_running_to_completed(self) -> None:
        validate_task_transition(TaskStatus.RUNNING, TaskStatus.COMPLETED)

    def test_running_to_failed(self) -> None:
        validate_task_transition(TaskStatus.RUNNING, TaskStatus.FAILED)

    def test_running_to_cancelled(self) -> None:
        validate_task_transition(TaskStatus.RUNNING, TaskStatus.CANCELLED)

    def test_running_to_pending_dispatch_returned(self) -> None:
        """returned adjudication reopens task to pending_dispatch."""
        validate_task_transition(TaskStatus.RUNNING, TaskStatus.PENDING_DISPATCH)

    def test_suspended_to_running(self) -> None:
        validate_task_transition(TaskStatus.SUSPENDED, TaskStatus.RUNNING)

    def test_suspended_to_cancelled(self) -> None:
        validate_task_transition(TaskStatus.SUSPENDED, TaskStatus.CANCELLED)


# ── 反向转换：终态不可复活 ──


class TestTerminalCannotRevive:
    @pytest.mark.parametrize(
        "terminal",
        [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED],
    )
    @pytest.mark.parametrize(
        "target",
        [
            TaskStatus.PENDING_DISPATCH,
            TaskStatus.RUNNING,
            TaskStatus.SUSPENDED,
        ],
    )
    def test_terminal_cannot_transition_to_non_terminal(
        self, terminal: TaskStatus, target: TaskStatus
    ) -> None:
        with pytest.raises(ValueError, match="terminal task status cannot transition"):
            validate_task_transition(terminal, target)

    def test_completed_to_completed_is_allowed(self) -> None:
        """Same-to-same on terminal is a no-op, not a violation."""
        validate_task_transition(TaskStatus.COMPLETED, TaskStatus.COMPLETED)

    def test_failed_to_failed_is_allowed(self) -> None:
        validate_task_transition(TaskStatus.FAILED, TaskStatus.FAILED)

    def test_cancelled_to_cancelled_is_allowed(self) -> None:
        validate_task_transition(TaskStatus.CANCELLED, TaskStatus.CANCELLED)


# ── 挂起必须有原因 ──


class TestSuspendReasonRequired:
    def test_suspended_without_reason_raises(self) -> None:
        with pytest.raises(ValueError, match="suspend_reason"):
            validate_task_transition(TaskStatus.RUNNING, TaskStatus.SUSPENDED)

    @pytest.mark.parametrize("reason", ["waiting_user", "waiting_system", "user_stop"])
    def test_suspended_with_valid_reason_passes(self, reason: str) -> None:
        validate_task_transition(TaskStatus.RUNNING, TaskStatus.SUSPENDED, suspend_reason=reason)

    def test_suspend_reason_only_valid_for_suspended(self) -> None:
        with pytest.raises(ValueError, match="only valid for suspended"):
            validate_task_transition(
                TaskStatus.RUNNING, TaskStatus.RUNNING, suspend_reason="waiting_system"
            )


# ── display_phase 投影 ──


class TestDisplayPhase:
    def test_running_without_adjudication(self) -> None:
        assert derive_display_phase("running", has_pending_adjudication=False) == "running"

    def test_running_with_adjudication_is_reviewing(self) -> None:
        assert derive_display_phase("running", has_pending_adjudication=True) == "reviewing"

    def test_suspended_is_paused(self) -> None:
        assert derive_display_phase("suspended") == "paused"

    def test_completed_is_done(self) -> None:
        assert derive_display_phase("completed") == "done"

    def test_failed_is_needs_attention(self) -> None:
        assert derive_display_phase("failed") == "needs_attention"

    def test_cancelled_is_needs_attention(self) -> None:
        assert derive_display_phase("cancelled") == "needs_attention"

    def test_pending_dispatch_is_running(self) -> None:
        assert derive_display_phase("pending_dispatch") == "running"


# ── safe_preview 工具 ──


class TestSafePreview:
    def test_collapses_whitespace(self) -> None:
        assert safe_preview("a\n\n b", max_chars=10) == "a b"

    def test_truncates_long_text(self) -> None:
        assert safe_preview("x" * 20, max_chars=8) == "xxxxxxx…"

    def test_short_text_unchanged(self) -> None:
        assert safe_preview("hello", max_chars=10) == "hello"
