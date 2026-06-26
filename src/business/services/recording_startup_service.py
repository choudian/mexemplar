from __future__ import annotations

from src.recording.recovery import RecordingRecoveryCoordinator


class RecordingStartupService:
    """Runs recording startup maintenance through a business-layer facade."""

    def ensure_recovered(self) -> None:
        RecordingRecoveryCoordinator.ensure_startup_recovery()
