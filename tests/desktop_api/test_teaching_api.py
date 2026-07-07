from __future__ import annotations

from src.business.services.teaching_service import TeachingService
from src.data.models_sqlite import Tool
from src.data.repositories import ToolRepository
from src.desktop_api.routers import teaching as teaching_router


class FakeHealth:
    def to_dict(self) -> dict[str, object]:
        return {"action_type_counts": {"click": 2}, "duration_seconds": 1.5}


class FakeDesktopRecordingService:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []
        self.abandoned: list[str] = []

    def start_after_minimize(self, recording_id: str) -> None:
        self.started.append(recording_id)

    def stop(self, recording_id: str) -> FakeHealth:
        self.stopped.append(recording_id)
        return FakeHealth()

    def mark_stopped(self, recording_id: str) -> None:
        self.stopped.append(recording_id)

    def mark_abandoned(self, recording_id: str) -> None:
        self.abandoned.append(recording_id)


class FakeBrowserRecorder:
    def __init__(self) -> None:
        self.armed_recording_id: str | None = None
        self.cleaned = False
        self.start_result = True
        self.stop_error: Exception | None = None

    def start_recording(self, recording_id: str | None = None) -> bool:
        self.armed_recording_id = recording_id
        return self.start_result

    def arm_extension_triggered_mode(self, recording_id: str | None = None) -> None:
        self.armed_recording_id = recording_id

    def stop_recording(self) -> dict[str, object]:
        if self.stop_error is not None:
            raise self.stop_error
        return {"recording_id": self.armed_recording_id}

    def cleanup(self) -> None:
        self.cleaned = True


def test_teaching_readiness_and_run_creation(desktop_api_client):
    readiness = desktop_api_client.get("/api/teaching/readiness")
    assert readiness.status_code == 200
    assert {item["mode"] for item in readiness.json()["modes"]} == {
        "browser",
        "extension",
        "desktop",
    }

    created = desktop_api_client.post("/api/teaching/runs", json={"mode": "browser"})
    assert created.status_code == 200
    assert created.json()["workflowId"].startswith("rec_")
    assert created.json()["stage"] == "selecting"


def test_desktop_recording_requires_minimize_callback(desktop_api_client):
    created = desktop_api_client.post("/api/teaching/runs", json={"mode": "desktop"})
    workflow_id = created.json()["workflowId"]

    start = desktop_api_client.post(
        f"/api/teaching/runs/{workflow_id}/recording/start",
        json={"mode": "desktop", "windowMinimized": False},
    )

    assert start.status_code == 409
    assert "minimize" in start.json()["detail"]


def test_teaching_stage_transitions_reject_skipped_steps(desktop_api_client):
    created = desktop_api_client.post("/api/teaching/runs", json={"mode": "browser"})
    workflow_id = created.json()["workflowId"]

    stop = desktop_api_client.post(f"/api/teaching/runs/{workflow_id}/recording/stop")
    trial = desktop_api_client.post(f"/api/teaching/runs/{workflow_id}/trial/start")

    assert stop.status_code == 409
    assert trial.status_code == 409


def test_teaching_desktop_flow_routes_through_business_service(desktop_api_client):
    fake_desktop = FakeDesktopRecordingService()
    learning_calls: list[tuple[str, str]] = []
    trial_calls: list[tuple[str, str]] = []

    def start_learning(workflow_id: str, mode: str) -> bool:
        learning_calls.append((workflow_id, mode))
        ToolRepository().create(
            Tool(
                tool_id="tool_learned",
                tool_name="Learned Skill",
                source="intent",
                status="pending",
                workflow_id=workflow_id,
            )
        )
        return True

    def start_trial(tool_id: str, workflow_id: str) -> bool:
        trial_calls.append((tool_id, workflow_id))
        return True

    service = TeachingService(
        desktop_service=fake_desktop,
        learning_starter=start_learning,
        trial_starter=start_trial,
    )
    desktop_api_client.app.dependency_overrides[teaching_router.get_teaching_service] = (
        lambda: service
    )
    try:
        created = desktop_api_client.post("/api/teaching/runs", json={"mode": "desktop"})
        workflow_id = created.json()["workflowId"]

        started = desktop_api_client.post(
            f"/api/teaching/runs/{workflow_id}/recording/start",
            json={"mode": "desktop", "windowMinimized": True},
        )
        stopped = desktop_api_client.post(f"/api/teaching/runs/{workflow_id}/recording/stop")
        intent = desktop_api_client.post(f"/api/teaching/runs/{workflow_id}/intent/confirm")
        trial = desktop_api_client.post(f"/api/teaching/runs/{workflow_id}/trial/start")
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert started.status_code == 200
    assert started.json()["stage"] == "recording"
    assert fake_desktop.started == [workflow_id]
    assert stopped.json()["stage"] == "intent_confirmation"
    assert stopped.json()["summary"]["desktopHealth"]["action_type_counts"] == {"click": 2}
    assert intent.json()["stage"] == "learning"
    assert trial.json()["stage"] == "trial_validation"
    assert learning_calls == [(workflow_id, "desktop")]
    assert trial_calls == [("tool_learned", workflow_id)]


def test_teaching_intent_reply_does_not_advance_to_learning(desktop_api_client):
    fake_recorder = FakeBrowserRecorder()
    reply_calls: list[tuple[str, str]] = []

    def continue_learning(workflow_id: str, content: str) -> bool:
        reply_calls.append((workflow_id, content))
        return True

    service = TeachingService(
        browser_recorder_factory=lambda: fake_recorder,
        learning_starter=lambda workflow_id, mode: True,
        learning_replier=continue_learning,
    )
    desktop_api_client.app.dependency_overrides[teaching_router.get_teaching_service] = (
        lambda: service
    )
    try:
        created = desktop_api_client.post("/api/teaching/runs", json={"mode": "extension"})
        workflow_id = created.json()["workflowId"]

        desktop_api_client.post(
            f"/api/teaching/runs/{workflow_id}/recording/start",
            json={"mode": "extension"},
        )
        stopped = desktop_api_client.post(f"/api/teaching/runs/{workflow_id}/recording/stop")
        reply = desktop_api_client.post(
            f"/api/teaching/runs/{workflow_id}/intent/reply",
            json={"content": "我补充一个边界条件"},
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert stopped.json()["stage"] == "intent_confirmation"
    assert fake_recorder.cleaned is True
    assert reply.status_code == 200
    assert reply.json()["stage"] == "intent_confirmation"
    assert reply_calls == [(workflow_id, "我补充一个边界条件")]


def test_extension_recording_uses_teaching_workflow_id():
    fake_recorder = FakeBrowserRecorder()
    service = TeachingService(browser_recorder_factory=lambda: fake_recorder)
    created = service.create_run("extension")
    workflow_id = str(created["workflowId"])

    started = service.start_recording(workflow_id, "extension")

    assert started["stage"] == "recording"
    assert fake_recorder.armed_recording_id == workflow_id


def test_browser_recording_start_failure_rejects_request(desktop_api_client):
    fake_recorder = FakeBrowserRecorder()
    fake_recorder.start_result = False
    service = TeachingService(browser_recorder_factory=lambda: fake_recorder)
    desktop_api_client.app.dependency_overrides[teaching_router.get_teaching_service] = (
        lambda: service
    )
    try:
        created = desktop_api_client.post("/api/teaching/runs", json={"mode": "browser"})
        workflow_id = created.json()["workflowId"]

        started = desktop_api_client.post(
            f"/api/teaching/runs/{workflow_id}/recording/start",
            json={"mode": "browser"},
        )
        run = service.get_run(workflow_id)
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert started.status_code == 409
    assert started.json()["detail"] == "browser recording failed to start"
    assert run["stage"] == "selecting"


def test_browser_recording_save_failure_rejects_stop_and_does_not_start_pm(desktop_api_client):
    fake_recorder = FakeBrowserRecorder()
    fake_recorder.stop_error = RuntimeError("recording_persistence_failed")
    learning_calls: list[tuple[str, str]] = []
    service = TeachingService(
        browser_recorder_factory=lambda: fake_recorder,
        learning_starter=lambda workflow_id, mode: learning_calls.append((workflow_id, mode)),
    )
    desktop_api_client.app.dependency_overrides[teaching_router.get_teaching_service] = (
        lambda: service
    )
    try:
        created = desktop_api_client.post("/api/teaching/runs", json={"mode": "browser"})
        workflow_id = created.json()["workflowId"]
        desktop_api_client.post(
            f"/api/teaching/runs/{workflow_id}/recording/start",
            json={"mode": "browser"},
        )

        stopped = desktop_api_client.post(f"/api/teaching/runs/{workflow_id}/recording/stop")
        run = service.get_run(workflow_id)
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert stopped.status_code == 409
    assert stopped.json()["detail"] == "browser recording failed to save"
    assert run["stage"] == "recording"
    assert fake_recorder.cleaned is True
    assert learning_calls == []
