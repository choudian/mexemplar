import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository
from src.recording.desktop.pynput_hook import DesktopActionEvent
from src.recording.desktop.pynput_hook import RecorderStartFailed
from src.recording.desktop.clip_sink import ClipWriteResult
from src.recording.desktop.frame_ring_buffer import FrameSample
from src.recording.desktop_recorder import ActiveDesktopRecorderRegistry, DesktopRecorder


class _FakeHook:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class _FailingHook(_FakeHook):
    def start(self):
        raise RecorderStartFailed("hook denied")


class _FakeClipboard:
    degraded_reason = None

    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def latest(self):
        return type(
            "Latest",
            (),
            {"text": "clip text", "image_path": None, "event_seq": 1},
        )()


class _FakeHotkey:
    def __init__(self):
        self.registered = False
        self.unregistered = False

    def register(self):
        self.registered = True
        return type("Result", (), {"ok": True, "reason": None})()

    def unregister(self):
        self.unregistered = True


class _FakeUia:
    def query_at(self, x, y):
        return type(
            "Summary",
            (),
            {
                "degraded_reason": None,
                "window_title": "Editor",
                "to_dict": lambda self: {"window_title": "Editor", "name": "box"},
            },
        )()


class _FakeFrameBuffer:
    fps = 15

    def __init__(self):
        self.calls = []

    def frames_for_action(self, timestamp, *, monitor_index=None):
        self.calls.append((timestamp, monitor_index))
        return [
            FrameSample(
                timestamp=timestamp - 0.5,
                image_data=object(),
                monitor_index=monitor_index or 0,
            )
        ]

    def clear(self):
        pass


class _FakePngSink:
    def write_frames(self, action_id, frames):
        return [f"{action_id}/frame_001.png" for _ in frames]


class _FakeClipSink:
    def __init__(self):
        self.clip_total = 0
        self.clip_success = 0

    def write_clip(self, action_id, frames):
        self.clip_total += 1
        self.clip_success += 1
        return ClipWriteResult(
            has_clip=True,
            path=__import__("pathlib").Path(f"{action_id}.mp4"),
            duration_ms=100,
            fps=15,
            resolution=(10, 10),
        )


def test_desktop_recorder_lifecycle_persists_health_stats(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    ActiveDesktopRecorderRegistry._active.clear()
    db = DuckDBManager(str(tmp_path / "recorder.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    hook = _FakeHook()
    clipboard = _FakeClipboard()
    hotkey = _FakeHotkey()
    recorder = DesktopRecorder(
        "rec-1",
        repository=repo,
        recording_root=tmp_path / "rec",
        hook=hook,
        clipboard_watcher=clipboard,
        hotkey=hotkey,
        enable_frame_capture=False,
    )
    try:
        recorder.start()
        recorder.record_action(DesktopActionEvent(type="typing", timestamp=1.0, text_content="abc"))
        health = recorder.stop()

        assert hook.started is True
        assert hook.stopped is True
        assert clipboard.started is True
        assert clipboard.stopped is True
        assert hotkey.registered is True
        assert hotkey.unregistered is True
        assert health.action_type_counts == {"typing": 1}
        assert repo.get_desktop_recording_meta("rec-1")["status"] == "stopped"
        assert repo.get_desktop_recording_meta("rec-1")["health_stats"]["action_type_counts"] == {
            "typing": 1
        }
    finally:
        ActiveDesktopRecorderRegistry._active.clear()
        db.close()
        duckdb_module._duckdb_instance = old_instance


def test_desktop_recorder_start_failure_marks_recording_abandoned(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    ActiveDesktopRecorderRegistry._active.clear()
    db = DuckDBManager(str(tmp_path / "recorder-start-failure.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    recorder = DesktopRecorder(
        "rec-fail",
        repository=repo,
        recording_root=tmp_path / "rec",
        hook=_FailingHook(),
        clipboard_watcher=_FakeClipboard(),
        hotkey=_FakeHotkey(),
        enable_frame_capture=False,
    )
    try:
        try:
            recorder.start()
        except RecorderStartFailed:
            pass
        else:
            raise AssertionError("start should fail")

        meta = repo.get_desktop_recording_meta("rec-fail")
        assert meta["status"] == "abandoned"
        assert meta["end_time"] is not None
        assert "hook_register_failed" in meta["health_stats"]["degraded_reasons"]
        assert ActiveDesktopRecorderRegistry.state()["active"] is False
    finally:
        ActiveDesktopRecorderRegistry._active.clear()
        db.close()
        duckdb_module._duckdb_instance = old_instance


def test_desktop_recorder_enriches_actions_with_subsystem_metadata(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    ActiveDesktopRecorderRegistry._active.clear()
    db = DuckDBManager(str(tmp_path / "recorder-enrich.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    clip_sink = _FakeClipSink()
    recorder = DesktopRecorder(
        "rec-2",
        repository=repo,
        recording_root=tmp_path / "rec",
        hook=_FakeHook(),
        uia_querier=_FakeUia(),
        clipboard_watcher=_FakeClipboard(),
        frame_buffer=_FakeFrameBuffer(),
        png_sink=_FakePngSink(),
        clip_sink=clip_sink,
        hotkey=_FakeHotkey(),
        enable_frame_capture=False,
    )
    try:
        recorder.start()
        recorder.record_action(
            DesktopActionEvent(type="mouse_left", timestamp=1.0, coord_x=10, coord_y=20)
        )
        recorder.stop()
        action = repo.list_desktop_actions("rec-2")[0]

        assert action["window_title"] == "Editor"
        assert action["uia_summary"] == {"window_title": "Editor", "name": "box"}
        assert action["clipboard_text"] == "clip text"
        assert recorder.health.uia_hit == 1
    finally:
        ActiveDesktopRecorderRegistry._active.clear()
        db.close()
        duckdb_module._duckdb_instance = old_instance


def test_desktop_recorder_snapshots_pre_action_frames_before_writer_wait(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    ActiveDesktopRecorderRegistry._active.clear()
    db = DuckDBManager(str(tmp_path / "recorder-preframes.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    frame_buffer = _FakeFrameBuffer()
    recorder = DesktopRecorder(
        "rec-3",
        repository=repo,
        recording_root=tmp_path / "rec",
        hook=_FakeHook(),
        clipboard_watcher=_FakeClipboard(),
        frame_buffer=frame_buffer,
        hotkey=_FakeHotkey(),
        enable_frame_capture=True,
    )
    recorder._ensure_frame_writer = lambda: None
    try:
        recorder.record_action(
            DesktopActionEvent(
                type="mouse_left",
                timestamp=10.0,
                coord_x=1,
                coord_y=2,
                monitor_index=1,
            )
        )

        _, _, queued_timestamp, pre_action_frames = recorder._frame_queue[0]
        assert queued_timestamp == 10.0
        assert frame_buffer.calls == [(10.0, 1)]
        assert [frame.timestamp for frame in pre_action_frames] == [9.5]
        assert [frame.monitor_index for frame in pre_action_frames] == [1]
    finally:
        ActiveDesktopRecorderRegistry._active.clear()
        db.close()
        duckdb_module._duckdb_instance = old_instance
