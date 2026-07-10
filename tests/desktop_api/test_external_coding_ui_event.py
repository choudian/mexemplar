import ast
from pathlib import Path

from src.desktop_api.ui_events import validate_ui_event_payload
from src.desktop_api.ui_events import exported_registry_payload_enums


def test_external_coding_changed_payload_is_safe_registered_event() -> None:
    validate_ui_event_payload(
        "assistant.external_coding.changed",
        {
            "codingSessionId": "ecs_123",
            "sessionId": "sess_1",
            "ownerType": "task",
            "ownerId": "tsk_1",
            "tool": "claude_code",
            "status": "plan_ready",
            "phase": "plan",
            "changeType": "plan_ready",
            "updatedAt": "2026-07-09T00:00:00",
        },
    )


def test_service_literal_change_types_are_registered() -> None:
    tree = ast.parse(Path("src/business/external_coding/service.py").read_text(encoding="utf-8"))
    emitted = {
        call.args[1].value
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "_emit"
        and len(call.args) >= 2
        and isinstance(call.args[1], ast.Constant)
        and isinstance(call.args[1].value, str)
    }
    registered = set(
        exported_registry_payload_enums()["assistant.external_coding.changed"]["changeType"]
    )

    assert emitted <= registered
