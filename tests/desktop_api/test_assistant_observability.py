"""014 US3/US4: assistant_agent_step / assistant_subagent_* 投影 + transcript/subagents 端点。"""

from __future__ import annotations

from src.desktop_api.routers import assistant as assistant_router
from src.desktop_api.ui_event_projector import project_internal_event

# --- projector ---


def test_activity_projection_filters_non_assistant_agent():
    assert (
        project_internal_event(
            "assistant_agent_step",
            {"agent_type": "pm", "session_id": "s1", "kind": "tool_call", "seq": 1},
        )
        == []
    )


def test_activity_projection_for_assistant_main():
    drafts = project_internal_event(
        "assistant_agent_step",
        {
            "agent_type": "assistant",
            "session_id": "s1",
            "subagent_id": None,
            "kind": "tool_call",
            "tool_name": "noop",
            "text": "args",
            "seq": 2,
        },
    )
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.event_type == "assistant.activity"
    assert draft.scope.get("sessionId") == "s1"
    assert draft.payload["kind"] == "tool_call"
    assert draft.payload["seq"] == 2
    assert draft.payload["redacted"] is False  # 非敏感文本正常显示


def test_activity_projection_flags_unsafe_text_keeps_original():
    drafts = project_internal_event(
        "assistant_agent_step",
        {
            "agent_type": "ephemeral_subagent",
            "session_id": "s1",
            "subagent_id": "c1",
            "kind": "tool_result",
            "text": "api_key=sk-secret-12345",
            "seq": 3,
        },
    )
    # 方案 B：保留原文 + 标记 redacted，UI 默认隐藏、双击查看
    assert drafts[0].payload["text"] == "api_key=sk-secret-12345"
    assert drafts[0].payload["redacted"] is True
    assert drafts[0].payload["subagentId"] == "c1"


def test_activity_projection_flags_sensitive_json_keeps_original():
    drafts = project_internal_event(
        "assistant_agent_step",
        {
            "agent_type": "assistant",
            "session_id": "s1",
            "kind": "tool_call",
            "tool_name": "secret_tool",
            "text": '{"api_key":"sk-secret-12345","query":"hello"}',
            "seq": 4,
        },
    )

    assert drafts[0].payload["text"] == '{"api_key":"sk-secret-12345","query":"hello"}'
    assert drafts[0].payload["redacted"] is True


def test_activity_projection_flags_sensitive_python_repr_keeps_original():
    drafts = project_internal_event(
        "assistant_agent_step",
        {
            "agent_type": "assistant",
            "session_id": "s1",
            "kind": "tool_result",
            "text": "{'api_key': 'sk-secret-12345', 'query': 'hello'}",
            "seq": 5,
        },
    )

    assert drafts[0].payload["text"] == "{'api_key': 'sk-secret-12345', 'query': 'hello'}"
    assert drafts[0].payload["redacted"] is True


def test_subagent_lifecycle_projection():
    started = project_internal_event(
        "assistant_subagent_started",
        {
            "session_id": "s1",
            "subagent_id": "c1",
            "label": "子助手",
            "task": "检索",
            "status": "running",
        },
    )
    assert started[0].event_type == "assistant.subagent"
    assert started[0].payload["status"] == "running"
    assert started[0].payload["subagentId"] == "c1"

    paused = project_internal_event(
        "assistant_subagent_paused",
        {"session_id": "s1", "subagent_id": "c1", "status": "suspended", "reason": "用户已停止"},
    )
    assert paused[0].payload["status"] == "suspended"


# --- endpoints ---


def test_transcript_endpoint_shapes_response(desktop_api_client):
    class FakeRuntime:
        def get_transcript(
            self,
            session_id: str,
            subagent_id: str | None = None,
            *,
            after_sequence: int | None = None,
            before_sequence: int | None = None,
        ) -> dict:
            assert subagent_id == "c1"
            assert after_sequence == 2
            assert before_sequence == 6
            return {
                "steps": [{"kind": "tool_call", "toolName": "noop", "text": "x", "seq": 1}],
                "compressed": True,
            }

    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: FakeRuntime()
    )
    try:
        resp = desktop_api_client.get(
            "/api/assistant/sessions/ast_1/transcript?subagentId=c1&afterSequence=2&beforeSequence=6"
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()
    assert body["compressed"] is True
    assert body["steps"][0]["toolName"] == "noop"


def test_transcript_endpoint_returns_404_for_foreign_subagent(desktop_api_client):
    class FakeRuntime:
        def get_transcript(
            self,
            session_id: str,
            subagent_id: str | None = None,
            *,
            after_sequence: int | None = None,
            before_sequence: int | None = None,
        ) -> dict:
            raise PermissionError("foreign subagent")

    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: FakeRuntime()
    )
    try:
        resp = desktop_api_client.get(
            "/api/assistant/sessions/ast_1/transcript?subagentId=foreign"
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()
    assert resp.status_code == 404


def test_subagents_endpoint_shapes_response(desktop_api_client):
    class FakeRuntime:
        def list_subagents(self, session_id: str) -> dict:
            return {
                "items": [
                    {
                        "subagentId": "c1",
                        "label": "子助手",
                        "task": "检索",
                        "status": "running",
                        "lastOutput": None,
                    }
                ]
            }

    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: FakeRuntime()
    )
    try:
        resp = desktop_api_client.get("/api/assistant/sessions/ast_1/subagents")
    finally:
        desktop_api_client.app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["items"][0]["status"] == "running"
