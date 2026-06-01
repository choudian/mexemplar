"""
SkillEquipmentService -- 方法论装备编排层。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from src.business.brain.skill_events import emit_skill_equipment_changed
from src.business.brain.specialist_service import parse_tool_whitelist
from src.data.repos.skill_equipment_repository import (
    ASSISTANT_ENTITY_ID,
    SkillEquipmentRepository,
)
from src.data.repos.skill_repository import SkillRepository, parse_json_list
from src.data.repos.specialist_repository import SpecialistRepository
from src.data.unified_config import get_unified_config

if TYPE_CHECKING:
    from src.data.models_sqlite import BrainSkill, BrainSkillEquipment

logger = logging.getLogger(__name__)


class SkillEquipmentService:
    """Manage methodology skill equipment for assistant and specialists."""

    def __init__(
        self,
        *,
        session: Session | None = None,
        skill_repo: SkillRepository | None = None,
        equipment_repo: SkillEquipmentRepository | None = None,
    ) -> None:
        self._skill_repo = skill_repo or SkillRepository(session=session)
        self._equipment_repo = equipment_repo or SkillEquipmentRepository(
            session=self._skill_repo.session
        )
        self._specialist_repo = SpecialistRepository(session=self._skill_repo.session)
        self._session = self._skill_repo.session

    def get_equipment_for_entity(self, entity_id: str) -> dict[str, Any]:
        """Return active methodology equipment and token-budget data for one entity."""
        entity_type, entity_id = self._normalize_entity(entity_id=entity_id)
        whitelist: list[str] = []
        entity_name = "Assistant 本体"
        if entity_type == "specialist":
            specialist = self._specialist_repo.get_specialist(entity_id)
            if specialist is None or not getattr(specialist, "is_active", False):
                raise KeyError("specialist_not_found")
            whitelist = parse_tool_whitelist(specialist.tool_whitelist)
            entity_name = specialist.name

        items = []
        for row, skill in self._equipment_repo.list_active_skills_for_entity(
            entity_type, entity_id
        ):
            required_tools = parse_json_list(skill.required_tools)
            missing = (
                []
                if entity_type == "assistant"
                else [t for t in required_tools if t not in whitelist]
            )
            items.append(
                {
                    "skill_id": skill.skill_id,
                    "chain_root_id": skill.chain_root_id,
                    "name": skill.name,
                    "description": skill.description,
                    "trigger_conditions": parse_json_list(skill.trigger_conditions),
                    "required_tools": required_tools,
                    "missing_required_tools": missing,
                    "equipped_order": row.equipped_order,
                    "equipped_at": row.equipped_at,
                }
            )
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "tool_whitelist": whitelist,
            "active_equipment": items,
            "token_budget_estimate": estimate_equipment_tokens(items),
            "token_budget_thresholds": self._thresholds(),
        }

    def equip(
        self,
        *,
        entity_id: str,
        skill_id: str,
        entity_type: str | None = None,
        equipped_order: int | None = None,
        commit: bool = True,
        emit_events: bool = True,
    ) -> BrainSkillEquipment:
        """Equip one active methodology skill for an entity."""
        entity_type, entity_id = self._normalize_entity(
            entity_id=entity_id, entity_type=entity_type
        )
        skill = self._require_active_skill(skill_id)
        order = (
            self._next_order_for_entity(entity_type, entity_id)
            if equipped_order is None
            else equipped_order
        )
        try:
            row = self._equipment_repo.equip(
                entity_type=entity_type,
                entity_id=entity_id,
                skill_id=skill.skill_id,
                equipped_order=order,
                commit=False,
            )
            if commit:
                self._session.commit()
            if emit_events and commit:
                emit_skill_equipment_changed(
                    change_type="equipped",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=skill.skill_id,
                )
            return row
        except Exception as exc:
            if commit:
                self._session.rollback()
            logger.error(
                "装备方法论失败: entity_type=%s entity_id=%s skill_id=%s: %s",
                entity_type,
                entity_id,
                skill.skill_id,
                exc,
                exc_info=True,
            )
            raise

    def unequip(
        self,
        *,
        entity_id: str,
        skill_id: str,
        entity_type: str | None = None,
        reason: str = "user_unequip",
        commit: bool = True,
        emit_events: bool = True,
    ) -> bool:
        """Mark an active equipment row as unequipped without deleting history."""
        entity_type, entity_id = self._normalize_entity(
            entity_id=entity_id, entity_type=entity_type
        )
        try:
            changed = self._equipment_repo.unequip_active(
                entity_type=entity_type,
                entity_id=entity_id,
                skill_id=skill_id,
                reason=reason,
                commit=False,
            )
            if commit:
                self._session.commit()
            if changed and emit_events and commit:
                emit_skill_equipment_changed(
                    change_type="unequipped" if reason == "user_unequip" else reason,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=skill_id,
                    unequipped_reason=reason,
                )
            return changed
        except Exception as exc:
            if commit:
                self._session.rollback()
            logger.error(
                "卸下方法论失败: entity_type=%s entity_id=%s skill_id=%s reason=%s: %s",
                entity_type,
                entity_id,
                skill_id,
                reason,
                exc,
                exc_info=True,
            )
            raise

    def update_equipment_for_entity(
        self,
        entity_id: str,
        skills: list[dict[str, int]],
        *,
        entity_type: str | None = None,
        commit: bool = True,
        emit_events: bool = True,
    ) -> dict:
        """Replace an entity's active equipment set and preserve unequipped rows."""
        entity_type, entity_id = self._normalize_entity(
            entity_id=entity_id, entity_type=entity_type
        )
        for item in skills:
            skill_id = str(item.get("skill_id") or "").strip()
            self._require_active_skill(skill_id)
        try:
            result = self._equipment_repo.replace_entity_equipment(
                entity_type=entity_type,
                entity_id=entity_id,
                desired=skills,
                commit=False,
            )
            if commit:
                self._session.commit()
        except Exception as exc:
            if commit:
                self._session.rollback()
            logger.error(
                "更新装备清单失败: entity_type=%s entity_id=%s skill_count=%d: %s",
                entity_type,
                entity_id,
                len(skills),
                exc,
                exc_info=True,
            )
            raise
        if emit_events and commit:
            for skill_id in result.get("newly_equipped", []):
                emit_skill_equipment_changed(
                    change_type="equipped",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=skill_id,
                )
            for skill_id in result.get("newly_unequipped", []):
                emit_skill_equipment_changed(
                    change_type="unequipped",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=skill_id,
                    unequipped_reason="user_unequip",
                )
            for skill_id in result.get("reordered", []):
                emit_skill_equipment_changed(
                    change_type="reorder",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=skill_id,
                )
        return result

    def reorder_equipment_for_entity(
        self,
        entity_id: str,
        skills: list[dict[str, int]],
        *,
        entity_type: str | None = None,
        commit: bool = True,
        emit_events: bool = True,
    ) -> dict:
        """Reorder the current equipment set without adding or removing skills."""
        normalized_type, normalized_id = self._normalize_entity(
            entity_id=entity_id, entity_type=entity_type
        )
        active_skill_ids = {
            row.skill_id
            for row in self._equipment_repo.list_active_for_entity(normalized_type, normalized_id)
        }
        desired_skill_ids = {
            str(item.get("skill_id") or "").strip()
            for item in skills
            if str(item.get("skill_id") or "").strip()
        }
        if desired_skill_ids != active_skill_ids:
            raise ValueError("skill_equipment_reorder_requires_current_set")
        return self.update_equipment_for_entity(
            normalized_id,
            skills,
            entity_type=normalized_type,
            commit=commit,
            emit_events=emit_events,
        )

    def default_equip_all(
        self,
        specialist_id: str,
        *,
        commit: bool = True,
        emit_events: bool = True,
    ) -> list[str]:
        """Default-equip all eligible active methodology skills for a new specialist."""
        equipped_skill_ids: list[str] = []
        try:
            for skill in self._skill_repo.list_active():
                if self._equip_if_eligible(
                    skill,
                    entity_type="specialist",
                    entity_id=specialist_id,
                    allow_system_bootstrap=False,
                ):
                    equipped_skill_ids.append(skill.skill_id)
            if commit:
                self._session.commit()
        except Exception as exc:
            if commit:
                self._session.rollback()
            logger.error(
                "默认装备全部方法论失败: specialist_id=%s: %s",
                specialist_id,
                exc,
                exc_info=True,
            )
            raise
        if not emit_events or not commit:
            return equipped_skill_ids
        for skill_id in equipped_skill_ids:
            emit_skill_equipment_changed(
                change_type="default_propagate",
                entity_type="specialist",
                entity_id=specialist_id,
                skill_id=skill_id,
            )
        return equipped_skill_ids

    def default_equip_active_skill(
        self,
        skill_id: str,
        *,
        commit: bool = True,
        skip_entities: set[tuple[str, str]] | None = None,
        emit_events: bool = True,
    ) -> list[str]:
        """Default-equip one active methodology skill to all eligible entities."""
        skill = self._require_active_skill(skill_id)
        skip_entities = skip_entities or set()
        equipped_to: list[str] = []
        try:
            for entity_type, entity_id in self._default_targets_for_skill(skill):
                if (entity_type, entity_id) in skip_entities:
                    continue
                if self._equip_if_eligible(
                    skill,
                    entity_type=entity_type,
                    entity_id=entity_id,
                ):
                    equipped_to.append(entity_id)
            if commit:
                self._session.commit()
        except Exception as exc:
            if commit:
                self._session.rollback()
            logger.error(
                "默认传播方法论装备失败: skill_id=%s: %s",
                skill.skill_id,
                exc,
                exc_info=True,
            )
            raise
        if emit_events and commit:
            for entity_id in equipped_to:
                entity_type = "assistant" if entity_id == ASSISTANT_ENTITY_ID else "specialist"
                emit_skill_equipment_changed(
                    change_type="default_propagate",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=skill.skill_id,
                )
        return equipped_to

    def supersede_equipment(
        self,
        *,
        old_skill_id: str,
        new_skill_id: str,
        commit: bool = True,
        emit_events: bool = True,
    ) -> dict[str, Any]:
        """Transfer active equipment from a superseded skill version to its successor."""
        new_skill = self._require_active_skill(new_skill_id)
        try:
            transferred = self._equipment_repo.transfer_active_equipment(
                old_skill_id=old_skill_id,
                new_skill_id=new_skill.skill_id,
                commit=False,
            )
            transferred_entities = {
                (row.equipped_entity_type, row.equipped_entity_id) for row in transferred
            }
            default_equipped_to = self.default_equip_active_skill(
                new_skill.skill_id,
                commit=False,
                skip_entities=transferred_entities,
                emit_events=False,
            )
            if commit:
                self._session.commit()
        except Exception as exc:
            if commit:
                self._session.rollback()
            logger.error(
                "接力迁移方法论装备失败: old_skill_id=%s new_skill_id=%s: %s",
                old_skill_id,
                new_skill.skill_id,
                exc,
                exc_info=True,
            )
            raise
        if emit_events and commit:
            for row in transferred:
                emit_skill_equipment_changed(
                    change_type="supersede_transfer",
                    entity_type=row.equipped_entity_type,
                    entity_id=row.equipped_entity_id,
                    skill_id=new_skill.skill_id,
                    unequipped_reason="supersede_transfer",
                )
            for entity_id in default_equipped_to:
                entity_type = "assistant" if entity_id == ASSISTANT_ENTITY_ID else "specialist"
                emit_skill_equipment_changed(
                    change_type="default_propagate",
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=new_skill.skill_id,
                )
        return {
            "transferred": [
                {
                    "entity_type": row.equipped_entity_type,
                    "entity_id": row.equipped_entity_id,
                    "skill_id": row.skill_id,
                }
                for row in transferred
            ],
            "default_equipped_to": default_equipped_to,
        }

    def force_unequip_all_for_skill(
        self,
        skill_id: str,
        *,
        commit: bool = True,
        emit_events: bool = True,
    ) -> int:
        """Force-unequip a skill from all entities as part of soft deletion."""
        affected = self._equipment_repo.active_entity_pairs_for_skill(skill_id)
        try:
            count = self._equipment_repo.force_unequip_all_for_skill(
                skill_id,
                reason="force_remove_on_soft_delete",
                commit=False,
            )
            if commit:
                self._session.commit()
        except Exception as exc:
            if commit:
                self._session.rollback()
            logger.error(
                "强制卸下方法论失败: skill_id=%s affected_count=%d: %s",
                skill_id,
                len(affected),
                exc,
                exc_info=True,
            )
            raise
        if emit_events and commit:
            for row in affected:
                emit_skill_equipment_changed(
                    change_type="force_remove_on_soft_delete",
                    entity_type=row["entity_type"],
                    entity_id=row["entity_id"],
                    skill_id=skill_id,
                    unequipped_reason="force_remove_on_soft_delete",
                )
        return count

    def _thresholds(self) -> dict[str, int]:
        config = get_unified_config()
        return {
            "warn_threshold": config.get_brain_skill_token_budget_warn_threshold(),
            "danger_threshold": config.get_brain_skill_token_budget_danger_threshold(),
        }

    def _require_active_skill(self, skill_id: str) -> BrainSkill:
        skill = self._skill_repo.get_skill(str(skill_id or "").strip())
        if skill is None or skill.status != "active":
            raise ValueError("skill_equipment_skill_not_active")
        return skill

    def _default_targets_for_skill(self, skill: BrainSkill) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = [("assistant", ASSISTANT_ENTITY_ID)]
        if self._skill_repo.get_chain_root_origin(skill.skill_id) == "system_bootstrap":
            return targets
        specialists, _ = self._specialist_repo.list_specialists(
            active_only=True,
            limit=100000,
            offset=0,
        )
        specialists.sort(
            key=lambda item: (
                getattr(item, "created_at", None) or datetime.min,
                getattr(item, "specialist_id", ""),
            )
        )
        targets.extend(("specialist", item.specialist_id) for item in specialists)
        return targets

    def _has_user_unequipped_chain(
        self, entity_type: str, entity_id: str, chain_root_id: str
    ) -> bool:
        return self._equipment_repo.has_user_unequipped_for_chain(
            entity_type=entity_type,
            entity_id=entity_id,
            chain_root_id=chain_root_id,
        )

    def _equip_if_eligible(
        self,
        skill: BrainSkill,
        *,
        entity_type: str,
        entity_id: str,
        allow_system_bootstrap: bool = True,
    ) -> bool:
        if (
            not allow_system_bootstrap
            and self._skill_repo.get_chain_root_origin(skill.skill_id) == "system_bootstrap"
        ):
            return False
        if self._has_user_unequipped_chain(entity_type, entity_id, skill.chain_root_id):
            return False
        if self._equipment_repo.get_active_equipment(entity_type, entity_id, skill.skill_id):
            return False
        self._equipment_repo.equip(
            entity_type=entity_type,
            entity_id=entity_id,
            skill_id=skill.skill_id,
            equipped_order=self._next_order_for_entity(entity_type, entity_id),
            commit=False,
        )
        return True

    def _next_order_for_entity(self, entity_type: str, entity_id: str) -> int:
        rows = self._equipment_repo.list_active_for_entity(entity_type, entity_id)
        if not rows:
            return 0
        return max(int(row.equipped_order or 0) for row in rows) + 1

    @staticmethod
    def _normalize_entity(*, entity_id: str, entity_type: str | None = None) -> tuple[str, str]:
        entity_id = str(entity_id or "").strip()
        if entity_type is None:
            entity_type = "assistant" if entity_id == ASSISTANT_ENTITY_ID else "specialist"
        if entity_type == "assistant":
            entity_id = ASSISTANT_ENTITY_ID
        return entity_type, entity_id


def estimate_equipment_tokens(items: list[dict[str, Any]]) -> int:
    """Estimate system-prompt tokens for the lightweight equipment list.

    The formula mirrors the feature plan: roughly four characters per token,
    plus a 20% safety margin because trigger text is mixed Chinese/ASCII prose.
    """
    rendered = []
    for item in items:
        rendered.append(str(item.get("skill_id") or ""))
        rendered.append(str(item.get("name") or ""))
        rendered.append(str(item.get("description") or ""))
        rendered.extend(str(trigger) for trigger in item.get("trigger_conditions") or [])
    return int(math.ceil(len("\n".join(rendered)) / 4 * 1.2))
