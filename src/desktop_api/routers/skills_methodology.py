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


def _active_equipment_names(service: SkillService, skill_id: str) -> list[str]:
    audit = service.get_equipment_audit(skill_id)
    return [
        str(row.get("equipped_entity_name") or row.get("equipped_entity_id") or "")
        for row in audit.get("rows", [])
        if row.get("status") == "active"
    ]


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
        detail = service.get_detail(skill_id)
        if detail.get("is_protected"):
            _require_confirmation(
                "skill.edit_protected",
                (
                    f"将编辑受保护方法论 {detail.get('name') or skill_id}。"
                    "保存会生成新版本并影响后续方法论创建指引。"
                ),
                extra_payload={"affectedSkillId": detail["skill_id"]},
            )
        result = service.user_edit_supersede(
            skill_id,
            {
                "name": body.name,
                "description": body.description,
                "trigger_conditions": body.trigger_conditions,
                "required_tools": body.required_tools,
                "body_markdown": body.body_markdown,
                "change_reason": body.change_reason,
            },
        )
        return service.get_detail(
            str(result.get("new_skill_id") or result.get("skill_id") or skill_id)
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
        detail = service.get_detail(skill_id)
        if detail.get("is_protected"):
            raise PermissionError("bootstrap_skill_not_softdeletable")
        affected_names = _active_equipment_names(service, detail["skill_id"])
        affected_preview = "、".join(name for name in affected_names if name)
        _require_confirmation(
            "skill.soft_delete",
            (
                f"将软删除方法论 {detail.get('name') or skill_id}，"
                f"并从 {len(affected_names)} 个装备者身上裁剪。"
                f"{'受影响装备者：' + affected_preview + '。' if affected_preview else ''}"
                "历史版本和审计记录会保留。"
            ),
            extra_payload={
                "affectedSkillId": detail["skill_id"],
                "affectedEquipmentCount": len(affected_names),
                "affectedSpecialistNames": affected_names,
            },
        )
        return service.force_soft_delete(skill_id)
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
