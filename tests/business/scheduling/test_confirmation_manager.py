"""创建确认卡的 fail-closed 状态机与重连快照（033 FR-006）。"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest

from src.business.scheduling import scheduling_confirmation_manager as confirmation
from src.business.scheduling.scheduler_worker import SchedulerWorker


def _draft() -> dict:
    return {
        "source_type": "direct",
        "schedule_kind": "one_shot",
        "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
        "instruction": "原始指令",
        "title": "原始标题",
        "source_ref": "原始指令",
        "scheduleDescription": "一次性 7月19日 18:00",
    }


@pytest.fixture(autouse=True)
def _reset_confirmation_state(monkeypatch):
    confirmation.reset_state_for_tests()
    monkeypatch.setattr(confirmation, "_resolve_timeout_seconds", lambda: 30)
    monkeypatch.setattr(confirmation, "_emit_requested", lambda pending: None)
    monkeypatch.setattr(confirmation, "_emit_resolved", lambda pending, status: None)
    yield
    confirmation.reset_state_for_tests()


def test_expired_confirmation_cannot_create_even_without_expiry_tick(monkeypatch):
    now = datetime(2026, 7, 19, 10, 0, 0)
    monkeypatch.setattr(confirmation, "utc_now_naive", lambda: now)
    request_id = confirmation.create(_draft(), "ast_expired")

    monkeypatch.setattr(
        confirmation,
        "utc_now_naive",
        lambda: now + timedelta(seconds=31),
    )
    calls: list[tuple[dict, bool]] = []

    class _Service:
        def create_from_draft(self, draft, *, unattended_auto_approve=False):
            calls.append((draft, unattended_auto_approve))
            return {"scheduledTaskId": "sch_should_not_exist"}

        def close(self):
            pass

    result = confirmation.submit_decision(
        request_id,
        "confirm",
        service_factory=_Service,
    )

    assert result is None
    assert calls == []
    assert confirmation.list_pending("ast_expired") == []
    assert request_id not in confirmation._PENDING


def test_stop_settlement_wins_over_late_confirmation():
    request_id = confirmation.create(_draft(), "ast_stopped")

    assert confirmation.settle_for_session_stopped("ast_stopped") == [request_id]
    assert request_id not in confirmation._PENDING
    assert (
        confirmation.submit_decision(
            request_id,
            "confirm",
            service_factory=lambda: pytest.fail("stopped card must not create"),
        )
        is None
    )


def test_stop_during_failed_confirmation_does_not_resurrect_pending(monkeypatch):
    request_id = confirmation.create(_draft(), "ast_stop_during_create")
    create_entered = threading.Event()
    release_create = threading.Event()
    resolved: list[str] = []
    outcome: dict[str, BaseException] = {}

    class _FailingService:
        def create_from_draft(self, _draft_value, *, unattended_auto_approve=False):
            create_entered.set()
            assert release_create.wait(timeout=2)
            raise RuntimeError("database unavailable")

        def close(self):
            pass

    monkeypatch.setattr(
        confirmation,
        "_emit_resolved",
        lambda _pending, status: resolved.append(status),
    )

    def confirm() -> None:
        try:
            confirmation.submit_decision(
                request_id,
                "confirm",
                service_factory=_FailingService,
            )
        except BaseException as exc:  # pragma: no branch - captured for thread assertion
            outcome["error"] = exc

    thread = threading.Thread(target=confirm)
    thread.start()
    assert create_entered.wait(timeout=2)

    assert confirmation.settle_for_session_stopped("ast_stop_during_create") == [request_id]
    release_create.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert isinstance(outcome.get("error"), RuntimeError)
    assert resolved == ["stopped"]
    assert confirmation.list_pending("ast_stop_during_create") == []
    assert request_id not in confirmation._PENDING


def test_requested_event_failure_leaves_no_confirmable_pending(monkeypatch):
    def _raise(_pending):
        raise RuntimeError("event projector unavailable")

    monkeypatch.setattr(confirmation, "_emit_requested", _raise)

    with pytest.raises(RuntimeError, match="event projector unavailable"):
        confirmation.create(_draft(), "ast_invisible")

    assert confirmation.list_pending() == []
    assert confirmation._PENDING == {}


def test_public_edited_draft_only_overrides_title_and_instruction():
    request_id = confirmation.create(_draft(), "ast_edit")
    captured: dict = {}

    class _Service:
        def create_from_draft(self, draft, *, unattended_auto_approve=False):
            captured.update(draft)
            captured["auto"] = unattended_auto_approve
            return {"scheduledTaskId": "sch_created"}

        def close(self):
            pass

    result = confirmation.submit_decision(
        request_id,
        "confirm",
        {
            "title": "用户改过的标题",
            "instruction": "用户改过的指令",
            "scheduleKind": "recurring",
            "sourceType": "todo",
            "scheduleDescription": "伪造展示",
        },
        True,
        service_factory=_Service,
    )

    assert result == {"scheduledTaskId": "sch_created"}
    assert captured["title"] == "用户改过的标题"
    assert captured["instruction"] == "用户改过的指令"
    assert captured["schedule_kind"] == "one_shot"
    assert captured["source_type"] == "direct"
    assert captured["schedule_payload"] == {"run_at": "2026-07-19T10:00:00"}
    assert captured["auto"] is True
    assert request_id not in confirmation._PENDING


def test_create_snapshots_mutable_draft_before_confirmation() -> None:
    draft = _draft()
    request_id = confirmation.create(draft, "ast_snapshot")
    draft["title"] = "迟到篡改"
    draft["schedule_payload"]["run_at"] = "2099-01-01T00:00:00"
    captured: dict = {}

    class _Service:
        def create_from_draft(self, confirmed_draft, *, unattended_auto_approve=False):
            captured.update(confirmed_draft)
            return {"scheduledTaskId": "sch_snapshot"}

        def close(self):
            pass

    confirmation.submit_decision(
        request_id,
        "confirm",
        service_factory=_Service,
    )

    assert captured["title"] == "原始标题"
    assert captured["schedule_payload"] == {"run_at": "2026-07-19T10:00:00"}


def test_cancelled_confirmation_is_removed_from_memory() -> None:
    request_id = confirmation.create(_draft(), "ast_cancelled")

    assert confirmation.submit_decision(request_id, "cancel") == {}

    assert request_id not in confirmation._PENDING


def test_pending_snapshot_is_globally_recoverable_and_renderable():
    first = confirmation.create(_draft(), "ast_first")
    second_draft = {**_draft(), "title": "第二张卡", "instruction": "第二条指令"}
    second = confirmation.create(second_draft, "ast_second")

    items = confirmation.list_pending()

    assert [item["requestId"] for item in items] == [first, second]
    assert items[0]["draft"] == {
        "title": "原始标题",
        "scheduleDescription": "一次性 7月19日 18:00",
        "instruction": "原始指令",
        "scheduleKind": "one_shot",
        "sourceType": "direct",
    }
    assert items[0]["unattendedAutoApprove"] is False
    assert [item["requestId"] for item in confirmation.list_pending("ast_second")] == [second]


def test_scheduler_tick_expires_confirmation_even_without_due_tasks(monkeypatch):
    calls: list[str] = []

    class _Manager:
        def expire_due(self):
            calls.append("expire")
            return []

    class _Repo:
        def list_due(self, _now, *, limit):
            assert limit == 100
            return []

    class _Service:
        _repo = _Repo()

    monkeypatch.setattr(
        confirmation,
        "get_scheduling_confirmation_manager",
        lambda: _Manager(),
    )
    worker = SchedulerWorker(
        _Service(),
        object(),
        run_repo=object(),
        retry_terminal_events=lambda: calls.append("retry_terminal") or 0,
    )

    worker._tick()

    assert calls == ["retry_terminal", "expire"]
