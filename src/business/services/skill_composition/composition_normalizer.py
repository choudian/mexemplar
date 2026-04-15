"""Pure helpers for skill composition validation and model mapping."""

import uuid
from typing import List, Sequence

from src.data.models import (
    SkillComposition,
    SkillCompositionMember,
    Tool,
    sort_composition_members,
)

from .types import SkillCompositionError


VALID_MODES = {"range", "ordered"}
VALID_STATUSES = {"draft", "published", "offline"}


def normalize_members(mode: str, members: List[dict], tool_repo) -> List[dict]:
    mode = (mode or "").strip()
    if mode not in VALID_MODES:
        raise SkillCompositionError("技能组合模式无效")
    if not members:
        raise SkillCompositionError("技能组合至少要包含一个技能")

    normalized = []
    seen_tool_ids = set()
    for index, member in enumerate(members, start=1):
        tool_id = str(member.get("tool_id") or "").strip()
        if not tool_id:
            raise SkillCompositionError("技能组合成员缺少技能 ID")
        if tool_id in seen_tool_ids:
            raise SkillCompositionError("同一个技能在同一组合中只能出现一次")
        seen_tool_ids.add(tool_id)
        normalized.append(
            {
                "tool_id": tool_id,
                "selected_order": int(member.get("selected_order") or index),
                "execution_order": (
                    int(member.get("execution_order") or index)
                    if mode == "ordered"
                    else None
                ),
            }
        )

    tool_map = {tool.tool_id: tool for tool in tool_repo.get_by_ids(list(seen_tool_ids))}
    missing = [tool_id for tool_id in seen_tool_ids if tool_id not in tool_map]
    if missing:
        raise SkillCompositionError(f"技能不存在：{', '.join(missing)}")

    unpublished = [tool.tool_name for tool in tool_map.values() if tool.status != "published"]
    if unpublished:
        raise SkillCompositionError("只能将已掌握技能加入技能组合")

    if mode == "ordered":
        execution_orders = [member["execution_order"] for member in normalized]
        if sorted(execution_orders) != list(range(1, len(normalized) + 1)):
            raise SkillCompositionError("顺序型技能组合的执行顺序必须连续且唯一")

    return sorted(normalized, key=lambda item: item["selected_order"])


def build_composition_orm(
    *,
    composition_id: str,
    composition_name: str,
    description: str,
    applicability: str,
    mode: str,
    status: str,
    assistant_enabled: bool,
    recommend_order: bool,
    needs_review: bool,
    composition_repo,
):
    composition_name = (composition_name or "").strip()
    applicability = (applicability or "").strip()
    if not composition_name:
        raise SkillCompositionError("技能组合名称不能为空")
    if not applicability:
        raise SkillCompositionError("适用场景不能为空")
    if mode not in VALID_MODES:
        raise SkillCompositionError("技能组合模式无效")
    if status not in VALID_STATUSES:
        raise SkillCompositionError("技能组合状态无效")
    if composition_repo.has_name_conflict(
        composition_name,
        exclude_composition_id=composition_id,
    ):
        raise SkillCompositionError("技能组合名称已存在")

    from src.data.models_sqlite import SkillComposition as SkillCompositionORM

    return SkillCompositionORM(
        composition_id=composition_id,
        composition_name=composition_name,
        description=(description or "").strip() or None,
        applicability=applicability,
        mode=mode,
        status=status,
        assistant_enabled=assistant_enabled,
        recommend_order=recommend_order,
        needs_review=needs_review,
    )


def build_member_orms(composition_id: str, members: Sequence[dict]):
    from src.data.models_sqlite import SkillCompositionMember as SkillCompositionMemberORM

    return [
        SkillCompositionMemberORM(
            member_id=f"cm_{uuid.uuid4().hex[:12]}",
            composition_id=composition_id,
            tool_id=member["tool_id"],
            selected_order=member["selected_order"],
            execution_order=member["execution_order"],
        )
        for member in members
    ]


def to_tool_model(tool) -> Tool:
    return Tool(
        tool_id=tool.tool_id,
        tool_name=tool.tool_name,
        description=tool.description,
        parameters=tool.parameters or [],
        steps=tool.steps or [],
        execution_code=tool.execution_code,
        code_language=tool.code_language,
        code_version=tool.code_version,
        execution_strategy=tool.execution_strategy,
        dependencies=tool.dependencies or [],
        source_intent_id=tool.source_intent_id,
        source=tool.source,
        trial_count=tool.trial_count,
        pending_tool_id=tool.pending_tool_id,
        workflow_id=tool.workflow_id,
        trial_success_count=tool.trial_success_count,
        status=tool.status,
        created_at=tool.created_at,
        updated_at=tool.updated_at,
    )


def to_composition_model(composition, members_orm, tool_repo) -> SkillComposition:
    tool_ids = [member.tool_id for member in members_orm]
    tool_map = {
        tool.tool_id: to_tool_model(tool)
        for tool in tool_repo.get_by_ids(tool_ids)
    }
    member_models = [
        SkillCompositionMember(
            member_id=member.member_id,
            composition_id=member.composition_id,
            tool_id=member.tool_id,
            selected_order=member.selected_order or 0,
            execution_order=member.execution_order,
            tool=tool_map.get(member.tool_id),
            created_at=member.created_at,
        )
        for member in members_orm
    ]
    member_models = sort_composition_members(member_models, composition.mode)

    return SkillComposition(
        composition_id=composition.composition_id,
        composition_name=composition.composition_name,
        description=composition.description,
        applicability=composition.applicability,
        mode=composition.mode,
        status=composition.status,
        assistant_enabled=bool(composition.assistant_enabled),
        recommend_order=bool(composition.recommend_order),
        needs_review=bool(composition.needs_review),
        members=member_models,
        created_at=composition.created_at,
        updated_at=composition.updated_at,
    )


def member_to_payload(member) -> dict:
    return {
        "tool_id": member.tool_id,
        "selected_order": member.selected_order,
        "execution_order": member.execution_order,
    }
