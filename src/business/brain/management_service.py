"""Business facade for brain management API operations."""

from __future__ import annotations

from typing import Optional

from src.business.brain.models import SegmentStatus, ZONE_LABELS, Zone
from src.data.repos.brain_repository import BrainRepository
from src.utils.events import emit


class BrainManagementService:
    """Expose user-facing brain management operations without leaking repositories to API adapters."""

    def __init__(self, repo: Optional[BrainRepository] = None):
        self._repo = repo or BrainRepository()

    def get_zones(self) -> list[dict]:
        counts = {summary["zone"]: summary for summary in self._repo.get_zone_summaries()}
        return [
            {
                "zone": zone.value,
                "label": ZONE_LABELS[zone],
                "entry_count": counts.get(zone.value, {}).get("entry_count", 0),
                "fading_count": counts.get(zone.value, {}).get("fading_count", 0),
            }
            for zone in Zone
        ]

    def get_zone_entries(
        self,
        zone: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        self._validate_zone(zone)
        statuses = status.split(",") if status else None
        entries = self._repo.get_entries_by_zone(zone, status=statuses, limit=limit, offset=offset)
        total = self._repo.count_entries_by_zone(zone, status=statuses)
        return [self._entry_to_dict(entry) for entry in entries], total

    def get_segments(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str = "all",
    ) -> tuple[list[dict], int]:
        segments = self._repo.get_segments(status_filter=status, limit=limit, offset=offset)
        total = self._repo.count_segments(status_filter=status)
        return [self._segment_to_dict(segment) for segment in segments], total

    def retry_segment(self, segment_id: str) -> dict:
        segment = self._repo.get_segment(segment_id)
        if segment is None:
            raise KeyError("segment_not_found")
        if getattr(segment, "status", "") != SegmentStatus.FAILED.value:
            raise ValueError("segment_not_failed")

        success = self._repo.transition_segment(
            segment_id,
            from_status=SegmentStatus.FAILED.value,
            to_status=SegmentStatus.PENDING.value,
        )
        if not success:
            raise RuntimeError("transition_failed")

        from src.business.brain.background_worker import notify_brain_worker

        notify_brain_worker()
        return {"segment_id": segment_id, "status": SegmentStatus.PENDING.value}

    def get_entry_evolution(self, entry_id: str) -> list[dict]:
        chain = self._repo.get_evolution_chain(entry_id)
        if not chain:
            raise KeyError("entry_not_found")
        return [self._entry_to_dict(entry) for entry in chain]

    def edit_entry(self, entry_id: str, *, content: str, scope: Optional[str] = None) -> dict:
        entry = self._repo.get_entry(entry_id)
        if entry is None or getattr(entry, "status", "") == "soft-deleted":
            raise KeyError("entry_not_found")
        if not content:
            raise ValueError("content_required")

        new_entry_id = self._repo.user_edit_entry(
            entry_id,
            new_content=content,
            new_scope=scope,
        )
        if new_entry_id is None:
            raise RuntimeError("entry_edit_failed")
        new_entry = self._repo.get_entry(new_entry_id)
        emit(
            "brain_zone_changed",
            zone=getattr(entry, "zone", ""),
            entry_id=new_entry_id,
            operation="edit",
        )
        return self._entry_to_dict(new_entry)

    def soft_delete_entry(self, entry_id: str) -> None:
        entry = self._repo.get_entry(entry_id)
        if entry is None:
            raise KeyError("entry_not_found")
        self._repo.soft_delete_entry(entry_id, feedback_operation="delete")
        emit(
            "brain_zone_changed",
            zone=getattr(entry, "zone", ""),
            entry_id=entry_id,
            operation="soft_delete",
        )

    @staticmethod
    def _validate_zone(zone: str) -> None:
        if zone not in {item.value for item in Zone}:
            raise ValueError("invalid_zone")

    @staticmethod
    def _entry_to_dict(entry) -> dict:
        return {
            "entry_id": getattr(entry, "entry_id", ""),
            "zone": getattr(entry, "zone", ""),
            "entry_type": getattr(entry, "entry_type", None),
            "content": getattr(entry, "content", ""),
            "status": getattr(entry, "status", ""),
            "origin": getattr(entry, "origin", ""),
            "reason": getattr(entry, "reason", ""),
            "scope": getattr(entry, "scope", None),
            "loaded_count": getattr(entry, "loaded_count", 0),
            "referenced_count": getattr(entry, "referenced_count", 0),
            "superseded_by": getattr(entry, "superseded_by", None),
            "verification_checkpoint": getattr(entry, "verification_checkpoint", None),
            "verification_status": getattr(entry, "verification_status", None),
            "verification_rationale": getattr(entry, "verification_rationale", None),
            "created_at": getattr(entry, "created_at", None),
            "updated_at": getattr(entry, "updated_at", None),
        }

    @staticmethod
    def _segment_to_dict(segment) -> dict:
        return {
            "segment_id": getattr(segment, "segment_id", ""),
            "session_id": getattr(segment, "session_id", ""),
            "status": getattr(segment, "status", ""),
            "retry_count": getattr(segment, "retry_count", 0),
            "boundary_reason": getattr(segment, "boundary_reason", None),
            "sealed_at": getattr(segment, "sealed_at", None),
            "completed_at": getattr(segment, "completed_at", None),
            "created_at": getattr(segment, "created_at", None),
        }
