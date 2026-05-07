from __future__ import annotations

from src.data.recording_repository import RecordingRepository
from src.recording.desktop_recorder import (
    DesktopRecorder,
    DesktopRecorderHealth,
)


class DesktopRecordingService:

    def __init__(self, repository: RecordingRepository | None = None):
        self.repository = repository or RecordingRepository()
        self._recorders: dict[str, DesktopRecorder] = {}

    def start_after_minimize(self, recording_id: str) -> None:
        recorder = self._recorders.get(recording_id)
        if recorder is None:
            recorder = DesktopRecorder(recording_id, repository=self.repository)
            self._recorders[recording_id] = recorder
        recorder.start()

    def get_health_stats(self, recording_id: str) -> DesktopRecorderHealth:
        recorder = self._recorders.get(recording_id)
        if recorder is not None:
            return DesktopRecorderHealth.from_value(recorder.health)
        meta = self.repository.get_desktop_recording_meta(recording_id)
        return DesktopRecorderHealth.from_value((meta or {}).get("health_stats"))

    def stop(self, recording_id: str) -> DesktopRecorderHealth:
        recorder = self._recorders.pop(recording_id, None)
        if recorder is None:
            self.repository.update_desktop_recording_status(recording_id, "stopped")
            return self.get_health_stats(recording_id)
        return recorder.stop()

    def mark_abandoned(self, recording_id: str) -> None:
        self.repository.update_desktop_recording_status(recording_id, "abandoned")

    def mark_stopped(self, recording_id: str) -> None:
        self.repository.update_desktop_recording_status(recording_id, "stopped")
