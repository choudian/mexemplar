import os
import sys
import threading
import time
import inspect
from collections import deque

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame, QWidget  # noqa: E402

import src.business.agents.tools.builtin_general_tools as general_tools  # noqa: E402
from src.ui.mixins.agent_handler_mixin import AgentHandlerMixin  # noqa: E402
from src.ui.page_ids import INTENT_CONFIRMATION, SKILLS  # noqa: E402
from src.ui.widgets.auth_toast import DECISION_ACCEPT, DECISION_ALLOW_ALL  # noqa: E402
from src.utils.logger import get_logger  # noqa: E402


@pytest.fixture(scope="module")
def app():
    try:
        qt_app = QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")
    return qt_app


@pytest.fixture(autouse=True)
def reset_confirmation_state():
    general_tools.reset_confirmation_state_for_tests()
    yield
    general_tools.reset_confirmation_state_for_tests()


class _DummySkillsPage:
    def __init__(self):
        self.refresh_calls = 0
        self.refresh_failures_calls = 0

    def refresh(self):
        self.refresh_calls += 1

    def refresh_failures(self):
        self.refresh_failures_calls += 1


class _DummyMainContent:
    def __init__(self, skills_page):
        self.skills_page = skills_page
        self.switched_pages = []

    def get_page(self, page_name):
        if page_name == SKILLS:
            return self.skills_page
        return None

    def switch_page(self, page_name):
        self.switched_pages.append(page_name)


class _DummyChatWidget:
    def __init__(self):
        self.auto_approve_states = []

    def set_auto_approve_enabled(self, enabled):
        self.auto_approve_states.append(enabled)


class _DummyWindow(QWidget, AgentHandlerMixin):
    def __init__(self, skills_page):
        super().__init__()
        self.logger = get_logger(__name__)
        self.main_content = _DummyMainContent(skills_page)
        self.toasts = []
        self.chat_widget = _DummyChatWidget()
        self._active_toast = None
        self._active_auth_toast = None
        self._auth_toast_queue = deque()
        self._auth_confirm_ignore_before = 0.0

    def _show_toast(self, message, **kwargs):
        self.toasts.append((message, kwargs))

    def _switch_to_pending_tools(self):
        self.main_content.switch_page(SKILLS)

    def _get_chat_widget(self):
        return self.chat_widget

    def _position_active_notification_toast(self):
        if self._active_toast is not None:
            self._active_toast.move(1, 1)


def _add_pending(
    request_id: str,
    tool_name: str = "write_file",
    created_at: float | None = None,
):
    pending = general_tools.PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=f"目标文件: {request_id}.txt",
        created_at=time.monotonic() if created_at is None else created_at,
        event=threading.Event(),
    )
    with general_tools._confirm_lock:
        general_tools._pending_confirms[request_id] = pending
    return pending


def test_failure_resolved_triggers_full_skills_refresh(app):
    page = _DummySkillsPage()
    window = _DummyWindow(page)

    window._on_failure_updated("wf-1", "programmer", "resolved", False)
    QTest.qWait(250)

    assert page.refresh_calls == 1
    assert page.refresh_failures_calls == 0

    window.deleteLater()


def test_failure_update_only_refreshes_failures(app):
    page = _DummySkillsPage()
    window = _DummyWindow(page)

    window._on_failure_updated("wf-1", "programmer", "updated", False)
    QTest.qWait(250)

    assert page.refresh_calls == 0
    assert page.refresh_failures_calls == 1

    window.deleteLater()


def test_tool_saved_from_triage_triggers_full_refresh(app):
    page = _DummySkillsPage()
    window = _DummyWindow(page)

    window._on_tool_saved("wf-1", "tool-1", from_triage=True)
    QTest.qWait(250)

    assert page.refresh_calls == 1
    assert page.refresh_failures_calls == 0
    assert window.main_content.switched_pages == [INTENT_CONFIRMATION]

    window.deleteLater()


def test_auth_confirm_queue_handles_five_requests_fifo_without_loss(app):
    window = _DummyWindow(_DummySkillsPage())
    pending = [_add_pending(f"req-{index}") for index in range(5)]

    for item in pending:
        window._on_confirm_action_requested(item.request_id, item.summary)
    app.processEvents()

    assert window._active_auth_toast.request_id == "req-0"
    assert [item[0] for item in window._auth_toast_queue] == [
        "req-1",
        "req-2",
        "req-3",
        "req-4",
    ]

    for index, item in enumerate(pending):
        window._on_auth_toast_decision(item.request_id, DECISION_ACCEPT)
        app.processEvents()
        assert item.event.is_set() is True
        assert item.result is True
        if index < 4:
            assert window._active_auth_toast.request_id == f"req-{index + 1}"

    assert window._active_auth_toast is None
    assert not window._auth_toast_queue
    window.deleteLater()


def test_auth_toast_does_not_replace_ordinary_toast(app):
    window = _DummyWindow(_DummySkillsPage())
    ordinary_toast = QFrame(window)
    ordinary_toast.show()
    window._active_toast = ordinary_toast
    pending = _add_pending("req-toast")

    window._on_confirm_action_requested(pending.request_id, pending.summary)
    app.processEvents()

    assert window._active_toast is ordinary_toast
    assert window._active_auth_toast is not ordinary_toast
    assert window._active_auth_toast.request_id == "req-toast"
    window.deleteLater()


def test_auth_toast_keeps_main_window_interaction_responsive(app):
    window = _DummyWindow(_DummySkillsPage())
    window.resize(640, 480)
    window.show()
    pending = _add_pending("req-responsive")
    window._on_confirm_action_requested(pending.request_id, pending.summary)
    app.processEvents()

    started = time.perf_counter()
    window.resize(660, 500)
    app.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms <= 100
    assert window._active_auth_toast is not None
    window.deleteLater()


def test_auth_toast_timeout_settles_worker_within_one_second(app, monkeypatch):
    monkeypatch.setattr(general_tools, "CONFIRM_TIMEOUT_MS", 40)
    window = _DummyWindow(_DummySkillsPage())
    window.show()
    app.processEvents()
    pending = _add_pending("req-timeout", "exec")

    started = time.perf_counter()
    window._on_confirm_action_requested(pending.request_id, pending.summary)
    QTest.qWait(120)
    app.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert pending.event.is_set() is True
    assert pending.result is False
    assert pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    assert elapsed_ms <= 1000
    window.deleteLater()


def test_queued_auth_toast_uses_remaining_timeout(app, monkeypatch):
    monkeypatch.setattr(general_tools, "CONFIRM_TIMEOUT_MS", 1000)
    window = _DummyWindow(_DummySkillsPage())
    now = time.monotonic()
    first = _add_pending("req-remaining-first", created_at=now)
    second = _add_pending("req-remaining-second", created_at=now - 0.45)

    window._on_confirm_action_requested(first.request_id, first.summary)
    window._on_confirm_action_requested(second.request_id, second.summary)
    app.processEvents()

    window._on_auth_toast_decision(first.request_id, DECISION_ACCEPT)
    app.processEvents()

    assert window._active_auth_toast.request_id == second.request_id
    assert 1 <= window._active_auth_toast._timeout_ms < 1000
    window.deleteLater()


def test_expired_queued_auth_toast_is_settled_without_display(app, monkeypatch):
    monkeypatch.setattr(general_tools, "CONFIRM_TIMEOUT_MS", 40)
    window = _DummyWindow(_DummySkillsPage())
    first = _add_pending("req-expired-first")
    expired = _add_pending("req-expired-second", created_at=time.monotonic() - 1)

    window._on_confirm_action_requested(first.request_id, first.summary)
    window._on_confirm_action_requested(expired.request_id, expired.summary)
    app.processEvents()

    window._on_auth_toast_decision(first.request_id, DECISION_ACCEPT)
    app.processEvents()

    assert expired.event.is_set() is True
    assert expired.result is False
    assert expired.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    assert window._active_auth_toast is None
    assert not window._auth_toast_queue
    window.deleteLater()


def test_auth_toast_allow_all_enables_auto_approve_and_drains_queue(app):
    window = _DummyWindow(_DummySkillsPage())
    pending = [_add_pending(f"req-allow-{index}") for index in range(10)]

    for item in pending:
        window._on_confirm_action_requested(item.request_id, item.summary)
    app.processEvents()

    window._on_auth_toast_decision("req-allow-0", DECISION_ALLOW_ALL)
    app.processEvents()

    assert general_tools.is_auto_approve_enabled() is True
    assert window._active_auth_toast is None
    assert not window._auth_toast_queue
    assert window.chat_widget.auto_approve_states[-1] is True
    assert all(item.event.is_set() for item in pending)
    assert all(item.result is True for item in pending)
    window.deleteLater()


def test_top_toggle_on_drains_active_and_queued_requests(app):
    window = _DummyWindow(_DummySkillsPage())
    pending = [_add_pending(f"req-toggle-{index}") for index in range(3)]

    for item in pending:
        window._on_confirm_action_requested(item.request_id, item.summary)
    app.processEvents()

    window._on_chat_auto_approve_toggled(True)
    app.processEvents()

    assert general_tools.is_auto_approve_enabled() is True
    assert window._active_auth_toast is None
    assert not window._auth_toast_queue
    assert all(item.event.is_set() for item in pending)
    assert all(item.result is True for item in pending)
    assert window.chat_widget.auto_approve_states[-1] is True
    window.deleteLater()


def test_top_toggle_off_reenables_auth_toast_for_future_requests(app):
    window = _DummyWindow(_DummySkillsPage())
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)

    window._on_chat_auto_approve_toggled(False)
    pending = _add_pending("req-after-off")
    window._on_confirm_action_requested(pending.request_id, pending.summary)
    app.processEvents()

    assert general_tools.is_auto_approve_enabled() is False
    assert pending.event.is_set() is False
    assert window._active_auth_toast.request_id == "req-after-off"
    window.deleteLater()


def test_new_chat_resets_auto_approve_and_settles_pending_requests(app):
    window = _DummyWindow(_DummySkillsPage())
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)
    general_tools.set_auto_approve_enabled(False, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)
    pending = [_add_pending(f"req-new-chat-{index}") for index in range(3)]

    for item in pending:
        window._on_confirm_action_requested(item.request_id, item.summary)
    app.processEvents()

    window._on_chat_new_chat_started()
    app.processEvents()

    assert general_tools.is_auto_approve_enabled() is False
    assert window._active_auth_toast is None
    assert not window._auth_toast_queue
    assert all(item.event.is_set() for item in pending)
    assert all(item.result is False for item in pending)
    assert all(item.decision == general_tools.CONFIRM_DECISION_TIMEOUT for item in pending)
    assert window.chat_widget.auto_approve_states[-1] is False
    window.deleteLater()


def test_new_chat_settles_business_pending_before_ui_signal_arrives(app):
    window = _DummyWindow(_DummySkillsPage())
    pending = _add_pending("req-late-before-queue")

    window._on_chat_new_chat_started()
    app.processEvents()

    assert pending.event.is_set() is True
    assert pending.result is False
    assert pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    assert pending.source == general_tools.CONFIRM_SOURCE_NEW_CHAT_RESET

    window._on_confirm_action_requested(pending.request_id, pending.summary)
    app.processEvents()

    assert window._active_auth_toast is None
    assert not window._auth_toast_queue
    window.deleteLater()


def test_new_chat_cutoff_filters_late_old_confirmation_signal(app):
    window = _DummyWindow(_DummySkillsPage())

    window._on_chat_new_chat_started()
    cutoff = window._auth_confirm_ignore_before
    late_old_pending = _add_pending(
        "req-late-old",
        created_at=cutoff - 0.001,
    )

    window._on_confirm_action_requested(late_old_pending.request_id, late_old_pending.summary)
    app.processEvents()

    assert late_old_pending.event.is_set() is True
    assert late_old_pending.result is False
    assert late_old_pending.source == general_tools.CONFIRM_SOURCE_NEW_CHAT_RESET
    assert window._active_auth_toast is None
    assert not window._auth_toast_queue
    window.deleteLater()


def test_assistant_auth_confirmation_no_longer_uses_qmessagebox_question():
    source = inspect.getsource(AgentHandlerMixin._on_confirm_action_requested)
    assert "QMessageBox.question" not in source
    assert "AuthToastSurface" in inspect.getsource(AgentHandlerMixin._show_next_auth_toast)
