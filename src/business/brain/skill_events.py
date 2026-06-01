"""Shared event emitters for methodology skill services."""

from __future__ import annotations

from src.data.repos.skill_equipment_repository import ASSISTANT_ENTITY_ID
from src.utils.events import emit


def emit_skill_equipment_changed(
    *,
    change_type: str,
    entity_id: str,
    skill_id: str,
    entity_type: str | None = None,
    unequipped_reason: str | None = None,
) -> None:
    emit(
        "brain_skill_equipment_changed",
        change_type=change_type,
        entity_type=entity_type
        or ("assistant" if entity_id == ASSISTANT_ENTITY_ID else "specialist"),
        entity_id=entity_id,
        skill_id=skill_id,
        unequipped_reason=unequipped_reason,
    )
