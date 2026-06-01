from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.agents.tools.skill_methodology_tools import create_load_skill_methodology_handler
from src.business.brain.skill_service import SkillService
from src.data.models_sqlite import Base
from src.data.repos.skill_equipment_repository import SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _skill(session, skill_id: str = "skill-1"):
    return SkillRepository(session=session).create_skill(
        skill_id=skill_id,
        name=f"方法论 {skill_id}",
        description="测试",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown="正文",
        origin="assistant_tool_call",
    )


def test_successful_load_tool_increments_loaded_count() -> None:
    session = _session()
    skill = _skill(session)
    SkillEquipmentRepository(session=session).equip(
        entity_type="assistant",
        entity_id="_assistant",
        skill_id=skill.skill_id,
    )
    handler = create_load_skill_methodology_handler(
        caller_type="assistant",
        caller_id="_assistant",
        session=session,
    )

    result = handler(skill.skill_id)

    assert result.startswith("---\n")
    session.refresh(skill)
    assert skill.loaded_count == 1


def test_failed_load_tool_does_not_increment_loaded_count() -> None:
    session = _session()
    skill = _skill(session)
    handler = create_load_skill_methodology_handler(
        caller_type="assistant",
        caller_id="_assistant",
        session=session,
    )

    result = json.loads(handler(skill.skill_id))

    assert result["error"] == "skill_not_in_equipment"
    session.refresh(skill)
    assert skill.loaded_count == 0


def test_human_detail_view_does_not_increment_loaded_count() -> None:
    session = _session()
    skill = _skill(session)

    detail = SkillService(session=session).get_detail(skill.skill_id)

    assert detail["skill_id"] == skill.skill_id
    session.refresh(skill)
    assert skill.loaded_count == 0
