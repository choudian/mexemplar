"""Scheduled assistant session creation must not mutate user-chat confirmation state."""

from __future__ import annotations

import pytest

from src.business.agents.config import AgentType
from src.business.services.chat_service import ChatService
from src.business.services.session_lifecycle import AssistantSessionLifecycle
from src.data.models_sqlite import Session
from src.data.repositories import SessionRepository


def test_scheduled_session_does_not_reset_process_confirmation(monkeypatch) -> None:
    resets: list[str] = []
    monkeypatch.setattr(
        AssistantSessionLifecycle,
        "reset_confirmation_state_for_new_chat",
        lambda _self: resets.append("reset"),
    )

    session_id = ChatService().create_session(
        source="scheduled",
        scheduled_task_id="sch_confirmation_isolation",
    )

    assert resets == []
    row = SessionRepository().get_by_id(session_id)
    assert row is not None
    assert row.source == "scheduled"
    assert row.scheduled_task_id == "sch_confirmation_isolation"
    assert row.is_scheduled == 1


def test_user_session_still_resets_process_confirmation(monkeypatch) -> None:
    resets: list[str] = []
    monkeypatch.setattr(
        AssistantSessionLifecycle,
        "reset_confirmation_state_for_new_chat",
        lambda _self: resets.append("reset"),
    )

    ChatService().create_session(source="user")

    assert resets == ["reset"]


@pytest.mark.parametrize(
    ("source", "scheduled_task_id"),
    [
        ("scheduled", None),
        ("scheduled", "   "),
        ("user", "sch_must_not_bind"),
        ("unknown", None),
    ],
)
def test_chat_service_rejects_contradictory_session_source(
    source: str,
    scheduled_task_id: str | None,
) -> None:
    with pytest.raises(ValueError):
        ChatService().create_session(
            source=source,
            scheduled_task_id=scheduled_task_id,
        )


@pytest.mark.parametrize(
    "session",
    [
        Session(
            session_id="ast_repo_scheduled_missing_task",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source="scheduled",
            is_scheduled=1,
        ),
        Session(
            session_id="ast_repo_scheduled_false_flag",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source="scheduled",
            scheduled_task_id="sch_repo",
            is_scheduled=0,
        ),
        Session(
            session_id="ast_repo_user_has_task",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source="user",
            scheduled_task_id="sch_repo",
            is_scheduled=0,
        ),
        Session(
            session_id="ast_repo_user_true_flag",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source="user",
            is_scheduled=1,
        ),
    ],
)
def test_session_repository_rejects_contradictory_source_fields(session: Session) -> None:
    with pytest.raises(ValueError):
        SessionRepository().create(session)


def test_scheduled_session_typed_entry_persists_consistent_relationship() -> None:
    session_id = ChatService().create_scheduled_session(
        "sch_typed_entry",
        session_id="ast_typed_scheduled_entry",
    )

    row = SessionRepository().get_by_id(session_id)
    assert row is not None
    assert row.source == "scheduled"
    assert row.scheduled_task_id == "sch_typed_entry"
    assert row.is_scheduled == 1
