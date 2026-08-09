from __future__ import annotations

from datetime import datetime, timezone

from src.business.task_collaboration.models import TaskGraphSnapshot, TaskSnapshot
from src.desktop_api.routers import assistant as assistant_router


class _Service:
    def __init__(self, snapshot: TaskGraphSnapshot | None):
        self.snapshot = snapshot

    def close(self) -> None:
        pass

    def get_current_graph_snapshot(self, session_id: str):
        return self.snapshot if session_id == "ast_1" else None

    def get_graph_snapshot(self, *, session_id: str, graph_id: str):
        if session_id == "ast_1" and graph_id == "tg_1":
            return self.snapshot
        return None

    @staticmethod
    def snapshot_to_dict(snapshot: TaskGraphSnapshot) -> dict:
        from src.business.task_collaboration.service import TaskCollaborationService

        return TaskCollaborationService.snapshot_to_dict(snapshot)

    def stop_graph(self, *, session_id: str, graph_id: str) -> int:
        if session_id != "ast_1" or graph_id != "tg_1":
            raise LookupError("not found")
        return 2

    def continue_graph(self, *, session_id: str, graph_id: str) -> int:
        if session_id != "ast_1" or graph_id != "tg_1":
            raise LookupError("not found")
        return 1


class _AdjudicationService:
    def close(self) -> None:
        pass

    def decide(
        self,
        *,
        adjudication_id: str,
        decision: str,
        decided_by: str,
        instruction: str,
        session_id: str,
    ):
        if session_id != "ast_1" or adjudication_id != "adj_1":
            raise LookupError("not found")
        if decision == "returned" and not instruction:
            raise ValueError("instruction is required when returning a task")
        return {
            "accepted": True,
            "adjudicationId": adjudication_id,
            "taskId": "tsk_1",
            "graphId": "tg_1",
            "decision": decision,
            "taskStatus": "done" if decision == "accepted" else "pending_dispatch",
        }


class _BoardService:
    def close(self) -> None:
        pass

    def list_board(self, session_id: str):
        if session_id != "ast_1":
            raise LookupError("not found")
        return [
            {
                "taskId": "tsk_board",
                "graphId": "tg_1",
                "title": "核对发票",
                "status": "pending_dispatch",
                "claimStatus": "open",
                "assignee": None,
                "updatedAt": "2026-06-17T12:00:00Z",
            }
        ]

    def claim_task(
        self,
        *,
        task_id: str,
        claimer_type: str,
        claimer_id: str,
        lease_seconds: int,
        session_id: str | None = None,
    ):
        if task_id != "tsk_board" or claimer_id == "taken":
            return None

        class Claim:
            claim_id = "clm_1"
            task_id = "tsk_board"
            claimer_type = "specialist"
            claimer_id = "sp_1"
            status = "claimed"

        return Claim()

    def release_claim(self, claim_id: str, *, session_id: str | None = None):
        if claim_id != "clm_1":
            return None

        class Claim:
            claim_id = "clm_1"
            task_id = "tsk_board"
            status = "released"

        return Claim()


class _MeetingService:
    def close(self) -> None:
        pass

    def get_transcript(
        self, channel_id: str, *, session_id: str | None = None, after_sequence=None, limit=None
    ):
        if channel_id != "mtg_1":
            raise LookupError("not found")
        return {
            "channelId": "mtg_1",
            "status": "open",
            "participants": [
                {"type": "specialist", "id": "sp_a", "label": "专员 A"},
                {"type": "specialist", "id": "sp_b", "label": "专员 B"},
            ],
            "turnsUsed": 1,
            "turnBudget": 12,
            "messages": [
                {
                    "sequence": 1,
                    "senderId": "sp_a",
                    "content": "按日期排序。",
                    "createdAt": "2026-06-17T12:00:00Z",
                }
            ],
            "nextAfterSequence": None,
            "conclusion": None,
        }


class _TodoService:
    def close(self) -> None:
        pass

    def list_todos(self, task_id: str, *, session_id: str | None = None):
        if task_id != "tsk_1" or (session_id is not None and session_id != "ast_1"):
            raise LookupError("not found")
        return [{"todoId": "todo_1", "text": "收集发票", "status": "done", "sortOrder": 1}]

    def update_todos(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        items,
        session_id: str | None = None,
    ):
        if task_id != "tsk_1" or (session_id is not None and session_id != "ast_1"):
            raise LookupError("not found")
        if executor_id != "sp_1":
            raise PermissionError("not owner")
        return items


class _Runtime:
    def stop_task_graph(self, session_id: str, graph_id: str, run_id: str | None = None) -> dict:
        if session_id != "ast_1" or graph_id != "tg_1":
            raise LookupError("not found")
        return {"affected": 2, "cancel_signal_accepted": run_id == "run_1"}

    def continue_task_graph(self, session_id: str, graph_id: str) -> dict:
        if session_id != "ast_1" or graph_id != "tg_1":
            raise LookupError("not found")
        return {"resumed": 1, "started": 1}


def _snapshot() -> TaskGraphSnapshot:
    return TaskGraphSnapshot(
        graph_id="tg_1",
        session_id="ast_1",
        user_message_sequence=1,
        version=1,
        tasks=[
            TaskSnapshot(
                task_id="tsk_1",
                graph_id="tg_1",
                parent_task_id=None,
                title="task",
                description_preview="safe",
                status="running",
                display_phase="running",
                requires_review=False,
                safe_explanation="",
                suspend_reason=None,
                assignee=None,
                adjudication_id=None,
                updated_at=datetime.now(timezone.utc),
            )
        ],
    )


def test_current_task_graph_returns_snapshot(monkeypatch, desktop_api_client) -> None:
    monkeypatch.setattr(
        "src.desktop_api.routers.assistant_tasks.get_task_collaboration_service",
        lambda: _Service(_snapshot()),
    )

    response = desktop_api_client.get("/api/assistant/sessions/ast_1/task-graphs/current")

    assert response.status_code == 200
    body = response.json()
    assert body["graph"]["graphId"] == "tg_1"
    assert body["graph"]["tasks"][0]["taskId"] == "tsk_1"
    assert "fence" not in str(body).lower()
    assert "lease" not in str(body).lower()


def test_task_graph_404_does_not_leak_cross_session(monkeypatch, desktop_api_client) -> None:
    monkeypatch.setattr(
        "src.desktop_api.routers.assistant_tasks.get_task_collaboration_service",
        lambda: _Service(_snapshot()),
    )

    response = desktop_api_client.get("/api/assistant/sessions/other/task-graphs/tg_1")

    assert response.status_code == 404


def test_stop_and_continue_task_graph_endpoints(desktop_api_client) -> None:
    desktop_api_client.app.dependency_overrides[assistant_router.get_assistant_runtime] = (
        lambda: _Runtime()
    )
    try:
        stop = desktop_api_client.post(
            "/api/assistant/sessions/ast_1/task-graphs/tg_1/stop",
            json={"runId": "run_1"},
        )
        cont = desktop_api_client.post("/api/assistant/sessions/ast_1/task-graphs/tg_1/continue")

        assert stop.status_code == 200
        assert stop.json()["affectedTaskCount"] == 2
        assert stop.json()["cancelSignalAccepted"] is True
        assert cont.status_code == 200
        assert cont.json()["resumedTaskCount"] == 1
        assert cont.json()["startedAttemptCount"] == 1
    finally:
        desktop_api_client.app.dependency_overrides.clear()


def test_adjudication_decision_endpoint_scopes_to_session(monkeypatch, desktop_api_client) -> None:
    monkeypatch.setattr(
        "src.desktop_api.routers.assistant_tasks.get_task_adjudication_service",
        lambda: _AdjudicationService(),
    )

    ok = desktop_api_client.post(
        "/api/assistant/sessions/ast_1/task-adjudications/adj_1/decision",
        json={"decision": "accepted", "instruction": ""},
    )
    missing = desktop_api_client.post(
        "/api/assistant/sessions/other/task-adjudications/adj_1/decision",
        json={"decision": "accepted", "instruction": ""},
    )
    invalid = desktop_api_client.post(
        "/api/assistant/sessions/ast_1/task-adjudications/adj_1/decision",
        json={"decision": "returned", "instruction": ""},
    )

    assert ok.status_code == 200
    assert ok.json()["taskStatus"] == "done"
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_task_board_endpoint_returns_safe_projection(monkeypatch, desktop_api_client) -> None:
    monkeypatch.setattr(
        "src.desktop_api.routers.assistant_tasks.get_task_board_service",
        lambda: _BoardService(),
    )

    response = desktop_api_client.get("/api/assistant/sessions/ast_1/task-board")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["taskId"] == "tsk_board"
    assert body["items"][0]["claimStatus"] == "open"
    assert "description" not in body["items"][0]


def test_task_board_claim_and_release_endpoints(monkeypatch, desktop_api_client) -> None:
    monkeypatch.setattr(
        "src.desktop_api.routers.assistant_tasks.get_task_board_service",
        lambda: _BoardService(),
    )

    claimed = desktop_api_client.post(
        "/api/assistant/sessions/ast_1/task-board/tsk_board/claim",
        json={"claimerType": "specialist", "claimerId": "sp_1", "leaseSeconds": 60},
    )
    conflict = desktop_api_client.post(
        "/api/assistant/sessions/ast_1/task-board/tsk_board/claim",
        json={"claimerType": "specialist", "claimerId": "taken", "leaseSeconds": 60},
    )
    released = desktop_api_client.post(
        "/api/assistant/sessions/ast_1/task-board/claims/clm_1/release",
    )

    assert claimed.status_code == 200
    assert claimed.json()["claimId"] == "clm_1"
    assert conflict.status_code == 409
    assert released.status_code == 200
    assert released.json()["status"] == "released"


def test_meeting_transcript_endpoint_returns_paged_projection(
    monkeypatch,
    desktop_api_client,
) -> None:
    monkeypatch.setattr(
        "src.desktop_api.routers.assistant_tasks.get_task_meeting_service",
        lambda: _MeetingService(),
    )

    response = desktop_api_client.get(
        "/api/assistant/sessions/ast_1/meetings/mtg_1?afterSequence=0&limit=10"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["channelId"] == "mtg_1"
    assert body["messages"][0]["content"] == "按日期排序。"
    assert "toolIds" not in str(body)


def test_todo_endpoints_return_and_update_private_checklist(
    monkeypatch,
    desktop_api_client,
) -> None:
    monkeypatch.setattr(
        "src.desktop_api.routers.assistant_tasks.get_task_todo_service",
        lambda: _TodoService(),
    )

    got = desktop_api_client.get("/api/assistant/sessions/ast_1/tasks/tsk_1/todos")
    updated = desktop_api_client.put(
        "/api/assistant/sessions/ast_1/tasks/tsk_1/todos",
        json={
            "executorType": "specialist",
            "executorId": "sp_1",
            "items": [{"todoId": "todo_1", "text": "收集发票", "status": "done", "sortOrder": 1}],
        },
    )
    forbidden = desktop_api_client.put(
        "/api/assistant/sessions/ast_1/tasks/tsk_1/todos",
        json={"executorType": "specialist", "executorId": "sp_2", "items": []},
    )

    assert got.status_code == 200
    assert got.json()["items"][0]["status"] == "done"
    assert updated.status_code == 200
    assert updated.json()["items"][0]["todoId"] == "todo_1"
    assert forbidden.status_code == 403
