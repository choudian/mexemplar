"""
Agent tools for creating and loading methodology skills.
"""

from __future__ import annotations

import logging

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema, to_json
from src.business.brain.skill_reference_counter import SkillReferenceCounterService
from src.business.brain.skill_service import SkillService
from src.data.repos.skill_equipment_repository import ASSISTANT_ENTITY_ID, SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository, parse_json_list

logger = logging.getLogger(__name__)


CREATE_SKILL_METHODOLOGY_SCHEMA = make_tool_schema(
    name="create_skill_methodology",
    description="把一段已发生的工作流程提炼为可被装备的方法论资产。新建模式产出全新方法论；supersede 模式产出已有方法论的新版本。",
    properties={
        "mode": {
            "type": "string",
            "enum": ["create", "supersede"],
            "description": "create=新建；supersede=对已有方法论接力新版本",
        },
        "target_skill_id": {
            "type": "string",
            "description": "supersede 模式必填，要 supersede 的当前 active 方法论 id",
        },
        "name": {"type": "string", "description": "方法论名称"},
        "description": {"type": "string", "description": "一句话短描述"},
        "trigger_conditions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "触发条件 list，必须至少一条非空",
        },
        "required_tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "建议或需要的工具名 list",
        },
        "body_markdown": {"type": "string", "description": "方法论正文 Markdown"},
        "source_segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "source_zone": {"type": "string", "enum": ["archive", "failure"]},
                },
                "required": ["segment_id", "source_zone"],
            },
            "description": "素材来源 list，至少一条，且仅允许 archive/failure",
        },
        "change_reason": {"type": "string", "description": "本次产出的原因"},
    },
    required=[
        "mode",
        "name",
        "description",
        "trigger_conditions",
        "body_markdown",
        "source_segments",
        "change_reason",
    ],
)


LOAD_SKILL_METHODOLOGY_SCHEMA = make_tool_schema(
    name="load_skill_methodology",
    description="拉取你已装备的某条方法论完整正文（SKILL.md 形态）。先按 trigger_conditions 判断命中再 load，不要无差别加载全部清单。",
    properties={"skill_id": {"type": "string", "description": "要 load 的方法论 id"}},
    required=["skill_id"],
)


def create_create_skill_methodology_handler(
    *,
    caller_type: str = "assistant",
    caller_id: str = ASSISTANT_ENTITY_ID,
    tool_whitelist: list[str] | None = None,
):
    def handler(
        mode: str,
        name: str,
        description: str,
        trigger_conditions: list[str],
        body_markdown: str,
        source_segments: list[dict],
        change_reason: str,
        required_tools: list[str] | None = None,
        target_skill_id: str = "",
    ) -> str:
        if caller_type == "specialist" and "create_skill_methodology" not in (tool_whitelist or []):
            return to_json(
                {"success": False, "error": "unauthorized_tool_call", "message": "无权限创建方法论"}
            )
        clean_mode = (mode or "").strip()
        if clean_mode not in {"create", "supersede"}:
            return to_json(
                {
                    "success": False,
                    "error": "invalid_mode",
                    "message": "mode 必须是 create 或 supersede",
                }
            )
        if clean_mode == "supersede" and not str(target_skill_id or "").strip():
            return to_json(
                {
                    "success": False,
                    "error": "missing_target_skill_id",
                    "message": "supersede 模式需要 target_skill_id",
                }
            )

        try:
            service = SkillService()
            origin = "assistant_tool_call" if caller_type == "assistant" else "specialist_tool_call"
            if clean_mode == "create":
                result = service.create(
                    name=name,
                    description=description,
                    trigger_conditions=trigger_conditions,
                    required_tools=required_tools or [],
                    body_markdown=body_markdown,
                    source_segments=source_segments,
                    origin=origin,
                    caller_type=caller_type,
                    caller_id=caller_id,
                    change_reason=change_reason,
                )
            else:
                result = service.supersede(
                    target_skill_id=target_skill_id,
                    name=name,
                    description=description,
                    trigger_conditions=trigger_conditions,
                    required_tools=required_tools or [],
                    body_markdown=body_markdown,
                    source_segments=source_segments,
                    origin=origin,
                    caller_type=caller_type,
                    caller_id=caller_id,
                    change_reason=change_reason,
                )
            return to_json(result)
        except ValueError as exc:
            token = str(exc).split(":", 1)[0]
            return to_json({"success": False, "error": token, "message": str(exc)})
        except KeyError:
            return to_json(
                {"success": False, "error": "skill_not_found", "message": "未找到方法论"}
            )
        except Exception as exc:
            logger.exception("create_skill_methodology failed")
            return to_json({"success": False, "error": "skill_create_failed", "message": str(exc)})

    return handler


def create_load_skill_methodology_handler(
    *,
    caller_type: str = "assistant",
    caller_id: str = ASSISTANT_ENTITY_ID,
    session=None,
    allowed_skill_ids: set[str] | None = None,
):
    frozen_allowed = (
        {str(item) for item in allowed_skill_ids} if allowed_skill_ids is not None else None
    )

    def handler(skill_id: str) -> str:
        entity_type = "assistant" if caller_type == "assistant" else "specialist"
        entity_id = ASSISTANT_ENTITY_ID if entity_type == "assistant" else caller_id
        try:
            if frozen_allowed is None:
                equipment_repo = SkillEquipmentRepository(session=session)
                row = equipment_repo.get_active_equipment(entity_type, entity_id, skill_id)
                if row is None:
                    return to_json(
                        {
                            "success": False,
                            "error": "skill_not_in_equipment",
                            "message": "该方法论不在当前装备清单内",
                        }
                    )
                skill_repo = SkillRepository(session=equipment_repo.session)
            else:
                if skill_id not in frozen_allowed:
                    return to_json(
                        {
                            "success": False,
                            "error": "skill_not_in_equipment",
                            "message": "该方法论不在当前装备清单内",
                        }
                    )
                skill_repo = SkillRepository(session=session)
            skill = skill_repo.get_skill(skill_id)
            if skill is None or skill.status != "active":
                return to_json(
                    {
                        "success": False,
                        "error": "skill_not_active",
                        "message": "该方法论不是 active 状态",
                    }
                )
            SkillReferenceCounterService(repo=skill_repo).increment_loaded_count(skill.skill_id)
            return _render_skill_md(skill)
        except Exception as exc:
            logger.exception("load_skill_methodology failed")
            return to_json({"success": False, "error": "skill_load_failed", "message": str(exc)})

    return handler


def _render_skill_md(skill) -> str:
    triggers = parse_json_list(skill.trigger_conditions)
    required_tools = parse_json_list(skill.required_tools)
    trigger_block = "\n".join(f"  - {item}" for item in triggers)
    tools_block = "\n".join(f"  - {item}" for item in required_tools) if required_tools else "  []"
    return (
        "---\n"
        f"name: {skill.name}\n"
        f"description: {skill.description}\n"
        "when_to_use: |\n"
        f"{trigger_block}\n"
        "allowed-tools:\n"
        f"{tools_block}\n"
        "---\n\n"
        f"# {skill.name}\n\n"
        f"{skill.body_markdown}"
    )


CREATE_SKILL_METHODOLOGY = ToolDefinition(
    name="create_skill_methodology",
    schema=CREATE_SKILL_METHODOLOGY_SCHEMA,
    handler=create_create_skill_methodology_handler(),
)

LOAD_SKILL_METHODOLOGY = ToolDefinition(
    name="load_skill_methodology",
    schema=LOAD_SKILL_METHODOLOGY_SCHEMA,
    handler=create_load_skill_methodology_handler(),
    has_side_effects=False,
)
