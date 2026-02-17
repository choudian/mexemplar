"""
录制模块

提供操作录制功能
"""

from .recorder import Recorder, RecordingSession, Action, NetworkRequest
from .data_collector import (
    DataCollector,
    ScreenCapture,
    MouseKeyboardMonitor,
    WindowInfoCollector,
    MouseEvent,
    KeyboardEvent,
    ScreenshotData,
    WindowInfo,
    RecordingEvent,
)
from .video_recorder import VideoRecorder
from .browser_recorder import BrowserRecorder
from .recorder_import import (
    import_recording_from_json,
    save_imported_recording,
    validate_imported_recording,
)

__all__ = [
    "Recorder",
    "RecordingSession",
    "Action",
    "NetworkRequest",
    "BrowserRecorder",
    "DataCollector",
    "ScreenCapture",
    "MouseKeyboardMonitor",
    "WindowInfoCollector",
    "VideoRecorder",
    "MouseEvent",
    "KeyboardEvent",
    "ScreenshotData",
    "WindowInfo",
    "RecordingEvent",
    "import_recording_from_json",
    "save_imported_recording",
    "validate_imported_recording",
]
