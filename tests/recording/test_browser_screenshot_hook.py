import logging
import queue
from pathlib import Path

from src.recording.browser_screenshot_hook import (
    BrowserScreenshotHook,
    _CaptureTask,
    _CaptureTaskQueue,
    _FrameRingBuffer,
    _FrameSample,
)


def _task(capture_id: str, moment: str) -> _CaptureTask:
    return _CaptureTask(
        capture_id=capture_id,
        moment=moment,
        source_trigger="mouse_left",
        event_ts=1.0,
    )


def _drain(queue_obj: _CaptureTaskQueue) -> list[_CaptureTask]:
    drained = []
    while True:
        try:
            drained.append(queue_obj.get(timeout=0))
        except queue.Empty:
            return drained


def test_capture_queue_drops_oldest_before_when_full(caplog):
    capture_queue = _CaptureTaskQueue(maxsize=3, logger_=logging.getLogger("capture-queue"))

    with caplog.at_level(logging.WARNING):
        assert capture_queue.put(_task("cap_0001", "before")) is True
        assert capture_queue.put(_task("cap_0002", "after")) is True
        assert capture_queue.put(_task("cap_0003", "before")) is True
        assert capture_queue.put(_task("cap_0004", "after")) is True

    drained = _drain(capture_queue)

    assert [task.capture_id for task in drained] == ["cap_0002", "cap_0003", "cap_0004"]
    assert all(task.capture_id != "cap_0001" for task in drained)
    assert "dropping oldest before task" in caplog.text


def test_capture_queue_drops_new_task_when_queue_is_all_after(caplog):
    capture_queue = _CaptureTaskQueue(maxsize=3, logger_=logging.getLogger("capture-queue"))

    with caplog.at_level(logging.WARNING):
        assert capture_queue.put(_task("cap_0001", "after")) is True
        assert capture_queue.put(_task("cap_0002", "after")) is True
        assert capture_queue.put(_task("cap_0003", "after")) is True
        assert capture_queue.put(_task("cap_0004", "before")) is False

    drained = _drain(capture_queue)

    assert [task.capture_id for task in drained] == ["cap_0001", "cap_0002", "cap_0003"]
    assert "dropping incoming before task" in caplog.text


def test_frame_ring_buffer_selects_latest_before():
    buffer = _FrameRingBuffer(max_samples=10)
    buffer.append(_FrameSample(timestamp=10.00, data=b"a"))
    buffer.append(_FrameSample(timestamp=10.08, data=b"b"))
    buffer.append(_FrameSample(timestamp=10.16, data=b"c"))

    picked = buffer.latest_before(10.10, max_age=1.0)

    assert picked is not None
    assert picked.timestamp == 10.08
    assert picked.data == b"b"


def test_frame_ring_buffer_selects_earliest_after():
    buffer = _FrameRingBuffer(max_samples=10)
    buffer.append(_FrameSample(timestamp=20.00, data=b"a"))
    buffer.append(_FrameSample(timestamp=20.09, data=b"b"))
    buffer.append(_FrameSample(timestamp=20.21, data=b"c"))

    picked = buffer.earliest_after(20.10, max_lag=2.0)

    assert picked is not None
    assert picked.timestamp == 20.21
    assert picked.data == b"c"


def test_browser_screenshot_hook_detects_enter_without_pynput():
    class _KeyWithVk:
        vk = 13

    assert BrowserScreenshotHook._is_enter_key(_KeyWithVk()) is True
    assert BrowserScreenshotHook._is_enter_key(type("Other", (), {"vk": 27})()) is False


def test_browser_screenshot_hook_uses_on_press_listener():
    source = Path("src/recording/browser_screenshot_hook.py").read_text(encoding="utf-8")

    assert "on_press=self._on_key_press" in source
    assert "on_key_press=self._on_key_press" not in source
