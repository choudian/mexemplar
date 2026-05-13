from __future__ import annotations

from src.data.recording_repository import RecordingRepository


class RecordingStartupService:
    """Runs recording startup maintenance through a business-layer facade."""

    def ensure_recovered(self) -> None:
        RecordingRepository.ensure_startup_recovery()
