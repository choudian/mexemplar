"""Tests for improvement proposal API endpoints — list, approve, reject.

Tests the typed API contract: request/response shape, safety projection,
and event emission.  Uses ProposalService directly rather than the full
FastAPI stack to avoid the desktop_api fixture bootstrap issue.
"""

from __future__ import annotations

from unittest.mock import patch

from src.business.self_improvement.proposal_service import ProposalService
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository


def _seed_proposal(source_review_id="rev_api_1", finding_index=0) -> str:
    """Create a pending proposal and return its ID."""
    with ImprovementProposalRepository() as repo:
        row = repo.create(
            source_review_id=source_review_id,
            finding_index=finding_index,
            severity="med",
            finding_type="efficiency",
            what="API test finding",
            evidence="evidence",
            suggestion="suggestion",
        )
        assert row is not None
        return row.id


def test_list_proposals_empty(in_memory_db):
    proposals = ProposalService().list_proposals()
    assert proposals == []


def test_list_proposals_returns_created(in_memory_db):
    pid = _seed_proposal()
    proposals = ProposalService().list_proposals()
    assert len(proposals) == 1
    assert proposals[0]["id"] == pid
    assert proposals[0]["status"] == "pending_review"
    # Safety projection: no raw provider error in public DTO
    assert proposals[0]["error"] is None


def test_approve_proposal(in_memory_db):
    pid = _seed_proposal()
    result = ProposalService().approve(pid, supplement="please fix the cache first")
    assert result is not None
    assert result["status"] == "approved"
    assert result["userSupplement"] == "please fix the cache first"


def test_approve_non_pending_returns_none(in_memory_db):
    pid = _seed_proposal()
    ProposalService().approve(pid, supplement="")
    result = ProposalService().approve(pid, supplement="")
    assert result is None  # CAS guard: not pending → None


def test_reject_proposal(in_memory_db):
    pid = _seed_proposal()
    result = ProposalService().reject(pid)
    assert result is not None
    assert result["status"] == "rejected"


def test_reject_invalid_transition(in_memory_db):
    """Cannot reject an already-approved proposal."""
    pid = _seed_proposal()
    ProposalService().approve(pid, supplement="")
    result = ProposalService().reject(pid)
    assert result is None  # approved → rejected not allowed


def test_list_proposals_filter_by_status(in_memory_db):
    pid1 = _seed_proposal("rev_filter_1", 0)
    pid2 = _seed_proposal("rev_filter_2", 0)
    ProposalService().reject(pid1)
    pending = ProposalService().list_proposals(status="pending_review")
    assert len(pending) == 1
    assert pending[0]["id"] == pid2


def test_approve_emits_blinker_event(in_memory_db):
    """批准后 emit improvement_proposal_changed blinker 事件。"""
    pid = _seed_proposal()
    with patch("src.business.self_improvement.proposal_service.emit") as mock_emit:
        ProposalService().approve(pid, supplement="test")
        mock_emit.assert_called_once()
        call_kwargs = mock_emit.call_args[1]
        assert call_kwargs["proposal_id"] == pid
        assert call_kwargs["change_type"] == "approved"


def test_safety_projection_no_secret_in_dto(in_memory_db):
    """DTO 不泄漏 provider 原始错误或 secret。"""
    pid = _seed_proposal()
    result = ProposalService().approve(pid, supplement="")
    # Result should not contain any secret/provider-specific fields
    assert "apiKey" not in result
    assert "providerError" not in result
    assert "stackTrace" not in result


# ---------------------------------------------------------------------------
# HTTP 层契约：经 desktop_api_client 走真实 FastAPI 栈，覆盖 query 校验与
# CAS miss 的 reason 投影（service 直测无法覆盖 router 的 Literal/limit 校验）。
# ---------------------------------------------------------------------------


def test_list_endpoint_returns_proposals(desktop_api_client) -> None:
    pid = _seed_proposal()
    response = desktop_api_client.get("/api/improvement-proposals")
    assert response.status_code == 200
    assert any(p["id"] == pid for p in response.json()["proposals"])


def test_list_endpoint_response_matches_contract_fields(desktop_api_client) -> None:
    """response_model 契约守卫：list 返回的 proposal 字段集合必须与 ProposalDto 一致。

    _to_dict 删/改字段会被 FastAPI response_model 校验拦截（500）；此断言额外锁定
    响应 key 集合不漂移，与前端 ImprovementProposalDto 双向对齐。
    """
    _seed_proposal()
    response = desktop_api_client.get("/api/improvement-proposals")
    assert response.status_code == 200
    proposal = response.json()["proposals"][0]
    expected = {
        "id",
        "sourceReviewId",
        "findingIndex",
        "status",
        "severity",
        "findingType",
        "what",
        "evidence",
        "suggestion",
        "userSupplement",
        "graphId",
        "worktreeAvailable",
        "branchName",
        "resultTestsPassed",
        "resultSummary",
        "error",
        "createdAt",
        "decidedAt",
        "completedAt",
    }
    assert set(proposal.keys()) == expected


def test_list_endpoint_hides_worktree_absolute_path(desktop_api_client, tmp_path) -> None:
    pid = _seed_proposal("rev_path", 0)
    ProposalService().approve(pid, supplement="")
    with ImprovementProposalRepository() as repo:
        assert (
            repo.mark_in_progress(
                pid,
                graph_id="tg_path",
                worktree_path=str(tmp_path / ".worktrees" / "improvement" / pid),
                branch_name=f"improvement/{pid}",
            )
            is not None
        )

    response = desktop_api_client.get("/api/improvement-proposals")

    assert response.status_code == 200
    proposal = next(item for item in response.json()["proposals"] if item["id"] == pid)
    assert "worktreePath" not in proposal
    assert proposal["worktreeAvailable"] is True


def test_list_endpoint_rejects_unknown_status(desktop_api_client) -> None:
    response = desktop_api_client.get("/api/improvement-proposals?status=bogus")
    assert response.status_code == 422


def test_list_endpoint_rejects_invalid_limit(desktop_api_client) -> None:
    response = desktop_api_client.get("/api/improvement-proposals?limit=0")
    assert response.status_code == 422


def test_approve_endpoint_returns_not_pending_after_approved(desktop_api_client) -> None:
    pid = _seed_proposal()
    with patch("src.desktop_api.routers.proposals.trigger_implementation_async") as mock_trigger:
        first = desktop_api_client.post(
            f"/api/improvement-proposals/{pid}/approve", json={"supplement": ""}
        )
    assert first.status_code == 200
    assert first.json()["accepted"] is True
    mock_trigger.assert_called_once_with(pid)

    second = desktop_api_client.post(
        f"/api/improvement-proposals/{pid}/approve", json={"supplement": ""}
    )
    assert second.status_code == 200
    assert second.json() == {"accepted": False, "reason": "not_pending"}


def test_reject_endpoint_returns_invalid_transition_after_approve(desktop_api_client) -> None:
    pid = _seed_proposal()
    with patch("src.desktop_api.routers.proposals.trigger_implementation_async"):
        desktop_api_client.post(
            f"/api/improvement-proposals/{pid}/approve", json={"supplement": ""}
        )
    response = desktop_api_client.post(f"/api/improvement-proposals/{pid}/reject")
    assert response.status_code == 200
    assert response.json() == {"accepted": False, "reason": "invalid_transition"}


def test_reject_failed_endpoint_returns_cleanup_failed_when_worktree_cleanup_fails(
    desktop_api_client,
    tmp_path,
) -> None:
    pid = _seed_proposal("rev_cleanup_fail", 0)
    ProposalService().approve(pid, supplement="")
    worktree = tmp_path / ".worktrees" / "improvement" / pid
    with ImprovementProposalRepository() as repo:
        assert (
            repo.mark_in_progress(
                pid,
                graph_id="tg_cleanup_fail",
                worktree_path=str(worktree),
                branch_name=f"improvement/{pid}",
            )
            is not None
        )
        assert repo.mark_failed(pid, error="tests failed", tests_passed=False) is not None

    with patch(
        "src.business.self_improvement.proposal_workspace.remove_worktree",
        side_effect=RuntimeError("git cleanup failed"),
    ):
        response = desktop_api_client.post(f"/api/improvement-proposals/{pid}/reject")

    assert response.status_code == 200
    assert response.json() == {"accepted": False, "reason": "cleanup_failed"}
    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(pid)
        assert row is not None
        assert row.status == "failed"
        assert row.worktree_path == str(worktree)
