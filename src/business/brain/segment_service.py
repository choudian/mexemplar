"""
Segment 边界服务 - 管理 Segment 的封存与边界触发
"""

import logging
from datetime import datetime, timezone
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
            segment_id,
            session_id,
            boundary_reason,
        )
        return segment_id

    def handle_idle_trigger(self, session_id: str) -> Optional[str]:
        """处理前端空闲计时器触发。

        主助理把任务委派给临时子代理或专员后会进入"等待"状态，UI 看上去空闲，但任务链
        并未结束。若此时直接封存段，蒸馏输入会缺少子代理的执行过程和最终结果，甚至把
        "进行中"误记为失败（见 BUG-2）。因此当会话仍有活跃子代理/专员在跑时，跳过本次
        idle 封存，等任务链结束后的下一次边界（再次 idle、window_close 等）再封存。

        Args:
            session_id: 所属会话 ID

        Returns:
            segment_id，如果成功封存；会话仍在等待子代理时返回 None。
        """
        if self._has_active_subagent(session_id):
            logger.info(
                "Segment idle seal deferred: session %s is waiting on an active subagent",
                session_id,
            )
            return None
        emit("segment_idle_trigger", session_id=session_id)
        return self.seal_segment(session_id, boundary_reason="idle")

    def handle_idle_and_cleanup(self, session_id: str) -> Optional[str]:
        """封存 idle 边界 Segment 并清理该会话已检索的上下文缓存（router 编排下沉）。"""
        segment_id = self.handle_idle_trigger(session_id)
        if segment_id is None:
            return None
        self._cleanup_retrieved_context(session_id)
        return segment_id

    def seal_and_cleanup(self, session_id: str, boundary_reason: str) -> Optional[str]:
        """封存通用边界 Segment 并清理已检索的上下文缓存（router 编排下沉）。"""
        segment_id = self.seal_segment(session_id, boundary_reason=boundary_reason)
        if segment_id:
            self._cleanup_retrieved_context(session_id)
        return segment_id

    def _cleanup_retrieved_context(self, session_id: str) -> None:
        from src.business.agents.tools.assistant_tools import cleanup_retrieved_context

        cleanup_retrieved_context(session_id)

    def _has_active_subagent(self, session_id: str) -> bool:
        """会话是否仍有活跃（运行中）的子代理/专员。

        主助理通过 `assistant_delegation_started` 交接（from=主会话, to=子会话）派活；
        子会话运行期间 status='active'，完成/暂停/失败后转其它状态。只要存在任一仍为
        active 的子会话，就说明主助理在等待结果，会话并非真正空闲。
        """
        try:
            from src.data.repos.session_repository import SessionRepository
            from src.data.repos.workflow_transition_repository import (
                WorkflowTransitionRepository,
            )
        except ImportError:
            return False

        transition_repo = WorkflowTransitionRepository()
        try:
            transitions = transition_repo.list_by_session(session_id)
        except Exception as exc:
            logger.warning("Failed to inspect delegations for session %s: %s", session_id, exc)
            return False
        finally:
            transition_repo.close()

        subagent_ids = [
            getattr(transition, "to_session_id", None)
            for transition in transitions
            if getattr(transition, "event_type", "") == "assistant_delegation_started"
            and getattr(transition, "from_session_id", None) == session_id
        ]
        subagent_ids = [sid for sid in subagent_ids if sid]
        if not subagent_ids:
            return False

        session_repo = SessionRepository()
        try:
            return any(session_repo.get_status(sid) == "active" for sid in subagent_ids)
        except Exception as exc:
            logger.warning("Failed to inspect subagent status for session %s: %s", session_id, exc)
            return False
        finally:
            session_repo.close()

    def _infer_message_range(self, session_id: str) -> tuple[Optional[str], Optional[str]]:
        """Infer the contiguous user-visible message range not covered by sealed segments."""
        try:
            from src.data.repos.message_repository import MessageRepository
        except ImportError:
            return None, None

        try:
            msg_repo = MessageRepository()
            try:
                raw_messages = msg_repo.get_context(session_id)
            finally:
                msg_repo.close()
            messages = [
                msg
                for msg in raw_messages
                if msg.role in {"user", "assistant"} and (msg.content or "").strip()
            ]
        except Exception as exc:
            logger.warning("Failed to infer Segment message range: %s", exc)
            return None, None

        if not messages:
            return None, None

        sequence_by_id = {
            getattr(msg, "message_id", ""): getattr(msg, "sequence", 0) for msg in messages
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

        unsealed = [msg for msg in messages if getattr(msg, "sequence", 0) > last_sealed_sequence]
        if not unsealed:
            return None, None
        return (
            getattr(unsealed[0], "message_id", None),
            getattr(unsealed[-1], "message_id", None),
        )

    def crash_reset_stale_segments(self, threshold_seconds: int) -> int:
        """Reset stale distilling segments to pending after a crash/restart."""
        repo = self._get_repo()
        # ORM returns naive UTC datetimes; strip tzinfo for arithmetic compatibility
        now = datetime.now(timezone.utc).replace(tzinfo=None)
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
