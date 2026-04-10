import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys

import pytest

from src.ui.widgets.recording_widget import RecordingWidget


@pytest.fixture(scope="module")
def app():
    try:
        from PyQt6.QtWidgets import QApplication

        qt_app = QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")
    return qt_app


def test_extension_start_wait_state_is_cancelable(app):
    widget = RecordingWidget()
    widget._select_mode("extension_triggered")

    started = []
    stopped = []
    widget.recording_started.connect(lambda mode, url: started.append((mode, url)))
    widget.recording_stopped.connect(lambda: stopped.append(True))

    widget.on_record_clicked()

    assert started == [("extension_triggered", "")]
    assert widget._awaiting_extension_start is True
    assert widget.is_recording is False
    assert widget.record_btn.isEnabled() is False
    assert widget.stop_btn.isEnabled() is True

    widget.on_stop_clicked()

    assert stopped == []
    assert widget._awaiting_extension_start is False
    assert widget.record_btn.isEnabled() is True
    assert widget.stop_btn.isEnabled() is False

    widget.deleteLater()


def test_extension_recording_events_update_widget_state(app):
    widget = RecordingWidget()
    widget._select_mode("extension_triggered")
    widget.on_record_clicked()

    widget.on_extension_recording_started("rec-123")

    assert widget._awaiting_extension_start is False
    assert widget.is_recording is True
    assert widget.record_btn.isEnabled() is False
    assert widget.stop_btn.isEnabled() is True
    assert widget.recording_indicator.isHidden() is False

    widget.on_extension_recording_stopped()

    assert widget.is_recording is False
    assert widget.record_btn.isEnabled() is True
    assert widget.stop_btn.isEnabled() is False
    assert widget.recording_indicator.isHidden() is True

    widget.deleteLater()
