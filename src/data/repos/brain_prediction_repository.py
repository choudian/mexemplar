"""Prediction-zone persistence for the assistant brain."""

import logging
from typing import Optional

from ..models_sqlite import BrainMemoryEntry, FeedbackSignal
from .brain_memory_repository import BrainMemoryEntryRepository
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class BrainPredictionRepository(BrainMemoryEntryRepository):
    """Repository for prediction generation and verification state."""

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
