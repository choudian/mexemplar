from __future__ import annotations

import logging
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_equipment_service import SkillEquipmentService
from src.data.models_sqlite import Base, BrainSkill, BrainSkillEquipment, BrainSpecialist
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _specialist(session, specialist_id: str) -> BrainSpecialist:
    row = BrainSpecialist(
        specialist_id=specialist_id,
        name=f"专员 {specialist_id}",
        description="测试专员",
        role_definition="执行测试任务",
        tool_whitelist="[]",
        origin="user_management_ui",
        reason="test",
        is_active=True,
    )
    session.add(row)
    session.commit()
    return row


def _skill(
    session,
    skill_id: str,
    *,
    origin: str = "assistant_tool_call",
    status: str = "active",
    chain_root_id: str | None = None,
    parent_skill_id: str | None = None,
    version: int = 1,
) -> BrainSkill:
    skill = SkillRepository(session=session).create_skill(
        skill_id=skill_id,
        name=f"方法论 {skill_id}",
        description="测试方法论",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown=f"# {skill_id}\n\n测试正文",
        origin=origin,
        parent_skill_id=parent_skill_id,
        chain_root_id=chain_root_id,
        version=version,
        commit=False,
    )
    skill.status = status
    if status == "superseded":
        skill.superseded_by = f"{skill_id}-successor"
    session.commit()
    return skill


def _active_skill_ids(session, entity_type: str, entity_id: str) -> list[str]:
    return [
        row.skill_id
        for row in session.query(BrainSkillEquipment)
        .filter(
            BrainSkillEquipment.equipped_entity_type == entity_type,
            BrainSkillEquipment.equipped_entity_id == entity_id,
            BrainSkillEquipment.status == "active",
        )
        .order_by(BrainSkillEquipment.equipped_order.asc(), BrainSkillEquipment.id.asc())
        .all()
    ]


def test_equip_unequip_and_reorder_leave_history() -> None:
    session = _session()
    _specialist(session, "sp-1")
    _skill(session, "skill-1")
    _skill(session, "skill-2")
    service = SkillEquipmentService(session=session)

    service.equip(entity_id="sp-1", skill_id="skill-1", equipped_order=5)
    service.equip(entity_id="sp-1", skill_id="skill-2", equipped_order=6)
    result = service.reorder_equipment_for_entity(
        "sp-1",
        [
            {"skill_id": "skill-2", "equipped_order": 0},
            {"skill_id": "skill-1", "equipped_order": 1},
        ],
    )

    assert result["reordered"] == ["skill-1", "skill-2"]
    assert _active_skill_ids(session, "specialist", "sp-1") == ["skill-2", "skill-1"]

    assert service.unequip(entity_id="sp-1", skill_id="skill-1") is True
    service.equip(entity_id="sp-1", skill_id="skill-1")

    rows = (
        session.query(BrainSkillEquipment)
        .filter(
            BrainSkillEquipment.equipped_entity_type == "specialist",
            BrainSkillEquipment.equipped_entity_id == "sp-1",
            BrainSkillEquipment.skill_id == "skill-1",
        )
        .order_by(BrainSkillEquipment.id.asc())
        .all()
    )
    assert [row.status for row in rows] == ["unequipped", "active"]
    assert rows[0].unequipped_reason == "user_unequip"


def test_default_equip_all_skips_system_bootstrap_for_new_specialist() -> None:
    session = _session()
    _specialist(session, "sp-1")
    _skill(session, "bootstrap", origin="system_bootstrap")
    _skill(session, "normal")

    equipped = SkillEquipmentService(session=session).default_equip_all("sp-1")

    assert equipped == ["normal"]
    assert _active_skill_ids(session, "specialist", "sp-1") == ["normal"]


def test_default_equip_active_skill_system_bootstrap_targets_assistant_only() -> None:
    session = _session()
    _specialist(session, "sp-1")
    _skill(session, "bootstrap", origin="system_bootstrap")

    equipped_to = SkillEquipmentService(session=session).default_equip_active_skill("bootstrap")

    assert equipped_to == ["_assistant"]
    assert _active_skill_ids(session, "assistant", "_assistant") == ["bootstrap"]
    assert _active_skill_ids(session, "specialist", "sp-1") == []


def test_default_equip_active_skill_respects_prior_user_unequip() -> None:
    session = _session()
    _specialist(session, "sp-1")
    _skill(session, "normal")
    service = SkillEquipmentService(session=session)
    service.default_equip_active_skill("normal")
    service.unequip(entity_id="sp-1", skill_id="normal")

    equipped_to = service.default_equip_active_skill("normal")

    assert equipped_to == []
    assert _active_skill_ids(session, "specialist", "sp-1") == []
    rows = (
        session.query(BrainSkillEquipment)
        .filter(
            BrainSkillEquipment.equipped_entity_type == "specialist",
            BrainSkillEquipment.equipped_entity_id == "sp-1",
            BrainSkillEquipment.skill_id == "normal",
        )
        .all()
    )
    assert [(row.status, row.unequipped_reason) for row in rows] == [("unequipped", "user_unequip")]


def test_supersede_transfers_active_equipment_and_respects_user_unequip() -> None:
    session = _session()
    _specialist(session, "sp-1")
    _specialist(session, "sp-2")
    old_skill = _skill(session, "old")
    service = SkillEquipmentService(session=session)
    service.default_equip_active_skill(old_skill.skill_id)
    service.unequip(entity_id="sp-2", skill_id=old_skill.skill_id)
    SkillRepository(session=session).mark_superseded(old_skill.skill_id, "new", commit=False)
    new_skill = _skill(
        session,
        "new",
        chain_root_id=old_skill.chain_root_id,
        parent_skill_id=old_skill.skill_id,
        version=2,
    )

    result = service.supersede_equipment(
        old_skill_id=old_skill.skill_id, new_skill_id=new_skill.skill_id
    )

    assert len(result["transferred"]) == 2
    assert _active_skill_ids(session, "assistant", "_assistant") == ["new"]
    assert _active_skill_ids(session, "specialist", "sp-1") == ["new"]
    assert _active_skill_ids(session, "specialist", "sp-2") == []
    old_reasons = {
        (row.equipped_entity_type, row.equipped_entity_id): row.unequipped_reason
        for row in session.query(BrainSkillEquipment)
        .filter(BrainSkillEquipment.skill_id == "old")
        .all()
    }
    assert old_reasons[("assistant", "_assistant")] == "supersede_transfer"
    assert old_reasons[("specialist", "sp-1")] == "supersede_transfer"
    assert old_reasons[("specialist", "sp-2")] == "user_unequip"


def test_supersede_keeps_manually_equipped_system_bootstrap_specialist() -> None:
    session = _session()
    _specialist(session, "sp-1")
    old_skill = _skill(session, "bootstrap", origin="system_bootstrap")
    service = SkillEquipmentService(session=session)
    service.default_equip_active_skill(old_skill.skill_id)
    service.equip(entity_id="sp-1", skill_id=old_skill.skill_id)
    SkillRepository(session=session).mark_superseded(
        old_skill.skill_id, "bootstrap-v2", commit=False
    )
    new_skill = _skill(
        session,
        "bootstrap-v2",
        origin="user_edit",
        chain_root_id=old_skill.chain_root_id,
        parent_skill_id=old_skill.skill_id,
        version=2,
    )

    service.supersede_equipment(old_skill_id=old_skill.skill_id, new_skill_id=new_skill.skill_id)

    assert _active_skill_ids(session, "assistant", "_assistant") == ["bootstrap-v2"]
    assert _active_skill_ids(session, "specialist", "sp-1") == ["bootstrap-v2"]


@pytest.mark.parametrize("status", ["superseded", "soft_deleted"])
def test_equip_rejects_non_active_skill(status: str) -> None:
    session = _session()
    _specialist(session, "sp-1")
    _skill(session, f"skill-{status}", status=status)

    with pytest.raises(ValueError, match="skill_equipment_skill_not_active"):
        SkillEquipmentService(session=session).equip(
            entity_id="sp-1",
            skill_id=f"skill-{status}",
        )

    assert session.query(BrainSkillEquipment).count() == 0


def test_equipment_write_failure_is_logged(caplog) -> None:
    session = _session()
    _specialist(session, "sp-1")
    _skill(session, "skill-1")
    service = SkillEquipmentService(session=session)

    def fail_equip(**_kwargs):
        raise RuntimeError("equipment write failed")

    service._equipment_repo.equip = fail_equip

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="equipment write failed"):
            service.equip(entity_id="sp-1", skill_id="skill-1")

    assert "装备方法论失败" in caplog.text
