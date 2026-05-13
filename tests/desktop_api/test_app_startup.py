from __future__ import annotations

from fastapi.testclient import TestClient

from src.business.services.recording_startup_service import RecordingStartupService
from src.desktop_api.app import SESSION_HEADER, create_app


def test_desktop_api_lifespan_runs_recording_startup_recovery(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(
        RecordingStartupService,
        "ensure_recovered",
        lambda self: calls.append(True),
    )

    token = "test-session-token"
    with TestClient(create_app(token), headers={SESSION_HEADER: token}) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert calls == [True]
