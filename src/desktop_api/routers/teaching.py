from __future__ import annotations

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
)

router = APIRouter(prefix="/api/teaching", tags=["teaching"])
_service: TeachingService | None = None
_service_runtime: DesktopAgentRuntime | None = None


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
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        raise HTTPException(status_code=409, detail=str(exc)) from exc
