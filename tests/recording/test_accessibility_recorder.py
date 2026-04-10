import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.recording.accessibility_recorder import (
    AccessibilityRecorder,
    EVENT_OBJECT_INVOKED,
    EVENT_OBJECT_VALUECHANGE,
)


def _make_temp_file(name: str) -> Path:
    base = Path.cwd() / ".reports" / "pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{uuid.uuid4().hex}_{name}"


def test_recorder_can_be_created():
    recorder = AccessibilityRecorder()
    assert recorder is not None
    assert not recorder.is_recording


def test_write_interaction_event():
    queue_file = _make_temp_file("actions.jsonl")
    recorder = AccessibilityRecorder()
    recorder._recording_id = "rec_001"
    recorder._queue_file = queue_file

    recorder._write_event(
        action_type="click",
        element_name="提交",
        element_role="button",
        url="https://example.com",
    )

    lines = queue_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["type"] == "browser_action"
    assert data["recording_id"] == "rec_001"
    assert data["action"]["action_type"] == "click"
    assert data["action"]["dom_element"]["text_content"] == "提交"


def test_start_stop_without_os_events():
    recorder = AccessibilityRecorder()
    with patch.object(recorder, "_install_hooks", return_value=None):
        with patch.object(recorder, "_remove_hooks", return_value=None):
            recorder.start("rec_001", Path("dummy.jsonl"))
            assert recorder.is_recording
            recorder.stop()
            assert not recorder.is_recording


def test_start_on_non_windows_is_noop():
    recorder = AccessibilityRecorder()
    with patch("src.recording.accessibility_recorder.PLATFORM_SUPPORTED", False):
        recorder.start("rec_001", Path("dummy.jsonl"))
        assert not recorder.is_recording
        assert recorder._thread is None


def test_url_update_from_chrome():
    recorder = AccessibilityRecorder()
    mock_control = MagicMock()
    mock_edit = MagicMock()
    mock_edit.Exists.return_value = True
    mock_edit.GetValuePattern.return_value.Value = "https://example.com/page"
    mock_control.EditControl.return_value = mock_edit

    recorder._update_url_from_chrome(mock_control)
    assert recorder._current_url == "https://example.com/page"


def test_url_update_ignores_non_http():
    recorder = AccessibilityRecorder()
    recorder._current_url = "https://old.url"
    mock_control = MagicMock()
    mock_edit = MagicMock()
    mock_edit.Exists.return_value = True
    mock_edit.GetValuePattern.return_value.Value = "chrome://settings"
    mock_control.EditControl.return_value = mock_edit

    recorder._update_url_from_chrome(mock_control)
    assert recorder._current_url == "https://old.url"


def test_click_event_refreshes_url_before_logging():
    recorder = AccessibilityRecorder()
    mock_control = MagicMock()
    mock_control.ProcessName = "chrome.exe"
    mock_control.Name = "提交"
    mock_control.ControlTypeName = "ButtonControl"
    mock_control.EditControl.return_value = None
    mock_auto = MagicMock()
    mock_auto.ControlFromHandle.return_value = mock_control

    def refresh_url(control):
        assert control is mock_control
        recorder._current_url = "https://example.com/current"
        return True

    with patch.dict("sys.modules", {"uiautomation": mock_auto}):
        with patch.object(recorder, "_update_url_from_chrome", side_effect=refresh_url) as mock_update:
            with patch.object(recorder, "_write_event") as mock_write:
                recorder._on_win_event(EVENT_OBJECT_INVOKED, 1, 0, 0)

    mock_update.assert_called_once_with(mock_control)
    mock_write.assert_called_once_with(
        "click",
        "提交",
        "ButtonControl",
        "https://example.com/current",
    )


def test_valuechange_updates_url_without_logging_fill_for_navigation():
    recorder = AccessibilityRecorder()
    recorder._current_url = "https://old.example.com"
    mock_control = MagicMock()
    mock_control.ProcessName = "chrome.exe"
    mock_control.Name = "Address and search bar"
    mock_control.ControlTypeName = "EditControl"
    mock_control.AutomationId = "address"
    mock_control.EditControl.return_value = None
    mock_control.GetValuePattern.return_value.Value = "https://example.com/next"
    mock_auto = MagicMock()
    mock_auto.ControlFromHandle.return_value = mock_control

    with patch.dict("sys.modules", {"uiautomation": mock_auto}):
        with patch.object(recorder, "_write_event") as mock_write:
            recorder._on_win_event(EVENT_OBJECT_VALUECHANGE, 1, 0, 0)

    assert recorder._current_url == "https://example.com/next"
    mock_write.assert_not_called()


def test_valuechange_still_logs_fill_when_url_refreshes_for_page_context():
    recorder = AccessibilityRecorder()
    mock_control = MagicMock()
    mock_control.ProcessName = "chrome.exe"
    mock_control.Name = "搜索"
    mock_control.ControlTypeName = "EditControl"
    mock_control.AutomationId = "search-box"
    mock_control.EditControl.return_value = None
    mock_control.GetValuePattern.return_value.Value = "hello"
    mock_auto = MagicMock()
    mock_auto.ControlFromHandle.return_value = mock_control

    def refresh_url(control):
        assert control is mock_control
        recorder._current_url = "https://example.com/search"
        return True

    with patch.dict("sys.modules", {"uiautomation": mock_auto}):
        with patch.object(recorder, "_update_url_from_chrome", side_effect=refresh_url):
            with patch.object(recorder, "_write_event") as mock_write:
                recorder._on_win_event(EVENT_OBJECT_VALUECHANGE, 1, 0, 0)

    mock_write.assert_called_once_with(
        "fill",
        "搜索",
        "EditControl",
        "https://example.com/search",
        value="hello",
    )
