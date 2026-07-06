"""Improvement proposal API — list, approve, reject, discussion."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
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
    discussionSessionId: str | None = None
    createdAt: str
    decidedAt: str | None = None
    completedAt: str | None = None


class ProposalListResponse(BaseModel):
    proposals: list[ProposalDto]


class ProposalDiscussionResponse(BaseModel):
    """讨论会话入口响应（028）：绑定或新建的普通助理会话。"""

    sessionId: str
    created: bool


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


@router.post("/{proposal_id}/discussion", response_model=ProposalDiscussionResponse)
def open_proposal_discussion(proposal_id: str) -> ProposalDiscussionResponse:
    """获取或创建提案讨论会话（幂等；零实施副作用，FR-425）。"""
    result = ProposalService().get_or_create_discussion_session(proposal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="提案不存在")
    return ProposalDiscussionResponse(sessionId=result["sessionId"], created=result["created"])
