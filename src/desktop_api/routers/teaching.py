from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.business.services.teaching_service import TeachingService
from src.desktop_api.orchestrator_runtime import DesktopAgentRuntime, get_desktop_agent_runtime
from src.desktop_api.schemas import (
    TeachingCreateRunRequest,
    TeachingDesktopHealthDecisionRequest,
    TeachingIntentReplyRequest,
    TeachingReadinessResponse,
    TeachingRecordingStartRequest,
    TeachingRunResponse,
    TrialPreviewDecisionRequest,
    TrialPreviewDecisionResponse,
)
from src.desktop_api.events import event_queue
from src.desktop_api.ui_events import UiEventDraft, trial_preview_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/teaching", tags=["teaching"])
_service: TeachingService | None = None
_service_runtime: DesktopAgentRuntime | None = None
_TEACHING_CONFLICT_DETAIL = "Teaching request cannot be completed in the current state."
_SAFE_CONFLICT_MESSAGES = frozenset({
    "desktop recording requires a completed window minimize callback",
    "recording mode does not match the teaching run",
    "requirements must be confirmed before starting a skill trial",
    "skill trial runner is unavailable",
    "no learned skill is available for this teaching run",
    "skill trial is already running",
    "desktop health decisions apply only to desktop recordings",
    "unsupported desktop health decision",
})


def get_teaching_service(
    runtime: DesktopAgentRuntime = Depends(get_desktop_agent_runtime),
) -> TeachingService:
    global _service, _service_runtime
    if _service is None or _service_runtime is not runtime:
        _service = TeachingService(
            learning_starter=runtime.start_learning,
            trial_starter=runtime.start_tool_trial,
            learning_replier=runtime.continue_learning,
        )
        _service_runtime = runtime
    return _service


def _run_response(payload: dict[str, object]) -> TeachingRunResponse:
    return TeachingRunResponse(
        workflowId=str(payload["workflowId"]),
        mode=payload["mode"],
        stage=payload["stage"],
        readiness=payload.get("readiness"),
        summary=payload.get("summary") or {},
    )


def _teaching_conflict(exc: ValueError, workflow_id: str) -> HTTPException:
    detail = str(exc) if str(exc) in _SAFE_CONFLICT_MESSAGES else _TEACHING_CONFLICT_DETAIL
    logger.warning(
        "Teaching request rejected",
        extra={"workflow_id": workflow_id, "reason": type(exc).__name__},
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return HTTPException(status_code=409, detail=detail)


@router.get("")
def teaching_status() -> dict[str, object]:
    return {"status": "ready", "resources": ["readiness", "runs"]}


@router.get("/readiness", response_model=TeachingReadinessResponse)
def get_readiness(service: TeachingService = Depends(get_teaching_service)) -> dict[str, object]:
    return service.get_readiness()


@router.post("/runs", response_model=TeachingRunResponse)
def create_run(
    request: TeachingCreateRunRequest,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    return _run_response(service.create_run(request.mode))


@router.get("/runs/{workflow_id}", response_model=TeachingRunResponse)
def get_run(
    workflow_id: str,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    try:
        return _run_response(service.get_run(workflow_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="teaching run not found") from exc


@router.post("/runs/{workflow_id}/recording/start", response_model=TeachingRunResponse)
def start_recording(
    workflow_id: str,
    request: TeachingRecordingStartRequest,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    try:
        return _run_response(
            service.start_recording(
                workflow_id,
                request.mode,
                window_minimized=request.windowMinimized,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="teaching run not found") from exc
    except ValueError as exc:
        raise _teaching_conflict(exc, workflow_id) from exc


@router.post("/runs/{workflow_id}/recording/stop", response_model=TeachingRunResponse)
def stop_recording(
    workflow_id: str,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    try:
        return _run_response(service.stop_recording(workflow_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="teaching run not found") from exc
    except ValueError as exc:
        raise _teaching_conflict(exc, workflow_id) from exc


@router.post(
    "/runs/{workflow_id}/recording/desktop-health-decision", response_model=TeachingRunResponse
)
def desktop_health_decision(
    workflow_id: str,
    request: TeachingDesktopHealthDecisionRequest,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    try:
        return _run_response(service.apply_desktop_health_decision(workflow_id, request.decision))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="teaching run not found") from exc
    except ValueError as exc:
        raise _teaching_conflict(exc, workflow_id) from exc


@router.post("/runs/{workflow_id}/intent/reply", response_model=TeachingRunResponse)
def reply_to_intent(
    workflow_id: str,
    request: TeachingIntentReplyRequest,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    try:
        return _run_response(service.reply_to_intent(workflow_id, request.content))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="teaching run not found") from exc
    except ValueError as exc:
        raise _teaching_conflict(exc, workflow_id) from exc


@router.post("/runs/{workflow_id}/intent/confirm", response_model=TeachingRunResponse)
def confirm_intent(
    workflow_id: str,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    try:
        return _run_response(service.confirm_intent(workflow_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="teaching run not found") from exc
    except ValueError as exc:
        raise _teaching_conflict(exc, workflow_id) from exc


@router.post("/runs/{workflow_id}/trial/start", response_model=TeachingRunResponse)
def start_trial(
    workflow_id: str,
    service: TeachingService = Depends(get_teaching_service),
) -> TeachingRunResponse:
    try:
        return _run_response(service.start_trial(workflow_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="teaching run not found") from exc
    except ValueError as exc:
        raise _teaching_conflict(exc, workflow_id) from exc


@router.post(
    "/trial-preview/{request_id}/decision",
    response_model=TrialPreviewDecisionResponse,
)
def decide_trial_preview(
    request_id: str,
    request: TrialPreviewDecisionRequest,
) -> TrialPreviewDecisionResponse:
    result = trial_preview_manager.record_decision(request_id, request.decision)
    workflow_id = str(result.get("workflowId") or "")
    trial_id = str(result.get("trialId") or "")
    if workflow_id:
        event_queue.publish_draft_nowait(
            UiEventDraft(
                "trial.preview_resolved",
                {
                    "requestId": request_id,
                    "workflowId": workflow_id,
                    "trialId": trial_id,
                    "decision": result.get("eventDecision") or request.decision,
                    "status": result.get("eventStatus") or result["status"],
                    "message": "Preview decision received.",
                },
                {"workflowId": workflow_id},
                workflow_id,
            )
        )
    response_status = result["status"]
    return TrialPreviewDecisionResponse(
        requestId=str(result["requestId"]),
        decision=request.decision,
        accepted=bool(result["accepted"]),
        status=response_status,
    )
