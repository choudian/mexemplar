"""Improvement proposal API — list, approve, reject, discussion."""

from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.business.self_improvement.proposal_bridge import trigger_implementation_async
from src.business.self_improvement.proposal_service import ProposalCleanupError, ProposalService
from src.business.self_improvement.proposal_source_inspector import (
    ProposalSourceForbidden,
    ProposalSourceInspector,
    ProposalSourceInvalidRequest,
    ProposalSourceInvalidView,
    ProposalSourceNotFound,
)

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


class ProposalSourceResponse(BaseModel):
    """Evidence package for proposal discussion and source review."""

    proposalId: str
    view: Literal["overview", "messages", "prompt", "timeline", "tool_output"]
    scope: str
    scopeNote: str | None = None
    proposal: dict[str, Any]
    source: dict[str, Any]
    review: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] | None = None
    nextActions: list[dict[str, Any]] | None = None
    items: list[dict[str, Any]] | None = None
    prompt: dict[str, Any] | None = None
    timeline: list[dict[str, Any]] | None = None
    reference: dict[str, Any] | None = None
    content: str | None = None
    contentTruncated: bool | None = None
    error: dict[str, Any] | None = None
    page: dict[str, Any] | None = None


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


@router.get("/{proposal_id}/source", response_model=ProposalSourceResponse)
def get_proposal_source(
    proposal_id: str,
    view: Literal["overview", "messages", "prompt", "timeline", "tool_output"] = Query(
        default="overview"
    ),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    referenceId: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    maxBytes: int = Query(default=32000, ge=1, le=131072),
) -> ProposalSourceResponse:
    """Return a read-only evidence package for a proposal source."""
    try:
        package = ProposalSourceInspector().inspect(
            proposal_id,
            view=view,
            cursor=cursor,
            limit=limit,
            reference_id=referenceId,
            offset=offset,
            max_bytes=maxBytes,
        )
    except ProposalSourceNotFound as exc:
        raise HTTPException(status_code=404, detail="提案或来源不存在") from exc
    except ProposalSourceForbidden as exc:
        raise HTTPException(status_code=403, detail="无权查看该提案来源") from exc
    except ProposalSourceInvalidView as exc:
        raise HTTPException(status_code=422, detail="不支持的来源视图") from exc
    except ProposalSourceInvalidRequest as exc:
        raise HTTPException(status_code=422, detail=str(exc) or "来源视图参数不完整") from exc
    return ProposalSourceResponse(**package)


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
