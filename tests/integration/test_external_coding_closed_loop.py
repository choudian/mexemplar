from __future__ import annotations

from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.external_coding_session_repository import (
    ExternalCodingSessionRepository,
)
from src.desktop_api.ui_event_projector import project_internal_event
from src.desktop_api.ui_events import validate_ui_event_payload


def test_persisted_coding_session_reaches_task_snapshot_and_safe_ui_event() -> None:
    session_id = "ast_external_closed_loop"
    with TaskCollaborationService() as task_service:
        graph_id = task_service.create_root_graph(
            session_id=session_id,
            title="实现外部编码闭环",
            description="由任务节点拥有外部编码会话",
        )
        initial = task_service.get_graph_snapshot(
            session_id=session_id,
            graph_id=graph_id,
        )
        assert initial is not None
        task_id = initial.tasks[0].task_id

        with ExternalCodingSessionRepository() as repo:
            row = repo.create_session(
                coding_session_id="ecs_closed_loop",
                session_id=session_id,
                owner_type="task",
                owner_id=task_id,
                parent_session_id=None,
                tool="claude_code",
                launch_mode="headless",
                status="plan_ready",
                phase="plan",
                selected_reason="safe quota projection",
                quota_state="available",
                worktree_path=".worktrees/coding/ecs_closed_loop",
                branch_name="coding/ecs_closed_loop",
                base_commit="a" * 40,
                artifact_dir="data/coding_sessions/ecs_closed_loop",
                handoff_path="data/coding_sessions/ecs_closed_loop/HANDOFF.md",
            )

        snapshot = task_service.get_graph_snapshot(
            session_id=session_id,
            graph_id=graph_id,
        )
        assert snapshot is not None
        coding_sessions = snapshot.tasks[0].external_coding_sessions
        assert [(item["codingSessionId"], item["status"]) for item in coding_sessions] == [
            (row.coding_session_id, "plan_ready")
        ]
        assert set(coding_sessions[0]) == {
            "codingSessionId",
            "tool",
            "status",
            "phase",
        }

    drafts = project_internal_event(
        "external_coding_session_changed",
        {
            "coding_session_id": row.coding_session_id,
            "session_id": session_id,
            "owner_type": "task",
            "owner_id": task_id,
            "tool": "claude_code",
            "status": "plan_ready",
            "phase": "plan",
            "change_type": "plan_ready",
            "updated_at": "2026-07-10T00:00:00Z",
            "raw_log": "Bearer secret-must-not-project",
            "artifact_body": "private implementation output",
            "account_id": "acct_private",
        },
    )

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.event_type == "assistant.external_coding.changed"
    assert draft.scope == {"sessionId": session_id}
    assert set(draft.payload) == {
        "codingSessionId",
        "sessionId",
        "ownerType",
        "ownerId",
        "tool",
        "status",
        "phase",
        "changeType",
        "updatedAt",
    }
    validate_ui_event_payload(draft.event_type, draft.payload)
