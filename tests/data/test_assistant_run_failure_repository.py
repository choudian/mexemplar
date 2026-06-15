from __future__ import annotations

from src.business.agents.config import AgentType
from src.business.services.assistant_failure_service import AssistantFailureService
from src.data.models_sqlite import Message, Session
from src.data.repos import (
    AssistantRunFailureRepository,
    MessageRepository,
    SessionRepository,
)


def _seed_session() -> str:
    session_id = "ast_failure_repo"
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    MessageRepository().create(
        Message(
            message_id="msg_failure_repo",
            session_id=session_id,
            sequence=1,
            role="user",
            content="original",
        )
    )
    return session_id


def test_failure_repository_state_machine_and_message_migration() -> None:
    session_id = _seed_session()
    service = AssistantFailureService()
    summary = service.record_terminal_failure(
        session_id=session_id,
        message_sequence=1,
        error="timeout while calling provider",
    )

    assert summary.category == "network"
    assert summary.attempt_count == 1

    preparation = service.prepare_retry(session_id, 1, "edited")
    current = AssistantRunFailureRepository().get_current(session_id)
    assert current is not None
    assert current.status == "retrying"
    assert current.attempt_count == 2

    service.record_terminal_failure(
        session_id=session_id,
        message_sequence=2,
        error="server error",
        source_failure_id=preparation.failure_id,
    )
    moved = AssistantRunFailureRepository().get_current(session_id)
    assert moved is not None
    assert moved.message_sequence == 2
    assert moved.status == "failed"
    assert moved.attempt_count == 2

    service.resolve(moved.failure_id)
    assert AssistantRunFailureRepository().get_current(session_id) is None


def test_duplicate_retry_claim_is_rejected_and_startup_recovers_retrying() -> None:
    session_id = _seed_session()
    service = AssistantFailureService()
    service.record_terminal_failure(
        session_id=session_id,
        message_sequence=1,
        error="quota exceeded",
    )

    first = AssistantRunFailureRepository().claim_retry(session_id, 1)
    second = AssistantRunFailureRepository().claim_retry(session_id, 1)

    assert first is not None
    assert second is None
    assert AssistantRunFailureRepository().recover_interrupted_retries() == 1
    recovered = AssistantRunFailureRepository().get_current(session_id)
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.attempt_count == 2
