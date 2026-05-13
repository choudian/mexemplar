from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.business.services.skill_composition.ui_adapter import SkillCompositionError, UiAdapter
from src.desktop_api.schemas import (
    CompositionAiHelperRequest,
    CompositionApplicabilityResponse,
    CompositionListResponse,
    CompositionOrderResponse,
    CompositionSummary,
    CompositionTrialRequest,
    CompositionUpsertRequest,
)

router = APIRouter(prefix="/api/compositions", tags=["compositions"])


def get_composition_adapter() -> UiAdapter:
    return UiAdapter()


def _payload(model) -> dict:
    return model.model_dump()


@router.get("", response_model=CompositionListResponse)
def list_compositions(
    adapter: UiAdapter = Depends(get_composition_adapter),
) -> CompositionListResponse:
    return CompositionListResponse(
        items=[CompositionSummary(**item) for item in adapter.list_compositions()]
    )


@router.post("", response_model=CompositionSummary)
def create_composition(
    request: CompositionUpsertRequest,
    adapter: UiAdapter = Depends(get_composition_adapter),
) -> CompositionSummary:
    try:
        return CompositionSummary(**adapter.create(_payload(request)))
    except SkillCompositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{composition_id}", response_model=CompositionSummary)
def update_composition(
    composition_id: str,
    request: CompositionUpsertRequest,
    adapter: UiAdapter = Depends(get_composition_adapter),
) -> CompositionSummary:
    try:
        return CompositionSummary(**adapter.update(composition_id, _payload(request)))
    except SkillCompositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{composition_id}/generate-applicability", response_model=CompositionApplicabilityResponse
)
def generate_applicability(
    composition_id: str,
    request: CompositionAiHelperRequest,
    adapter: UiAdapter = Depends(get_composition_adapter),
) -> CompositionApplicabilityResponse:
    del composition_id
    try:
        return CompositionApplicabilityResponse(
            applicability=adapter.generate_applicability(_payload(request))
        )
    except SkillCompositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{composition_id}/recommend-order", response_model=CompositionOrderResponse)
def recommend_order(
    composition_id: str,
    request: CompositionAiHelperRequest,
    adapter: UiAdapter = Depends(get_composition_adapter),
) -> CompositionOrderResponse:
    del composition_id
    try:
        result = adapter.recommend_order(_payload(request))
        return CompositionOrderResponse(
            members=result.get("members") or result.get("ordered_members") or [],
            reason=result.get("reason") or "",
        )
    except SkillCompositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{composition_id}/trial")
def start_trial(
    composition_id: str,
    request: CompositionTrialRequest,
    adapter: UiAdapter = Depends(get_composition_adapter),
) -> dict[str, object]:
    del request
    try:
        return adapter.start_trial(composition_id)
    except SkillCompositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{composition_id}/publish", response_model=CompositionSummary)
def publish_composition(
    composition_id: str,
    adapter: UiAdapter = Depends(get_composition_adapter),
) -> CompositionSummary:
    try:
        return CompositionSummary(**adapter.publish(composition_id))
    except SkillCompositionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
