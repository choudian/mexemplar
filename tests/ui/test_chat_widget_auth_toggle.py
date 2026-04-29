import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.ui.widgets.chat_widget import ChatWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


@pytest.fixture()
def widget(monkeypatch, app):
    monkeypatch.setattr(ChatWidget, "_load_sessions", lambda self: None)
    monkeypatch.setattr(ChatWidget, "_get_display_name", lambda self: "测试用户")
    chat_widget = ChatWidget()
    chat_widget.show()
    app.processEvents()
    yield chat_widget
    chat_widget.close()
    chat_widget.deleteLater()


def _toggle(widget: ChatWidget) -> QPushButton:
    toggle = widget.findChild(QPushButton, "chat_auto_approve_toggle")
    assert toggle is not None
    return toggle


def test_toggle_defaults_off_and_emits_state_change(widget, app):
    events = []
    widget.auto_approve_toggled.connect(events.append)
    toggle = _toggle(widget)

    assert toggle.isChecked() is False
    assert "关闭" in toggle.text()

    QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
    app.processEvents()

    assert events == [True]
    assert toggle.isChecked() is True
    assert "开启" in toggle.text()
    assert toggle.property("autoApproveEnabled") is True


def test_programmatic_state_sync_is_reflected_without_extra_signal(widget, app):
    events = []
    widget.auto_approve_toggled.connect(events.append)

    widget.set_auto_approve_enabled(True)
    assert _toggle(widget).isChecked() is True
    assert "开启" in _toggle(widget).text()
    assert events == []

    app.processEvents()

    widget.set_auto_approve_enabled(False)
    assert _toggle(widget).isChecked() is False
    assert "关闭" in _toggle(widget).text()
    assert events == []

    app.processEvents()


def test_new_chat_resets_toggle_and_emits_new_chat_started(widget, app):
    started = []
    widget.new_chat_started.connect(lambda: started.append(True))

    widget.set_auto_approve_enabled(True)
    widget.on_new_chat()
    app.processEvents()

    assert started == [True]
    assert _toggle(widget).isChecked() is False
    assert "关闭" in _toggle(widget).text()


# ── T024: Toggle 可见性测试 ──


def test_toggle_hidden_on_initial_state(widget, app):
    """Toggle 在会话列表默认状态下不显示。"""
    toggle = _toggle(widget)
    # After fixture setup, widget shows session list — toggle hidden
    assert toggle.isVisible() is False


def test_toggle_hidden_on_new_chat_empty(widget, app):
    """新对话起始态 Toggle 隐藏。"""
    widget.on_new_chat()
    app.processEvents()
    toggle = _toggle(widget)
    assert toggle.isVisible() is False


def test_toggle_visible_after_first_send(widget, app, monkeypatch):
    """发送第一条消息后 Toggle 显示。"""
    monkeypatch.setattr(ChatWidget, "_create_session", lambda self, tool_ids=None: "test_sid")
    widget.on_new_chat()
    app.processEvents()

    events = []
    widget.send_message_requested.connect(lambda *args: events.append(args))

    widget.message_input.setPlainText("hello")
    app.processEvents()
    QTest.mouseClick(widget.send_button, Qt.MouseButton.LeftButton)
    app.processEvents()

    toggle = _toggle(widget)
    assert toggle.isVisible() is True
    assert len(events) == 1


def test_toggle_visible_for_existing_session_with_messages(widget, app, monkeypatch):
    """切换到有消息的会话时 Toggle 显示。"""
    from src.business.services.chat_service import ChatHistoryPage, DisplayChatMessage

    dtos = [DisplayChatMessage(sequence=1, role="user", content="hi")]
    monkeypatch.setattr(
        "src.business.services.chat_service.ChatService.get_display_messages",
        lambda self, sid, **kw: ChatHistoryPage(messages=dtos, has_more_before=False),
    )

    widget._switch_to_session("existing_session")
    widget._stack.setCurrentIndex(widget.VIEW_CONVERSATION)
    app.processEvents()

    toggle = _toggle(widget)
    assert toggle.isVisible() is True


def test_toggle_hidden_for_empty_session(widget, app, monkeypatch):
    """切换到空会话时 Toggle 隐藏。"""
    from src.business.services.chat_service import ChatHistoryPage

    monkeypatch.setattr(
        "src.business.services.chat_service.ChatService.get_display_messages",
        lambda self, sid, **kw: ChatHistoryPage(messages=[], has_more_before=False),
    )

    widget._switch_to_session("empty_session")
    widget._stack.setCurrentIndex(widget.VIEW_CONVERSATION)
    app.processEvents()

    toggle = _toggle(widget)
    assert toggle.isVisible() is False


def test_toggle_hidden_on_session_list(widget, app):
    """回到会话列表时 Toggle 隐藏。"""
    widget._mark_conversation_started()
    widget._stack.setCurrentIndex(widget.VIEW_CONVERSATION)
    app.processEvents()
    assert _toggle(widget).isVisible() is True

    widget.show_session_list()
    app.processEvents()
    assert _toggle(widget).isVisible() is False


def test_visibility_change_does_not_emit_signal(widget, app):
    """可见性变化不发出 auto_approve_toggled 信号。"""
    events = []
    widget.auto_approve_toggled.connect(events.append)

    widget._set_auto_approve_toggle_visible(True)
    app.processEvents()
    widget._set_auto_approve_toggle_visible(False)
    app.processEvents()

    assert events == []
