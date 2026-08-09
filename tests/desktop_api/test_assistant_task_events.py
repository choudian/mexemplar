from __future__ import annotations

from src.desktop_api.ui_event_projector import project_internal_event
from src.desktop_api.ui_events import exported_registry_examples, validate_ui_event_payload


def test_task_graph_event_registry_and_projector() -> None:
    examples = exported_registry_examples()
    validate_ui_event_payload(
        "assistant.task_graph.changed", examples["assistant.task_graph.changed"]
    )

    drafts = project_internal_event(
        "assistant_task_graph_changed",
        {
            "session_id": "ast_1",
            "graph_id": "tg_1",
            "task_id": "tsk_1",
            "change_type": "task_updated",
            "status": "running",
            "display_phase": "reviewing",
            "requires_review": True,
            "safe_explanation": "等待上级检查结果",
        },
    )

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.event_type == "assistant.task_graph.changed"
    assert draft.scope == {"sessionId": "ast_1"}
    assert draft.payload["graphId"] == "tg_1"
    assert "sourceEvent" not in draft.payload


def test_task_graph_us2_event_change_types_are_registered() -> None:
    payload = {
        "graphId": "tg_1",
        "changeType": "graph_stopped",
        "status": "suspended",
    }

    validate_ui_event_payload("assistant.task_graph.changed", payload)


def test_root_failure_projects_to_task_graph_event() -> None:
    drafts = project_internal_event(
        "assistant_task_root_failed",
        {
            "session_id": "ast_1",
            "graph_id": "tg_1",
            "task_id": "tsk_root",
            "change_type": "root_failed",
            "status": "failed",
            "display_phase": "needs_attention",
            "safe_explanation": "处理这条消息时发生了内部错误。",
        },
    )

    assert drafts[0].event_type == "assistant.task_graph.changed"
    assert drafts[0].payload["changeType"] == "root_failed"


def test_adjudication_changed_projects_to_task_graph_event() -> None:
    drafts = project_internal_event(
        "assistant_task_adjudication_changed",
        {
            "session_id": "ast_1",
            "graph_id": "tg_1",
            "task_id": "tsk_1",
            "change_type": "adjudication_decided",
            "status": "done",
            "display_phase": "done",
            "requires_review": False,
            "safe_explanation": "",
        },
    )

    assert len(drafts) == 1
    assert drafts[0].event_type == "assistant.task_graph.changed"
    assert drafts[0].payload["changeType"] == "adjudication_decided"
    validate_ui_event_payload(drafts[0].event_type, drafts[0].payload)


def test_board_and_meeting_events_project_through_public_contracts() -> None:
    board_events = []
    for change_type, claim_status in (
        ("opened", "open"),
        ("claimed", "claimed"),
        ("completed", "completed"),
    ):
        board_events.append(
            project_internal_event(
                "assistant_task_board_changed",
                {
                    "session_id": "ast_1",
                    "graph_id": "tg_1",
                    "task_id": "tsk_board",
                    "change_type": change_type,
                    "claim_status": claim_status,
                },
            )[0]
        )
    meeting = project_internal_event(
        "assistant_meeting_changed",
        {
            "session_id": "ast_1",
            "graph_id": "tg_1",
            "task_id": "tsk_parent",
            "channel_id": "mtg_1",
            "change_type": "message_added",
            "sequence": 1,
            "status": "open",
        },
    )[0]

    for board in board_events:
        validate_ui_event_payload(board.event_type, board.payload)
        assert board.event_type == "assistant.task_board.changed"
    validate_ui_event_payload(meeting.event_type, meeting.payload)
    assert meeting.event_type == "assistant.meeting.changed"


def test_question_events_project_through_public_contract() -> None:
    draft = project_internal_event(
        "assistant_task_question_changed",
        {
            "session_id": "ast_1",
            "graph_id": "tg_1",
            "task_id": "tsk_1",
            "question_id": "qst_1",
            "kind": "resource_request",
            "status": "escalated_to_parent",
            "change_type": "created",
        },
    )[0]

    validate_ui_event_payload(draft.event_type, draft.payload)
    assert draft.event_type == "assistant.task_question.changed"


def test_todo_events_project_through_public_contract() -> None:
    for change_type in ("created", "updated", "deleted", "reordered"):
        draft = project_internal_event(
            "assistant_todo_changed",
            {
                "session_id": "ast_1",
                "task_id": "tsk_1",
                "todo_id": "todo_1",
                "change_type": change_type,
                "status": "done",
                "sort_order": 1,
            },
        )[0]

        validate_ui_event_payload(draft.event_type, draft.payload)
        assert draft.event_type == "assistant.todo.changed"
