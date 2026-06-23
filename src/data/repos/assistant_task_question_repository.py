"""Repository for persisted task questions and resource requests."""

from __future__ import annotations

from datetime import datetime

from src.data.models_sqlite import AssistantTaskQuestion
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id

_OPEN_QUESTION_STATUSES = ("open", "escalated_to_parent", "escalated_to_user")
# 终态：进入这些状态时写 resolved_at。
_RESOLVED_QUESTION_STATUSES = frozenset({"answered", "cancelled", "expired"})


class AssistantTaskQuestionRepository(BaseRepository):
    def create_question(
        self,
        *,
        graph_id: str,
        task_id: str,
        asker_type: str,
        asker_id: str,
        kind: str,
        question_text: str,
        parent_task_id: str | None = None,
        recipient_type: str | None = None,
        recipient_id: str | None = None,
        capability_delta: str | None = None,
        expires_at: datetime | None = None,
        question_id: str | None = None,
    ) -> AssistantTaskQuestion:
        self.ensure_immediate_transaction()
        row = AssistantTaskQuestion(
            question_id=question_id or generate_id("qst"),
            graph_id=graph_id,
            task_id=task_id,
            parent_task_id=parent_task_id,
            asker_type=asker_type,
            asker_id=asker_id,
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            kind=kind,
            question_text=question_text,
            capability_delta=capability_delta,
            expires_at=expires_at,
            status="open",
        )
        return self._add_and_flush(row)

    def get_by_id(self, question_id: str) -> AssistantTaskQuestion | None:
        return self.session.get(AssistantTaskQuestion, question_id)

    def update_status(
        self,
        question_id: str,
        status: str,
        *,
        safe_answer_summary: str | None = None,
        capability_delta: str | None = None,
        escalated_to_user: bool | None = None,
        user_request_id: str | None = None,
    ) -> AssistantTaskQuestion | None:
        self.ensure_immediate_transaction()
        row = self.session.get(AssistantTaskQuestion, question_id)
        if row is None:
            return None
        row.status = status
        if safe_answer_summary is not None:
            row.safe_answer_summary = safe_answer_summary
        if capability_delta is not None:
            row.capability_delta = capability_delta
        if escalated_to_user is not None:
            row.escalated_to_user = escalated_to_user
        if user_request_id is not None:
            row.user_request_id = user_request_id
        row.updated_at = utc_now_naive()
        if status in _RESOLVED_QUESTION_STATUSES:
            row.resolved_at = row.updated_at
        return self._update_and_flush(row)

    def list_open_for_task(self, task_id: str) -> list[AssistantTaskQuestion]:
        return (
            self.session.query(AssistantTaskQuestion)
            .filter(
                AssistantTaskQuestion.task_id == task_id,
                AssistantTaskQuestion.status.in_(_OPEN_QUESTION_STATUSES),
            )
            .order_by(AssistantTaskQuestion.created_at)
            .all()
        )

    def scan_expired(self, now: datetime) -> list[AssistantTaskQuestion]:
        return (
            self.session.query(AssistantTaskQuestion)
            .filter(
                AssistantTaskQuestion.status.in_(_OPEN_QUESTION_STATUSES),
                AssistantTaskQuestion.expires_at.is_not(None),
                AssistantTaskQuestion.expires_at <= now,
            )
            .all()
        )
