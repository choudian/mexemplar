"""Repository for execution review queue and advisory reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.data.models_sqlite import ExecutionReview

from .base_repository import BaseRepository, generate_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExecutionReviewRepository(BaseRepository):
    def enqueue(self, turn_session_id: str, priority: int = 0) -> str:
        review_id = generate_id("exr")
        row = ExecutionReview(
            id=review_id,
            turn_session_id=turn_session_id,
            status="pending",
            priority=int(priority),
            advisory=1,
            created_at=_now(),
        )
        self.session.add(row)
        self._commit()
        return review_id

    def claim_pending(self, limit: int = 5) -> list[ExecutionReview]:
        candidates = (
            self.session.query(ExecutionReview)
            .filter(ExecutionReview.status == "pending")
            .order_by(ExecutionReview.priority.desc(), ExecutionReview.created_at.asc())
            .limit(max(1, int(limit)))
            .all()
        )
        claimed_ids: list[str] = []
        for row in candidates:
            updated = (
                self.session.query(ExecutionReview)
                .filter(ExecutionReview.id == row.id, ExecutionReview.status == "pending")
                .update(
                    {ExecutionReview.status: "in_progress"},
                    synchronize_session=False,
                )
            )
            if updated == 1:
                claimed_ids.append(row.id)
        self._commit()
        if not claimed_ids:
            return []
        self.session.expire_all()
        return (
            self.session.query(ExecutionReview)
            .filter(ExecutionReview.id.in_(claimed_ids))
            .order_by(ExecutionReview.priority.desc(), ExecutionReview.created_at.asc())
            .all()
        )

    def save_result(
        self,
        review_id: str,
        verdict: str,
        findings: list[dict[str, Any]],
        model_used: str,
    ) -> None:
        self.session.query(ExecutionReview).filter(ExecutionReview.id == review_id).update(
            {
                ExecutionReview.status: "completed",
                ExecutionReview.verdict: verdict,
                ExecutionReview.findings_json: json.dumps(findings, ensure_ascii=False),
                ExecutionReview.model_used: model_used,
                ExecutionReview.advisory: 1,
                ExecutionReview.reviewed_at: _now(),
            },
            synchronize_session=False,
        )
        self._commit()
        self.session.expire_all()

    def mark_skipped(self, review_id: str, reason: str) -> None:
        self._finish_with_status(review_id, "skipped", reason)

    def mark_failed(self, review_id: str, error: str) -> None:
        self._finish_with_status(review_id, "failed", error)

    def list_recent(self, limit: int = 50) -> list[ExecutionReview]:
        return (
            self.session.query(ExecutionReview)
            .filter(ExecutionReview.status == "completed")
            .order_by(ExecutionReview.reviewed_at.desc(), ExecutionReview.created_at.desc())
            .limit(max(1, int(limit)))
            .all()
        )

    def count_session_today(self, turn_session_id: str) -> int:
        today = _now()[:10]
        return int(
            self.session.query(ExecutionReview)
            .filter(
                ExecutionReview.turn_session_id == turn_session_id,
                ExecutionReview.created_at >= today,
            )
            .count()
        )

    def _finish_with_status(self, review_id: str, status: str, detail: str) -> None:
        self.session.query(ExecutionReview).filter(ExecutionReview.id == review_id).update(
            {
                ExecutionReview.status: status,
                ExecutionReview.error: detail[:500],
                ExecutionReview.reviewed_at: _now(),
            },
            synchronize_session=False,
        )
        self._commit()
        self.session.expire_all()
