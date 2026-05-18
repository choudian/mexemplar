from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.business.services.skills_service import SkillsService
from src.desktop_api.orchestrator_runtime import DesktopAgentRuntime, get_desktop_agent_runtime
from src.desktop_api.schemas import (
    SkillActionResponse,
    SkillCategoryResponse,
    SkillMetadataUpdateRequest,
    SkillTrialReplyRequest,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])


def get_skills_service(
    runtime: DesktopAgentRuntime = Depends(get_desktop_agent_runtime),
) -> SkillsService:
    return SkillsService(
        trial_starter=runtime.start_tool_trial,
        trial_replier=runtime.continue_tool_trial,
        retry_starter=runtime.retry_teaching_failure,
        trial_history_loader=runtime.get_trial_history,
    )


@router.get("")
def list_skills(
    category: str | None = Query(default=None, pattern="^(pending|published|failed)$"),
    service: SkillsService = Depends(get_skills_service),
):
    if category:
        return SkillCategoryResponse(**service.get_category(category))
    return {"categories": service.get_all_categories()}


@router.post("/{tool_id}/trial", response_model=SkillActionResponse)
def start_trial(
    tool_id: str,
    service: SkillsService = Depends(get_skills_service),
) -> SkillActionResponse:
    try:
        return SkillActionResponse(**service.start_trial(tool_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{tool_id}/trial/messages")
def get_trial_messages(
    tool_id: str,
    service: SkillsService = Depends(get_skills_service),
) -> dict:
    return service.get_trial_history(tool_id)


@router.post("/{tool_id}/trial/reply", response_model=SkillActionResponse)
def reply_trial(
    tool_id: str,
    request: SkillTrialReplyRequest,
    service: SkillsService = Depends(get_skills_service),
) -> SkillActionResponse:
    try:
        return SkillActionResponse(**service.continue_trial(tool_id, request.content))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{tool_id}")
def update_skill(
    tool_id: str,
    request: SkillMetadataUpdateRequest,
    service: SkillsService = Depends(get_skills_service),
) -> dict[str, object]:
    try:
        referenced = service.update_tool_metadata(tool_id, request.name, request.description)
        return {"toolId": tool_id, "referencedCompositions": referenced}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{tool_id}", response_model=SkillActionResponse)
def delete_skill(
    tool_id: str,
    service: SkillsService = Depends(get_skills_service),
) -> SkillActionResponse:
    try:
        service.delete_tool(tool_id)
        return SkillActionResponse(accepted=True, toolId=tool_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/failures/{workflow_id}/retry", response_model=SkillActionResponse)
def retry_failure(
    workflow_id: str,
    service: SkillsService = Depends(get_skills_service),
) -> SkillActionResponse:
    try:
        return SkillActionResponse(**service.retry_failure(workflow_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/failures/{workflow_id}/dismiss", response_model=SkillActionResponse)
def dismiss_failure(
    workflow_id: str,
    service: SkillsService = Depends(get_skills_service),
) -> SkillActionResponse:
    try:
        return SkillActionResponse(**service.dismiss_failure(workflow_id))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
