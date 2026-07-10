"""API contract tests for external coding session endpoints."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.business.external_coding.quota_probe import QuotaExhaustedError
from src.desktop_api.routers import external_coding_sessions


def _detail(**overrides) -> dict:
    base = {
        "codingSessionId": "ecs_test",
        "sessionId": "sess_test",
        "ownerType": "task",
        "ownerId": "tsk_test",
        "tool": "claude_code",
        "launchMode": "headless",
        "status": "planning",
        "phase": "plan",
        "selectedReason": "test",
        "quotaState": "unknown",
        "worktreePath": "worktree",
        "branchName": "coding/ecs_test",
        "artifactDir": "artifacts",
        "planPreview": None,
        "resultPreview": None,
        "logTail": None,
        "lastErrorCategory": None,
        "lastErrorMessage": None,
        "resumeCount": 0,
        "reviewRecommended": True,
        "reviewSkippedReason": None,
        "createdAt": "2026-07-09T00:00:00",
        "updatedAt": "2026-07-09T00:00:00",
        "completedAt": None,
        "attempts": [],
        "quota": [],
        "mergeRecords": [],
        "rollbackDecisions": [],
        "availableActions": ["inspect", "abandon"],
        "artifacts": {},
    }
    base.update(overrides)
    return base


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _record(self, method: str, **kwargs):
        self.calls.append((method, kwargs))
        return _detail()

    def start_session(self, **kwargs):
        return self._record("start_session", **kwargs)

    def list_sessions(self, **kwargs):
        self.calls.append(("list_sessions", kwargs))
        return [_detail()]

    def get_session(self, coding_session_id: str):
        self.calls.append(("get_session", {"coding_session_id": coding_session_id}))
        return _detail()

    def refresh_session(self, coding_session_id: str):
        self.calls.append(("refresh_session", {"coding_session_id": coding_session_id}))
        return _detail()

    def decide_plan(self, **kwargs):
        return self._record("decide_plan", **kwargs)

    def resume_session(self, **kwargs):
        return self._record("resume_session", **kwargs)

    def record_review_outcome(self, **kwargs):
        self.calls.append(("record_review_outcome", kwargs))
        return _detail(
            status="completed",
            phase="done",
            reviewRecommended=False,
            reviewSkippedReason=None,
        )

    def abandon_session(self, **kwargs):
        return self._record("abandon_session", **kwargs)

    def escalate_to_user(self, **kwargs):
        return self._record("escalate_to_user", **kwargs)

    def analyze_merge(self, **kwargs):
        self.calls.append(("analyze_merge", kwargs))
        return {
            "mergeRecordId": "ecm_001",
            "codingSessionId": "ecs_test",
            "conflictRisk": "low",
            "status": "analysis_ready",
        }

    def merge_session(self, **kwargs):
        self.calls.append(("merge_session", kwargs))
        return {
            "mergeRecordId": "ecm_001",
            "codingSessionId": "ecs_test",
            "conflictRisk": "low",
            "status": "merged",
        }

    def create_rollback_plan(self, **kwargs):
        self.calls.append(("create_rollback_plan", kwargs))
        return {
            "rollbackId": "ecr_001",
            "codingSessionId": "ecs_test",
            "status": "proposed",
            "chosenStrategy": "revert_commit",
            "intentSummary": "rollback plan",
            "safeExplanation": "将通过新提交撤销本会话改动。",
        }

    def confirm_rollback(self, **kwargs):
        self.calls.append(("confirm_rollback", kwargs))
        return {
            "rollbackId": "ecr_001",
            "codingSessionId": "ecs_test",
            "status": "applied",
            "chosenStrategy": "revert_commit",
            "intentSummary": "rollback plan",
            "safeExplanation": "已通过新提交撤销本会话改动。",
        }

    def close(self):
        return None


def _app_and_service(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(
        external_coding_sessions,
        "get_external_coding_service",
        lambda: service,
    )
    app = FastAPI()
    app.include_router(external_coding_sessions.router)
    client = TestClient(app)
    return client, service


def test_create_session_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.post(
        "/api/external-coding/sessions",
        json={
            "ownerType": "task",
            "ownerId": "tsk_001",
            "objective": "implement feature",
        },
    )
    assert resp.status_code == 200
    assert ("start_session",) == (service.calls[0][0],)


def test_create_session_maps_exhausted_quota_to_conflict(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)

    def raise_quota_exhausted(**_kwargs):
        raise QuotaExhaustedError("explicit override is required")

    service.start_session = raise_quota_exhausted
    resp = client.post(
        "/api/external-coding/sessions",
        json={
            "ownerType": "task",
            "ownerId": "tsk_001",
            "objective": "implement feature",
        },
    )

    assert resp.status_code == 409
    assert "override" in resp.json()["detail"]


def test_list_sessions_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.get("/api/external-coding/sessions")
    assert resp.status_code == 200
    assert resp.json()["items"]


def test_get_session_detail_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.get("/api/external-coding/sessions/ecs_test")
    assert resp.status_code == 200
    assert service.calls[0][0] == "get_session"


def test_refresh_session_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.post("/api/external-coding/sessions/ecs_test/refresh")
    assert resp.status_code == 200
    assert service.calls[0][0] == "refresh_session"


def test_plan_decision_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.post(
        "/api/external-coding/sessions/ecs_test/plan-decision",
        json={"decision": "approved"},
    )
    assert resp.status_code == 200
    assert service.calls[0][0] == "decide_plan"
    assert service.calls[0][1]["decision"] == "approved"


def test_merge_analysis_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.post(
        "/api/external-coding/sessions/ecs_test/merge-analysis",
        json={"targetBranch": "main", "targetWorktreePath": "/repo"},
    )
    assert resp.status_code == 200
    assert service.calls[0][0] == "analyze_merge"


def test_merge_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.post(
        "/api/external-coding/sessions/ecs_test/merge",
        json={"mergeRecordId": "ecm_001"},
    )
    assert resp.status_code == 200
    assert service.calls[0][0] == "merge_session"


def test_rollback_plan_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.post(
        "/api/external-coding/sessions/ecs_test/rollback-plan",
        json={"intentSummary": "revert this session"},
    )
    assert resp.status_code == 200
    assert resp.json()["safeExplanation"] == "将通过新提交撤销本会话改动。"
    assert service.calls[0][0] == "create_rollback_plan"


def test_confirm_rollback_endpoint(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resp = client.post(
        "/api/external-coding/sessions/ecs_test/confirm-rollback",
        json={"rollbackId": "ecr_001", "confirmedBy": "agent"},
    )
    assert resp.status_code == 200
    assert service.calls[0][0] == "confirm_rollback"
    assert service.calls[0][1]["confirmed_by"] == "agent"


def test_resume_and_abandon_endpoints_delegate_to_service(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)
    resumed = client.post(
        "/api/external-coding/sessions/ecs_test/resume",
        json={"instruction": "继续从 PLAN.md 修正", "phase": "plan"},
    )
    abandoned = client.post(
        "/api/external-coding/sessions/ecs_test/abandon",
        json={"reason": "偏离目标"},
    )
    assert resumed.status_code == 200
    assert abandoned.status_code == 200


def test_review_outcome_endpoint_records_independent_checks(monkeypatch) -> None:
    client, service = _app_and_service(monkeypatch)

    resp = client.post(
        "/api/external-coding/sessions/ecs_test/review-outcome",
        json={
            "independentlyReviewed": True,
            "independentlyTested": True,
            "skippedReason": "",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["reviewRecommended"] is False
    assert service.calls[0] == (
        "record_review_outcome",
        {
            "coding_session_id": "ecs_test",
            "independently_reviewed": True,
            "independently_tested": True,
            "skipped_reason": "",
        },
    )
