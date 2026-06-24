"""Memory entry persistence for the assistant brain."""

import logging
from typing import Optional

from sqlalchemy import text

from ..models_sqlite import BrainMemoryEntry, BrainSegment, FeedbackSignal
from .brain_feedback_repository import BrainFeedbackSignalRepository
from .brain_repository_common import _BRAIN_ZONES, _RecordId
from src.data.helpers import build_like_pattern
from src.utils.ids import new_id
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class BrainMemoryEntryRepository(BrainFeedbackSignalRepository):
    """Repository for brain memory entries and their evolution chain."""
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
        entry_id = entry_id or new_id()
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
            pattern = build_like_pattern(keyword)
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
            pattern = build_like_pattern(keyword)
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
            signal_id = new_id()
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
        new_entry_id = new_id()
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

        new_entry_id = new_id()
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
            return created_ids
        except Exception as e:
            self.session.rollback()
            logger.error("批量创建 Segment entries 失败: %s", e)
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
