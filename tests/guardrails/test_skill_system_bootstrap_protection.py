from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_bootstrap_service import SkillBootstrapService
from src.business.brain.skill_equipment_service import SkillEquipmentService
from src.data.models_sqlite import Base, BrainSkill, BrainSkillEquipment, BrainSpecialist
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_bootstrap_initial_equipment_skips_specialists(tmp_path):
    session = _session()
    session.add(
        BrainSpecialist(
            specialist_id="spec_existing",
            name="报表专员",
            description="处理报表",
            role_definition="负责报表整理",
            tool_whitelist="[]",
            origin="manual",
            reason="test",
            is_active=True,
        )
    )
    session.commit()

    SkillBootstrapService(
        session=session, seed_file_path=str(tmp_path / "missing.md")
    ).bootstrap_missing_skill(
        session=session,
        use_unified_config=False,
    )

    rows = session.query(BrainSkillEquipment).all()
    assert [(row.equipped_entity_type, row.equipped_entity_id) for row in rows] == [
        ("assistant", "_assistant")
    ]


def _skill(
    session,
    skill_id: str,
    *,
    origin: str,
    chain_root_id: str | None = None,
    parent_skill_id: str | None = None,
    version: int = 1,
) -> BrainSkill:
    return SkillRepository(session=session).create_skill(
        skill_id=skill_id,
        name=f"方法论 {skill_id}",
        description="测试方法论",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown="测试正文",
        origin=origin,
        chain_root_id=chain_root_id,
        parent_skill_id=parent_skill_id,
        version=version,
    )


def test_system_bootstrap_chain_default_propagation_uses_chain_root_origin():
    session = _session()
    session.add(
        BrainSpecialist(
            specialist_id="spec_existing",
            name="报表专员",
            description="处理报表",
            role_definition="负责报表整理",
            tool_whitelist="[]",
            origin="manual",
            reason="test",
            is_active=True,
        )
    )
    session.commit()
    root = _skill(session, "bootstrap-root", origin="system_bootstrap")
    SkillRepository(session=session).mark_superseded(root.skill_id, "bootstrap-v2")
    v2 = _skill(
        session,
        "bootstrap-v2",
        origin="user_edit",
        chain_root_id=root.chain_root_id,
        parent_skill_id=root.skill_id,
        version=2,
    )

    equipped_to = SkillEquipmentService(session=session).default_equip_active_skill(v2.skill_id)

    assert equipped_to == ["_assistant"]
    rows = session.query(BrainSkillEquipment).all()
    assert [(row.equipped_entity_type, row.equipped_entity_id) for row in rows] == [
        ("assistant", "_assistant")
    ]


def test_manual_system_bootstrap_equipment_transfers_on_supersede():
    session = _session()
    session.add(
        BrainSpecialist(
            specialist_id="spec_existing",
            name="报表专员",
            description="处理报表",
            role_definition="负责报表整理",
            tool_whitelist="[]",
            origin="manual",
            reason="test",
            is_active=True,
        )
    )
    session.commit()
    root = _skill(session, "bootstrap-root", origin="system_bootstrap")
    service = SkillEquipmentService(session=session)
    service.equip(entity_id="spec_existing", skill_id=root.skill_id)
    SkillRepository(session=session).mark_superseded(root.skill_id, "bootstrap-v2", commit=False)
    v2 = _skill(
        session,
        "bootstrap-v2",
        origin="user_edit",
        chain_root_id=root.chain_root_id,
        parent_skill_id=root.skill_id,
        version=2,
    )

    service.supersede_equipment(old_skill_id=root.skill_id, new_skill_id=v2.skill_id)

    rows = session.query(BrainSkillEquipment).filter(BrainSkillEquipment.status == "active").all()
    assert {(row.equipped_entity_type, row.equipped_entity_id, row.skill_id) for row in rows} == {
        ("specialist", "spec_existing", "bootstrap-v2"),
        ("assistant", "_assistant", "bootstrap-v2"),
    }
