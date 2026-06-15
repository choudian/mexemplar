from __future__ import annotations

import threading
import time
from unittest.mock import patch

from src.business.agents.tools import builtin_general_tools as general_tools
from src.data.models_sqlite import BrainSegment, Message
from src.data.repositories import MessageRepository
from src.desktop_api.routers import assistant as assistant_router


class FakeAssistantRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def dispatch_message(
        self,
        session_id: str,
        content: str,
        continue_subagent: dict | None = None,
    ) -> bool:
        self.calls.append((session_id, content, continue_subagent))
        return True

    def retry_message(
        self,
        session_id: str,
        message_sequence: int,
        content: str | None = None,
    ) -> bool:
        self.calls.append((session_id, str(message_sequence), {"content": content}))
        return True


def test_assistant_session_lifecycle(desktop_api_client):
    created = desktop_api_client.post(
        "/api/assistant/sessions",
        json={"title": "Quarterly planning", "toolIds": ["tool_1"]},
    )
    assert created.status_code == 200
    session_id = created.json()["sessionId"]

    listed = desktop_api_client.get("/api/assistant/sessions")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["title"] == "Quarterly planning"

    renamed = desktop_api_client.patch(
        f"/api/assistant/sessions/{session_id}",
        json={"title": "Updated planning"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Updated planning"

    searched = desktop_api_client.get("/api/assistant/sessions?query=updated")
    assert searched.status_code == 200
    assert [item["sessionId"] for item in searched.json()["items"]] == [session_id]

    deleted = desktop_api_client.delete(f"/api/assistant/sessions/{session_id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"archived": True, "sessionId": session_id}

    listed_after_delete = desktop_api_client.get("/api/assistant/sessions")
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json()["items"] == []


def test_create_session_resets_confirmation_state(desktop_api_client):
    general_tools.reset_confirmation_state_for_tests()
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)
    pending = general_tools.PendingConfirmation(
        request_id="req-reset",
        tool_name="exec",
        summary="命令首行: dangerous",
        created_at=time.monotonic() - 1,
        event=threading.Event(),
    )
    with general_tools._confirm_lock:
        general_tools._pending_confirms[pending.request_id] = pending

    created = desktop_api_client.post("/api/assistant/sessions", json={})

    assert created.status_code == 200
    assert general_tools.is_auto_approve_enabled() is False
    assert pending.event.is_set()
    assert pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    general_tools.reset_confirmation_state_for_tests()


def test_assistant_messages_are_display_filtered_and_send_dispatches(desktop_api_client):
    created = desktop_api_client.post("/api/assistant/sessions", json={})
    session_id = created.json()["sessionId"]

    repo = MessageRepository()
    repo.create(
        Message(
            message_id="msg_system",
            session_id=session_id,
            sequence=1,
            role="system",
            content="hidden",
        )
    )
    repo.create(
        Message(
            message_id="msg_user", session_id=session_id, sequence=2, role="user", content="hello"
        )
    )
    repo.create(
        Message(
            message_id="msg_assistant",
            session_id=session_id,
            sequence=3,
            role="assistant",
            content="**hi**",
        )
    )
    repo.create(
        Message(
            message_id="msg_tool", session_id=session_id, sequence=4, role="tool", content="hidden"
        )
    )

    messages = desktop_api_client.get(f"/api/assistant/sessions/{session_id}/messages?limit=10")
    assert messages.status_code == 200
    assert messages.json()["items"] == [
        {
            "sequence": 2,
            "role": "user",
            "content": "hello",
            "createdAt": messages.json()["items"][0]["createdAt"],
            "rendering": "plain_text",
        },
        {
            "sequence": 3,
            "role": "assistant",
            "content": "**hi**",
            "createdAt": messages.json()["items"][1]["createdAt"],
            "rendering": "safe_markdown",
        },
    ]

    fake_runtime = FakeAssistantRuntime()
    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: fake_runtime
    )
    try:
        sent = desktop_api_client.post(
            f"/api/assistant/sessions/{session_id}/messages",
            json={"content": "continue"},
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert sent.status_code == 200
    assert sent.json() == {"accepted": True, "sessionId": session_id}
    assert fake_runtime.calls == [(session_id, "continue", None)]


def test_assistant_send_message_passes_structured_continue_subagent(desktop_api_client):
    fake_runtime = FakeAssistantRuntime()
    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: fake_runtime
    )
    try:
        sent = desktop_api_client.post(
            "/api/assistant/sessions/ast_1/messages",
            json={
                "content": "继续任务",
                "continueSubagent": {"subagentId": "sub_1", "supplemental": "补充"},
            },
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert sent.status_code == 200
    assert fake_runtime.calls == [
        ("ast_1", "继续任务", {"subagentId": "sub_1", "supplemental": "补充"})
    ]


def test_assistant_retry_endpoint_dispatches_original_or_edited_content(desktop_api_client):
    fake_runtime = FakeAssistantRuntime()
    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: fake_runtime
    )
    try:
        original = desktop_api_client.post(
            "/api/assistant/sessions/ast_1/retry",
            json={"messageSequence": 7},
        )
        edited = desktop_api_client.post(
            "/api/assistant/sessions/ast_1/retry",
            json={"messageSequence": 7, "content": "edited"},
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert original.status_code == 200
    assert edited.status_code == 200
    assert fake_runtime.calls == [
        ("ast_1", "7", {"content": None}),
        ("ast_1", "7", {"content": "edited"}),
    ]


def test_assistant_retry_endpoint_maps_domain_errors(desktop_api_client):
    from src.business.services.assistant_failure_service import (
        AssistantRetryConflict,
        AssistantRetryValidation,
        AssistantSessionNotFound,
    )

    class ErrorRuntime(FakeAssistantRuntime):
        error: Exception

        def retry_message(self, *_args, **_kwargs) -> bool:
            raise self.error

    runtime = ErrorRuntime()
    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: runtime
    )
    try:
        for error, expected in [
            (AssistantSessionNotFound("missing"), 404),
            (AssistantRetryConflict("stale"), 409),
            (AssistantRetryValidation("empty"), 422),
        ]:
            runtime.error = error
            response = desktop_api_client.post(
                "/api/assistant/sessions/ast_1/retry",
                json={"messageSequence": 1},
            )
            assert response.status_code == expected
    finally:
        desktop_api_client.app.dependency_overrides.clear()


def test_confirmation_decision_unknown_request_is_stable(desktop_api_client):
    response = desktop_api_client.post(
        "/api/assistant/confirmations/missing-request/decision",
        json={"decision": "deny"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "requestId": "missing-request",
        "decision": "deny",
        "accepted": False,
    }


def test_segment_boundary_endpoint_seals_with_explicit_reason(desktop_api_client, in_memory_db):
    created = desktop_api_client.post("/api/assistant/sessions", json={})
    session_id = created.json()["sessionId"]
    MessageRepository().create(
        Message(
            message_id="msg_boundary",
            session_id=session_id,
            sequence=1,
            role="user",
            content="需要封存的上下文",
        )
    )

    response = desktop_api_client.post(
        "/api/assistant/segment-boundary",
        json={"session_id": session_id, "reason": "new_session"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    with in_memory_db.get_session() as session:
        segment = session.get(BrainSegment, payload["segment_id"])
        assert segment is not None
        assert segment.boundary_reason == "new_session"


def test_segment_idle_endpoint_returns_stable_internal_error(desktop_api_client):
    with patch(
        "src.business.brain.segment_service.SegmentService.handle_idle_trigger",
        side_effect=RuntimeError("private database path"),
    ):
        response = desktop_api_client.post("/api/assistant/sessions/ast-1/segment-idle")

    assert response.status_code == 500
    assert response.json()["detail"] == {"error": "internal_error"}
    assert "private database path" not in response.text


def test_segment_boundary_endpoint_returns_stable_internal_error(desktop_api_client):
    with patch(
        "src.business.brain.segment_service.SegmentService.seal_segment",
        side_effect=RuntimeError("private database path"),
    ):
        response = desktop_api_client.post(
            "/api/assistant/segment-boundary",
            json={"session_id": "ast-1", "reason": "window_close"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == {"error": "internal_error"}
    assert "private database path" not in response.text
