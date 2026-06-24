from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from src.business.brain.skill_bootstrap_service import SkillBootstrapService
from src.business.brain.skill_equipment_service import SkillEquipmentService
from src.business.brain.skill_service import SkillService
from src.desktop_api.confirmations import request_high_risk_confirmation
from src.desktop_api.schemas import (
    BootstrapStatusResponse,
    EntityEquipmentResponse,
    EquipmentUpdateResponse,
    SkillDetail,
    SkillEquipmentAuditResponse,
    SkillHistoryResponse,
    SkillListResponse,
    SkillSoftDeleteResponse,
)

router = APIRouter(tags=["skills-methodology"])
_CONFLICT_RUNTIME_ERRORS = frozenset(
    {
        "skill_bootstrap_supersede_conflict",
        "skill_soft_delete_conflict",
        "skill_supersede_conflict",
    }
)


class SkillEditBody(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    trigger_conditions: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    body_markdown: str = Field(min_length=1)
    change_reason: str | None = None

    @field_validator("name", "description", "body_markdown")
    @classmethod
    def text_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("trigger_conditions")
    @classmethod
    def triggers_not_empty(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        if not cleaned:
            raise ValueError("skill_trigger_conditions_required")
        return cleaned

    @field_validator("required_tools")
    @classmethod
    def clean_required_tools(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]


class EquipmentUpdateItemBody(BaseModel):
    skill_id: str = Field(min_length=1)
    equipped_order: int = Field(default=0, ge=0)


class EquipmentUpdateBody(BaseModel):
    skills: list[EquipmentUpdateItemBody] = Field(default_factory=list)


def _require_confirmation(
    action_type: str,
    summary: str,
    *,
    extra_payload: dict[str, object] | None = None,
) -> None:
    if request_high_risk_confirmation(action_type, summary, extra_payload=extra_payload):
        return
    raise HTTPException(status_code=409, detail={"error": "confirmation_denied"})


def _runtime_http_exception(exc: RuntimeError) -> HTTPException:
    error = str(exc).split(":", 1)[0]
    if error in _CONFLICT_RUNTIME_ERRORS:
        return HTTPException(status_code=409, detail={"error": error})
    return HTTPException(status_code=500, detail={"error": "skill_operation_failed"})


@router.get("/api/skills/methodology", response_model=SkillListResponse)
async def list_methodology_skills(
    sort: str = Query(default="recently_changed"),
    filter: str | None = Query(default=None),
):
    try:
        return {"items": SkillService().list_active(sort=sort, filter_key=filter)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc


@router.get("/api/skills/methodology/bootstrap-status", response_model=BootstrapStatusResponse)
async def bootstrap_status():
    try:
        return SkillBootstrapService().bootstrap_status()
    except Exception as exc:
        raise HTTPException(status_code=500, detail={"error": "skill_bootstrap_failed"}) from exc


@router.get("/api/skills/methodology/{skill_id}", response_model=SkillDetail)
async def get_methodology_skill(skill_id: str):
    try:
        return SkillService().get_detail(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "skill_not_found"})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc


@router.put("/api/skills/methodology/{skill_id}", response_model=SkillDetail)
def edit_methodology_skill(skill_id: str, body: SkillEditBody):
    try:
        service = SkillService()
        return service.edit_with_protection_check(
            skill_id,
            {
                "name": body.name,
                "description": body.description,
                "trigger_conditions": body.trigger_conditions,
                "required_tools": body.required_tools,
                "body_markdown": body.body_markdown,
                "change_reason": body.change_reason,
            },
            require_confirmation=_require_confirmation,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "skill_not_found"})
    except ValueError as exc:
        error = str(exc).split(":", 1)[0]
        status = 409 if error == "skill_name_collision" else 400
        raise HTTPException(status_code=status, detail={"error": error, "message": str(exc)})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc


@router.post(
    "/api/skills/methodology/{skill_id}/soft-delete", response_model=SkillSoftDeleteResponse
)
def soft_delete_methodology_skill(skill_id: str):
    try:
        service = SkillService()
        return service.soft_delete_with_confirmation(
            skill_id,
            require_confirmation=_require_confirmation,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "skill_not_found"})
    except PermissionError:
        raise HTTPException(status_code=403, detail={"error": "bootstrap_skill_not_softdeletable"})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc


@router.get("/api/skills/methodology/{skill_id}/history", response_model=SkillHistoryResponse)
async def methodology_skill_history(skill_id: str):
    try:
        return SkillService().get_history(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "skill_not_found"})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc


@router.get(
    "/api/skills/methodology/{skill_id}/audit-equipment",
    response_model=SkillEquipmentAuditResponse,
)
async def methodology_skill_equipment_audit(skill_id: str):
    try:
        return SkillService().get_equipment_audit(skill_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "skill_not_found"})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc


@router.get("/api/specialists/{entity_id}/equipment", response_model=EntityEquipmentResponse)
async def get_specialist_equipment(entity_id: str):
    try:
        return SkillEquipmentService().get_equipment_for_entity(entity_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "specialist_not_found"})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc


@router.put("/api/specialists/{entity_id}/equipment", response_model=EquipmentUpdateResponse)
async def update_specialist_equipment(entity_id: str, body: EquipmentUpdateBody):
    try:
        return SkillEquipmentService().update_equipment_for_entity(
            entity_id,
            [item.model_dump() for item in body.skills],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "specialist_not_found"})
    except ValueError as exc:
        error = str(exc).split(":", 1)[0]
        raise HTTPException(status_code=400, detail={"error": error, "message": str(exc)})
    except RuntimeError as exc:
        raise _runtime_http_exception(exc) from exc
