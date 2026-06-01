"""
SkillRepository -- 方法论资产仓库

只暴露状态机操作，不提供物理删除方法。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4


from src.data.models_sqlite import (
    BrainMemoryEntry,
    BrainSegment,
    BrainSkill,
    BrainSkillSourceSegment,
)
from src.data.repos.base_repository import BaseRepository
from src.utils.timezone import utc_now_naive

SKILL_ORIGINS = frozenset(
    {
        "system_bootstrap",
        "user_edit",
        "assistant_tool_call",
        "specialist_tool_call",
        "external_import",
    }
)
SKILL_STATUSES = frozenset({"active", "superseded", "soft_deleted"})
SOURCE_ZONES = frozenset({"archive", "failure"})


def new_skill_id() -> str:
    return uuid4().hex[:50]


def json_list(value: Any) -> str:
    if value is None:
        return "[]"
    if not isinstance(value, list):
        raise ValueError("value must be a list")
    return json.dumps(
        [str(item).strip() for item in value if str(item).strip()], ensure_ascii=False
    )


def parse_json_list(value: Any, *, field_name: str = "value") -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None or value == "":
        return []
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a JSON list string")
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        raise ValueError(f"{field_name} must be a JSON list") from None
    if not isinstance(parsed, list):
        raise ValueError(f"{field_name} must be a JSON list")
    return [str(item) for item in parsed if str(item).strip()]


class SkillRepository(BaseRepository):
    """方法论资产仓库。"""

    def create_skill(
        self,
        *,
        name: str,
        description: str,
        trigger_conditions: list[str],
        required_tools: list[str] | None,
        body_markdown: str,
        origin: str,
        source_segments: list[dict[str, str]] | None = None,
        skill_id: str | None = None,
        parent_skill_id: str | None = None,
        chain_root_id: str | None = None,
        version: int = 1,
        last_changed_by: str | None = None,
        change_reason: str | None = None,
        loaded_count: int = 0,
        referenced_count: int = 0,
        last_referenced_at: datetime | None = None,
        commit: bool = True,
    ) -> BrainSkill:
        self._validate_origin(origin)
        self._validate_payload(
            name=name,
            description=description,
            trigger_conditions=trigger_conditions,
            body_markdown=body_markdown,
        )
        skill_id = skill_id or new_skill_id()
        chain_root_id = chain_root_id or skill_id
        now = utc_now_naive()
        skill = BrainSkill(
            skill_id=skill_id,
            name=name.strip(),
            description=description.strip(),
            trigger_conditions=json_list(trigger_conditions),
            required_tools=json_list(required_tools or []),
            body_markdown=body_markdown.strip(),
            status="active",
            origin=origin,
            parent_skill_id=parent_skill_id,
            chain_root_id=chain_root_id,
            version=version,
            created_at=now,
            updated_at=now,
            last_changed_by=last_changed_by,
            change_reason=change_reason,
            loaded_count=int(loaded_count or 0),
            referenced_count=int(referenced_count or 0),
            last_referenced_at=last_referenced_at,
        )
        self.session.add(skill)
        self.session.flush()
        for source in source_segments or []:
            self.add_source_segment(
                skill_id=skill.skill_id,
                segment_id=str(source.get("segment_id") or "").strip(),
                source_zone=str(source.get("source_zone") or "").strip(),
                commit=False,
            )
        if commit:
            self.session.commit()
            self.session.refresh(skill)
        return skill

    def add_source_segment(
        self,
        *,
        skill_id: str,
        segment_id: str,
        source_zone: str,
        commit: bool = True,
    ) -> BrainSkillSourceSegment:
        if not segment_id:
            raise ValueError("segment_id must not be empty")
        if source_zone not in SOURCE_ZONES:
            raise ValueError("source_zone must be archive or failure")
        row = BrainSkillSourceSegment(
            skill_id=skill_id,
            segment_id=segment_id,
            source_zone=source_zone,
        )
        self.session.add(row)
        if commit:
            self.session.commit()
            self.session.refresh(row)
        return row

    def get(self, skill_id: str) -> BrainSkill | None:
        return self.session.get(BrainSkill, skill_id)

    def get_active(self, skill_id: str) -> BrainSkill | None:
        return (
            self.session.query(BrainSkill)
            .filter(BrainSkill.skill_id == skill_id, BrainSkill.status == "active")
            .first()
        )

    def list_active(
        self,
        *,
        origin: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[BrainSkill]:
        query = self.session.query(BrainSkill).filter(BrainSkill.status == "active")
        if origin is not None:
            self._validate_origin(origin)
            query = query.filter(BrainSkill.origin == origin)
        query = query.order_by(BrainSkill.created_at.desc()).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def get_active_by_name(
        self, name: str, *, exclude_skill_id: str | None = None
    ) -> BrainSkill | None:
        query = self.session.query(BrainSkill).filter(
            BrainSkill.status == "active",
            BrainSkill.name == name.strip(),
        )
        if exclude_skill_id is not None:
            query = query.filter(BrainSkill.skill_id != exclude_skill_id)
        return query.first()

    def get_current_active_for_chain(self, skill_id_or_chain_root_id: str) -> BrainSkill | None:
        chain_root_id = self.resolve_chain_root(skill_id_or_chain_root_id)
        if chain_root_id is None:
            return None
        return (
            self.session.query(BrainSkill)
            .filter(BrainSkill.chain_root_id == chain_root_id, BrainSkill.status == "active")
            .order_by(BrainSkill.version.desc(), BrainSkill.created_at.desc())
            .first()
        )

    def get_chain(self, skill_id_or_chain_root_id: str) -> list[BrainSkill]:
        root_id = self.resolve_chain_root(skill_id_or_chain_root_id)
        if root_id is None:
            return []
        return (
            self.session.query(BrainSkill)
            .filter(BrainSkill.chain_root_id == root_id)
            .order_by(BrainSkill.version.asc(), BrainSkill.created_at.asc())
            .all()
        )

    def resolve_chain_root(self, skill_id: str) -> str | None:
        skill = self.get(skill_id)
        if skill is None:
            # Accept an already-known chain_root_id.
            root = (
                self.session.query(BrainSkill.skill_id)
                .filter(BrainSkill.chain_root_id == skill_id)
                .first()
            )
            return skill_id if root is not None else None
        return skill.chain_root_id or skill.skill_id

    def get_chain_root_skill(self, skill_id: str) -> BrainSkill | None:
        root_id = self.resolve_chain_root(skill_id)
        if root_id is None:
            return None
        return self.get(root_id)

    def is_chain_protected(self, skill_id: str) -> bool:
        root = self.get_chain_root_skill(skill_id)
        return bool(root and root.origin == "system_bootstrap")

    def system_bootstrap_chain_roots(self, chain_root_ids: list[str]) -> set[str]:
        clean_ids = [str(root_id) for root_id in chain_root_ids if str(root_id).strip()]
        if not clean_ids:
            return set()
        return {
            str(row[0])
            for row in self.session.query(BrainSkill.skill_id)
            .filter(
                BrainSkill.skill_id.in_(clean_ids),
                BrainSkill.origin == "system_bootstrap",
            )
            .all()
        }

    def has_user_edit_in_chain(self, chain_root_id: str) -> bool:
        return (
            self.session.query(BrainSkill.skill_id)
            .filter(BrainSkill.chain_root_id == chain_root_id, BrainSkill.origin == "user_edit")
            .first()
            is not None
        )

    def mark_superseded(self, old_skill_id: str, new_skill_id: str, *, commit: bool = True) -> bool:
        skill = self.get(old_skill_id)
        if skill is None or skill.status != "active":
            return False
        skill.status = "superseded"
        skill.superseded_by = new_skill_id
        skill.updated_at = utc_now_naive()
        if commit:
            self.session.commit()
        return True

    def mark_soft_deleted(self, skill_id: str, *, commit: bool = True) -> bool:
        skill = self.get(skill_id)
        if skill is None or skill.status != "active":
            return False
        skill.status = "soft_deleted"
        skill.updated_at = utc_now_naive()
        if commit:
            self.session.commit()
        return True

    def increment_loaded_count(self, skill_id: str, *, commit: bool = True) -> bool:
        skill = self.get(skill_id)
        if skill is None or skill.status != "active":
            return False
        skill.loaded_count = int(skill.loaded_count or 0) + 1
        skill.updated_at = utc_now_naive()
        if commit:
            self.session.commit()
        return True

    def increment_referenced_count(self, skill_id: str, *, commit: bool = True) -> bool:
        skill = self.get(skill_id)
        if skill is None or skill.status != "active":
            return False
        skill.referenced_count = int(skill.referenced_count or 0) + 1
        skill.last_referenced_at = utc_now_naive()
        skill.updated_at = utc_now_naive()
        if commit:
            self.session.commit()
        return True

    def source_segments_for_skill(self, skill_id: str) -> list[BrainSkillSourceSegment]:
        return (
            self.session.query(BrainSkillSourceSegment)
            .filter(BrainSkillSourceSegment.skill_id == skill_id)
            .order_by(BrainSkillSourceSegment.id.asc())
            .all()
        )

    def source_segment_details_for_skill(self, skill_id: str) -> list[dict[str, str]]:
        rows = self.source_segments_for_skill(skill_id)
        segment_ids = [row.segment_id for row in rows]
        latest_entry_by_segment: dict[str, BrainMemoryEntry] = {}
        if segment_ids:
            entries = (
                self.session.query(BrainMemoryEntry)
                .filter(BrainMemoryEntry.source_segment_id.in_(segment_ids))
                .order_by(
                    BrainMemoryEntry.source_segment_id.asc(),
                    BrainMemoryEntry.created_at.desc(),
                    BrainMemoryEntry.entry_id.desc(),
                )
                .all()
            )
            for entry in entries:
                segment_id = getattr(entry, "source_segment_id", None)
                if segment_id and segment_id not in latest_entry_by_segment:
                    latest_entry_by_segment[segment_id] = entry
        return [
            {
                "segment_id": row.segment_id,
                "source_zone": row.source_zone,
                "segment_summary": (
                    getattr(latest_entry_by_segment.get(row.segment_id), "content", "")[:300]
                    if latest_entry_by_segment.get(row.segment_id)
                    else ""
                ),
                "segment_status": (
                    getattr(latest_entry_by_segment.get(row.segment_id), "status", "active")
                    if latest_entry_by_segment.get(row.segment_id)
                    else "active"
                ),
            }
            for row in rows
        ]

    def validate_source_segments(self, source_segments: list[dict[str, str]]) -> None:
        if not source_segments:
            raise ValueError("skill_source_segments_required")
        for source in source_segments:
            segment_id = str(source.get("segment_id") or "").strip()
            source_zone = str(source.get("source_zone") or "").strip()
            if source_zone not in SOURCE_ZONES:
                raise ValueError("skill_source_segment_wrong_zone")
            if not segment_id:
                raise ValueError("skill_source_segments_required")
            zones = {
                row[0]
                for row in self.session.query(BrainMemoryEntry.zone)
                .filter(
                    BrainMemoryEntry.source_segment_id == segment_id,
                    BrainMemoryEntry.status != "soft-deleted",
                )
                .all()
            }
            if zones:
                if source_zone not in zones:
                    raise ValueError("skill_source_segment_wrong_zone")
                continue
            # pending/distilling segment 可能尚未产生 memory entry；允许引用真实存在的过渡态 segment。
            if self.session.get(BrainSegment, segment_id) is None:
                raise ValueError("skill_source_segment_wrong_zone")

    # Compatibility aliases for the business service layer.
    def get_skill(self, skill_id: str) -> BrainSkill | None:
        return self.get(skill_id)

    def list_source_segments(self, skill_id: str) -> list[BrainSkillSourceSegment]:
        return self.source_segments_for_skill(skill_id)

    def assert_no_same_name_active(
        self,
        name: str,
        *,
        excluding_skill_id: str | None = None,
    ) -> None:
        occupied = self.get_active_by_name(name, exclude_skill_id=excluding_skill_id)
        if occupied is not None:
            raise ValueError(f"skill_name_collision:{occupied.skill_id}")

    def get_chain_root_origin(self, skill_id: str) -> str | None:
        root = self.get_chain_root_skill(skill_id)
        return getattr(root, "origin", None)

    def increment_referenced_count_for_root(self, chain_root_id: str) -> bool:
        active = self.get_current_active_for_chain(chain_root_id)
        if active is None or active.status != "active":
            return False
        return self.increment_referenced_count(active.skill_id)

    @staticmethod
    def _validate_origin(origin: str) -> None:
        if origin not in SKILL_ORIGINS:
            raise ValueError(f"invalid skill origin: {origin}")

    @staticmethod
    def _validate_payload(
        *,
        name: str,
        description: str,
        trigger_conditions: list[str],
        body_markdown: str,
    ) -> None:
        if not str(name or "").strip():
            raise ValueError("skill name must not be empty")
        if not str(description or "").strip():
            raise ValueError("skill description must not be empty")
        if not str(body_markdown or "").strip():
            raise ValueError("skill body must not be empty")
        if not isinstance(trigger_conditions, list) or not [
            item for item in trigger_conditions if str(item).strip()
        ]:
            raise ValueError("skill trigger_conditions must contain at least one item")
