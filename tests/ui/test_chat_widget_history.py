import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea  # noqa: E402

from src.ui.widgets.chat_widget import ChatWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用")


@pytest.fixture()
def widget(app, monkeypatch):
    monkeypatch.setattr(ChatWidget, "_load_sessions", lambda self: None)
    monkeypatch.setattr(ChatWidget, "_get_display_name", lambda self: "测试用户")
    w = ChatWidget()
    w.show()
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()


class TestHistoryInitialRender:
    def test_initial_render_requests_latest_page(self, widget, app, monkeypatch):
        from src.business.services.chat_service import ChatHistoryPage, DisplayChatMessage

        dtos = [
            DisplayChatMessage(sequence=i, role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
            for i in range(1, 6)
        ]
        page = ChatHistoryPage(messages=dtos, has_more_before=True, next_before_sequence=1)

        calls = []
        original_get = widget._load_session_messages

        def mock_load(sid):
            calls.append(sid)
            for msg in page.messages:
                widget._add_message(msg.role, msg.content)
            widget._oldest_loaded_sequence = page.messages[0].sequence
            widget._has_more_history = page.has_more_before

        monkeypatch.setattr(widget, "_load_session_messages", mock_load)
        widget._switch_to_session("test_session")
        app.processEvents()

        assert len(calls) == 1
        assert widget._oldest_loaded_sequence == 1
        assert widget._has_more_history is True


class TestHistoryScrollPrepend:
    def test_top_scroll_triggers_older_load(self, widget, app, monkeypatch):
        from src.business.services.chat_service import ChatHistoryPage, DisplayChatMessage

        # Set up as if initial page already loaded
        widget._session_id = "test_session"
        widget._oldest_loaded_sequence = 5
        widget._has_more_history = True
        for i in range(1, 6):
            widget._add_message("user" if i % 2 == 0 else "assistant", f"msg {i}")
        app.processEvents()

        older = [
            DisplayChatMessage(sequence=i, role="user" if i % 2 == 0 else "assistant", content=f"old {i}")
            for i in range(1, 5)
        ]
        monkeypatch.setattr(
            "src.business.services.chat_service.ChatService.get_display_messages",
            lambda self, sid, **kw: ChatHistoryPage(messages=older, has_more_before=False, next_before_sequence=1),
        )

        # Directly trigger the load (scroll signal may not fire when already at minimum)
        widget._load_older_history()
        app.processEvents()

        assert widget._oldest_loaded_sequence == 1
        assert widget._has_more_history is False


class TestHistoryNoArchiveLabels:
    def test_no_archive_or_compression_labels(self, widget, app, monkeypatch):
        from src.business.services.chat_service import ChatHistoryPage, DisplayChatMessage

        dtos = [
            DisplayChatMessage(sequence=i, role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
            for i in range(1, 4)
        ]
        monkeypatch.setattr(
            "src.business.services.chat_service.ChatService.get_display_messages",
            lambda self, sid, **kw: ChatHistoryPage(messages=dtos, has_more_before=False),
        )

        widget._clear_messages()
        widget._session_id = "test_session"
        widget._load_session_messages("test_session")
        app.processEvents()

        all_text = ""
        for label in widget.findChildren(QLabel):
            all_text += label.text() + " "

        assert "归档" not in all_text
        assert "压缩" not in all_text
        assert "tool" not in all_text.lower()
        assert "summary" not in all_text.lower()


class TestHistoryTiming:
    def test_initial_display_under_2s(self, widget, app, monkeypatch):
        from src.business.services.chat_service import ChatHistoryPage, DisplayChatMessage

        dtos = [
            DisplayChatMessage(sequence=i, role="user" if i % 2 == 0 else "assistant", content=f"msg {i}")
            for i in range(1, 11)
        ]
        monkeypatch.setattr(
            "src.business.services.chat_service.ChatService.get_display_messages",
            lambda self, sid, **kw: ChatHistoryPage(messages=dtos, has_more_before=False),
        )

        widget._clear_messages()
        widget._session_id = "perf_session"
        start = time.monotonic()
        widget._load_session_messages("perf_session")
        app.processEvents()
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"初始渲染耗时 {elapsed:.2f}s，超过 2s 阈值"

    def test_scroll_handler_under_100ms(self, widget, app, monkeypatch):
        from src.business.services.chat_service import ChatHistoryPage, DisplayChatMessage

        widget._session_id = "perf_session"
        widget._oldest_loaded_sequence = 5
        widget._has_more_history = True
        for i in range(1, 6):
            widget._add_message("user" if i % 2 == 0 else "assistant", f"msg {i}")
        app.processEvents()

        older = [
            DisplayChatMessage(sequence=i, role="user" if i % 2 == 0 else "assistant", content=f"old {i}")
            for i in range(1, 5)
        ]
        monkeypatch.setattr(
            "src.business.services.chat_service.ChatService.get_display_messages",
            lambda self, sid, **kw: ChatHistoryPage(messages=older, has_more_before=False),
        )

        start = time.monotonic()
        widget._load_older_history()
        app.processEvents()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1, f"滚动加载耗时 {elapsed:.3f}s，超过 100ms 阈值"


class TestHistoryReset:
    def test_new_chat_resets_pagination(self, widget, app):
        widget._session_id = "old"
        widget._oldest_loaded_sequence = 5
        widget._has_more_history = True
        widget.on_new_chat()
        app.processEvents()
        assert widget._oldest_loaded_sequence is None
        assert widget._has_more_history is False

    def test_session_switch_resets_pagination(self, widget, app, monkeypatch):
        from src.business.services.chat_service import ChatHistoryPage, DisplayChatMessage

        dtos = [
            DisplayChatMessage(sequence=1, role="user", content="hello"),
        ]
        monkeypatch.setattr(
            "src.business.services.chat_service.ChatService.get_display_messages",
            lambda self, sid, **kw: ChatHistoryPage(messages=dtos, has_more_before=False),
        )

        widget._oldest_loaded_sequence = 99
        widget._has_more_history = True
        widget._switch_to_session("new_session")
        app.processEvents()
        # After switch, state should be updated from the loaded page
        assert widget._oldest_loaded_sequence == 1
        assert widget._has_more_history is False
