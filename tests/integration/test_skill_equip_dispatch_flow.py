from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.business.agents.config import AgentType
from src.business.brain.skill_equipment_service import SkillEquipmentService
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.business.orchestration.agent.tool_registry import ToolRegistry
from src.data.models_sqlite import BrainSpecialist
from src.data.repos.skill_repository import SkillRepository


def _specialist(in_memory_db, specialist_id: str = "sp-1") -> BrainSpecialist:
    with in_memory_db.get_session() as session:
        row = BrainSpecialist(
            specialist_id=specialist_id,
            name="测试专员",
            description="测试派活",
            role_definition="完成测试任务",
            tool_whitelist="[]",
            origin="user_management_ui",
            reason="test",
            is_active=True,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row


def _skill(in_memory_db, skill_id: str = "skill-1"):
    with in_memory_db.get_session() as session:
        return SkillRepository(session=session).create_skill(
            skill_id=skill_id,
            name="派活方法论",
            description="派活时注入清单",
            trigger_conditions=["派活测试时"],
            required_tools=[],
            body_markdown="SECRET_BODY_NOT_IN_PROMPT",
            origin="assistant_tool_call",
        )


def _build_delegated_tools(*, specialist_id, allowed_methodology_skill_ids=None):
    """构造 ToolRegistry + fake 依赖(依赖注入改造后无需 bare orchestrator)。"""
    registry = ToolRegistry(
        session_store=MagicMock(),
        dynamic_manager_cache=MagicMock(),
        delegation_orchestrator=MagicMock(),
        resolve_recording_mode=MagicMock(),
        redispatch_answered_task=MagicMock(),
    )
    kwargs: dict = {
        "agent_type": AgentType.SPECIALIST,
        "specialist_id": specialist_id,
    }
    if allowed_methodology_skill_ids is not None:
        kwargs["allowed_methodology_skill_ids"] = allowed_methodology_skill_ids
    return registry.build_delegated_executor_tools(None, **kwargs)()


def test_methodology_equipment_reaches_specialist_prompt_and_load_tool(in_memory_db) -> None:
    specialist = _specialist(in_memory_db)
    skill = _skill(in_memory_db)
    with in_memory_db.get_session() as session:
        SkillEquipmentService(session=session).equip(
            entity_id=specialist.specialist_id, skill_id=skill.skill_id
        )

    prompt = AgentOrchestrator._build_specialist_prompt(specialist, [])
    snapshot = AgentOrchestrator._extract_methodology_equipment_snapshot(prompt)

    assert "skill-1" in prompt
    assert "派活方法论" in snapshot
    assert "SECRET_BODY_NOT_IN_PROMPT" not in prompt

    tools = _build_delegated_tools(
        specialist_id=specialist.specialist_id,
        allowed_methodology_skill_ids={skill.skill_id},
    )
    load_tool = next(tool for tool in tools if tool.name == "load_skill_methodology")
    result = load_tool.handler(skill.skill_id)

    assert result.startswith("---\n")
    with in_memory_db.get_session() as session:
        loaded = SkillRepository(session=session).get_skill(skill.skill_id)
        assert loaded.loaded_count == 1


def test_equip_change_during_dispatch_does_not_interrupt_frozen_round(in_memory_db) -> None:
    specialist = _specialist(in_memory_db)
    skill = _skill(in_memory_db)
    with in_memory_db.get_session() as session:
        service = SkillEquipmentService(session=session)
        service.equip(entity_id=specialist.specialist_id, skill_id=skill.skill_id)

    prompt_before_change = AgentOrchestrator._build_specialist_prompt(specialist, [])
    frozen_tools = _build_delegated_tools(
        specialist_id=specialist.specialist_id,
        allowed_methodology_skill_ids={skill.skill_id},
    )
    frozen_load = next(tool for tool in frozen_tools if tool.name == "load_skill_methodology")

    with in_memory_db.get_session() as session:
        SkillEquipmentService(session=session).unequip(
            entity_id=specialist.specialist_id, skill_id=skill.skill_id
        )

    frozen_result = frozen_load.handler(skill.skill_id)
    live_tools_next_round = _build_delegated_tools(specialist_id=specialist.specialist_id)
    live_load = next(
        tool for tool in live_tools_next_round if tool.name == "load_skill_methodology"
    )
    live_result = json.loads(live_load.handler(skill.skill_id))

    assert "skill-1" in prompt_before_change
    assert frozen_result.startswith("---\n")
    assert live_result["error"] == "skill_not_in_equipment"
