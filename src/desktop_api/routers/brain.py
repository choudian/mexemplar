"""
大脑管理 API 路由
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Response
from src.business.brain.management_service import BrainManagementService
from src.business.brain.specialist_service import SpecialistService

router = APIRouter(prefix="/api/brain", tags=["brain"])
logger = logging.getLogger(__name__)


@router.get("/zones")
async def get_zones():
    """返回 6 个分区的汇总信息"""
    return {"zones": BrainManagementService().get_zones()}


@router.get("/zones/{zone}/entries")
async def get_zone_entries(
    zone: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None),
):
    """列出指定分区的条目（分页）"""
    try:
        items, total = BrainManagementService().get_zone_entries(
            zone,
            status=status,
            limit=limit,
            offset=offset,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": "invalid_zone"})
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/segments")
async def get_segments(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str = Query(default="all"),
):
    """列出 Segments"""
    items, total = BrainManagementService().get_segments(
        status=status,
        limit=limit,
        offset=offset,
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/segments/{segment_id}/retry")
async def retry_segment(segment_id: str):
    """手动触发失败 Segment 的重试"""
    try:
        return BrainManagementService().retry_segment(segment_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    except ValueError:
        raise HTTPException(status_code=409, detail={"error": "segment_not_failed"})
    except RuntimeError:
        raise HTTPException(status_code=409, detail={"error": "transition_failed"})


@router.get("/entries/{entry_id}/evolution")
async def get_entry_evolution(entry_id: str):
    """获取条目的演化链"""
    try:
        return {"chain": BrainManagementService().get_entry_evolution(entry_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "not_found"})


@router.put("/entries/{entry_id}")
async def edit_entry(entry_id: str, body: dict):
    """用户编辑条目"""
    content = body.get("content", "")
    if not content or not content.strip():
        raise HTTPException(status_code=422, detail={"error": "content must not be empty"})
    try:
        return BrainManagementService().edit_entry(
            entry_id,
            content=content.strip(),
            scope=body.get("scope"),
        )
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    except ValueError:
        raise HTTPException(status_code=422, detail={"error": "validation_error"})
    except RuntimeError:
        raise HTTPException(status_code=500, detail={"error": "internal_error"})


@router.delete("/entries/{entry_id}", status_code=204)
async def delete_entry(entry_id: str):
    """用户软删除条目"""
    try:
        BrainManagementService().soft_delete_entry(entry_id)
    except KeyError:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return Response(status_code=204)


# ═══════════════════════════════════════════════
# Specialist CRUD (T077)
# ═══════════════════════════════════════════════


@router.post("/specialists")
async def create_specialist(body: dict):
    """创建新专员"""
    name = body.get("name", "")
    description = body.get("description", "")
    role_definition = body.get("role_definition", "")
    tool_whitelist_raw = body.get("tool_whitelist", [])
    tool_whitelist = [str(item) for item in tool_whitelist_raw if isinstance(item, str) and item.strip()]

    if not name or not description or not role_definition:
        raise HTTPException(status_code=422, detail={"error": "validation_error"})

    try:
        service = SpecialistService()
        specialist = service.create_specialist(
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=tool_whitelist,
            origin="user_management_ui",
            reason="通过管理界面创建",
        )
        return specialist
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"error": str(e)})


@router.get("/specialists")
async def list_specialists(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    active_only: bool = Query(default=True),
):
    """列出专员"""
    service = SpecialistService()
    specialists, total = service.list_specialists(
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return {
        "items": specialists,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/specialists/{specialist_id}")
async def get_specialist(specialist_id: str):
    """查询单个专员"""
    service = SpecialistService()
    specialist = service.get_specialist(specialist_id)
    if specialist is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return specialist


@router.put("/specialists/{specialist_id}")
async def update_specialist(specialist_id: str, body: dict):
    """更新专员"""
    try:
        service = SpecialistService()
        specialist = service.update_specialist(
            specialist_id=specialist_id,
            name=body.get("name"),
            description=body.get("description"),
            role_definition=body.get("role_definition"),
            tool_whitelist=body.get("tool_whitelist"),
            changed_by="user_management_ui",
            change_reason=body.get("change_reason", "通过管理界面更新"),
        )
        return specialist
    except ValueError as e:
        if "不存在" in str(e):
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        raise HTTPException(status_code=409, detail={"error": str(e)})


@router.delete("/specialists/{specialist_id}", status_code=204)
async def delete_specialist(specialist_id: str):
    """删除专员"""
    service = SpecialistService()
    success = service.delete_specialist(specialist_id)
    if not success:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return Response(status_code=204)


@router.get("/specialists/{specialist_id}/versions")
async def get_specialist_versions(
    specialist_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """获取专员的版本历史"""
    service = SpecialistService()
    specialist = service.get_specialist(specialist_id)
    if specialist is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})

    versions = service.get_version_history(
        specialist_id=specialist_id,
        limit=limit,
        offset=offset,
    )
    return {"items": versions}


# ═══════════════════════════════════════════════
# Skill Pool (T116)
# ═══════════════════════════════════════════════


@router.get("/skill-pool")
async def get_skill_pool():
    """返回当前 assistant 可用的全部技能（专员白名单超集）"""
    try:
        return {"skills": SpecialistService().list_skill_pool()}
    except ImportError:
        return {"skills": []}
    except Exception as e:
        logger.error("Failed to list skill pool: %s", e)
        raise HTTPException(status_code=500, detail={"error": "internal_error"})


@router.delete("/skill-pool/{tool_id}", status_code=204)
async def remove_skill_from_pool(tool_id: str, force: bool = Query(default=False)):
    """
    从技能池移除工具。

    如果有专员白名单引用该工具且 force=false，返回 409。
    如果 force=true，自动裁剪所有专员白名单后删除。
    """
    service = SpecialistService()
    result = service.remove_skill_from_pool(tool_id, force=force)
    if not result.get("removed"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "skill_in_use",
                "affected_specialists": [
                    {"specialist_id": s["specialist_id"], "name": s["name"]}
                    for s in result.get("affected_specialists", [])
                ],
            },
        )
    return Response(status_code=204)
