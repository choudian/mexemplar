"""Feedback and recruitment signal persistence for the assistant brain."""

import json
import logging
from typing import Optional

from ..models_sqlite import BrainRecruitmentSignal, FeedbackSignal
from .base_repository import BaseRepository
from .brain_repository_common import _append_json_list_item
from src.utils.ids import new_id

logger = logging.getLogger(__name__)


class BrainFeedbackSignalRepository(BaseRepository):
    """Repository for feedback, skill-pool, and recruitment signals."""
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
        signal_id = new_id()
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
                    signal_id=new_id(),
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
                    signal_id=new_id(),
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