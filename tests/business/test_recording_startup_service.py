from __future__ import annotations

from src.business.services.recording_startup_service import RecordingStartupService
from src.data.recording_repository import RecordingRepository


def test_recording_startup_service_runs_repository_recovery(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        RecordingRepository,
        "ensure_startup_recovery",
        staticmethod(lambda: calls.append(True)),
    )

    RecordingStartupService().ensure_recovered()

    assert calls == [True]
