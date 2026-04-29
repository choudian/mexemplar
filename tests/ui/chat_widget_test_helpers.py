import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QPushButton, QLabel, QTextEdit  # noqa: E402

from src.ui.widgets.chat_widget import ChatWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


@pytest.fixture()
def chat_widget(app, monkeypatch):
    monkeypatch.setattr(ChatWidget, "_load_sessions", lambda self: None)
    monkeypatch.setattr(ChatWidget, "_get_display_name", lambda self: "测试用户")
    w = ChatWidget()
    w.show()
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()


def find_toggle(widget: ChatWidget) -> QPushButton:
    toggle = widget.findChild(QPushButton, "chat_auto_approve_toggle")
    assert toggle is not None, "未找到免确认 Toggle"
    return toggle


def find_messages_scroll(widget: ChatWidget):
    from PyQt6.QtWidgets import QScrollArea

    scroll = widget.findChild(QScrollArea, "messages_scroll")
    assert scroll is not None, "未找到 messages_scroll"
    return scroll


def find_bubbles(widget: ChatWidget, role: str) -> list:
    return widget.findChildren(QLabel, f"content_{role}")


def find_markdown_views(widget: ChatWidget) -> list:
    from src.ui.widgets.markdown_message_view import MarkdownMessageView

    return widget.findChildren(MarkdownMessageView)


def count_bubbles(widget: ChatWidget, role: str) -> int:
    return len(find_bubbles(widget, role))


def send_via_input(widget: ChatWidget, text: str, app):
    widget.message_input.setPlainText(text)
    app.processEvents()
    QTest.mouseClick(widget.send_button, Qt.MouseButton.LeftButton)
    app.processEvents()


def scroll_to_top(widget: ChatWidget, app):
    scroll = find_messages_scroll(widget)
    bar = scroll.verticalScrollBar()
    bar.setValue(bar.minimum())
    app.processEvents()
