"""
Segment 边界服务 - 管理 Segment 的封存与边界触发
"""

import logging
from datetime import datetime
from typing import Optional
from src.utils.events import emit

logger = logging.getLogger(__name__)


class SegmentService:
    """管理 Segment 的封存与边界触发"""

    def __init__(self, repo=None):
        self._repo = repo

    def _get_repo(self):
        if self._repo is None:
            from src.data.repos.brain_repository import BrainRepository
            self._repo = BrainRepository()
        return self._repo

    def seal_segment(
        self,
        session_id: str,
        boundary_reason: str,
        message_id_start: Optional[str] = None,
        message_id_end: Optional[str] = None,
    ) -> Optional[str]:
        """封存当前 open segment 为 pending 状态。

        Args:
            session_id: 所属会话 ID
            boundary_reason: 边界触发原因
            message_id_start: 第一条消息 ID
            message_id_end: 最后一条消息 ID

        Returns:
            segment_id，如果成功封存
        """
        repo = self._get_repo()
        if message_id_start is None or message_id_end is None:
            inferred_start, inferred_end = self._infer_message_range(session_id)
            message_id_start = message_id_start or inferred_start
            message_id_end = message_id_end or inferred_end
            if message_id_start is None or message_id_end is None:
                logger.info(
                    "Segment seal skipped: no new messages for session=%s reason=%s",
                    session_id,
                    boundary_reason,
                )
                return None
        segment = repo.create_segment(
            session_id=session_id,
            boundary_reason=boundary_reason,
            message_id_start=message_id_start,
            message_id_end=message_id_end,
        )
        segment_id = getattr(segment, "segment_id", str(segment))

        emit(
            "segment_boundary_triggered",
            session_id=session_id,
            segment_id=segment_id,
            reason=boundary_reason,
        )
        logger.info(
            "Segment sealed: %s, session=%s, reason=%s",
            segment_id, session_id, boundary_reason,
        )
        return segment_id

    def handle_idle_trigger(self, session_id: str) -> Optional[str]:
        """处理前端空闲计时器触发。

        Args:
            session_id: 所属会话 ID

        Returns:
            segment_id，如果成功封存
        """
        emit("segment_idle_trigger", session_id=session_id)
        return self.seal_segment(session_id, boundary_reason="idle")

    def _infer_message_range(self, session_id: str) -> tuple[Optional[str], Optional[str]]:
        """Infer the unsealed user-visible message range for the session."""
        try:
            from src.data.repositories import MessageRepository
        except ImportError:
            return None, None

        try:
            messages = [
                msg
                for msg in MessageRepository().get_context(session_id)
                if msg.role in {"user", "assistant"} and (msg.content or "").strip()
            ]
        except Exception as exc:
            logger.warning("Failed to infer Segment message range: %s", exc)
            return None, None

        if not messages:
            return None, None

        sequence_by_id = {
            getattr(msg, "message_id", ""): getattr(msg, "sequence", 0)
            for msg in messages
        }
        last_sealed_sequence = 0
        repo = self._get_repo()
        try:
            for segment in repo.get_segments_by_session(session_id):
                end_id = getattr(segment, "message_id_end", None)
                if end_id in sequence_by_id:
                    last_sealed_sequence = max(last_sealed_sequence, sequence_by_id[end_id])
        except Exception as exc:
            logger.warning("Failed to inspect previous Segments for %s: %s", session_id, exc)

        unsealed = [
            msg
            for msg in messages
            if getattr(msg, "sequence", 0) > last_sealed_sequence
        ]
        if not unsealed:
            return None, None
        return (
            getattr(unsealed[0], "message_id", None),
            getattr(unsealed[-1], "message_id", None),
        )

    def crash_reset_stale_segments(self, threshold_seconds: int) -> int:
        """Reset stale distilling segments to pending after a crash/restart."""
        repo = self._get_repo()
        now = datetime.now()
        reset_count = 0
        for segment in repo.get_segments_by_status("distilling"):
            started_at = getattr(segment, "distilling_started_at", None)
            if started_at is None:
                continue
            if (now - started_at).total_seconds() < threshold_seconds:
                continue
            segment_id = getattr(segment, "segment_id", "")
            if repo.transition_segment_status(
                segment_id,
                from_status="distilling",
                to_status="pending",
            ):
                reset_count += 1
        return reset_count
