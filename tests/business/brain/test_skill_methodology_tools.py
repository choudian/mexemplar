from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.agents.tools.skill_methodology_tools import create_load_skill_methodology_handler
from src.data.models_sqlite import Base, BrainSpecialist
from src.data.repos.skill_equipment_repository import SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_load_for_specialist_and_assistant() -> None:
    session = _session()
    session.add(
        BrainSpecialist(
            specialist_id="sp-1",
            name="测试专员",
            description="测试",
            role_definition="执行测试",
            tool_whitelist="[]",
            origin="user_management_ui",
            reason="test",
            is_active=True,
        )
    )
    skill = SkillRepository(session=session).create_skill(
        skill_id="skill-1",
        name="测试方法论",
        description="用于测试 load",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown="按步骤完成测试。",
        origin="assistant_tool_call",
    )
    equipment_repo = SkillEquipmentRepository(session=session)
    equipment_repo.equip(entity_type="assistant", entity_id="_assistant", skill_id=skill.skill_id)
    equipment_repo.equip(entity_type="specialist", entity_id="sp-1", skill_id=skill.skill_id)

    assistant_load = create_load_skill_methodology_handler(
        caller_type="assistant",
        caller_id="_assistant",
        session=session,
    )
    specialist_load = create_load_skill_methodology_handler(
        caller_type="specialist",
        caller_id="sp-1",
        session=session,
    )
    outsider_load = create_load_skill_methodology_handler(
        caller_type="specialist",
        caller_id="sp-2",
        session=session,
    )

    assistant_result = assistant_load(skill.skill_id)
    specialist_result = specialist_load(skill.skill_id)
    outsider_result = json.loads(outsider_load(skill.skill_id))

    assert assistant_result.startswith("---\n")
    assert specialist_result.startswith("---\n")
    assert "按步骤完成测试。" in assistant_result
    assert "按步骤完成测试。" in specialist_result
    assert outsider_result["error"] == "skill_not_in_equipment"
    session.refresh(skill)
    assert skill.loaded_count == 2
