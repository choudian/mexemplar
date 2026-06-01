"""
SkillEquipmentRepository -- 方法论装备关系仓库

装备/卸下均保留历史行，不提供物理删除方法。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func

from src.data.models_sqlite import BrainSkill, BrainSkillEquipment
from src.data.repos.base_repository import BaseRepository
from src.utils.timezone import utc_now_naive

ENTITY_TYPES = frozenset({"assistant", "specialist"})
EQUIPMENT_STATUSES = frozenset({"active", "unequipped"})
UNEQUIPPED_REASONS = frozenset(
    {"user_unequip", "force_remove_on_soft_delete", "supersede_transfer"}
)
ASSISTANT_ENTITY_ID = "_assistant"


class SkillEquipmentRepository(BaseRepository):
    """方法论装备关系仓库。"""

    def equip(
        self,
        *,
        entity_type: str,
        entity_id: str,
        skill_id: str,
        equipped_order: int = 0,
        commit: bool = True,
    ) -> BrainSkillEquipment:
        self._validate_entity(entity_type, entity_id)
        if self.get_active_equipment(entity_type, entity_id, skill_id) is not None:
            raise ValueError("skill already equipped for entity")
        row = BrainSkillEquipment(
            equipped_entity_type=entity_type,
            equipped_entity_id=entity_id,
            skill_id=skill_id,
            status="active",
            equipped_order=int(equipped_order or 0),
            equipped_at=utc_now_naive(),
        )
        self.session.add(row)
        if commit:
            self.session.commit()
            self.session.refresh(row)
        return row

    def get_active_equipment(
        self,
        entity_type: str,
        entity_id: str,
        skill_id: str,
    ) -> BrainSkillEquipment | None:
        return (
            self.session.query(BrainSkillEquipment)
            .filter(
                BrainSkillEquipment.equipped_entity_type == entity_type,
                BrainSkillEquipment.equipped_entity_id == entity_id,
                BrainSkillEquipment.skill_id == skill_id,
                BrainSkillEquipment.status == "active",
            )
            .first()
        )

    def list_active_for_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[BrainSkillEquipment]:
        return (
            self.session.query(BrainSkillEquipment)
            .filter(
                BrainSkillEquipment.equipped_entity_type == entity_type,
                BrainSkillEquipment.equipped_entity_id == entity_id,
                BrainSkillEquipment.status == "active",
            )
            .order_by(BrainSkillEquipment.equipped_order.asc(), BrainSkillEquipment.id.asc())
            .all()
        )

    def list_active_skills_for_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[tuple[BrainSkillEquipment, BrainSkill]]:
        return (
            self.session.query(BrainSkillEquipment, BrainSkill)
            .join(BrainSkill, BrainSkill.skill_id == BrainSkillEquipment.skill_id)
            .filter(
                BrainSkillEquipment.equipped_entity_type == entity_type,
                BrainSkillEquipment.equipped_entity_id == entity_id,
                BrainSkillEquipment.status == "active",
                BrainSkill.status == "active",
            )
            .order_by(BrainSkillEquipment.equipped_order.asc(), BrainSkillEquipment.id.asc())
            .all()
        )

    def list_active_for_skill(self, skill_id: str) -> list[BrainSkillEquipment]:
        return (
            self.session.query(BrainSkillEquipment)
            .filter(
                BrainSkillEquipment.skill_id == skill_id,
                BrainSkillEquipment.status == "active",
            )
            .order_by(
                BrainSkillEquipment.equipped_entity_type.asc(),
                BrainSkillEquipment.equipped_entity_id.asc(),
                BrainSkillEquipment.equipped_order.asc(),
            )
            .all()
        )

    def count_active_for_skill(self, skill_id: str) -> int:
        return (
            self.session.query(BrainSkillEquipment)
            .filter(
                BrainSkillEquipment.skill_id == skill_id,
                BrainSkillEquipment.status == "active",
            )
            .count()
        )

    def unequip(
        self,
        equipment: BrainSkillEquipment | int,
        *,
        reason: str,
        commit: bool = True,
    ) -> bool:
        self._validate_reason(reason)
        row = (
            equipment
            if isinstance(equipment, BrainSkillEquipment)
            else self.session.get(BrainSkillEquipment, equipment)
        )
        if row is None or row.status != "active":
            return False
        row.status = "unequipped"
        row.unequipped_at = utc_now_naive()
        row.unequipped_reason = reason
        if commit:
            self.session.commit()
        return True

    def unequip_active(
        self,
        *,
        entity_type: str,
        entity_id: str,
        skill_id: str,
        reason: str,
        commit: bool = True,
    ) -> bool:
        row = self.get_active_equipment(entity_type, entity_id, skill_id)
        return self.unequip(row, reason=reason, commit=commit) if row else False

    def force_unequip_all_for_skill(
        self,
        skill_id: str,
        *,
        reason: str = "force_remove_on_soft_delete",
        commit: bool = True,
    ) -> int:
        rows = self.list_active_for_skill(skill_id)
        count = 0
        for row in rows:
            if self.unequip(row, reason=reason, commit=False):
                count += 1
        if commit:
            self.session.commit()
        return count

    def transfer_active_equipment(
        self,
        *,
        old_skill_id: str,
        new_skill_id: str,
        commit: bool = True,
    ) -> list[BrainSkillEquipment]:
        old_rows = self.list_active_for_skill(old_skill_id)
        new_rows: list[BrainSkillEquipment] = []
        for row in old_rows:
            old_order = int(row.equipped_order or 0)
            entity_type = row.equipped_entity_type
            entity_id = row.equipped_entity_id
            self.unequip(row, reason="supersede_transfer", commit=False)
            new_rows.append(
                self.equip(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=new_skill_id,
                    equipped_order=old_order,
                    commit=False,
                )
            )
        if commit:
            self.session.commit()
        return new_rows

    def replace_entity_equipment(
        self,
        *,
        entity_type: str,
        entity_id: str,
        skills: list[dict[str, Any]] | None = None,
        desired: list[dict[str, Any]] | None = None,
        commit: bool = True,
    ) -> dict[str, list[str] | int]:
        self._validate_entity(entity_type, entity_id)
        skills = skills if skills is not None else desired
        skills = skills or []
        desired_map: dict[str, int] = {
            str(item.get("skill_id") or "").strip(): int(item.get("equipped_order") or idx)
            for idx, item in enumerate(skills)
            if str(item.get("skill_id") or "").strip()
        }
        active = self.list_active_for_entity(entity_type, entity_id)
        active_by_skill = {row.skill_id: row for row in active}
        newly_equipped: list[str] = []
        newly_unequipped: list[str] = []
        reordered: list[str] = []

        for skill_id, row in active_by_skill.items():
            if skill_id not in desired_map:
                self.unequip(row, reason="user_unequip", commit=False)
                newly_unequipped.append(skill_id)
            elif int(row.equipped_order or 0) != desired_map[skill_id]:
                row.equipped_order = desired_map[skill_id]
                reordered.append(skill_id)

        for skill_id, order in desired_map.items():
            if skill_id not in active_by_skill:
                self.equip(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    skill_id=skill_id,
                    equipped_order=order,
                    commit=False,
                )
                newly_equipped.append(skill_id)

        if commit:
            self.session.commit()
        return {
            "active_equipment_count": len(desired_map),
            "newly_equipped": newly_equipped,
            "newly_unequipped": newly_unequipped,
            "reordered": reordered,
        }

    def list_history_for_skill(self, skill_id: str) -> list[BrainSkillEquipment]:
        return (
            self.session.query(BrainSkillEquipment)
            .filter(BrainSkillEquipment.skill_id == skill_id)
            .order_by(BrainSkillEquipment.equipped_at.desc(), BrainSkillEquipment.id.desc())
            .all()
        )

    def active_count_for_skill(self, skill_id: str) -> int:
        return self.count_active_for_skill(skill_id)

    def active_counts_for_skills(self, skill_ids: list[str]) -> dict[str, int]:
        clean_ids = [str(skill_id) for skill_id in skill_ids if str(skill_id).strip()]
        if not clean_ids:
            return {}
        rows = (
            self.session.query(BrainSkillEquipment.skill_id, func.count(BrainSkillEquipment.id))
            .filter(
                BrainSkillEquipment.skill_id.in_(clean_ids),
                BrainSkillEquipment.status == "active",
            )
            .group_by(BrainSkillEquipment.skill_id)
            .all()
        )
        return {str(skill_id): int(count) for skill_id, count in rows}

    def active_entity_pairs_for_skill(self, skill_id: str) -> list[dict[str, str]]:
        return [
            {
                "entity_type": row.equipped_entity_type,
                "entity_id": row.equipped_entity_id,
            }
            for row in self.list_active_for_skill(skill_id)
        ]

    def has_user_unequipped_for_chain(
        self,
        *,
        entity_type: str,
        entity_id: str,
        chain_root_id: str,
    ) -> bool:
        return (
            self.session.query(BrainSkillEquipment.id)
            .join(BrainSkill, BrainSkill.skill_id == BrainSkillEquipment.skill_id)
            .filter(
                BrainSkillEquipment.equipped_entity_type == entity_type,
                BrainSkillEquipment.equipped_entity_id == entity_id,
                BrainSkill.chain_root_id == chain_root_id,
                BrainSkillEquipment.status == "unequipped",
                BrainSkillEquipment.unequipped_reason == "user_unequip",
            )
            .first()
            is not None
        )

    def list_history_for_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[BrainSkillEquipment]:
        return (
            self.session.query(BrainSkillEquipment)
            .filter(
                BrainSkillEquipment.equipped_entity_type == entity_type,
                BrainSkillEquipment.equipped_entity_id == entity_id,
            )
            .order_by(BrainSkillEquipment.equipped_at.desc(), BrainSkillEquipment.id.desc())
            .all()
        )

    @staticmethod
    def _validate_entity(entity_type: str, entity_id: str) -> None:
        if entity_type not in ENTITY_TYPES:
            raise ValueError(f"invalid equipped entity type: {entity_type}")
        if not str(entity_id or "").strip():
            raise ValueError("equipped entity id must not be empty")
        if entity_type == "assistant" and entity_id != ASSISTANT_ENTITY_ID:
            raise ValueError("assistant equipment entity_id must be _assistant")

    @staticmethod
    def _validate_reason(reason: str) -> None:
        if reason not in UNEQUIPPED_REASONS:
            raise ValueError(f"invalid unequipped reason: {reason}")
