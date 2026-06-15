"""Repository for persistent Assistant terminal-failure recovery state."""

from __future__ import annotations

import uuid
from datetime import datetime

from src.data.models_sqlite import AssistantRunFailure

from .base_repository import BaseRepository

_CURRENT_STATUSES = ("failed", "retrying")


class AssistantRunFailureRepository(BaseRepository):
    def get_by_id(self, failure_id: str) -> AssistantRunFailure | None:
        return (
            self.session.query(AssistantRunFailure)
            .filter(AssistantRunFailure.failure_id == failure_id)
            .first()
        )

    def get_current(self, session_id: str) -> AssistantRunFailure | None:
        return (
            self.session.query(AssistantRunFailure)
            .filter(
                AssistantRunFailure.session_id == session_id,
                AssistantRunFailure.status.in_(_CURRENT_STATUSES),
            )
            .order_by(AssistantRunFailure.updated_at.desc())
            .first()
        )

    def get_current_for_sequences(
        self,
        session_id: str,
        message_sequences: list[int],
    ) -> dict[int, AssistantRunFailure]:
        if not message_sequences:
            return {}
        rows = (
            self.session.query(AssistantRunFailure)
            .filter(
                AssistantRunFailure.session_id == session_id,
                AssistantRunFailure.message_sequence.in_(message_sequences),
                AssistantRunFailure.status.in_(_CURRENT_STATUSES),
            )
            .all()
        )
        return {row.message_sequence: row for row in rows}

    def record_failure(
        self,
        *,
        session_id: str,
        message_sequence: int,
        category: str,
        safe_message: str,
        safe_suggestion: str,
        internal_code: str | None,
        exception_type: str | None,
        source_failure_id: str | None = None,
    ) -> AssistantRunFailure:
        now = datetime.now()
        self.ensure_immediate_transaction()
        row = (
            self.get_by_id(source_failure_id) if source_failure_id else self.get_current(session_id)
        )
        if row is not None and row.session_id == session_id:
            row.message_sequence = message_sequence
            row.category = category
            row.safe_message = safe_message
            row.safe_suggestion = safe_suggestion
            row.internal_code = internal_code
            row.exception_type = exception_type
            row.status = "failed"
            row.failed_at = now
            row.updated_at = now
            row.resolved_at = None
        else:
            row = AssistantRunFailure(
                failure_id=f"asf_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                message_sequence=message_sequence,
                category=category,
                safe_message=safe_message,
                safe_suggestion=safe_suggestion,
                internal_code=internal_code,
                exception_type=exception_type,
                attempt_count=1,
                status="failed",
                created_at=now,
                updated_at=now,
                failed_at=now,
            )
            self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def claim_retry(self, session_id: str, message_sequence: int) -> AssistantRunFailure | None:
        self.ensure_immediate_transaction()
        row = self.get_current(session_id)
        if row is None or row.status != "failed" or row.message_sequence != message_sequence:
            self.session.rollback()
            return None
        row.status = "retrying"
        row.attempt_count += 1
        row.updated_at = datetime.now()
        row.resolved_at = None
        self.session.commit()
        self.session.refresh(row)
        return row

    def restore_failed(self, failure_id: str) -> bool:
        row = self.get_by_id(failure_id)
        if row is None or row.status != "retrying":
            return False
        row.status = "failed"
        row.updated_at = datetime.now()
        self.session.commit()
        return True

    def resolve(self, failure_id: str) -> AssistantRunFailure | None:
        row = self.get_by_id(failure_id)
        if row is None or row.status == "resolved":
            return row
        now = datetime.now()
        row.status = "resolved"
        row.resolved_at = now
        row.updated_at = now
        self.session.commit()
        self.session.refresh(row)
        return row

    def resolve_current(self, session_id: str) -> AssistantRunFailure | None:
        row = self.get_current(session_id)
        if row is None:
            return None
        return self.resolve(row.failure_id)

    def recover_interrupted_retries(self) -> int:
        now = datetime.now()
        count = (
            self.session.query(AssistantRunFailure)
            .filter(AssistantRunFailure.status == "retrying")
            .update(
                {
                    AssistantRunFailure.status: "failed",
                    AssistantRunFailure.updated_at: now,
                    AssistantRunFailure.failed_at: now,
                },
                synchronize_session=False,
            )
        )
        self.session.commit()
        return int(count or 0)
