"""Business facade for Assistant terminal-failure recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.business.agents.config import AgentType, ResultType
from src.data.repos import (
    AssistantRunFailureRepository,
    MessageRepository,
    SessionRepository,
)

from .assistant_failure_classifier import classify_assistant_failure


class AssistantSessionNotFound(LookupError):
    pass


class AssistantRetryConflict(RuntimeError):
    pass


class AssistantRetryValidation(ValueError):
    pass


@dataclass(frozen=True)
class AssistantFailureSummary:
    category: str
    message: str
    suggestion: str
    attempt_count: int
    failed_at: datetime

    def to_public_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "message": self.message,
            "suggestion": self.suggestion,
            "attemptCount": self.attempt_count,
            "failedAt": self.failed_at.isoformat(),
        }


@dataclass(frozen=True)
class AssistantRetryPreparation:
    failure_id: str
    source_message_sequence: int
    content: str
    reuse_user_message: bool


class AssistantFailureService:
    def __init__(
        self,
        failure_repo: AssistantRunFailureRepository | None = None,
        message_repo: MessageRepository | None = None,
        session_repo: SessionRepository | None = None,
    ) -> None:
        self._failure_repo = failure_repo or AssistantRunFailureRepository()
        self._message_repo = message_repo or MessageRepository()
        self._session_repo = session_repo or SessionRepository()

    def get_summaries(
        self,
        session_id: str,
        message_sequences: list[int],
    ) -> dict[int, AssistantFailureSummary]:
        rows = self._failure_repo.get_current_for_sequences(session_id, message_sequences)
        return {sequence: self._summary(row) for sequence, row in rows.items()}

    def record_terminal_failure(
        self,
        *,
        session_id: str,
        message_sequence: int,
        result_type: ResultType | None = None,
        error: str | None = None,
        exception: BaseException | None = None,
        source_failure_id: str | None = None,
    ) -> AssistantFailureSummary:
        classified = classify_assistant_failure(
            result_type=result_type,
            error=error,
            exception=exception,
        )
        row = self._failure_repo.record_failure(
            session_id=session_id,
            message_sequence=message_sequence,
            category=classified.category,
            safe_message=classified.message,
            safe_suggestion=classified.suggestion,
            internal_code=classified.internal_code,
            exception_type=classified.exception_type,
            source_failure_id=source_failure_id,
        )
        return self._summary(row)

    def prepare_retry(
        self,
        session_id: str,
        message_sequence: int,
        content: str | None,
    ) -> AssistantRetryPreparation:
        session = self._session_repo.get_by_id(session_id)
        if session is None or session.agent_type != AgentType.ASSISTANT:
            raise AssistantSessionNotFound(session_id)

        message = self._message_repo.get_by_sequence(session_id, message_sequence)
        if message is None or message.role != "user":
            raise AssistantRetryConflict("failed message is no longer current")

        edited_content: str | None = None
        if content is not None:
            edited_content = content.strip()
            if not edited_content:
                raise AssistantRetryValidation("content must not be empty")

        row = self._failure_repo.claim_retry(session_id, message_sequence)
        if row is None:
            raise AssistantRetryConflict("failed message is no longer current")
        original = (message.content or "").strip()
        if not original:
            self._failure_repo.restore_failed(row.failure_id)
            raise AssistantRetryConflict("original message is unavailable")
        return AssistantRetryPreparation(
            failure_id=row.failure_id,
            source_message_sequence=message_sequence,
            content=edited_content if edited_content is not None else original,
            reuse_user_message=edited_content is None,
        )

    def resolve(self, failure_id: str) -> None:
        self._failure_repo.resolve(failure_id)

    def restore_failed(self, failure_id: str) -> None:
        self._failure_repo.restore_failed(failure_id)

    def resolve_current_for_new_message(self, session_id: str) -> int | None:
        row = self._failure_repo.resolve_current(session_id)
        return row.message_sequence if row is not None else None

    def recover_interrupted_retries(self) -> int:
        return self._failure_repo.recover_interrupted_retries()

    @staticmethod
    def _summary(row) -> AssistantFailureSummary:
        return AssistantFailureSummary(
            category=row.category,
            message=row.safe_message,
            suggestion=row.safe_suggestion,
            attempt_count=row.attempt_count,
            failed_at=row.failed_at,
        )
