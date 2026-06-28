"""Execution review report API."""

from __future__ import annotations

from fastapi import APIRouter, Query

from src.business.self_improvement.execution_review_service import (
    ExecutionReviewQueryService,
)

router = APIRouter(prefix="/api/execution-reviews", tags=["execution-reviews"])


@router.get("")
def list_execution_reviews(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    return {"reviews": ExecutionReviewQueryService().list_recent(limit=limit)}
