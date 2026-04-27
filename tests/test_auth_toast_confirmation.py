import threading
import time
from pathlib import Path

import pytest

import src.business.agents.tools.builtin_general_tools as general_tools


@pytest.fixture(autouse=True)
def reset_confirmation_state():
    general_tools.reset_confirmation_state_for_tests()
    yield
    general_tools.reset_confirmation_state_for_tests()


def _make_pending(
    request_id: str = "req-1",
    tool_name: str = "write_file",
    summary: str = "目标文件: demo.txt",
):
    return general_tools.PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=summary,
        created_at=time.monotonic(),
        event=threading.Event(),
    )


def test_set_confirm_result_supports_backward_compatible_default_source(caplog):
    pending = _make_pending()
    with general_tools._confirm_lock:
        general_tools._pending_confirms[pending.request_id] = pending

    with caplog.at_level("INFO"):
        general_tools.set_confirm_result(pending.request_id, True)

    assert pending.event.is_set() is True
    assert pending.result is True
    assert pending.source == general_tools.CONFIRM_SOURCE_TOAST
    assert pending.decision == general_tools.CONFIRM_DECISION_ACCEPTED
    assert '"decision": "accepted"' in caplog.text


def test_set_confirm_result_ignores_unknown_request_id():
    general_tools.set_confirm_result("missing", True)

    with general_tools._confirm_lock:
        assert general_tools._pending_confirms == {}


def test_write_summary_only_contains_target_path():
    summary = general_tools._build_write_summary(Path("demo.txt"))
    assert "demo.txt" in summary
    assert "content" not in summary.lower()


def test_edit_summary_truncates_old_and_new_text():
    summary = general_tools._build_edit_summary(
        Path("demo.txt"),
        "before-" * 40,
        "after-" * 40,
    )
    assert "demo.txt" in summary
    assert "before-before" in summary
    assert "after-after" in summary
    assert len(summary) < 320


def test_summary_helpers_redact_obvious_secrets():
    summary = general_tools._build_edit_summary(
        Path("demo.txt"),
        "password=super-secret-value",
        "token=secret-token-value",
    )
    assert "super-secret-value" not in summary
    assert "secret-token-value" not in summary
    assert "password=***" in summary
    assert "token=***" in summary


def test_exec_summary_keeps_only_first_line():
    summary = general_tools._build_exec_summary("python --version\nRemove-Item important.txt")
    assert "python --version" in summary
    assert "Remove-Item" not in summary


def test_auto_approve_scope_flips_on_and_off():
    assert general_tools.is_auto_approve_enabled() is False
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)
    assert general_tools.is_auto_approve_enabled() is True
    general_tools.reset_auto_approve()
    assert general_tools.is_auto_approve_enabled() is False


def test_confirm_or_reject_logs_auto_approved_path(caplog):
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)

    with caplog.at_level("INFO"):
        result = general_tools._confirm_or_reject("write_file", "目标文件: demo.txt")

    assert result is None
    assert '"decision": "auto_approved"' in caplog.text
    assert '"source": "auto_scope"' in caplog.text


def test_timeout_source_maps_to_timeout_decision(caplog):
    pending = _make_pending(
        request_id="req-timeout",
        tool_name="exec",
        summary="命令首行: python --version",
    )
    with general_tools._confirm_lock:
        general_tools._pending_confirms[pending.request_id] = pending

    with caplog.at_level("INFO"):
        general_tools.set_confirm_result(
            pending.request_id,
            False,
            general_tools.CONFIRM_SOURCE_TOAST_TIMEOUT,
        )

    assert pending.event.is_set() is True
    assert pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    assert '"decision": "timeout"' in caplog.text


def test_remaining_timeout_uses_pending_created_at(monkeypatch):
    monkeypatch.setattr(general_tools, "CONFIRM_TIMEOUT_MS", 1000)
    pending = _make_pending(request_id="req-remaining")
    pending.created_at = time.monotonic() - 0.4
    with general_tools._confirm_lock:
        general_tools._pending_confirms[pending.request_id] = pending

    remaining_ms = general_tools.get_confirmation_remaining_timeout_ms(pending.request_id)

    assert remaining_ms is not None
    assert 1 <= remaining_ms < 1000


def test_settle_pending_confirmations_respects_created_before_cutoff():
    cutoff = time.monotonic()
    old_pending = _make_pending(request_id="req-old")
    old_pending.created_at = cutoff - 0.1
    new_pending = _make_pending(request_id="req-new")
    new_pending.created_at = cutoff + 0.1
    with general_tools._confirm_lock:
        general_tools._pending_confirms[old_pending.request_id] = old_pending
        general_tools._pending_confirms[new_pending.request_id] = new_pending

    settled = general_tools.settle_pending_confirmations(
        False,
        general_tools.CONFIRM_SOURCE_NEW_CHAT_RESET,
        created_before=cutoff,
    )

    assert settled == [old_pending.request_id]
    assert old_pending.event.is_set() is True
    assert old_pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    assert new_pending.event.is_set() is False
