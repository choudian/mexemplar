from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from fastapi import APIRouter, HTTPException, Query

from src.business.external_coding import ExternalCodingSessionService
from src.business.external_coding.quota_probe import QuotaExhaustedError
from src.desktop_api.schemas import (
    ExternalCodingAbandonRequest,
    ExternalCodingEscalateRequest,
    ExternalCodingMergeAnalysisRequest,
    ExternalCodingMergeRecordDetail,
    ExternalCodingMergeRequest,
    ExternalCodingPlanDecisionRequest,
    ExternalCodingResumeRequest,
    ExternalCodingReviewOutcomeRequest,
    ExternalCodingRollbackConfirmRequest,
    ExternalCodingRollbackDecisionDetail,
    ExternalCodingRollbackPlanRequest,
    ExternalCodingSessionCreateRequest,
    ExternalCodingSessionDetail,
    ExternalCodingSessionListResponse,
    ExternalCodingSessionSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/external-coding", tags=["external-coding"])


def get_external_coding_service() -> ExternalCodingSessionService:
    return ExternalCodingSessionService()


@contextmanager
def _service() -> Iterator[ExternalCodingSessionService]:
    service = get_external_coding_service()
    try:
        yield service
    except HTTPException:
        raise
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except QuotaExhaustedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("External coding endpoint failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error.") from exc
    finally:
        service.close()


@router.post("/sessions", response_model=ExternalCodingSessionDetail)
async def create_external_coding_session(
    body: ExternalCodingSessionCreateRequest,
) -> ExternalCodingSessionDetail:
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(
            service.start_session(
                session_id=body.sessionId,
                owner_type=body.ownerType,
                owner_id=body.ownerId,
                objective=body.objective,
                context=body.context,
                tool_preference=body.toolPreference,
                launch_mode=body.launchMode,
                target_branch=body.targetBranch,
                target_worktree_path=body.targetWorktreePath,
                explicit_exhausted_override=body.explicitExhaustedOverride,
            )
        )


@router.get("/sessions", response_model=ExternalCodingSessionListResponse)
async def list_external_coding_sessions(
    sessionId: str | None = Query(None),
    ownerType: str | None = Query(None),
    ownerId: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
) -> ExternalCodingSessionListResponse:
    with _service() as service:
        items = service.list_sessions(
            session_id=sessionId,
            owner_type=ownerType,
            owner_id=ownerId,
            status=status,
            limit=limit,
        )
    return ExternalCodingSessionListResponse(
        items=[ExternalCodingSessionSummary.model_validate(item) for item in items]
    )


@router.get("/sessions/{coding_session_id}", response_model=ExternalCodingSessionDetail)
async def get_external_coding_session(coding_session_id: str) -> ExternalCodingSessionDetail:
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(service.get_session(coding_session_id))


@router.post("/sessions/{coding_session_id}/refresh", response_model=ExternalCodingSessionDetail)
async def refresh_external_coding_session(coding_session_id: str) -> ExternalCodingSessionDetail:
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(
            service.refresh_session(coding_session_id)
        )


@router.post(
    "/sessions/{coding_session_id}/plan-decision",
    response_model=ExternalCodingSessionDetail,
)
async def decide_external_coding_plan(
    coding_session_id: str,
    body: ExternalCodingPlanDecisionRequest,
) -> ExternalCodingSessionDetail:
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(
            service.decide_plan(
                coding_session_id=coding_session_id,
                decision=body.decision,
                decided_by=body.decidedBy,
                feedback=body.feedback,
            )
        )


@router.post("/sessions/{coding_session_id}/resume", response_model=ExternalCodingSessionDetail)
async def resume_external_coding_session(
    coding_session_id: str,
    body: ExternalCodingResumeRequest,
) -> ExternalCodingSessionDetail:
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(
            service.resume_session(
                coding_session_id=coding_session_id,
                instruction=body.instruction,
                phase=body.phase,
            )
        )


@router.post("/sessions/{coding_session_id}/abandon", response_model=ExternalCodingSessionDetail)
async def abandon_external_coding_session(
    coding_session_id: str,
    body: ExternalCodingAbandonRequest,
) -> ExternalCodingSessionDetail:
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(
            service.abandon_session(coding_session_id=coding_session_id, reason=body.reason)
        )


@router.post(
    "/sessions/{coding_session_id}/review-outcome",
    response_model=ExternalCodingSessionDetail,
)
async def record_external_coding_review_outcome(
    coding_session_id: str,
    body: ExternalCodingReviewOutcomeRequest,
) -> ExternalCodingSessionDetail:
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(
            service.record_review_outcome(
                coding_session_id=coding_session_id,
                independently_reviewed=body.independentlyReviewed,
                independently_tested=body.independentlyTested,
                skipped_reason=body.skippedReason,
            )
        )


@router.post(
    "/sessions/{coding_session_id}/escalate-to-user",
    response_model=ExternalCodingSessionDetail,
)
async def escalate_external_coding_session_to_user(
    coding_session_id: str,
    body: ExternalCodingEscalateRequest,
) -> ExternalCodingSessionDetail:
    """FR-020: Agent escalates an interrupted session to waiting_user."""
    with _service() as service:
        return ExternalCodingSessionDetail.model_validate(
            service.escalate_to_user(
                coding_session_id=coding_session_id,
                reason=body.reason,
            )
        )


@router.post(
    "/sessions/{coding_session_id}/merge-analysis",
    response_model=ExternalCodingMergeRecordDetail,
)
async def analyze_external_coding_merge(
    coding_session_id: str,
    body: ExternalCodingMergeAnalysisRequest,
) -> ExternalCodingMergeRecordDetail:
    with _service() as service:
        return ExternalCodingMergeRecordDetail.model_validate(
            service.analyze_merge(
                coding_session_id=coding_session_id,
                target_branch=body.targetBranch,
                target_worktree_path=body.targetWorktreePath,
            )
        )


@router.post(
    "/sessions/{coding_session_id}/merge",
    response_model=ExternalCodingMergeRecordDetail,
)
async def merge_external_coding_session(
    coding_session_id: str,
    body: ExternalCodingMergeRequest,
) -> ExternalCodingMergeRecordDetail:
    with _service() as service:
        return ExternalCodingMergeRecordDetail.model_validate(
            service.merge_session(
                coding_session_id=coding_session_id,
                merge_record_id=body.mergeRecordId,
                agent_decision=body.agentDecision,
            )
        )


@router.post(
    "/sessions/{coding_session_id}/rollback-plan",
    response_model=ExternalCodingRollbackDecisionDetail,
)
async def create_external_coding_rollback_plan(
    coding_session_id: str,
    body: ExternalCodingRollbackPlanRequest,
) -> ExternalCodingRollbackDecisionDetail:
    with _service() as service:
        return ExternalCodingRollbackDecisionDetail.model_validate(
            service.create_rollback_plan(
                coding_session_id=coding_session_id,
                intent_summary=body.intentSummary,
            )
        )


@router.post(
    "/sessions/{coding_session_id}/confirm-rollback",
    response_model=ExternalCodingRollbackDecisionDetail,
)
async def confirm_external_coding_rollback(
    coding_session_id: str,
    body: ExternalCodingRollbackConfirmRequest,
) -> ExternalCodingRollbackDecisionDetail:
    with _service() as service:
        return ExternalCodingRollbackDecisionDetail.model_validate(
            service.confirm_rollback(
                coding_session_id=coding_session_id,
                rollback_id=body.rollbackId,
                confirmed_by=body.confirmedBy,
            )
        )
