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
