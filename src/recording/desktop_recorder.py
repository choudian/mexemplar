from __future__ import annotations

import json
import logging
import threading
import time
import collections
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.data.recording_repository import RecordingRepository
from src.data.unified_config import get_unified_config
from src.recording.desktop import DESKTOP_ACTION_TYPES
from src.recording.desktop.clip_sink import ClipSink
from src.recording.desktop.clipboard_watcher import ClipboardWatcher
from src.recording.desktop.frame_ring_buffer import FrameRingBuffer, FrameSample
from src.recording.desktop.hotkey_register import DesktopStopHotkey
from src.recording.desktop.png_sink import PngSink
from src.recording.desktop.pynput_hook import (
    DesktopActionEvent,
    DesktopPynputHook,
    RecorderStartFailed,
)
from src.recording.desktop.uia_querier import UiaQuerier
from src.utils.events import (
    desktop_action_count_changed,
    desktop_recording_degraded,
    desktop_recorder_start_failed,
    recording_stopped,
)
from src.utils.helpers import get_default_data_dir

logger = logging.getLogger(__name__)

_UIA_ACTION_TYPES = set(DESKTOP_ACTION_TYPES) - {"typing", "hotkey"}


@dataclass
class DesktopRecorderHealth:
    uia_hit: int = 0
    uia_total: int = 0
    clip_success: int = 0
    clip_total: int = 0
    clipboard_event_count: int = 0
    action_type_counts: dict[str, int] = field(default_factory=dict)
    frame_total: int = 0
    duration_seconds: float = 0.0

    @property
    def action_total(self) -> int:
        return sum(self.action_type_counts.values())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_value(cls, value: dict[str, Any] | "DesktopRecorderHealth" | None) -> "DesktopRecorderHealth":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__})
        return cls()


class ActiveDesktopRecorderRegistry:
    _lock = threading.RLock()
    _active: dict[str, str] = {}

    @classmethod
    def start(cls, recording_id: str, mode: str = "desktop") -> None:
        with cls._lock:
            if cls._active:
                raise RuntimeError("recording_already_active")
            cls._active[recording_id] = mode

    @classmethod
    def stop(cls, recording_id: str) -> None:
        with cls._lock:
            cls._active.pop(recording_id, None)

    @classmethod
    def state(cls) -> dict[str, Any]:
        with cls._lock:
            return {"active": bool(cls._active), "recordings": dict(cls._active)}


class DesktopRecorder:
    def __init__(
        self,
        recording_id: str,
        *,
        repository: RecordingRepository | None = None,
        recording_root: Path | None = None,
        hook: DesktopPynputHook | None = None,
        uia_querier: UiaQuerier | None = None,
        clipboard_watcher: ClipboardWatcher | None = None,
        frame_buffer: FrameRingBuffer | None = None,
        png_sink: PngSink | None = None,
        clip_sink: ClipSink | None = None,
        hotkey: DesktopStopHotkey | None = None,
        enable_frame_capture: bool = True,
    ):
        self.recording_id = recording_id
        self.repository = repository or RecordingRepository()
        self.recording_root = recording_root or get_default_data_dir() / "recordings" / recording_id
        self.health = DesktopRecorderHealth()
        self._hook = hook or DesktopPynputHook(self.record_action)
        self._uia_querier = uia_querier or UiaQuerier()
        self._clipboard_watcher = clipboard_watcher or ClipboardWatcher(
            recording_id, self.recording_root
        )
        self._frame_buffer = frame_buffer or FrameRingBuffer()
        self._png_sink = png_sink or PngSink(self.recording_root)
        self._clip_sink = clip_sink or ClipSink(
            self.recording_root,
            enable_clip=get_unified_config().get_desktop_enable_clip(),
            fps=self._frame_buffer.fps,
        )
        self._hotkey = hotkey or DesktopStopHotkey()
        self._enable_frame_capture = enable_frame_capture
        self._frame_capture_stop = threading.Event()
        self._frame_capture_thread: threading.Thread | None = None
        self._last_clipboard_event_seq = 0
        self._emitted_degraded_reasons: set[str] = set()
        self._started_at: float | None = None
        self._running = False
        self._frame_queue: collections.deque[
            tuple[dict[str, Any], str, float, list[FrameSample]]
        ] = collections.deque(maxlen=50)
        self._frame_writer_thread: threading.Thread | None = None
        self._frame_writer_stop = threading.Event()

    def start(self) -> None:
        ActiveDesktopRecorderRegistry.start(self.recording_id)
        self.repository.ensure_desktop_tables()
        if self.repository.get_desktop_recording_meta(self.recording_id) is None:
            self.repository.insert_desktop_recording(
                {
                    "recording_id": self.recording_id,
                    "start_time": time.time(),
                    "monitor_index": 0,
                    "status": "recording",
                }
            )
        self.recording_root.mkdir(parents=True, exist_ok=True)
        try:
            self._start_optional_components()
            self._hook.start()
        except RecorderStartFailed:
            ActiveDesktopRecorderRegistry.stop(self.recording_id)
            self._stop_optional_components()
            desktop_recorder_start_failed.send(
                self,
                recording_id=self.recording_id,
                reason="hook_register_failed",
            )
            raise
        except Exception:
            ActiveDesktopRecorderRegistry.stop(self.recording_id)
            self._stop_optional_components()
            raise
        self._started_at = time.time()
        self._running = True

    def stop(self) -> DesktopRecorderHealth:
        if self._running:
            self._hook.stop()
            self._stop_optional_components()
            self._frame_buffer.clear()
        self._running = False
        if self._started_at is not None:
            self.health.duration_seconds = max(0.0, time.time() - self._started_at)
        self.repository.update_desktop_recording_health_stats(
            self.recording_id, self.health.to_dict()
        )
        self.repository.update_desktop_recording_status(self.recording_id, "stopped")
        ActiveDesktopRecorderRegistry.stop(self.recording_id)
        recording_stopped.send(
            self,
            recording_id=self.recording_id,
            recording_mode="desktop",
            action_count=self.get_action_count(),
        )
        return self.health

    def record_action(self, event: DesktopActionEvent | dict[str, Any]) -> str:
        if isinstance(event, DesktopActionEvent):
            payload = asdict(event)
        else:
            payload = dict(event)
        action_type = payload["type"]
        action_id = payload.get("action_id") or str(uuid.uuid4())
        timestamp = payload.get("timestamp") or time.time()
        self._enrich_with_uia(payload, action_type)
        self._enrich_with_clipboard(payload)
        self.health.action_type_counts[action_type] = (
            self.health.action_type_counts.get(action_type, 0) + 1
        )
        self.repository.insert_desktop_action(
            {
                "action_id": action_id,
                "recording_id": self.recording_id,
                "type": action_type,
                "coord_x": payload.get("coord_x"),
                "coord_y": payload.get("coord_y"),
                "monitor_index": payload.get("monitor_index", 0),
                "window_title": payload.get("window_title"),
                "text_content": payload.get("text_content"),
                "uia_summary": payload.get("uia_summary"),
                "clipboard_text": payload.get("clipboard_text"),
                "clipboard_image_path": payload.get("clipboard_image_path"),
                "timestamp": timestamp,
                "duration_ms": payload.get("duration_ms"),
                "frame_count": 0,
                "has_clip": False,
                "clip_path": None,
                "clip_duration_ms": None,
                "clip_fps": None,
                "clip_resolution": None,
            }
        )
        if self._enable_frame_capture:
            pre_action_frames = self._frame_buffer.frames_for_action(
                float(timestamp),
                monitor_index=payload.get("monitor_index", 0),
            )
            self._frame_queue.append((payload, action_id, timestamp, pre_action_frames))
            self._ensure_frame_writer()
        if self.get_action_count() % 5 == 0:
            desktop_action_count_changed.send(
                self,
                recording_id=self.recording_id,
                action_count=self.get_action_count(),
            )
        return action_id

    def get_action_count(self) -> int:
        return self.health.action_total

    def _start_optional_components(self) -> None:
        self._clipboard_watcher.start()
        if self._clipboard_watcher.degraded_reason:
            self._emit_degraded("clipboard_subscribe_failed")

        hotkey_result = self._hotkey.register()
        if not hotkey_result.ok:
            self._emit_degraded(hotkey_result.reason or "hotkey_register_failed")

        if self._enable_frame_capture:
            self._start_frame_capture()

    def _stop_optional_components(self) -> None:
        self._frame_capture_stop.set()
        self._frame_writer_stop.set()
        if self._frame_capture_thread and self._frame_capture_thread.is_alive():
            self._frame_capture_thread.join(timeout=1.0)
        self._frame_capture_thread = None
        if self._frame_writer_thread and self._frame_writer_thread.is_alive():
            self._frame_writer_thread.join(timeout=3.0)
        self._frame_writer_thread = None
        self._hotkey.unregister()
        self._clipboard_watcher.stop()
        close_uia = getattr(self._uia_querier, "close", None)
        if callable(close_uia):
            close_uia()

    def _start_frame_capture(self) -> None:
        self._frame_capture_stop.clear()

        def _capture_loop() -> None:
            try:
                import mss
                from PIL import Image

                with mss.mss() as sct:
                    monitors = list(sct.monitors[1:]) or [sct.monitors[0]]
                    while not self._frame_capture_stop.is_set():
                        captured_at = time.time()
                        for monitor_index, monitor in enumerate(monitors):
                            shot = sct.grab(monitor)
                            image = Image.frombytes("RGB", shot.size, shot.rgb)
                            self._frame_buffer.append(
                                FrameSample(
                                    timestamp=captured_at,
                                    image_data=image,
                                    monitor_index=monitor_index,
                                )
                            )
                        time.sleep(max(0.01, 1.0 / self._frame_buffer.fps))
            except Exception:
                self._emit_degraded("frame_capture_failed")

        self._frame_capture_thread = threading.Thread(
            target=_capture_loop,
            daemon=True,
            name=f"DesktopFrameCapture-{self.recording_id}",
        )
        self._frame_capture_thread.start()

    def _ensure_frame_writer(self) -> None:
        if self._frame_writer_thread is not None and self._frame_writer_thread.is_alive():
            return
        self._frame_writer_stop.clear()

        def _writer_loop() -> None:
            try:
                while True:
                    if not self._frame_queue:
                        if self._frame_writer_stop.is_set():
                            break
                        self._frame_writer_stop.wait(0.2)
                        continue
                    payload, action_id, timestamp, pre_action_frames = self._frame_queue.popleft()
                    elapsed = time.time() - timestamp
                    remaining = max(0.0, 2.1 - elapsed)
                    if remaining > 0:
                        self._frame_writer_stop.wait(remaining)
                    self._enrich_with_frames_and_clip(
                        payload,
                        action_id,
                        timestamp,
                        pre_action_frames,
                    )
            except Exception:
                logger.exception("[DesktopRecorder] frame writer loop crashed")
            finally:
                self._frame_writer_thread = None

        self._frame_writer_thread = threading.Thread(
            target=_writer_loop,
            daemon=True,
            name=f"DesktopFrameWriter-{self.recording_id}",
        )
        self._frame_writer_thread.start()

    def _enrich_with_uia(self, payload: dict[str, Any], action_type: str) -> None:
        if payload.get("coord_x") is None or payload.get("coord_y") is None:
            return
        if action_type not in _UIA_ACTION_TYPES:
            return
        self.health.uia_total += 1
        summary = self._uia_querier.query_at(int(payload["coord_x"]), int(payload["coord_y"]))
        summary_dict = summary.to_dict()
        if summary.degraded_reason:
            self._emit_degraded("uia_query_failed")
        else:
            self.health.uia_hit += 1
        payload.setdefault("uia_summary", summary_dict)
        if summary.window_title:
            payload.setdefault("window_title", summary.window_title)

    def _enrich_with_clipboard(self, payload: dict[str, Any]) -> None:
        latest = self._clipboard_watcher.latest()
        if latest.event_seq and latest.event_seq != self._last_clipboard_event_seq:
            self.health.clipboard_event_count += 1
            self._last_clipboard_event_seq = latest.event_seq
        payload.setdefault("clipboard_text", latest.text)
        if latest.image_path is not None:
            payload.setdefault("clipboard_image_path", str(latest.image_path))

    def _enrich_with_frames_and_clip(
        self,
        payload: dict[str, Any],
        action_id: str,
        timestamp: float,
        pre_action_frames: list[FrameSample] | None = None,
    ) -> None:
        monitor_index = payload.get("monitor_index", 0)
        post_action_frames = self._frame_buffer.frames_for_action(
            float(timestamp),
            monitor_index=monitor_index,
            start_time=float(timestamp),
        )
        frames = (pre_action_frames or []) + post_action_frames
        if not frames:
            return
        try:
            frame_paths = self._png_sink.write_frames(action_id, frames)
        except Exception:
            self._emit_degraded("png_sink_failed")
            frame_paths = []
        self.health.frame_total += len(frame_paths)

        before_total = self._clip_sink.clip_total
        before_success = self._clip_sink.clip_success
        clip = self._clip_sink.write_clip(action_id, frames)
        self.health.clip_total += self._clip_sink.clip_total - before_total
        self.health.clip_success += self._clip_sink.clip_success - before_success

        self.repository.update_desktop_action_frames(
            action_id,
            {
                "frame_count": len(frame_paths),
                "has_clip": clip.has_clip,
                "clip_path": str(clip.path) if clip.path else None,
                "clip_duration_ms": clip.duration_ms,
                "clip_fps": clip.fps,
                "clip_resolution": (
                    json.dumps(clip.resolution, ensure_ascii=False)
                    if clip.resolution is not None
                    else None
                ),
            },
        )

    def _emit_degraded(self, reason: str) -> None:
        if reason in self._emitted_degraded_reasons:
            return
        self._emitted_degraded_reasons.add(reason)
        desktop_recording_degraded.send(
            self,
            recording_id=self.recording_id,
            reason=reason,
        )
