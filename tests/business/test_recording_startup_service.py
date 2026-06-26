from __future__ import annotations

from src.business.services.recording_startup_service import RecordingStartupService
from src.recording.recovery import RecordingRecoveryCoordinator


def test_recording_startup_service_runs_coordinator_recovery(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        RecordingRecoveryCoordinator,
        "ensure_startup_recovery",
        staticmethod(lambda: calls.append(True)),
    )

    RecordingStartupService().ensure_recovered()

    assert calls == [True]
