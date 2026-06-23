"""
BrainRepository -- 大脑架构数据仓库

负责 BrainSegment、BrainMemoryEntry 和 FeedbackSignal 的 CRUD 操作。
Segment 状态流转使用 CAS (Compare-And-Swap) 保证原子性。
"""

import json
import logging
from typing import Optional
from uuid import uuid4

from sqlalchemy import text

from ..models_sqlite import BrainMemoryEntry, BrainRecruitmentSignal, BrainSegment, FeedbackSignal
from .base_repository import BaseRepository
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


def _new_id() -> str:
    """生成 50 字符的唯一 ID（两个 UUID4 hex 拼接后截取）。"""
    return (uuid4().hex + uuid4().hex)[:50]


_BRAIN_ZONES = ("hot", "persistent", "archive", "subconscious", "failure", "prediction")
_SEGMENT_UPDATE_COLUMNS = frozenset(
    {
        "all_empty_retried",
        "completed_at",
        "distilling_started_at",
        "message_id_end",
        "message_id_start",
        "retry_count",
        "sealed_at",
        "updated_at",
    }
)


class _RecordId(str):
    """String id with a snapshot of ORM attributes for legacy call sites."""

    def __new__(cls, value: str, source):
        obj = str.__new__(cls, value)
        for key, val in vars(source).items():
            if not key.startswith("_"):
                setattr(obj, key, val)
        return obj


def _append_json_list_item(raw: Optional[str], item: Optional[str], *, limit: int) -> str:
    """Append a non-empty item to a JSON string list while keeping recent examples bounded."""
    try:
        values = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        values = []
    if not isinstance(values, list):
        values = []
    if item:
        item_text = str(item).strip()
        if item_text and item_text not in values:
            values.append(item_text)
    return json.dumps(values[-limit:], ensure_ascii=False)


def _like_contains_pattern(keyword: str) -> str:
    term = str(keyword or "").strip()
    if not term:
        raise ValueError("keyword must not be empty")
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class BrainRepository(BaseRepository):
    """大脑架构数据仓库"""

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
        segment_id = segment_id or _new_id()
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

    # ------------------------------------------------------------------
    # Memory Entry CRUD
    # ------------------------------------------------------------------

    def create_entry(
        self,
        zone: str,
        content: str,
        origin: str,
        reason: str,
        source_segment_id: Optional[str] = None,
        source_session_id: Optional[str] = None,
        entry_type: Optional[str] = None,
        scope: Optional[str] = None,
        entry_id: Optional[str] = None,
        superseded_by: Optional[str] = None,
        relevance_score: float = 1.0,
        status: str = "active",
        verification_checkpoint: Optional[str] = None,
        verification_status: Optional[str] = None,
        verification_rationale: Optional[str] = None,
        commit: bool = True,
    ) -> str:
        """创建一条记忆条目，返回可当字符串使用的 entry 快照。"""
        entry_id = entry_id or _new_id()
        entry = BrainMemoryEntry(
            entry_id=entry_id,
            zone=zone,
            content=content,
            origin=origin,
            reason=reason,
            source_segment_id=source_segment_id,
            source_session_id=source_session_id,
            entry_type=entry_type,
            scope=scope,
            superseded_by=superseded_by,
            relevance_score=relevance_score,
            status=status,
            verification_checkpoint=verification_checkpoint,
            verification_status=verification_status,
            verification_rationale=verification_rationale,
        )
        try:
            self.session.add(entry)
            if commit:
                self.session.commit()
                self.session.refresh(entry)
            else:
                self.session.flush()
            logger.info("Memory entry 已创建: %s (zone=%s)", entry_id, zone)
            return _RecordId(entry_id, entry)
        except Exception as e:
            self.session.rollback()
            logger.error("创建 Memory entry 失败: %s", e)
            raise

    def get_entry_by_id(self, entry_id: str) -> Optional[BrainMemoryEntry]:
        """Compatibility alias for spec-kit tests and callers."""
        return self.get_entry(entry_id)

    def get_entry(self, entry_id: str) -> Optional[BrainMemoryEntry]:
        """按 ID 查询 Memory Entry。"""
        entry_id = getattr(entry_id, "entry_id", entry_id)
        return (
            self.session.query(BrainMemoryEntry)
            .filter(BrainMemoryEntry.entry_id == entry_id)
            .first()
        )

    def get_entries_by_zone(
        self,
        zone: str,
        status: Optional[str] = None,
        limit: Optional[int] = 50,
        offset: int = 0,
    ) -> list[BrainMemoryEntry]:
        """按 zone 查询记忆条目，默认排除 soft-deleted，返回 entry 列表。"""
        query = self.session.query(BrainMemoryEntry).filter(BrainMemoryEntry.zone == zone)
        if status is not None:
            if isinstance(status, (list, tuple, set)):
                query = query.filter(BrainMemoryEntry.status.in_(tuple(status)))
            else:
                query = query.filter(BrainMemoryEntry.status == status)
        else:
            query = query.filter(BrainMemoryEntry.status != "soft-deleted")

        query = query.order_by(BrainMemoryEntry.created_at.desc()).offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    def count_entries_by_zone(
        self,
        zone: str,
        status: Optional[str | list[str]] = None,
    ) -> int:
        query = self.session.query(BrainMemoryEntry).filter(BrainMemoryEntry.zone == zone)
        if status is not None:
            if isinstance(status, (list, tuple, set)):
                query = query.filter(BrainMemoryEntry.status.in_(tuple(status)))
            else:
                query = query.filter(BrainMemoryEntry.status == status)
        else:
            query = query.filter(BrainMemoryEntry.status != "soft-deleted")
        return query.count()

    def get_latest_distilled_segment_id(self) -> Optional[str]:
        """返回最近完成、且仍有 active hot/persistent 条目的 Segment ID。

        跨 Segment 的 prediction / subconscious 任务用它做"段身份"去重：只要这一段与上次
        任务输出标记的 Segment 相同，就说明没有新的可消费蒸馏材料，可跳过本轮 LLM 调用。
        按 Segment 完成顺序（completed_at）排序，而非条目时间戳，因此不受用户编辑旧条目
        （沿用旧段 ID 但刷新 created_at）或系统时钟回拨影响。无可用段时返回 None，调用方据此
        保守运行，绝不漏蒸馏。
        """
        has_live_entry = (
            self.session.query(BrainMemoryEntry.entry_id)
            .filter(
                BrainMemoryEntry.source_segment_id == BrainSegment.segment_id,
                BrainMemoryEntry.zone.in_(("hot", "persistent")),
                BrainMemoryEntry.status == "active",
            )
            .exists()
        )
        row = (
            self.session.query(BrainSegment.segment_id)
            .filter(BrainSegment.status == "completed", has_live_entry)
            .order_by(BrainSegment.completed_at.desc(), BrainSegment.segment_id.desc())
            .first()
        )
        return row[0] if row else None

    def get_latest_output_segment_marker(self, zone: str, origin: str) -> Optional[str]:
        """返回指定 zone+origin 最近一条输出条目记录的 source_segment_id 段标记。

        prediction / subconscious 任务每次运行时会把产出的条目标记为当时处理的最新
        Segment ID；下一轮用它与 get_latest_distilled_segment_id() 比较来判断是否已处理过
        该段。无输出或未标记时返回 None。
        """
        row = (
            self.session.query(BrainMemoryEntry.source_segment_id)
            .filter(
                BrainMemoryEntry.zone == zone,
                BrainMemoryEntry.origin == origin,
            )
            .order_by(
                BrainMemoryEntry.created_at.desc(),
                BrainMemoryEntry.entry_id.desc(),
            )
            .first()
        )
        return row[0] if row else None

    def search_archive_entries(
        self,
        query: str,
        limit: int = 50,
    ) -> list[BrainMemoryEntry]:
        """Search archive entries by keyword while preserving repository ownership.

        Invalidated entries are included so callers can apply the required
        degraded fallback ranking. Soft-deleted entries remain excluded.
        """
        keywords = [part.strip() for part in query.split() if part.strip()]
        if not keywords:
            return []

        search = self.session.query(BrainMemoryEntry).filter(
            BrainMemoryEntry.zone == "archive",
            BrainMemoryEntry.status.in_(("active", "invalidated")),
        )
        for keyword in keywords:
            pattern = _like_contains_pattern(keyword)
            search = search.filter(
                (BrainMemoryEntry.content.like(pattern, escape="\\"))
                | (BrainMemoryEntry.reason.like(pattern, escape="\\"))
            )

        return search.order_by(BrainMemoryEntry.relevance_score.desc()).limit(limit).all()

    def search_entries(
        self,
        zone: str,
        query: str,
        *,
        statuses: Optional[list[str] | tuple[str, ...] | set[str]] = None,
        limit: int = 50,
    ) -> list[BrainMemoryEntry]:
        """Search entries in one zone by keyword while excluding soft-deleted rows."""
        keywords = [part.strip() for part in (query or "").split() if part.strip()]
        if not keywords:
            return []

        search = self.session.query(BrainMemoryEntry).filter(BrainMemoryEntry.zone == zone)
        if statuses is None:
            search = search.filter(BrainMemoryEntry.status != "soft-deleted")
        else:
            search = search.filter(BrainMemoryEntry.status.in_(tuple(statuses)))

        for keyword in keywords:
            pattern = _like_contains_pattern(keyword)
            search = search.filter(
                (BrainMemoryEntry.content.like(pattern, escape="\\"))
                | (BrainMemoryEntry.reason.like(pattern, escape="\\"))
            )

        return (
            search.order_by(
                BrainMemoryEntry.relevance_score.desc(), BrainMemoryEntry.created_at.desc()
            )
            .limit(limit)
            .all()
        )

    def update_entry_status(self, entry_id: str, new_status: str) -> bool:
        """更新 entry 的 status，返回 True 表示找到并更新。"""
        entry_id = getattr(entry_id, "entry_id", entry_id)
        entry = self.get_entry(entry_id)
        if entry is None:
            return False
        try:
            entry.status = new_status
            self.session.commit()
            logger.info("Entry %s status -> %s", entry_id, new_status)
            return True
        except Exception as e:
            self.session.rollback()
            logger.error("更新 entry status 失败: %s", e)
            raise

    def invalidate_entry(self, entry_id: str, reason: str) -> bool:
        """Mark an entry invalidated and record a feedback signal.

        原子条件 UPDATE：只在条目仍非 soft-deleted 时置为 invalidated，避免与后台 decay
        并发时把已软删条目“复活”成 invalidated、断掉演化链。读写之间被并发软删则返回 False。
        """
        entry_id = getattr(entry_id, "entry_id", entry_id)
        entry = self.get_entry(entry_id)
        if entry is None or entry.status == "soft-deleted":
            return False
        try:
            invalidated = (
                self.session.query(BrainMemoryEntry)
                .filter(
                    BrainMemoryEntry.entry_id == entry_id,
                    BrainMemoryEntry.status != "soft-deleted",
                )
                .update(
                    {"status": "invalidated", "updated_at": utc_now_naive()},
                    synchronize_session=False,
                )
            )
            if not invalidated:
                # 读写之间被并发软删：不复活、不建 feedback。
                return False
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error("Entry invalidation failed: %s", e)
            raise
        # 信号写失败不回滚已完成的 invalidation，独立处理
        try:
            signal_id = _new_id()
            self.session.add(
                FeedbackSignal(
                    signal_id=signal_id,
                    zone=entry.zone,
                    operation="invalidate",
                    target_id=entry_id,
                    context_summary=f"{reason}: {entry.content[:200]}",
                )
            )
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.warning(
                "Feedback signal for invalidation failed (entry already invalidated): %s", e
            )
        return True

    def supersede_entry(
        self,
        old_entry_id: str,
        new_content: str,
        reason: str,
        *,
        origin: str = "system_supersession",
    ) -> Optional[str]:
        """Create a replacement entry and soft-delete the old one through superseded_by.

        原子条件 UPDATE 守卫旧条目软删：只在仍非 soft-deleted 时执行，赢了才建后继条目。
        与后台 decay 并发时，若旧条目已被 decay 软删（已自带后继），放弃本次 supersede
        返回 None，避免演化链分叉。
        """
        old_entry = self.get_entry(old_entry_id)
        if old_entry is None:
            return None
        new_entry_id = _new_id()
        try:
            superseded = (
                self.session.query(BrainMemoryEntry)
                .filter(
                    BrainMemoryEntry.entry_id == old_entry_id,
                    BrainMemoryEntry.status != "soft-deleted",
                )
                .update(
                    {"status": "soft-deleted", "superseded_by": new_entry_id},
                    synchronize_session=False,
                )
            )
            if not superseded:
                # 旧条目已被并发软删（通常 decay 已建后继）：放弃，不新建条目、不分叉链。
                return None
            replacement = BrainMemoryEntry(
                entry_id=new_entry_id,
                zone=old_entry.zone,
                content=new_content,
                status="active",
                origin=origin,
                reason=reason,
                scope=old_entry.scope,
                entry_type=old_entry.entry_type,
                source_segment_id=old_entry.source_segment_id,
                source_session_id=old_entry.source_session_id,
                relevance_score=old_entry.relevance_score,
            )
            self.session.add(replacement)
            self.session.commit()
            return new_entry_id
        except Exception as e:
            self.session.rollback()
            logger.error("Entry supersession failed: %s", e)
            raise

    def soft_delete_entry(
        self,
        entry_id: str,
        superseded_by: Optional[str] = None,
        feedback_operation: Optional[str] = None,
        commit: bool = True,
    ) -> bool:
        """软删除 entry（status='soft-deleted'），可选设置 superseded_by。返回 True 表示成功。

        原子条件 UPDATE：只软删仍非 soft-deleted 的条目，由数据库保证并发只有一个成功
        （避免后台衰减与用户删除并发时重复创建 feedback signal，或衰减路由重复建 archive 条目）。
        对已是 soft-deleted 的条目返回 False——不重复软删、不创建 feedback。
        """
        entry_id = getattr(entry_id, "entry_id", entry_id)
        superseded_by = getattr(superseded_by, "entry_id", superseded_by)
        # 先读：feedback signal 需要 entry.content/zone；也用于判断条目是否存在。
        entry = self.get_entry(entry_id)
        if entry is None:
            return False
        try:
            values = {"status": "soft-deleted"}
            if superseded_by is not None:
                values["superseded_by"] = superseded_by
            superseded = (
                self.session.query(BrainMemoryEntry)
                .filter(
                    BrainMemoryEntry.entry_id == entry_id,
                    BrainMemoryEntry.status != "soft-deleted",
                )
                .update(values, synchronize_session=False)
            )
            if not superseded:
                # 已被并发软删（或本就是 soft-deleted）：不创建 feedback、不重复软删。
                return False
            if commit:
                self.session.commit()
            else:
                self.session.flush()
            if feedback_operation:
                if not commit:
                    raise ValueError("feedback_operation requires commit=True")
                self.create_feedback_signal(
                    zone=entry.zone,
                    operation=feedback_operation,
                    target_id=entry_id,
                    context_summary=entry.content[:200],
                )
            logger.info("Entry %s 已软删除", entry_id)
            return True
        except Exception as e:
            self.session.rollback()
            logger.error("软删除 entry 失败: %s", e)
            raise

    def user_edit_entry(
        self,
        old_entry_id: str,
        new_content: str,
        new_scope: Optional[str] = None,
    ) -> Optional[str]:
        """用户编辑 entry：旧条目 soft-delete + 创建新条目 + superseded_by 链接。

        原子条件 UPDATE 守卫旧条目软删：只在仍非 soft-deleted 时执行，赢了才建新条目。
        与后台 decay 并发时若旧条目已被软删，放弃编辑返回 None，避免演化链分叉。

        Returns:
            新 entry_id，失败/被并发软删返回 None
        """
        old_entry = self.get_entry(old_entry_id)
        if old_entry is None:
            return None

        new_entry_id = _new_id()
        try:
            superseded = (
                self.session.query(BrainMemoryEntry)
                .filter(
                    BrainMemoryEntry.entry_id == old_entry_id,
                    BrainMemoryEntry.status != "soft-deleted",
                )
                .update(
                    {"status": "soft-deleted", "superseded_by": new_entry_id},
                    synchronize_session=False,
                )
            )
            if not superseded:
                # 旧条目已被并发软删：放弃编辑，不新建条目、不分叉演化链。
                return None

            new_entry = BrainMemoryEntry(
                entry_id=new_entry_id,
                zone=old_entry.zone,
                content=new_content,
                status="active",
                origin="user_edit",
                reason="User manual edit",
                scope=new_scope if new_scope is not None else old_entry.scope,
                entry_type=old_entry.entry_type,
                source_segment_id=old_entry.source_segment_id,
                source_session_id=old_entry.source_session_id,
                superseded_by=None,
            )
            self.session.add(new_entry)
            self.session.commit()

            self.create_feedback_signal(
                zone=old_entry.zone,
                operation="edit",
                target_id=old_entry_id,
                context_summary=old_entry.content[:200],
            )

            logger.info("Entry %s edited -> %s", old_entry_id, new_entry_id)
            return new_entry_id
        except Exception as e:
            self.session.rollback()
            logger.error("User edit entry 失败: %s", e)
            raise

    def batch_update_referenced_counts(self, entry_ids: list[str]) -> None:
        """批量递增指定 entry 的 referenced_count。"""
        if not entry_ids:
            return
        placeholders = ", ".join(f":eid_{i}" for i in range(len(entry_ids)))
        params = {f"eid_{i}": eid for i, eid in enumerate(entry_ids)}
        sql = text(
            "UPDATE brain_memory_entries "
            "SET referenced_count = referenced_count + 1, updated_at = CURRENT_TIMESTAMP "
            f"WHERE entry_id IN ({placeholders})"
        )
        try:
            self.session.execute(sql, params)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error("批量更新 referenced_count 失败: %s", e)
            raise

    def batch_increment_referenced_count(self, entry_ids: list[str]) -> None:
        """Compatibility alias for singular method naming."""
        self.batch_update_referenced_counts(entry_ids)

    def batch_increment_loaded_counts(self, entry_ids: list[str]) -> None:
        """批量递增指定 entry 的 loaded_count。"""
        if not entry_ids:
            return
        placeholders = ", ".join(f":eid_{i}" for i in range(len(entry_ids)))
        params = {f"eid_{i}": eid for i, eid in enumerate(entry_ids)}
        sql = text(
            "UPDATE brain_memory_entries "
            "SET loaded_count = loaded_count + 1, updated_at = CURRENT_TIMESTAMP "
            f"WHERE entry_id IN ({placeholders})"
        )
        try:
            self.session.execute(sql, params)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error("批量更新 loaded_count 失败: %s", e)
            raise

    def batch_increment_loaded_count(self, entry_ids: list[str]) -> None:
        """Compatibility alias for callers/tests using singular method naming."""
        self.batch_increment_loaded_counts(entry_ids)

    def create_entries_for_segment(self, entries: list[dict]) -> list[str]:
        """Atomically insert a batch of memory entries for one distilled segment."""
        if not entries:
            return []
        created_ids: list[str] = []
        try:
            for entry_data in entries:
                entry_id = entry_data.get("entry_id") or _new_id()
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
            return created_ids
        except Exception as e:
            self.session.rollback()
            logger.error("批量创建 Segment entries 失败: %s", e)
            raise

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
                entry_id = entry_data.get("entry_id") or _new_id()
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

    def create_prediction_entry(
        self,
        content: str,
        reason: str,
        verification_checkpoint: str,
        *,
        source_session_id: Optional[str] = None,
        source_segment_id: Optional[str] = None,
    ) -> str:
        """Create a prediction-zone entry."""
        return self.create_entry(
            zone="prediction",
            content=content,
            origin="prediction_generation",
            reason=reason,
            source_session_id=source_session_id,
            source_segment_id=source_segment_id,
            verification_checkpoint=verification_checkpoint,
        )

    def get_prediction_context_entries(
        self,
        hot_limit: int = 10,
        persistent_limit: int = 5,
        verified_limit: int = 5,
    ) -> dict[str, list[BrainMemoryEntry]]:
        """Return recent entries used by the prediction service."""
        hot = (
            self.session.query(BrainMemoryEntry)
            .filter(BrainMemoryEntry.zone == "hot", BrainMemoryEntry.status == "active")
            .order_by(BrainMemoryEntry.created_at.desc())
            .limit(hot_limit)
            .all()
        )
        persistent = (
            self.session.query(BrainMemoryEntry)
            .filter(
                BrainMemoryEntry.zone == "persistent",
                BrainMemoryEntry.status == "active",
            )
            .order_by(BrainMemoryEntry.created_at.desc())
            .limit(persistent_limit)
            .all()
        )
        verified_predictions = (
            self.session.query(BrainMemoryEntry)
            .filter(
                BrainMemoryEntry.zone == "prediction",
                BrainMemoryEntry.verification_status.isnot(None),
            )
            .order_by(BrainMemoryEntry.updated_at.desc())
            .limit(verified_limit)
            .all()
        )
        return {
            "hot": hot,
            "persistent": persistent,
            "verified_predictions": verified_predictions,
        }

    def get_pending_prediction_entries(self) -> list[BrainMemoryEntry]:
        """Return active predictions that have not been verified yet."""
        return (
            self.session.query(BrainMemoryEntry)
            .filter(
                BrainMemoryEntry.zone == "prediction",
                BrainMemoryEntry.status == "active",
                BrainMemoryEntry.verification_status.is_(None),
                BrainMemoryEntry.verification_checkpoint.isnot(None),
            )
            .order_by(BrainMemoryEntry.created_at.asc())
            .all()
        )

    def get_entries_for_prediction_verification(
        self,
        prediction_entry: BrainMemoryEntry,
        limit: int = 50,
    ) -> list[BrainMemoryEntry]:
        """Return non-prediction memories from the prediction's verification period."""
        created_at = getattr(prediction_entry, "created_at", None)
        base_query = self.session.query(BrainMemoryEntry).filter(
            BrainMemoryEntry.zone != "prediction",
            BrainMemoryEntry.status != "soft-deleted",
        )
        query = base_query
        if created_at is not None:
            query = query.filter(BrainMemoryEntry.created_at >= created_at)
        rows = query.order_by(BrainMemoryEntry.created_at.asc()).limit(limit).all()
        if rows or created_at is None:
            return rows
        # SQLite timestamp precision can make same-tick test/setup rows appear
        # before the prediction. Fall back to recent non-prediction memories so
        # verification still has evidence instead of silently assessing nothing.
        return base_query.order_by(BrainMemoryEntry.created_at.desc()).limit(limit).all()

    def count_prediction_verification_failures(self, entry_id: str) -> int:
        """Return the number of failed verification attempts recorded for one prediction."""
        return (
            self.session.query(FeedbackSignal)
            .filter(
                FeedbackSignal.zone == "prediction",
                FeedbackSignal.operation == "verification_failed",
                FeedbackSignal.target_id == entry_id,
            )
            .count()
        )

    def record_prediction_verification_failure(self, entry_id: str, reason: str) -> str:
        """Record one failed prediction-verification attempt for bounded retry handling."""
        return self.create_feedback_signal(
            zone="prediction",
            operation="verification_failed",
            target_id=entry_id,
            context_summary=(reason or "verification failed")[:500],
        )

    def update_prediction_verification(
        self,
        entry_id: str,
        status: str,
        rationale: str = "",
    ) -> bool:
        entry = self.get_entry(entry_id)
        if entry is None or entry.zone != "prediction":
            return False
        try:
            entry.verification_status = status
            entry.verification_rationale = rationale
            if entry.status == "active":  # 只从 active 降级，不覆盖 invalidated/archived 等状态
                entry.status = "fading"
            entry.updated_at = utc_now_naive()
            self.session.commit()
            return True
        except Exception as e:
            self.session.rollback()
            logger.error("Prediction verification update failed: %s", e)
            raise

    def apply_invalidation_review_decay(self, factor: float = 0.9) -> int:
        """Periodically degrade invalidated entries without deleting them."""
        try:
            result = self.session.execute(
                text(
                    "UPDATE brain_memory_entries "
                    "SET relevance_score = CASE "
                    "WHEN relevance_score * :factor < 0.01 THEN 0.01 "
                    "ELSE relevance_score * :factor END, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE status = 'invalidated'"
                ),
                {"factor": factor},
            )
            self.session.commit()
            return int(result.rowcount or 0)
        except Exception as e:
            self.session.rollback()
            logger.error("Invalidation review decay failed: %s", e)
            raise

    def get_evolution_chain(self, entry_id: str) -> list[BrainMemoryEntry]:
        """
        沿 superseded_by 链追溯，返回从最旧到最新的演进链。

        superseded_by 语义：当前 entry 的 superseded_by 指向取代它的新 entry_id。
        因此沿 superseded_by 是往"新"方向走，反向查找 superseded_by == current
        是往"旧"方向走。

        返回列表按时间从旧到新排列。
        """
        chain: list[BrainMemoryEntry] = []
        visited: set[str] = set()

        # 第一步：从 entry_id 向旧方向走，找到链头（最旧的 entry）
        head_id = entry_id
        step1_visited: set[str] = set()
        while head_id not in step1_visited:
            step1_visited.add(head_id)
            predecessor = (
                self.session.query(BrainMemoryEntry)
                .filter(BrainMemoryEntry.superseded_by == head_id)
                .first()
            )
            if predecessor is None:
                break
            head_id = predecessor.entry_id

        # 第二步：从链头沿 superseded_by 向新方向遍历整条链
        current_id: Optional[str] = head_id
        while current_id and current_id not in visited:
            entry = self.get_entry(current_id)
            if entry is None:
                break
            visited.add(current_id)
            chain.append(entry)
            current_id = entry.superseded_by

        return chain

    def get_zone_summaries(self) -> list[dict]:
        """返回各分区的统计摘要：zone 名称、active 条目数、fading 条目数。"""
        sql = text(
            "SELECT zone, "
            "  SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_count, "
            "  SUM(CASE WHEN status = 'fading' THEN 1 ELSE 0 END) AS fading_count "
            "FROM brain_memory_entries "
            "WHERE status IN ('active', 'fading') "
            "GROUP BY zone "
            "ORDER BY zone"
        )
        try:
            result = self.session.execute(sql)
            counts = {}
            for row in result:
                counts[row[0]] = {
                    "entry_count": (row[1] or 0) + (row[2] or 0),
                    "fading_count": row[2] or 0,
                }
            summaries = []
            for zone in _BRAIN_ZONES:
                zone_counts = counts.get(
                    zone,
                    {"entry_count": 0, "fading_count": 0},
                )
                summaries.append(
                    {
                        "zone": zone,
                        "entry_count": zone_counts["entry_count"],
                        "fading_count": zone_counts["fading_count"],
                    }
                )
            return summaries
        except Exception as e:
            logger.error("获取 zone summaries 失败: %s", e)
            raise

    # ------------------------------------------------------------------
    # Feedback Signal
    # ------------------------------------------------------------------

    def create_feedback_signal(
        self,
        zone: str,
        operation: str,
        target_id: str,
        context_summary: str,
    ) -> str:
        """创建一条反馈信号，返回 signal_id。"""
        signal_id = _new_id()
        signal = FeedbackSignal(
            signal_id=signal_id,
            zone=zone,
            operation=operation,
            target_id=target_id,
            context_summary=context_summary,
        )
        try:
            self.session.add(signal)
            self.session.commit()
            logger.info(
                "Feedback signal 已创建: %s (zone=%s, op=%s)",
                signal_id,
                zone,
                operation,
            )
            return signal_id
        except Exception as e:
            self.session.rollback()
            logger.error("创建 feedback signal 失败: %s", e)
            raise

    def get_recent_feedback_signals(
        self,
        zone: Optional[str] = None,
        limit: int = 10,
    ) -> list[FeedbackSignal]:
        """Return recent edit/delete/invalidation signals for prompt injection."""
        query = self.session.query(FeedbackSignal)
        if zone is not None:
            query = query.filter(FeedbackSignal.zone == zone)
        return query.order_by(FeedbackSignal.created_at.desc()).limit(limit).all()

    def mark_skill_pool_removed(
        self,
        tool_id: str,
        identifiers: set[str] | list[str] | tuple[str, ...],
        *,
        commit: bool = True,
    ) -> str:
        """Persist an assistant skill-pool exclusion."""
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            raise ValueError("tool_id must not be empty")
        payload = json.dumps(
            {"identifiers": sorted(str(item) for item in identifiers if str(item).strip())},
            ensure_ascii=False,
        )
        signal = (
            self.session.query(FeedbackSignal)
            .filter(
                FeedbackSignal.zone == "specialist",
                FeedbackSignal.operation == "skill_pool_remove",
                FeedbackSignal.target_id == tool_id,
            )
            .first()
        )
        try:
            if signal is None:
                signal = FeedbackSignal(
                    signal_id=_new_id(),
                    zone="specialist",
                    operation="skill_pool_remove",
                    target_id=tool_id,
                    context_summary=payload,
                )
                self.session.add(signal)
            else:
                signal.context_summary = payload
            if commit:
                self.session.commit()
            else:
                self.session.flush()
            return signal.signal_id
        except Exception as e:
            self.session.rollback()
            logger.error("Skill pool exclusion write failed: %s", e)
            raise

    def get_removed_skill_pool_identifiers(self) -> set[str]:
        """Return tool ids/names excluded from the assistant skill pool."""
        rows = (
            self.session.query(FeedbackSignal)
            .filter(
                FeedbackSignal.zone == "specialist",
                FeedbackSignal.operation == "skill_pool_remove",
            )
            .all()
        )
        removed: set[str] = set()
        for row in rows:
            target_id = str(getattr(row, "target_id", "") or "").strip()
            if target_id:
                removed.add(target_id)
            try:
                payload = json.loads(getattr(row, "context_summary", "") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            identifiers = payload.get("identifiers", [])
            if isinstance(identifiers, list):
                removed.update(str(item) for item in identifiers if str(item).strip())
        return removed

    def get_recruitment_signals_for_scan(
        self,
        min_count: int,
    ) -> list[BrainRecruitmentSignal]:
        """Return unconsumed recruitment signals that reached the threshold."""
        return (
            self.session.query(BrainRecruitmentSignal)
            .filter(
                BrainRecruitmentSignal.delegation_count >= min_count,
                BrainRecruitmentSignal.specialist_id.is_(None),
            )
            .order_by(BrainRecruitmentSignal.updated_at.desc())
            .all()
        )

    def record_recruitment_signal(
        self,
        task_pattern: str,
        session_id: Optional[str] = None,
        delegation_summary: Optional[str] = None,
    ) -> str:
        """Record one delegation occurrence for automatic specialist recruitment."""
        normalized_pattern = (task_pattern or "").strip()[:500]
        if not normalized_pattern:
            raise ValueError("task_pattern must not be empty")

        signal = (
            self.session.query(BrainRecruitmentSignal)
            .filter(
                BrainRecruitmentSignal.task_pattern == normalized_pattern,
                BrainRecruitmentSignal.specialist_id.is_(None),
            )
            .first()
        )
        try:
            if signal is None:
                signal = BrainRecruitmentSignal(
                    signal_id=_new_id(),
                    task_pattern=normalized_pattern,
                    delegation_count=0,
                    example_session_ids="[]",
                    example_delegation_summaries="[]",
                )
                self.session.add(signal)
                self.session.flush()

            signal.delegation_count = int(signal.delegation_count or 0) + 1
            signal.example_session_ids = _append_json_list_item(
                signal.example_session_ids,
                session_id,
                limit=8,
            )
            signal.example_delegation_summaries = _append_json_list_item(
                signal.example_delegation_summaries,
                delegation_summary,
                limit=8,
            )
            self.session.commit()
            return signal.signal_id
        except Exception as e:
            self.session.rollback()
            logger.error("Recruitment signal record failed: %s", e)
            raise

    def mark_recruitment_signal_consumed(
        self,
        signal_id: str,
        specialist_id: str,
        *,
        commit: bool = True,
    ) -> bool:
        signal = (
            self.session.query(BrainRecruitmentSignal)
            .filter(BrainRecruitmentSignal.signal_id == signal_id)
            .first()
        )
        if signal is None:
            return False
        try:
            signal.specialist_id = specialist_id
            if commit:
                self.session.commit()
            else:
                self.session.flush()
            return True
        except Exception as e:
            self.session.rollback()
            logger.error("Recruitment signal update failed: %s", e)
            raise
