"""Improvement proposal API — list, approve, reject."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.business.self_improvement.proposal_bridge import trigger_implementation_async
from src.business.self_improvement.proposal_service import ProposalCleanupError, ProposalService

router = APIRouter(prefix="/api/improvement-proposals", tags=["improvement-proposals"])
ProposalStatus = Literal["pending_review", "approved", "in_progress", "done", "failed", "rejected"]


class ApproveBody(BaseModel):
    supplement: str = ""


class ProposalDto(BaseModel):
    """Public proposal representation — mirrors ``ProposalService._to_dict``.

    Acts as the response contract: FastAPI validates every serialized proposal
    against this schema, so a drift between ``_to_dict`` and the frontend DTO
    surfaces here (500 / failed test) instead of breaking the UI at runtime.
    """

    id: str
    sourceReviewId: str
    findingIndex: int
    status: ProposalStatus
    severity: str | None = None
    findingType: str | None = None
    what: str | None = None
    evidence: str | None = None
    suggestion: str | None = None
    userSupplement: str | None = None
    graphId: str | None = None
    worktreeAvailable: bool = False
    branchName: str | None = None
    resultTestsPassed: bool | None = None
    resultSummary: str | None = None
    error: str | None = None
    createdAt: str
    decidedAt: str | None = None
    completedAt: str | None = None


class ProposalListResponse(BaseModel):
    proposals: list[ProposalDto]


@router.get("", response_model=ProposalListResponse)
def list_improvement_proposals(
    status: Optional[ProposalStatus] = Query(
        default=None, description="按状态筛选；非法值返回 422。"
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> ProposalListResponse:
    proposals = ProposalService().list_proposals(status=status, limit=limit)
    return ProposalListResponse(proposals=proposals)


@router.post("/{proposal_id}/approve")
def approve_proposal(proposal_id: str, body: ApproveBody) -> dict:
    result = ProposalService().approve(proposal_id, supplement=body.supplement)
    if result is None:
        return {"accepted": False, "reason": "not_pending"}
    trigger_implementation_async(proposal_id)
    return {"accepted": True, "id": result["id"], "status": result["status"]}


@router.post("/{proposal_id}/reject")
def reject_proposal(proposal_id: str) -> dict:
    try:
        result = ProposalService().reject(proposal_id)
    except ProposalCleanupError:
        return {"accepted": False, "reason": "cleanup_failed"}
    if result is None:
        return {"accepted": False, "reason": "invalid_transition"}
    return {"accepted": True, "id": result["id"], "status": result["status"]}
