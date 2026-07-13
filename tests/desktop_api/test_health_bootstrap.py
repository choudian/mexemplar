from __future__ import annotations

from fastapi.testclient import TestClient

from src.business.services.desktop_bootstrap_service import ChatService, DesktopBootstrapService
from src.business.services import desktop_bootstrap_service as bootstrap_module
from src.business.services.desktop_health_service import DesktopHealthCheck, DesktopHealthService


def test_health_returns_ready_connection_state(desktop_api_client: TestClient) -> None:
    response = desktop_api_client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert {check["name"] for check in payload["checks"]} >= {
        "config",
        "sqlite",
        "events",
        "sidecar",
    }


def test_bootstrap_returns_shell_data_without_repository_shape(
    desktop_api_client: TestClient,
) -> None:
    response = desktop_api_client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connection"]["status"] == "ready"
    assert "displayName" in payload["user"]
    assert set(payload["navigation"]) == {
        "pendingSkillCount",
        "publishedSkillCount",
        "failureCount",
        "compositionCount",
    }
    assert payload["settingsSummary"]["theme"]
    assert payload["brain"]["segmentIdleThresholdSeconds"] > 0


def test_health_service_reports_critical_probe_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        DesktopHealthService,
        "_probe_config",
        lambda self: DesktopHealthCheck("config", "failed", "config unavailable"),
    )
    monkeypatch.setattr(
        DesktopHealthService,
        "_probe_sqlite",
        lambda self: DesktopHealthCheck("sqlite", "ok", "sqlite available"),
    )

    state = DesktopHealthService().get_connection_state(event_stream_available=True)

    assert state["status"] == "failed"
    checks = {check["name"]: check for check in state["checks"]}
    assert checks["config"]["status"] == "failed"


def test_bootstrap_degraded_checks_are_visible(desktop_api_client: TestClient, monkeypatch) -> None:
    def fail_display_name(self) -> str:
        raise RuntimeError("profile store unavailable")

    monkeypatch.setattr(ChatService, "get_display_name", fail_display_name)

    response = desktop_api_client.get("/api/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["connection"]["status"] == "degraded"
    checks = {check["name"]: check for check in payload["connection"]["checks"]}
    assert checks["bootstrap.user"]["status"] == "degraded"
    assert payload["user"]["displayName"] == "本地用户"


def test_bootstrap_settings_summary_comes_from_unified_config(monkeypatch) -> None:
    class FakeConfig:
        def get(self, key, default=None):
            return {"ui.theme": "dark", "ui.density": "compact"}.get(key, default)

    monkeypatch.setattr(bootstrap_module, "get_unified_config", lambda: FakeConfig())

    summary = DesktopBootstrapService().get_settings_summary()

    assert summary == {
        "theme": "dark",
        "dark": True,
        "density": "compact",
        "accent": "",
        "radius": "medium",
    }


def test_bootstrap_brain_config_comes_from_unified_config(monkeypatch) -> None:
    class FakeConfig:
        def get_brain_segment_idle_threshold(self):
            return 42

    monkeypatch.setattr(bootstrap_module, "get_unified_config", lambda: FakeConfig())

    config = DesktopBootstrapService().get_brain_config()

    assert config == {"segmentIdleThresholdSeconds": 42}
