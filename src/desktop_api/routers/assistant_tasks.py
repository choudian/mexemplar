from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Callable, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query

from src.business.task_collaboration.adjudication import TaskAdjudicationService
from src.business.task_collaboration.board import TaskBoardService
from src.business.task_collaboration.meetings import TaskMeetingService
from src.business.task_collaboration.service import TaskCollaborationService
from src.business.task_collaboration.todos import TaskTodoService
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.routers.assistant import get_assistant_runtime
from src.desktop_api.schemas import (
    AssistantCurrentTaskGraphResponse,
    AssistantMeetingTranscriptResponse,
    AssistantTaskAdjudicationDecisionRequest,
    AssistantTaskAdjudicationDecisionResponse,
    AssistantTaskBoardClaimRequest,
    AssistantTaskBoardClaimResponse,
    AssistantTaskBoardResponse,
    AssistantTaskGraphCancelRequest,
    AssistantTaskGraphCancelResponse,
    AssistantTaskGraphSnapshot,
    AssistantTodoResponse,
    AssistantTodoUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/assistant", tags=["assistant-tasks"])


@router.get("/task-collaboration/health")
async def assistant_task_collaboration_health() -> dict[str, str]:
    return {"status": "ready"}


def get_task_collaboration_service() -> TaskCollaborationService:
    return TaskCollaborationService()


def get_task_adjudication_service() -> TaskAdjudicationService:
    return TaskAdjudicationService()


def get_task_board_service() -> TaskBoardService:
    return TaskBoardService()


def get_task_meeting_service() -> TaskMeetingService:
    return TaskMeetingService()


def get_task_todo_service() -> TaskTodoService:
    return TaskTodoService()


@contextmanager
def _task_service(factory: Callable[[], object]) -> Iterator[object]:
    """统一 task-collaboration service 生命周期：yield service，出口 close。

    HTTPException 原样上抛（保留端点内显式抛出的 4xx）；其余未捕获异常记日志后映射 500，
    不泄漏内部细节。端点内对 ``LookupError`` / ``ValueError`` / ``PermissionError`` 等业务
    异常的 4xx 映射仍就地处理（先于本上下文的 ``except Exception``）。
    """
    service = factory()
    try:
        yield service
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Task collaboration endpoint failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal error.") from exc
    finally:
        service.close()


@router.get(
    "/sessions/{session_id}/task-graphs/current",
    response_model=AssistantCurrentTaskGraphResponse,
)
async def get_current_task_graph(session_id: str) -> AssistantCurrentTaskGraphResponse:
    with _task_service(get_task_collaboration_service) as service:
        snapshot = service.get_current_graph_snapshot(session_id)
        if snapshot is None:
            return AssistantCurrentTaskGraphResponse(graph=None)
        return AssistantCurrentTaskGraphResponse(
            graph=AssistantTaskGraphSnapshot.model_validate(service.snapshot_to_dict(snapshot))
        )


@router.get(
    "/sessions/{session_id}/task-graphs/{graph_id}",
    response_model=AssistantTaskGraphSnapshot,
)
async def get_task_graph(session_id: str, graph_id: str) -> AssistantTaskGraphSnapshot:
    with _task_service(get_task_collaboration_service) as service:
        snapshot = service.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Task graph not found.")
        return AssistantTaskGraphSnapshot.model_validate(service.snapshot_to_dict(snapshot))


@router.post(
    "/sessions/{session_id}/task-graphs/{graph_id}/cancel",
    response_model=AssistantTaskGraphCancelResponse,
)
async def cancel_task_graph(
    session_id: str,
    graph_id: str,
    body: AssistantTaskGraphCancelRequest | None = None,
) -> AssistantTaskGraphCancelResponse:
    with _task_service(get_task_collaboration_service) as service:
        try:
            cancelled = service.cancel_graph(
                session_id=session_id,
                graph_id=graph_id,
                expected_graph_version=body.expectedGraphVersion if body else None,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Task graph not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AssistantTaskGraphCancelResponse(
        accepted=True,
        graphId=graph_id,
        cancelledTaskCount=cancelled,
    )


@router.post(
    "/sessions/{session_id}/task-adjudications/{adjudication_id}/decision",
    response_model=AssistantTaskAdjudicationDecisionResponse,
)
async def decide_task_adjudication(
    session_id: str,
    adjudication_id: str,
    body: AssistantTaskAdjudicationDecisionRequest,
) -> AssistantTaskAdjudicationDecisionResponse:
    # scheduler 装配已由 AssistantRuntime init 保证，无需 per-request 重复确认
    with _task_service(get_task_adjudication_service) as service:
        try:
            result = service.decide(
                adjudication_id=adjudication_id,
                decision=body.decision,
                decided_by="user",
                instruction=body.instruction,
                session_id=session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Task adjudication not found.") from exc
    return AssistantTaskAdjudicationDecisionResponse(**result)


@router.get(
    "/sessions/{session_id}/task-board",
    response_model=AssistantTaskBoardResponse,
)
async def get_task_board(session_id: str) -> AssistantTaskBoardResponse:
    with _task_service(get_task_board_service) as service:
        try:
            items = service.list_board(session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Task board not found.") from exc
    return AssistantTaskBoardResponse(items=items)


@router.post(
    "/sessions/{session_id}/task-board/{task_id}/claim",
    response_model=AssistantTaskBoardClaimResponse,
)
async def claim_task_board_item(
    session_id: str,
    task_id: str,
    body: AssistantTaskBoardClaimRequest,
) -> AssistantTaskBoardClaimResponse:
    with _task_service(get_task_board_service) as service:
        claim = service.claim_task(
            task_id=task_id,
            claimer_type=body.claimerType,
            claimer_id=body.claimerId,
            lease_seconds=body.leaseSeconds,
            session_id=session_id,
        )
        if claim is None:
            raise HTTPException(status_code=409, detail="Task board item is not claimable.")
    return AssistantTaskBoardClaimResponse(
        accepted=True,
        claimId=claim.claim_id,
        taskId=claim.task_id,
        status=claim.status,
    )


@router.post(
    "/sessions/{session_id}/task-board/claims/{claim_id}/release",
    response_model=AssistantTaskBoardClaimResponse,
)
async def release_task_board_claim(
    session_id: str,
    claim_id: str,
) -> AssistantTaskBoardClaimResponse:
    with _task_service(get_task_board_service) as service:
        claim = service.release_claim(claim_id, session_id=session_id)
        if claim is None:
            raise HTTPException(status_code=404, detail="Task board claim not found.")
    return AssistantTaskBoardClaimResponse(
        accepted=True,
        claimId=claim.claim_id,
        taskId=claim.task_id,
        status=claim.status,
    )


@router.get(
    "/sessions/{session_id}/meetings/{channel_id}",
    response_model=AssistantMeetingTranscriptResponse,
)
async def get_meeting_transcript(
    session_id: str,
    channel_id: str,
    after_sequence: int | None = Query(None, alias="afterSequence"),
    limit: int | None = Query(None, ge=1, le=500, description="Max messages to return"),
) -> AssistantMeetingTranscriptResponse:
    with _task_service(get_task_meeting_service) as service:
        try:
            transcript = service.get_transcript(
                channel_id,
                session_id=session_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Meeting channel not found.") from exc
    return AssistantMeetingTranscriptResponse(**transcript)


@router.get(
    "/sessions/{session_id}/tasks/{task_id}/todos",
    response_model=AssistantTodoResponse,
)
async def get_task_todos(session_id: str, task_id: str) -> AssistantTodoResponse:
    with _task_service(get_task_todo_service) as service:
        try:
            items = service.list_todos(task_id, session_id=session_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Task todos not found.") from exc
    return AssistantTodoResponse(taskId=task_id, items=items)


@router.put(
    "/sessions/{session_id}/tasks/{task_id}/todos",
    response_model=AssistantTodoResponse,
)
async def update_task_todos(
    session_id: str,
    task_id: str,
    body: AssistantTodoUpdateRequest,
) -> AssistantTodoResponse:
    with _task_service(get_task_todo_service) as service:
        try:
            items = service.update_todos(
                task_id=task_id,
                executor_type=body.executorType,
                executor_id=body.executorId,
                items=[item.model_dump() for item in body.items],
                session_id=session_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Todo owner mismatch.") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Task todos not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssistantTodoResponse(taskId=task_id, items=items)
