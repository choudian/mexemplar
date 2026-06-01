from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.agents.tools.skill_methodology_tools import create_load_skill_methodology_handler
from src.data.models_sqlite import Base
from src.data.repos.skill_equipment_repository import SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_load_skill_methodology_has_no_same_turn_call_limit() -> None:
    session = _session()
    repo = SkillRepository(session=session)
    skills = []
    for index in range(5):
        skill = repo.create_skill(
            skill_id=f"skill-{index}",
            name=f"测试方法论 {index}",
            description="测试 load 次数",
            trigger_conditions=["需要测试时"],
            required_tools=[],
            body_markdown="完整正文",
            origin="assistant_tool_call",
        )
        SkillEquipmentRepository(session=session).equip(
            entity_type="assistant",
            entity_id="_assistant",
            skill_id=skill.skill_id,
        )
        skills.append(skill)
    handler = create_load_skill_methodology_handler(
        caller_type="assistant",
        caller_id="_assistant",
        session=session,
    )

    results = [handler(skill.skill_id) for skill in skills]

    assert all(result.startswith("---\n") for result in results)
    for skill in skills:
        session.refresh(skill)
        assert skill.loaded_count == 1
