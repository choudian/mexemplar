from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from src.business.debug.service import get_debug_service
from src.desktop_api.schemas import (
    DebugControlRequest,
    DebugControlStatus,
    DebugFlowDetailResponse,
    DebugFlowListResponse,
    DebugReferenceResponse,
    DebugTraceDetail,
    DebugTraceListResponse,
    ErrorDetail,
    ErrorResponse,
)

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/control", response_model=DebugControlStatus)
async def get_control() -> dict:
    return get_debug_service().get_status()


@router.put("/control", response_model=DebugControlStatus)
async def update_control(request: DebugControlRequest) -> dict | JSONResponse:
    service = get_debug_service()
    try:
        if request.enabled:
            return service.arm(warning_acknowledged=request.warningAcknowledged)
        return service.stop()
    except ValueError as exc:
        if str(exc) == "debug_warning_required":
            return _error(422, "debug_warning_required", "Debug warning must be acknowledged.")
        raise


@router.get("/traces", response_model=DebugTraceListResponse)
async def list_traces(
    source: str | None = None,
    agentType: str | None = None,
    sessionId: str | None = None,
    workflowId: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict | JSONResponse:
    try:
        response = get_debug_service().list_traces(
            source=source,
            agent_type=agentType,
            session_id=sessionId,
            workflow_id=workflowId,
            limit=limit,
        )
        return _no_store_json(response)
    except LookupError as exc:
        return _lookup_error(exc)


@router.get("/traces/{trace_id}", response_model=DebugTraceDetail)
async def get_trace(trace_id: str) -> dict | JSONResponse:
    try:
        return _no_store_json(get_debug_service().get_trace_detail(trace_id))
    except LookupError as exc:
        return _lookup_error(exc)


@router.delete("/traces", status_code=204, response_class=Response, response_model=None)
async def clear_traces() -> Response | JSONResponse:
    try:
        get_debug_service().clear()
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    except LookupError as exc:
        return _lookup_error(exc)


@router.get("/flows", response_model=DebugFlowListResponse)
async def list_flows(
    workflowId: str | None = None,
    sessionId: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> dict | JSONResponse:
    try:
        response = get_debug_service().list_flows(
            workflow_id=workflowId,
            session_id=sessionId,
            limit=limit,
        )
        return _no_store_json(response)
    except LookupError as exc:
        return _lookup_error(exc)


@router.get("/flows/{workflow_id}", response_model=DebugFlowDetailResponse)
async def get_flow(workflow_id: str) -> dict | JSONResponse:
    try:
        return _no_store_json(get_debug_service().get_flow_detail(workflow_id))
    except LookupError as exc:
        return _lookup_error(exc)


@router.get("/references/{reference_id}", response_model=DebugReferenceResponse)
async def expand_reference(reference_id: str) -> dict | JSONResponse:
    try:
        return _no_store_json(get_debug_service().expand_reference(reference_id))
    except LookupError as exc:
        return _lookup_error(exc)


def _no_store_json(payload: dict) -> JSONResponse:
    return JSONResponse(content=_jsonable(payload), headers={"Cache-Control": "no-store"})


def _lookup_error(exc: LookupError) -> JSONResponse:
    code = str(exc)
    if code == "debug_disabled":
        return _error(404, "debug_disabled", "Debug trace is not enabled.")
    if code == "trace_not_found":
        return _error(404, "trace_not_found", "Trace was not found.")
    if code == "reference_not_found":
        return _error(404, "reference_not_found", "Reference was not found.")
    return _error(404, "debug_not_found", "Debug resource was not found.")


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    payload = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def _jsonable(value):
    from fastapi.encoders import jsonable_encoder

    return jsonable_encoder(value)
