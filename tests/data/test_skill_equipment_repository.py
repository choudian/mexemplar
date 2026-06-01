from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.data.models_sqlite import Base, BrainSkillEquipment
from src.data.repos.skill_equipment_repository import SkillEquipmentRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_active_unique_partial_index_rejects_duplicate_active_rows() -> None:
    session = _session()
    session.add_all(
        [
            BrainSkillEquipment(
                equipped_entity_type="specialist",
                equipped_entity_id="sp-1",
                skill_id="skill-1",
                status="active",
            ),
            BrainSkillEquipment(
                equipped_entity_type="specialist",
                equipped_entity_id="sp-1",
                skill_id="skill-1",
                status="active",
            ),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_unequip_keeps_history_and_allows_later_reequip() -> None:
    session = _session()
    repo = SkillEquipmentRepository(session=session)

    first = repo.equip(
        entity_type="specialist",
        entity_id="sp-1",
        skill_id="skill-1",
    )
    assert repo.unequip(first, reason="user_unequip") is True
    second = repo.equip(
        entity_type="specialist",
        entity_id="sp-1",
        skill_id="skill-1",
    )

    rows = repo.list_history_for_entity("specialist", "sp-1")
    assert len(rows) == 2
    assert {row.status for row in rows} == {"active", "unequipped"}
    assert second.id != first.id


def test_bidirectional_active_and_history_queries() -> None:
    session = _session()
    repo = SkillEquipmentRepository(session=session)
    repo.equip(
        entity_type="assistant", entity_id="_assistant", skill_id="skill-1", equipped_order=1
    )
    specialist_row = repo.equip(
        entity_type="specialist",
        entity_id="sp-1",
        skill_id="skill-1",
        equipped_order=2,
    )
    repo.equip(entity_type="specialist", entity_id="sp-1", skill_id="skill-2", equipped_order=0)
    repo.unequip(specialist_row, reason="force_remove_on_soft_delete")

    entity_active = repo.list_active_for_entity("specialist", "sp-1")
    skill_active = repo.list_active_for_skill("skill-1")
    skill_history = repo.list_history_for_skill("skill-1")

    assert [row.skill_id for row in entity_active] == ["skill-2"]
    assert [(row.equipped_entity_type, row.equipped_entity_id) for row in skill_active] == [
        ("assistant", "_assistant")
    ]
    assert {(row.status, row.unequipped_reason) for row in skill_history} == {
        ("active", None),
        ("unequipped", "force_remove_on_soft_delete"),
    }


@pytest.mark.parametrize(
    ("status", "unequipped_reason"),
    [("active", "user_unequip"), ("unequipped", None)],
)
def test_status_and_unequipped_fields_must_change_together(
    status: str,
    unequipped_reason: str | None,
) -> None:
    session = _session()
    session.add(
        BrainSkillEquipment(
            equipped_entity_type="specialist",
            equipped_entity_id="sp-1",
            skill_id="skill-1",
            status=status,
            unequipped_reason=unequipped_reason,
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
