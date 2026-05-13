from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, Literal

from src.business.services.desktop_recording_service import DesktopRecordingService
from src.business.services.recording_readiness_service import RecordingReadinessService
from src.data.repositories import ToolRepository
from src.recording.browser_recorder import BrowserRecorder
from src.utils.events import emit

TeachingMode = Literal["browser", "extension", "desktop"]
TeachingStage = Literal[
    "selecting",
    "recording",
    "intent_confirmation",
    "learning",
    "trial_validation",
    "published",
    "failed",
    "abandoned",
]

_ALLOWED_TRANSITIONS: dict[TeachingStage, set[TeachingStage]] = {
    "selecting": {"recording"},
    "recording": {"intent_confirmation", "abandoned"},
    "intent_confirmation": {"intent_confirmation", "learning", "abandoned", "selecting"},
    "learning": {"trial_validation", "failed"},
    "trial_validation": {"published", "failed"},
    "published": set(),
    "failed": {"selecting"},
    "abandoned": {"selecting"},
}


@dataclass
class TeachingRun:
    workflow_id: str
    mode: TeachingMode
    stage: TeachingStage = "selecting"
    summary: dict[str, object] = field(default_factory=dict)

    def can_transition(self, next_stage: TeachingStage) -> bool:
        return next_stage in _ALLOWED_TRANSITIONS[self.stage]

    def transition(self, next_stage: TeachingStage) -> None:
        if not self.can_transition(next_stage):
            raise ValueError(f"invalid teaching stage transition: {self.stage} -> {next_stage}")
        self.stage = next_stage

    def to_dict(self) -> dict[str, object]:
        return {
            "workflowId": self.workflow_id,
            "mode": self.mode,
            "stage": self.stage,
            "summary": self.summary,
        }


class TeachingService:
    """Workflow facade for teaching a skill through the redesigned API."""

    _runs: dict[str, TeachingRun] = {}

    def __init__(
        self,
        readiness_service: RecordingReadinessService | None = None,
        desktop_service: DesktopRecordingService | None = None,
        browser_recorder_factory: Callable[[], BrowserRecorder] | None = None,
        learning_starter: Callable[[str, str], bool | None] | None = None,
        trial_starter: Callable[[str, str], bool | None] | None = None,
    ) -> None:
        self._readiness = readiness_service or RecordingReadinessService()
        self._desktop_service = desktop_service
        self._browser_recorder_factory = browser_recorder_factory or BrowserRecorder
        self._browser_recorders: dict[str, BrowserRecorder] = {}
        self._learning_starter = learning_starter
        self._trial_starter = trial_starter

    def _get_desktop_service(self) -> DesktopRecordingService:
        if self._desktop_service is None:
            self._desktop_service = DesktopRecordingService()
        return self._desktop_service

    def get_readiness(self) -> dict[str, object]:
        return self._readiness.to_response()

    def create_run(self, mode: TeachingMode) -> dict[str, object]:
        workflow_id = f"rec_{uuid.uuid4().hex[:12]}"
        run = TeachingRun(workflow_id=workflow_id, mode=mode)
        self._runs[workflow_id] = run
        payload = run.to_dict()
        payload["readiness"] = self.get_readiness()
        return payload

    def _get_run(self, workflow_id: str) -> TeachingRun:
        try:
            return self._runs[workflow_id]
        except KeyError as exc:
            raise KeyError(f"unknown teaching workflow: {workflow_id}") from exc

    def start_recording(
        self,
        workflow_id: str,
        mode: TeachingMode,
        *,
        window_minimized: bool = False,
    ) -> dict[str, object]:
        run = self._get_run(workflow_id)
        if mode != run.mode:
            raise ValueError("recording mode does not match the teaching run")
        if mode == "desktop":
            if not window_minimized:
                raise ValueError("desktop recording requires a completed window minimize callback")
            self._get_desktop_service().start_after_minimize(workflow_id)
        elif mode == "extension":
            recorder = self._browser_recorder_factory()
            recorder.arm_extension_triggered_mode(recording_id=workflow_id)
            self._browser_recorders[workflow_id] = recorder
        else:
            recorder = self._browser_recorder_factory()
            recorder.start_recording(recording_id=workflow_id)
            self._browser_recorders[workflow_id] = recorder

        run.transition("recording")
        emit("recording_started", sender=self, workflow_id=workflow_id, recording_mode=mode)
        return run.to_dict()

    def stop_recording(self, workflow_id: str) -> dict[str, object]:
        run = self._get_run(workflow_id)
        summary: dict[str, object] = {}
        if run.mode == "desktop":
            health = self._get_desktop_service().stop(workflow_id)
            summary["desktopHealth"] = health.to_dict()
        else:
            recorder = self._browser_recorders.pop(workflow_id, None)
            if recorder is not None:
                summary["recording"] = recorder.stop_recording()

        run.transition("intent_confirmation")
        run.summary = summary
        emit("recording_stopped", sender=self, workflow_id=workflow_id, recording_mode=run.mode)
        return run.to_dict()

    def apply_desktop_health_decision(self, workflow_id: str, decision: str) -> dict[str, object]:
        run = self._get_run(workflow_id)
        if run.mode != "desktop":
            raise ValueError("desktop health decisions apply only to desktop recordings")
        if decision == "continue":
            self._get_desktop_service().mark_stopped(workflow_id)
            run.transition("intent_confirmation")
        elif decision == "discard":
            self._get_desktop_service().mark_abandoned(workflow_id)
            run.transition("abandoned")
        elif decision == "rerecord":
            self._get_desktop_service().mark_abandoned(workflow_id)
            run.transition("selecting")
        else:
            raise ValueError("unsupported desktop health decision")
        return run.to_dict()

    def reply_to_intent(self, workflow_id: str, content: str) -> dict[str, object]:
        run = self._get_run(workflow_id)
        run.transition("intent_confirmation")
        run.summary["lastIntentReply"] = content
        emit("agent_needs_user_input", sender=self, workflow_id=workflow_id, question=content)
        return run.to_dict()

    def confirm_intent(self, workflow_id: str) -> dict[str, object]:
        run = self._get_run(workflow_id)
        if not run.can_transition("learning"):
            run.transition("learning")
        if self._learning_starter is None:
            raise ValueError("teaching learning runner is unavailable")
        accepted = self._learning_starter(workflow_id, run.mode)
        if accepted is False:
            raise ValueError("teaching learning is already running")
        run.transition("learning")
        return run.to_dict()

    def start_trial(self, workflow_id: str) -> dict[str, object]:
        run = self._get_run(workflow_id)
        if not run.can_transition("trial_validation"):
            run.transition("trial_validation")
        if self._trial_starter is None:
            raise ValueError("skill trial runner is unavailable")
        tool = ToolRepository().get_by_workflow_id(workflow_id)
        if tool is None:
            raise ValueError("no learned skill is available for this teaching run")
        accepted = self._trial_starter(tool.tool_id, workflow_id)
        if accepted is False:
            raise ValueError("skill trial is already running")
        run.transition("trial_validation")
        return run.to_dict()
