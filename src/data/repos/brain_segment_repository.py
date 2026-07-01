"""Segment persistence for the assistant brain."""

import logging
from typing import Optional

from sqlalchemy import text

from ..models_sqlite import BrainMemoryEntry, BrainSegment
from .base_repository import BaseRepository
from .brain_repository_common import _RecordId, _SEGMENT_UPDATE_COLUMNS
from src.utils.ids import new_id
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class BrainSegmentRepository(BaseRepository):
    """Repository for BrainSegment rows and segment completion transactions."""

    # ------------------------------------------------------------------
    # Segment CRUD
    # ------------------------------------------------------------------

    def create_segment(
        self,
        session_id: str,
        boundary_reason: str,
        message_id_start: Optional[str] = None,
        message_id_end: Optional[str] = None,
        segment_id: Optional[str] = None,
    ) -> str:
        """创建一个新的 segment（status='pending'），返回可当字符串使用的 segment 快照。"""
        segment_id = segment_id or new_id()
        now = utc_now_naive()
        segment = BrainSegment(
            segment_id=segment_id,
            session_id=session_id,
            status="pending",
            boundary_reason=boundary_reason,
            message_id_start=message_id_start,
            message_id_end=message_id_end,
            sealed_at=now,
            created_at=now,
            updated_at=now,
        )
        try:
            self.session.add(segment)
            self.session.commit()
            self.session.refresh(segment)
            logger.info("Segment 已创建: %s (session=%s)", segment_id, session_id)
            return _RecordId(segment_id, segment)
        except Exception as e:
            self.session.rollback()
            logger.error("创建 Segment 失败: %s", e)
            raise

    def get_segment_by_id(self, segment_id: str) -> Optional[BrainSegment]:
        """Compatibility alias for spec-kit tests and callers."""
        return self.get_segment(segment_id)

    def get_segment(self, segment_id: str) -> Optional[BrainSegment]:
        """按 ID 查询 Segment。"""
        segment_id = getattr(segment_id, "segment_id", segment_id)
        return (
            self.session.query(BrainSegment).filter(BrainSegment.segment_id == segment_id).first()
        )

    def get_segment_zone(self, segment_id: str) -> Optional[str]:
        """Return the visible zone for a distilled segment source, if any."""
        segment_id = getattr(segment_id, "segment_id", segment_id)
        row = (
            self.session.query(BrainMemoryEntry.zone)
            .filter(BrainMemoryEntry.source_segment_id == segment_id)
            .order_by(BrainMemoryEntry.created_at.desc())
            .first()
        )
        return row[0] if row else None

    def get_pending_segments(self) -> list[BrainSegment]:
        """返回所有 status='pending' 的 segment，按 created_at 升序。"""
        return (
            self.session.query(BrainSegment)
            .filter(BrainSegment.status == "pending")
            .order_by(BrainSegment.created_at)
            .all()
        )

    def get_distilling_segments(self) -> list[BrainSegment]:
        """返回所有 status='distilling' 的 segment（用于崩溃恢复）。"""
        return (
            self.session.query(BrainSegment)
            .filter(BrainSegment.status == "distilling")
            .order_by(BrainSegment.created_at)
            .all()
        )

    def transition_segment(
        self,
        segment_id: str,
        from_status: str,
        to_status: str,
        **updates,
    ) -> bool:
        return self.transition_segment_status(segment_id, from_status, to_status, **updates)

    def transition_segment_status(
        self,
        segment_id: str,
        from_status: str,
        to_status: str,
        **updates,
    ) -> bool:
        """
        原子 CAS 状态转换。

        使用 UPDATE WHERE status=from_status 实现 compare-and-swap，
        返回 True 表示恰好更新了 1 行（转换成功）。
        额外的列更新通过 **updates 传入。
        """
        segment_id = getattr(segment_id, "segment_id", segment_id)
        now = utc_now_naive()
        if to_status == "distilling":
            updates.setdefault("distilling_started_at", now)
        if to_status == "completed":
            updates.setdefault("completed_at", now)
        if from_status == "failed" and to_status == "pending":
            updates.setdefault("retry_count", text("retry_count + 1"))

        if updates:
            set_parts = []
            params = {
                "segment_id": segment_id,
                "from_status": from_status,
                "to_status": to_status,
            }
            for key, value in updates.items():
                if key not in _SEGMENT_UPDATE_COLUMNS:
                    allowed = ", ".join(sorted(_SEGMENT_UPDATE_COLUMNS))
                    raise ValueError(
                        f"Disallowed column in segment update: {key}. Allowed columns: {allowed}"
                    )
                if hasattr(value, "text"):
                    set_parts.append(f"{key} = {value.text}")
                else:
                    set_parts.append(f"{key} = :{key}")
                    params[key] = value
            set_clause = ", ".join(set_parts)
            sql = text(
                f"UPDATE brain_segments "
                f"SET status = :to_status, {set_clause}, updated_at = CURRENT_TIMESTAMP "
                f"WHERE segment_id = :segment_id AND status = :from_status"
            )
        else:
            sql = text(
                "UPDATE brain_segments "
                "SET status = :to_status, updated_at = CURRENT_TIMESTAMP "
                "WHERE segment_id = :segment_id AND status = :from_status"
            )
            params = {
                "segment_id": segment_id,
                "from_status": from_status,
                "to_status": to_status,
            }

        try:
            result = self.session.execute(sql, params)
            self.session.commit()
            success = result.rowcount == 1
            if success:
                logger.info("Segment %s: %s -> %s", segment_id, from_status, to_status)
            else:
                logger.warning(
                    "Segment CAS 失败: %s (期望 %s, 目标 %s), rowcount=%s",
                    segment_id,
                    from_status,
                    to_status,
                    result.rowcount,
                )
            return success
        except Exception as e:
            self.session.rollback()
            logger.error("Segment 状态转换失败: %s", e)
            raise

    def get_segments_by_status(self, status: str) -> list[BrainSegment]:
        return (
            self.session.query(BrainSegment)
            .filter(BrainSegment.status == status)
            .order_by(BrainSegment.created_at.asc())
            .all()
        )

    def get_segments_by_session(self, session_id: str) -> list[BrainSegment]:
        return (
            self.session.query(BrainSegment)
            .filter(BrainSegment.session_id == session_id)
            .order_by(BrainSegment.created_at.asc())
            .all()
        )

    def increment_retry_count(self, segment_id: str) -> None:
        """递增 segment 的 retry_count。"""
        sql = text(
            "UPDATE brain_segments "
            "SET retry_count = retry_count + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE segment_id = :segment_id"
        )
        try:
            self.session.execute(sql, {"segment_id": segment_id})
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error("递增 retry_count 失败: %s", e)
            raise

    def retry_distilling_segment(self, segment_id: str) -> bool:
        """Move a distilling segment back to pending and increment its retry count."""
        segment_id = getattr(segment_id, "segment_id", segment_id)
        sql = text(
            "UPDATE brain_segments "
            "SET status = 'pending', retry_count = retry_count + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE segment_id = :segment_id AND status = 'distilling'"
        )
        try:
            result = self.session.execute(sql, {"segment_id": segment_id})
            self.session.commit()
            success = result.rowcount == 1
            if success:
                logger.info("Segment %s: distilling -> pending (retry_count + 1)", segment_id)
            else:
                logger.warning(
                    "Segment retry CAS 失败: %s (期望 distilling), rowcount=%s",
                    segment_id,
                    result.rowcount,
                )
            return success
        except Exception as e:
            self.session.rollback()
            logger.error("Segment retry 状态转换失败: %s", e)
            raise

    def get_segments(
        self,
        status_filter: str = "all",
        limit: int = 20,
        offset: int = 0,
    ) -> list[BrainSegment]:
        """查询 Segments，支持按状态过滤。"""
        q = self.session.query(BrainSegment)
        if status_filter not in ("all", None):
            q = q.filter(BrainSegment.status == status_filter)
        return q.order_by(BrainSegment.created_at.desc()).offset(offset).limit(limit).all()

    def count_segments(self, status_filter: str = "all") -> int:
        """统计 Segments 数量。"""
        q = self.session.query(BrainSegment)
        if status_filter not in ("all", None):
            q = q.filter(BrainSegment.status == status_filter)
        return q.count()

    def complete_segment_with_entries(
        self,
        segment_id: str,
        entries: list[dict],
    ) -> list[str]:
        """Atomically insert distilled entries and mark the segment completed.

        This keeps the segment state and generated memories in the same database
        transaction, so a crash before commit cannot leave completed entries for
        a still-distilling segment or vice versa.
        """
        if not entries:
            entries = []
        created_ids: list[str] = []
        try:
            result = self.session.execute(
                text(
                    "UPDATE brain_segments "
                    "SET status = 'completed', completed_at = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE segment_id = :segment_id AND status = 'distilling'"
                ),
                {"segment_id": segment_id},
            )
            if result.rowcount != 1:
                self.session.rollback()
                logger.warning(
                    "Segment complete CAS failed: %s, rowcount=%s",
                    segment_id,
                    result.rowcount,
                )
                return []

            for entry_data in entries:
                entry_id = entry_data.get("entry_id") or new_id()
                entry = BrainMemoryEntry(
                    entry_id=entry_id,
                    zone=entry_data.get("zone", "hot"),
                    entry_type=entry_data.get("entry_type"),
                    content=entry_data["content"],
                    status=entry_data.get("status", "active"),
                    origin=entry_data.get("origin", "distillation"),
                    reason=entry_data["reason"],
                    scope=entry_data.get("scope"),
                    source_segment_id=entry_data.get("source_segment_id"),
                    source_session_id=entry_data.get("source_session_id"),
                    superseded_by=entry_data.get("superseded_by"),
                    relevance_score=entry_data.get("relevance_score", 1.0),
                    verification_checkpoint=entry_data.get("verification_checkpoint"),
                    verification_status=entry_data.get("verification_status"),
                    verification_rationale=entry_data.get("verification_rationale"),
                )
                self.session.add(entry)
                created_ids.append(entry_id)

            self.session.commit()
            logger.info(
                "Segment %s completed with %d distilled entries",
                segment_id,
                len(created_ids),
            )
            return created_ids
        except Exception as e:
            self.session.rollback()
            logger.error("完成 Segment 沉淀事务失败: %s", e)
            raise
