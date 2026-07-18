from __future__ import annotations

from unittest.mock import MagicMock

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


def test_desktop_api_lifespan_uses_mcp_shutdown_facade(monkeypatch):
    """Desktop adapter 只调业务 facade，并在 lifespan 退出时关闭 MCP loop/thread。"""
    import src.business.mcp as mcp_business

    service = MagicMock()
    service.sdk_available = True
    monkeypatch.setattr(
        mcp_business,
        "get_mcp_server_service",
        lambda: service,
    )
    monkeypatch.setattr(
        RecordingStartupService,
        "ensure_recovered",
        lambda self: None,
    )

    token = "test-session-token"
    with TestClient(create_app(token), headers={SESSION_HEADER: token}) as client:
        assert client.get("/api/health").status_code == 200

    service.shutdown.assert_called_once_with()
    service.stop_all.assert_not_called()
