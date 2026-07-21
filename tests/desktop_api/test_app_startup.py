from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.business.services.recording_startup_service import RecordingStartupService
from src.desktop_api.app import SESSION_HEADER, create_app


def _patch_unrelated_lifespan_work(monkeypatch) -> None:
    """让本文件的调度接线测试只观察 lifespan 顺序，不启动无关后台线程。"""
    import src.business.mcp as mcp_business
    import src.desktop_api.app as app_module
    from src.business.brain.background_worker import BrainBackgroundWorker
    from src.business.brain.skill_bootstrap_service import SkillBootstrapService
    from src.business.services.assistant_failure_service import AssistantFailureService
    from src.business.services import grand_tour_fixture_service
    from src.business.self_improvement import execution_review_trigger
    from src.business.task_collaboration.background_worker import (
        TaskCollaborationBackgroundWorker,
    )
    from src.data import real_tour_audit

    monkeypatch.setattr(RecordingStartupService, "ensure_recovered", lambda self: None)
    monkeypatch.setattr(
        AssistantFailureService,
        "recover_interrupted_retries",
        lambda self: 0,
    )
    monkeypatch.setattr(app_module, "ensure_builtin_deps", lambda: None)
    monkeypatch.setattr(real_tour_audit, "ensure_initialized", lambda: None)
    monkeypatch.setattr(grand_tour_fixture_service, "ensure_fixture_skill", lambda: None)
    monkeypatch.setattr(execution_review_trigger, "register", lambda: None)
    monkeypatch.setattr(SkillBootstrapService, "ensure_bootstrap_skill", lambda self: None)
    monkeypatch.setattr(BrainBackgroundWorker, "start", lambda self: None)
    monkeypatch.setattr(BrainBackgroundWorker, "stop", lambda self: None)
    monkeypatch.setattr(TaskCollaborationBackgroundWorker, "start", lambda self: None)
    monkeypatch.setattr(TaskCollaborationBackgroundWorker, "stop", lambda self: None)
    mcp_service = MagicMock()
    mcp_service.sdk_available = False
    monkeypatch.setattr(
        mcp_business,
        "get_mcp_server_service",
        lambda: mcp_service,
    )
    monkeypatch.setattr(app_module.event_queue, "shutdown", lambda: None)


def _patch_scheduler_lifespan(
    monkeypatch,
    calls: list[str],
    *,
    fail_start: bool = False,
    fail_launcher_close: bool = False,
):
    from src.business.scheduling import run_completion_monitor as monitor_module
    from src.business.scheduling import scheduling_confirmation_manager as confirmation_module
    from src.business.scheduling import scheduler_service as service_module
    from src.business.scheduling import scheduler_worker as worker_module
    from src.business.scheduling import session_launcher as launcher_module
    from src.business.scheduling import unattended_confirmation_manager as unattended_module

    _patch_unrelated_lifespan_work(monkeypatch)
    service_module.clear_default_scheduler_launcher()
    created: dict[str, object] = {}

    class _Launcher:
        def __init__(
            self,
            dispatch_callback,
            *,
            reserve_callback,
            release_callback,
            session_quiescent_callback,
        ):
            self.dispatch_callback = dispatch_callback
            created["launcher_callbacks"] = {
                "reserve": reserve_callback,
                "release": release_callback,
                "quiescent": session_quiescent_callback,
            }
            created["launcher"] = self
            calls.append("launcher_init")

        def close(self):
            calls.append("launcher_close")
            if fail_launcher_close:
                raise RuntimeError("launcher close failed")

    class _Worker:
        def __init__(self, service, launcher, *, retry_terminal_events=None):
            assert service is None
            assert launcher is created["launcher"]
            assert retry_terminal_events == created["monitor"].retry_pending_terminal_events
            created["worker"] = self
            calls.append("worker_init")

        def start(self):
            calls.append("worker_start")
            if fail_start:
                raise RuntimeError("worker startup failed")

        def stop(self):
            calls.append("worker_stop")

    class _Unattended:
        def load_all(self):
            calls.append("unattended_load")

    class _Confirmations:
        def settle_all_for_shutdown(self):
            calls.append("confirmations_settle")

    original_register = service_module.configure_default_scheduler_launcher
    original_clear = service_module.clear_default_scheduler_launcher

    def _register(launcher):
        calls.append("launcher_register")
        original_register(launcher)

    def _clear(launcher=None):
        calls.append("launcher_unregister")
        original_clear(launcher)

    monkeypatch.setattr(launcher_module, "SessionLauncher", _Launcher)
    monkeypatch.setattr(worker_module, "SchedulerWorker", _Worker)
    monkeypatch.setattr(service_module, "configure_default_scheduler_launcher", _register)
    monkeypatch.setattr(service_module, "clear_default_scheduler_launcher", _clear)
    monkeypatch.setattr(
        unattended_module,
        "get_unattended_confirmation_manager",
        lambda: _Unattended(),
    )
    monkeypatch.setattr(
        confirmation_module,
        "get_scheduling_confirmation_manager",
        lambda: _Confirmations(),
    )

    def _install_monitor(**kwargs):
        created["monitor_kwargs"] = kwargs
        calls.append("monitor_install")
        monitor = MagicMock()
        created["monitor"] = monitor
        return monitor

    monkeypatch.setattr(
        monitor_module,
        "install_run_completion_monitor",
        _install_monitor,
    )
    monkeypatch.setattr(
        monitor_module,
        "shutdown_run_completion_monitor",
        lambda: calls.append("monitor_shutdown"),
    )
    return service_module, created


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


def test_scheduler_lifespan_orders_registration_authorization_monitor_and_worker(
    monkeypatch,
):
    calls: list[str] = []
    service_module, created = _patch_scheduler_lifespan(monkeypatch, calls)
    token = "test-session-token"

    try:
        with TestClient(create_app(token), headers={SESSION_HEADER: token}) as client:
            assert client.get("/api/health").status_code == 200
            assert service_module._get_default_scheduler_launcher() is created["launcher"]
            assert calls.index("launcher_register") < calls.index("unattended_load")
            assert calls.index("unattended_load") < calls.index("monitor_install")
            assert calls.index("monitor_install") < calls.index("worker_start")
            assert created["monitor_kwargs"]["has_pending_reentry"].__name__ == (
                "has_pending_reentry"
            )
            assert created["launcher_callbacks"]["reserve"].__name__ == (
                "reserve_scheduled_session"
            )
            assert created["launcher_callbacks"]["release"].__name__ == (
                "release_scheduled_session_reservation"
            )
            assert created["launcher_callbacks"]["quiescent"].__name__ == (
                "is_scheduled_session_quiescent"
            )

        assert calls.index("worker_stop") < calls.index("monitor_shutdown")
        assert calls.index("monitor_shutdown") < calls.index("confirmations_settle")
        assert calls.index("confirmations_settle") < calls.index("launcher_unregister")
        assert calls.index("launcher_unregister") < calls.index("launcher_close")
        assert service_module._get_default_scheduler_launcher() is None
    finally:
        service_module.clear_default_scheduler_launcher()


def test_scheduler_lifespan_cleans_partial_startup_before_serving(monkeypatch):
    calls: list[str] = []
    service_module, _ = _patch_scheduler_lifespan(
        monkeypatch,
        calls,
        fail_start=True,
    )
    token = "test-session-token"

    try:
        with TestClient(create_app(token), headers={SESSION_HEADER: token}) as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "degraded"
            checks = {item["name"]: item for item in payload["checks"]}
            assert checks["scheduling"]["status"] == "degraded"
            assert "automatic triggers are disabled" in checks["scheduling"]["message"]
            assert service_module._get_default_scheduler_launcher() is None
            first_unregister = calls.index("launcher_unregister")
            assert calls.index("monitor_install") < calls.index("worker_start")
            assert calls.index("worker_start") < calls.index("worker_stop")
            assert calls.index("worker_stop") < first_unregister
            assert first_unregister < calls.index("monitor_shutdown")
            assert calls.index("monitor_shutdown") < calls.index("launcher_close")
    finally:
        service_module.clear_default_scheduler_launcher()


def test_scheduler_startup_cleanup_continues_when_launcher_close_fails(monkeypatch):
    calls: list[str] = []
    service_module, _ = _patch_scheduler_lifespan(
        monkeypatch,
        calls,
        fail_start=True,
        fail_launcher_close=True,
    )
    token = "test-session-token"

    try:
        with TestClient(create_app(token), headers={SESSION_HEADER: token}) as client:
            assert client.get("/api/health").status_code == 200
            assert service_module._get_default_scheduler_launcher() is None
        assert "launcher_close" in calls
        assert "confirmations_settle" in calls
    finally:
        service_module.clear_default_scheduler_launcher()


def test_scheduler_shutdown_cleanup_continues_when_launcher_close_fails(monkeypatch):
    calls: list[str] = []
    service_module, _ = _patch_scheduler_lifespan(
        monkeypatch,
        calls,
        fail_launcher_close=True,
    )
    token = "test-session-token"

    try:
        with TestClient(create_app(token), headers={SESSION_HEADER: token}) as client:
            assert client.get("/api/health").status_code == 200
        assert "launcher_close" in calls
        assert service_module._get_default_scheduler_launcher() is None
    finally:
        service_module.clear_default_scheduler_launcher()
