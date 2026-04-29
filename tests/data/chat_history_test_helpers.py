from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.data.models_sqlite import Message, Session
from src.business.agents.config import AgentType
from src.data.repositories import MessageRepository, SessionRepository


def create_assistant_session(session_id: str | None = None) -> str:
    sid = session_id or f"test_ast_{uuid.uuid4().hex[:8]}"
    repo = SessionRepository()
    repo.create(
        Session(
            session_id=sid,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    return sid


def seed_message(
    session_id: str,
    sequence: int,
    role: str,
    content: str | None,
    message_type: str = "normal",
    is_archived: bool = False,
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
) -> Message:
    msg = Message(
        message_id=f"msg_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        sequence=sequence,
        role=role,
        content=content,
        message_type=message_type,
        is_archived=is_archived,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        tool_name=None,
        compressed_range=None,
        created_at=datetime.now(timezone.utc),
    )
    return MessageRepository().create(msg)


def seed_display_messages(
    session_id: str,
    count: int,
    archived_until: int = 0,
) -> list[Message]:
    msgs = []
    for i in range(count):
        seq = i + 1
        role = "user" if i % 2 == 0 else "assistant"
        content = f"消息 {seq} ({role})"
        is_archived = seq <= archived_until
        msgs.append(
            seed_message(
                session_id=session_id,
                sequence=seq,
                role=role,
                content=content,
                is_archived=is_archived,
            )
        )
    return msgs
