"""
SkillService -- 方法论资产生命周期业务层。
"""

from __future__ import annotations

import difflib
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, TypedDict
from uuid import uuid4

from sqlalchemy.orm import Session

from src.business.brain.skill_events import emit_skill_equipment_changed
from src.data.repos.skill_equipment_repository import SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository, parse_json_list
from src.data.repos.specialist_repository import SpecialistRepository
from src.data.skill_bootstrap_seed import BOOTSTRAP_HOW_TO_SKILL_ID as _BOOTSTRAP_SKILL_ID
from src.utils.events import emit
from src.utils.timezone import utc_now_naive

if TYPE_CHECKING:
    from src.data.models_sqlite import BrainSkill

logger = logging.getLogger(__name__)


class SkillSummaryDict(TypedDict):
    skill_id: str
    name: str
    description: str
    trigger_conditions: list[str]
    required_tools: list[str]
    version: int
    chain_root_id: str
    origin: str
    is_protected: bool
    loaded_count: int
    referenced_count: int
    equipped_count: int
    last_referenced_at: datetime | None
    created_at: datetime


class SkillConfirmationCallback(Protocol):
    def __call__(
        self,
        action_type: str,
        summary: str,
        *,
        extra_payload: dict[str, object] | None = None,
    ) -> None:
        """Raise from the caller boundary when confirmation is denied."""


class SkillService:
    """方法论创建、接力、编辑、软删除与查询服务。"""

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
        self._session = self._skill_repo.session

    def create(
        self,
        *,
        name: str,
        description: str,
        trigger_conditions: list[str],
        required_tools: list[str] | None,
        body_markdown: str,
        source_segments: list[dict[str, str]],
        origin: str,
        caller_type: str,
        caller_id: str,
        change_reason: str,
    ) -> dict[str, Any]:
        self._validate_source_segments(source_segments)
        self._skill_repo.assert_no_same_name_active(name)
        try:
            skill = self._skill_repo.create_skill(
                name=name,
                description=description,
                trigger_conditions=trigger_conditions,
                required_tools=required_tools or [],
                body_markdown=body_markdown,
                origin=origin,
                source_segments=source_segments,
                last_changed_by=caller_id,
                change_reason=change_reason,
                commit=False,
            )
            auto_equipped = self._equipment_service().default_equip_active_skill(
                skill.skill_id,
                commit=False,
                emit_events=False,
            )
            self._session.commit()
            self._emit_skill_changed(
                skill,
                operation="create",
                caller_type=caller_type,
                caller_id=caller_id,
            )
            for entity_id in auto_equipped:
                emit_skill_equipment_changed(
                    change_type="default_propagate",
                    entity_id=entity_id,
                    skill_id=skill.skill_id,
                )
            return {
                "success": True,
                "skill_id": skill.skill_id,
                "chain_root_id": skill.chain_root_id,
                "version": skill.version,
                "name": skill.name,
                "auto_equipped_to": auto_equipped,
            }
        except Exception as exc:
            self._session.rollback()
            logger.error(
                "创建方法论失败: name=%s caller_type=%s caller_id=%s: %s",
                name,
                caller_type,
                caller_id,
                exc,
                exc_info=True,
            )
            raise

    def supersede(
        self,
        *,
        target_skill_id: str,
        name: str,
        description: str,
        trigger_conditions: list[str],
        required_tools: list[str] | None,
        body_markdown: str,
        source_segments: list[dict[str, str]],
        origin: str,
        caller_type: str,
        caller_id: str,
        change_reason: str,
    ) -> dict[str, Any]:
        try:
            # 并发安全由 mark_superseded 的原子条件 UPDATE 保证（WHERE status='active'）：
            # 两个并发 supersede 只有一个能把 base 标记为 superseded，另一个抛 skill_supersede_conflict。
            base = self._skill_repo.get_current_active_for_chain(target_skill_id)
            if base is None:
                raise KeyError("skill_not_found")
            self._validate_source_segments(
                source_segments,
                allow_empty=origin == "user_edit" and self.is_system_bootstrap_chain(base.skill_id),
            )
            name_changed = name.strip() != base.name
            if name_changed:
                self._skill_repo.assert_no_same_name_active(name, excluding_skill_id=base.skill_id)
            new_skill_id = self._next_version_id(base)
            if not self._skill_repo.mark_superseded(base.skill_id, new_skill_id, commit=False):
                raise RuntimeError("skill_supersede_conflict")
            new_skill = self._skill_repo.create_skill(
                skill_id=new_skill_id,
                name=name,
                description=description,
                trigger_conditions=trigger_conditions,
                required_tools=required_tools or [],
                body_markdown=body_markdown,
                origin=origin,
                source_segments=source_segments,
                parent_skill_id=base.skill_id,
                chain_root_id=base.chain_root_id,
                version=int(base.version or 1) + 1,
                last_changed_by=caller_id,
                change_reason=change_reason,
                loaded_count=base.loaded_count,
                referenced_count=base.referenced_count,
                last_referenced_at=base.last_referenced_at,
                commit=False,
            )
            equipment_result = self._equipment_service().supersede_equipment(
                old_skill_id=base.skill_id,
                new_skill_id=new_skill.skill_id,
                commit=False,
                emit_events=False,
            )
            self._session.commit()
            self._emit_skill_changed(
                new_skill,
                operation="supersede" if origin != "user_edit" else "user_edit",
                caller_type=caller_type,
                caller_id=caller_id,
            )
            emit(
                "brain_skill_supersede_completed",
                sender=new_skill.chain_root_id,
                old_skill_id=base.skill_id,
                new_skill_id=new_skill.skill_id,
                version=new_skill.version,
                equipment_count_migrated=len(equipment_result["transferred"]),
            )
            for row in equipment_result["transferred"]:
                emit_skill_equipment_changed(
                    change_type="supersede_transfer",
                    entity_id=row["entity_id"],
                    skill_id=new_skill.skill_id,
                    entity_type=row["entity_type"],
                    unequipped_reason="supersede_transfer",
                )
            for entity_id in equipment_result["default_equipped_to"]:
                emit_skill_equipment_changed(
                    change_type="default_propagate",
                    entity_id=entity_id,
                    skill_id=new_skill.skill_id,
                )
            return {
                "success": True,
                "skill_id": new_skill.skill_id,
                "new_skill_id": new_skill.skill_id,
                "chain_root_id": new_skill.chain_root_id,
                "version": new_skill.version,
                "name": new_skill.name,
            }
        except Exception as exc:
            self._session.rollback()
            logger.error(
                "接力更新方法论失败: target_skill_id=%s name=%s origin=%s caller_id=%s: %s",
                target_skill_id,
                name,
                origin,
                caller_id,
                exc,
                exc_info=True,
            )
            raise

    def user_edit_supersede(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned = self._validate_user_edit_payload(payload)
        return self.supersede(
            target_skill_id=skill_id,
            name=cleaned["name"],
            description=cleaned["description"],
            trigger_conditions=cleaned["trigger_conditions"],
            required_tools=cleaned["required_tools"],
            body_markdown=cleaned["body_markdown"],
            source_segments=cleaned["source_segments"] or self._source_segments_for_skill(skill_id),
            origin="user_edit",
            caller_type="user",
            caller_id="_user",
            change_reason=cleaned["change_reason"] or "用户编辑",
        )

    def edit_with_protection_check(
        self,
        skill_id: str,
        payload: dict[str, Any],
        *,
        require_confirmation: SkillConfirmationCallback,
    ) -> dict[str, Any]:
        """Edit a methodology skill, asking the caller to confirm protected edits."""
        detail = self.get_detail(skill_id)
        if detail.get("is_protected"):
            require_confirmation(
                "skill.edit_protected",
                (
                    f"将编辑受保护方法论 {detail.get('name') or skill_id}。"
                    "保存会生成新版本并影响后续方法论创建指引。"
                ),
                extra_payload={"affectedSkillId": detail["skill_id"]},
            )
        result = self.user_edit_supersede(skill_id, payload)
        return self.get_detail(
            str(result.get("new_skill_id") or result.get("skill_id") or skill_id)
        )

    def force_soft_delete(self, skill_id: str) -> dict[str, Any]:
        skill = self._skill_repo.get_current_active_for_chain(skill_id)
        if skill is None:
            raise KeyError("skill_not_found")
        if self.is_system_bootstrap_chain(skill.skill_id):
            raise PermissionError("bootstrap_skill_not_softdeletable")
        affected = self._equipment_repo.active_entity_pairs_for_skill(skill.skill_id)
        try:
            pruned = self._equipment_service().force_unequip_all_for_skill(
                skill.skill_id,
                commit=False,
                emit_events=False,
            )
            if not self._skill_repo.mark_soft_deleted(skill.skill_id, commit=False):
                raise RuntimeError("skill_soft_delete_conflict")
            self._session.commit()
            self._emit_skill_changed(
                skill,
                operation="soft_delete",
                caller_type="user",
                caller_id="_user",
            )
            for row in affected:
                emit_skill_equipment_changed(
                    change_type="force_remove_on_soft_delete",
                    entity_id=row["entity_id"],
                    skill_id=skill.skill_id,
                    entity_type=row["entity_type"],
                    unequipped_reason="force_remove_on_soft_delete",
                )
            return {
                "deleted_skill_id": skill.skill_id,
                "pruned_equipment_count": pruned,
                "affected_specialist_ids": [
                    row["entity_id"] for row in affected if row["entity_type"] == "specialist"
                ],
            }
        except Exception as exc:
            self._session.rollback()
            logger.error(
                "强制软删除方法论失败: skill_id=%s: %s",
                skill_id,
                exc,
                exc_info=True,
            )
            raise

    def soft_delete_with_confirmation(
        self,
        skill_id: str,
        *,
        require_confirmation: SkillConfirmationCallback,
    ) -> dict[str, Any]:
        """Soft-delete a methodology skill after confirming equipment pruning impact."""
        detail = self.get_detail(skill_id)
        if detail.get("is_protected"):
            raise PermissionError("bootstrap_skill_not_softdeletable")
        affected_names = self._active_equipment_names(detail["skill_id"])
        affected_preview = "、".join(name for name in affected_names if name)
        require_confirmation(
            "skill.soft_delete",
            (
                f"将软删除方法论 {detail.get('name') or skill_id}，"
                f"并从 {len(affected_names)} 个装备者身上裁剪。"
                f"{'受影响装备者：' + affected_preview + '。' if affected_preview else ''}"
                "历史版本和审计记录会保留。"
            ),
            extra_payload={
                "affectedSkillId": detail["skill_id"],
                "affectedEquipmentCount": len(affected_names),
                "affectedSpecialistNames": affected_names,
            },
        )
        return self.force_soft_delete(skill_id)

    def list_active(
        self, *, sort: str = "recently_changed", filter_key: str | None = None
    ) -> list[SkillSummaryDict]:
        rows = self._skill_repo.list_active()
        protected_roots = self._skill_repo.system_bootstrap_chain_roots(
            [row.chain_root_id for row in rows]
        )
        equipped_counts = self._equipment_repo.active_counts_for_skills(
            [row.skill_id for row in rows]
        )
        items = [
            self._summary(
                row,
                protected_roots=protected_roots,
                equipped_counts=equipped_counts,
            )
            for row in rows
        ]
        if filter_key == "never_referenced":
            items = [item for item in items if item["referenced_count"] == 0]
        elif filter_key == "not_referenced_30d":
            cutoff = utc_now_naive() - timedelta(days=30)
            items = [
                item
                for item in items
                if item["last_referenced_at"] is None or item["last_referenced_at"] < cutoff
            ]
        sort_key = {
            "recently_changed": "created_at",
            "loaded_count": "loaded_count",
            "referenced_count": "referenced_count",
            "equipped_count": "equipped_count",
        }.get(sort, "created_at")
        items.sort(key=lambda item: item.get(sort_key) or 0, reverse=True)
        return items

    def get_detail(self, skill_id: str) -> dict:
        skill = self._skill_repo.get_skill(skill_id)
        if skill is None:
            raise KeyError("skill_not_found")
        return {
            **self._summary(skill),
            "body_markdown": skill.body_markdown,
            "parent_skill_id": skill.parent_skill_id,
            "status": skill.status,
            "source_segments": self._source_segment_details(skill.skill_id),
        }

    def get_history(self, skill_id: str) -> dict:
        chain = self._skill_repo.get_chain(skill_id)
        if not chain:
            raise KeyError("skill_not_found")
        nodes = []
        previous_body: str | None = None
        for node in chain:
            diff = None
            if previous_body is not None:
                diff = "\n".join(
                    difflib.unified_diff(
                        previous_body.splitlines(),
                        node.body_markdown.splitlines(),
                        fromfile="previous",
                        tofile=f"v{node.version}",
                        lineterm="",
                    )
                )
            nodes.append(
                {
                    "skill_id": node.skill_id,
                    "version": node.version,
                    "name": node.name,
                    "description": node.description,
                    "trigger_conditions": parse_json_list(node.trigger_conditions),
                    "required_tools": parse_json_list(node.required_tools),
                    "body_markdown": node.body_markdown,
                    "diff_from_previous": diff,
                    "origin": node.origin,
                    "changed_by": node.last_changed_by,
                    "change_reason": node.change_reason,
                    "created_at": node.created_at,
                }
            )
            previous_body = node.body_markdown
        return {"chain_root_id": chain[0].chain_root_id, "nodes": nodes}

    def get_equipment_audit(self, skill_id: str) -> dict:
        chain = self._skill_repo.get_chain(skill_id)
        if not chain:
            raise KeyError("skill_not_found")
        rows = []
        for node in chain:
            rows.extend(self._equipment_repo.list_history_for_skill(node.skill_id))
        rows.sort(key=lambda row: (row.equipped_at or datetime.min, row.id or 0), reverse=True)
        return {
            "skill_id": skill_id,
            "rows": [
                {
                    "skill_id": row.skill_id,
                    "equipped_entity_type": row.equipped_entity_type,
                    "equipped_entity_id": row.equipped_entity_id,
                    "equipped_entity_name": self._entity_name(
                        row.equipped_entity_type, row.equipped_entity_id
                    ),
                    "status": row.status,
                    "equipped_at": row.equipped_at,
                    "unequipped_at": row.unequipped_at,
                    "unequipped_reason": row.unequipped_reason,
                }
                for row in rows
            ],
        }

    def is_system_bootstrap_chain(self, skill_id: str) -> bool:
        return self._skill_repo.get_chain_root_origin(skill_id) == "system_bootstrap"

    def _summary(
        self,
        skill: BrainSkill,
        *,
        protected_roots: set[str] | None = None,
        equipped_counts: dict[str, int] | None = None,
    ) -> SkillSummaryDict:
        return {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "description": skill.description,
            "trigger_conditions": parse_json_list(skill.trigger_conditions),
            "required_tools": parse_json_list(skill.required_tools),
            "version": skill.version,
            "chain_root_id": skill.chain_root_id,
            "origin": skill.origin,
            "is_protected": (
                skill.chain_root_id in protected_roots
                if protected_roots is not None
                else self.is_system_bootstrap_chain(skill.skill_id)
            ),
            "loaded_count": skill.loaded_count or 0,
            "referenced_count": skill.referenced_count or 0,
            "equipped_count": (
                equipped_counts.get(skill.skill_id, 0)
                if equipped_counts is not None
                else self._equipment_repo.active_count_for_skill(skill.skill_id)
            ),
            "last_referenced_at": skill.last_referenced_at,
            "created_at": skill.created_at,
        }

    def _source_segments_for_skill(self, skill_id: str) -> list[dict[str, str]]:
        return [
            {"segment_id": row.segment_id, "source_zone": row.source_zone}
            for row in self._skill_repo.list_source_segments(skill_id)
        ]

    def _source_segment_details(self, skill_id: str) -> list[dict[str, str]]:
        return self._skill_repo.source_segment_details_for_skill(skill_id)

    def _validate_source_segments(
        self,
        source_segments: list[dict[str, str]],
        *,
        allow_empty: bool = False,
    ) -> None:
        if allow_empty and not source_segments:
            return
        self._skill_repo.validate_source_segments(source_segments)

    def _equipment_service(self):
        from src.business.brain.skill_equipment_service import SkillEquipmentService

        return SkillEquipmentService(
            session=self._session,
            skill_repo=self._skill_repo,
            equipment_repo=self._equipment_repo,
        )

    def _entity_name(self, entity_type: str, entity_id: str) -> str:
        if entity_type == "assistant":
            return "Assistant 本体"
        specialist = SpecialistRepository(session=self._session).get_specialist(entity_id)
        return getattr(specialist, "name", entity_id)

    def _active_equipment_names(self, skill_id: str) -> list[str]:
        audit = self.get_equipment_audit(skill_id)
        return [
            str(row.get("equipped_entity_name") or row.get("equipped_entity_id") or "")
            for row in audit.get("rows", [])
            if row.get("status") == "active"
        ]

    @staticmethod
    def _next_version_id(base: BrainSkill) -> str:
        if base.chain_root_id == _BOOTSTRAP_SKILL_ID:
            return f"{base.chain_root_id}.v{int(base.version or 1) + 1}"
        return f"skl_{uuid4().hex[:46]}"

    @staticmethod
    def _emit_skill_changed(
        skill: BrainSkill,
        *,
        operation: str,
        caller_type: str,
        caller_id: str,
    ) -> None:
        emit(
            "brain_skill_changed",
            sender=skill.skill_id,
            skill_id=skill.skill_id,
            operation=operation,
            chain_root_id=skill.chain_root_id,
            new_skill_id=skill.skill_id,
            caller_type=caller_type,
            caller_id=caller_id,
        )

    @staticmethod
    def _validate_user_edit_payload(payload: dict[str, Any]) -> dict[str, Any]:
        required = ("name", "description", "trigger_conditions", "body_markdown")
        missing = [field for field in required if field not in payload]
        if missing:
            raise ValueError(f"skill_edit_missing_fields:{','.join(missing)}")
        return {
            "name": str(payload["name"]).strip(),
            "description": str(payload["description"]).strip(),
            "trigger_conditions": payload["trigger_conditions"],
            "required_tools": payload.get("required_tools") or [],
            "body_markdown": str(payload["body_markdown"]).strip(),
            "source_segments": payload.get("source_segments"),
            "change_reason": str(payload.get("change_reason") or "").strip(),
        }
