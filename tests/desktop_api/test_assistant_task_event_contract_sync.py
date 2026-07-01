from __future__ import annotations

from pathlib import Path

from src.desktop_api.ui_events import (
    exported_registry_examples,
    validate_ui_event_payload,
)

ROOT = Path(__file__).resolve().parents[2]


def test_task_collaboration_event_contracts_exist_in_backend_and_frontend() -> None:
    frontend_contract = (ROOT / "frontend/src/api/uiEventTypes.ts").read_text(encoding="utf-8")
    examples = exported_registry_examples()
    expected = {
        "assistant.task_graph.changed",
        "assistant.task_board.changed",
        "assistant.task_question.changed",
        "assistant.meeting.changed",
        "assistant.todo.changed",
    }

    assert expected.issubset(examples)
    for event_type in expected:
        assert event_type in frontend_contract
        validate_ui_event_payload(event_type, examples[event_type])
    assert '"opened"' in frontend_contract
    assert '"completed"' in frontend_contract
    assert '"deleted"' in frontend_contract
    assert '"reordered"' in frontend_contract
