from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_equipment_service import SkillEquipmentService
from src.business.brain.skill_service import SkillService
from src.data.models_sqlite import Base, BrainSkill, BrainSkillEquipment, BrainSpecialist
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _specialist(session, specialist_id: str = "sp-1") -> None:
    session.add(
        BrainSpecialist(
            specialist_id=specialist_id,
            name=f"专员 {specialist_id}",
            description="测试专员",
            role_definition="执行测试",
            tool_whitelist="[]",
            origin="user_management_ui",
            reason="test",
            is_active=True,
        )
    )
    session.commit()


def _skill(
    session, skill_id: str, *, chain_root_id: str | None = None, version: int = 1
) -> BrainSkill:
    return SkillRepository(session=session).create_skill(
        skill_id=skill_id,
        name=f"方法论 {skill_id}",
        description="测试方法论",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown="测试正文",
        origin="assistant_tool_call",
        chain_root_id=chain_root_id,
        version=version,
    )


def test_user_unequip_marks_equipment_row_without_delete() -> None:
    session = _session()
    _specialist(session)
    _skill(session, "skill-1")
    service = SkillEquipmentService(session=session)
    service.equip(entity_id="sp-1", skill_id="skill-1")

    service.unequip(entity_id="sp-1", skill_id="skill-1")

    rows = session.query(BrainSkillEquipment).all()
    assert len(rows) == 1
    assert rows[0].status == "unequipped"
    assert rows[0].unequipped_reason == "user_unequip"


def test_force_soft_delete_prunes_equipment_rows_without_delete() -> None:
    session = _session()
    _specialist(session)
    _skill(session, "skill-1")
    SkillEquipmentService(session=session).equip(entity_id="sp-1", skill_id="skill-1")

    result = SkillService(session=session).force_soft_delete("skill-1")

    assert result["pruned_equipment_count"] == 1
    rows = session.query(BrainSkillEquipment).all()
    assert len(rows) == 1
    assert rows[0].status == "unequipped"
    assert rows[0].unequipped_reason == "force_remove_on_soft_delete"
    assert session.get(BrainSkill, "skill-1").status == "soft_deleted"


def test_supersede_transfer_keeps_old_equipment_history_row() -> None:
    session = _session()
    _specialist(session)
    old_skill = _skill(session, "old")
    service = SkillEquipmentService(session=session)
    service.equip(entity_id="sp-1", skill_id=old_skill.skill_id)
    SkillRepository(session=session).mark_superseded(old_skill.skill_id, "new", commit=False)
    new_skill = _skill(session, "new", chain_root_id=old_skill.chain_root_id, version=2)

    service.supersede_equipment(old_skill_id=old_skill.skill_id, new_skill_id=new_skill.skill_id)

    rows = session.query(BrainSkillEquipment).order_by(BrainSkillEquipment.id.asc()).all()
    assert len(rows) == 3
    assert rows[0].skill_id == "old"
    assert rows[0].status == "unequipped"
    assert rows[0].unequipped_reason == "supersede_transfer"
    assert {(row.skill_id, row.status) for row in rows[1:]} == {("new", "active")}


def test_repository_soft_delete_keeps_skill_row() -> None:
    session = _session()
    _skill(session, "skill-1")

    SkillRepository(session=session).mark_soft_deleted("skill-1")

    retained = session.get(BrainSkill, "skill-1")
    assert retained is not None
    assert retained.status == "soft_deleted"


def test_api_soft_delete_keeps_skill_row(in_memory_db, monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from src.desktop_api.app import SESSION_HEADER, create_app

    token = "test-token"
    client = TestClient(create_app(token), headers={SESSION_HEADER: token})
    monkeypatch.setattr(
        "src.desktop_api.routers.skills_methodology.request_high_risk_confirmation",
        lambda *_args, **_kwargs: True,
    )
    with in_memory_db.get_session() as session:
        _skill(session, "skill-api")

    response = client.post("/api/skills/methodology/skill-api/soft-delete")

    assert response.status_code == 200
    with in_memory_db.get_session() as session:
        retained = session.get(BrainSkill, "skill-api")
        assert retained is not None
        assert retained.status == "soft_deleted"


@pytest.mark.parametrize(
    ("table_name", "error_token"),
    [
        ("brain_skills", "brain_skills_no_physical_delete"),
        ("brain_skill_equipment", "brain_skill_equipment_no_physical_delete"),
    ],
)
def test_direct_sql_delete_is_blocked_for_skill_tables(table_name: str, error_token: str) -> None:
    session = _session()
    _specialist(session)
    _skill(session, "skill-1")
    SkillEquipmentService(session=session).equip(entity_id="sp-1", skill_id="skill-1")

    with pytest.raises(IntegrityError, match=error_token):
        session.execute(text(f"DELETE FROM {table_name}"))
        session.commit()
