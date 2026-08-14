from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from src.business.services.chat_service import ChatService, DisplayChatMessage
from src.business.services.assistant_failure_service import (
    AssistantRetryConflict,
    AssistantRetryValidation,
    AssistantSessionNotFound,
)
from src.business.agents.tools.clarification_manager import ClarificationValidationError
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.clarifications import (
    pending_clarification_snapshot,
    record_clarification_decision,
)
from src.desktop_api.confirmations import record_confirmation_decision
from src.desktop_api.schemas import (
    AssistantAutoApproveRequest,
    AssistantAutoApproveResponse,
    AssistantClarificationDecisionRequest,
    AssistantClarificationDecisionResponse,
    AssistantClarificationPendingResponse,
    AssistantClarificationSnapshot,
    AssistantConfirmationDecisionRequest,
    AssistantConfirmationDecisionResponse,
    AssistantCreateSessionRequest,
    AssistantCreateSessionResponse,
    AssistantMessage,
    AssistantMessagesResponse,
    AssistantRenameSessionRequest,
    AssistantRetryRequest,
    AssistantRetryResponse,
    AssistantSendMessageRequest,
    AssistantSendMessageResponse,
    AssistantSessionListResponse,
    AssistantSessionSummary,
    AssistantStopRequest,
    AssistantStopResponse,
    AssistantSubagentListResponse,
    AssistantTranscriptResponse,
    ExecutorDetailResponse,
    SegmentBoundaryRequest,
)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
_runtime: AssistantRuntime | None = None
logger = logging.getLogger(__name__)


def get_chat_service() -> ChatService:
    return ChatService()


def get_assistant_runtime() -> AssistantRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AssistantRuntime()
    return _runtime


def _session_to_dto(item: dict) -> AssistantSessionSummary:
    return AssistantSessionSummary(
        sessionId=item["session_id"],
        title=item["title"],
        preview=item.get("preview") or "",
        status=item.get("status") or "active",
        createdAt=item.get("date"),
        updatedAt=item.get("updated_at"),
        dateLabel=item.get("date_str") or "",
    )


def _message_to_dto(message: DisplayChatMessage) -> AssistantMessage:
    if message.role == "summary":
        role = "summary"
    else:
        role = "assistant" if message.role == "assistant" else "user"
    return AssistantMessage(
        sequence=message.sequence,
        role=role,
        content=message.content,
        createdAt=message.created_at,
        rendering="safe_markdown" if role in ("assistant", "summary") else "plain_text",
        failure=message.failure.to_public_dict() if message.failure is not None else None,
    )


@router.get("")
def assistant_status() -> dict[str, object]:
    return {"status": "ready", "resources": ["sessions", "messages", "confirmations"]}


@router.get("/sessions", response_model=AssistantSessionListResponse)
def list_sessions(
    query: str = "",
    limit: int = Query(200, ge=1, le=500),
    service: ChatService = Depends(get_chat_service),
) -> AssistantSessionListResponse:
    sessions = service.get_sessions_with_preview(limit=limit, query=query)
    return AssistantSessionListResponse(items=[_session_to_dto(item) for item in sessions])


@router.post("/sessions", response_model=AssistantCreateSessionResponse)
def create_session(
    request: AssistantCreateSessionRequest,
    service: ChatService = Depends(get_chat_service),
) -> AssistantCreateSessionResponse:
    try:
        session_id = service.create_session(tool_ids=request.toolIds, title=request.title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssistantCreateSessionResponse(sessionId=session_id)


@router.patch("/sessions/{session_id}", response_model=AssistantSessionSummary)
def rename_session(
    session_id: str,
    request: AssistantRenameSessionRequest,
    service: ChatService = Depends(get_chat_service),
) -> AssistantSessionSummary:
    try:
        return _session_to_dto(service.rename_session(session_id, request.title))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="assistant session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
) -> dict[str, object]:
    if not service.archive_session(session_id):
        raise HTTPException(status_code=404, detail="assistant session not found")
    return {"archived": True, "sessionId": session_id}


@router.get(
    "/sessions/{session_id}/messages",
    response_model=AssistantMessagesResponse,
    response_model_exclude_none=True,
)
def get_messages(
    session_id: str,
    limit: int = Query(10, ge=1, le=100),
    beforeSequence: int | None = Query(default=None, ge=1),
    service: ChatService = Depends(get_chat_service),
) -> AssistantMessagesResponse:
    page = service.get_display_messages(
        session_id,
        limit=limit,
        before_sequence=beforeSequence,
    )
    return AssistantMessagesResponse(
        items=[_message_to_dto(message) for message in page.messages],
        hasMoreBefore=page.has_more_before,
        nextBeforeSequence=page.next_before_sequence,
    )


@router.post("/sessions/{session_id}/messages", response_model=AssistantSendMessageResponse)
def send_message(
    session_id: str,
    request: AssistantSendMessageRequest,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantSendMessageResponse:
    try:
        accepted = runtime.dispatch_message(
            session_id,
            request.content,
            continue_subagent=(
                request.continueSubagent.model_dump() if request.continueSubagent else None
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssistantSendMessageResponse(accepted=accepted, sessionId=session_id)


@router.post(
    "/sessions/{session_id}/retry",
    response_model=AssistantRetryResponse,
)
def retry_message(
    session_id: str,
    request: AssistantRetryRequest,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantRetryResponse:
    try:
        accepted = runtime.retry_message(
            session_id,
            request.messageSequence,
            request.content,
        )
    except AssistantSessionNotFound as exc:
        raise HTTPException(status_code=404, detail="assistant session not found") from exc
    except AssistantRetryConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AssistantRetryValidation as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssistantRetryResponse(
        accepted=accepted,
        sessionId=session_id,
        messageSequence=request.messageSequence,
    )


@router.post("/sessions/{session_id}/stop", response_model=AssistantStopResponse)
def stop_session(
    session_id: str,
    request: AssistantStopRequest | None = Body(default=None),
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantStopResponse:
    """方块停止 = 全停：取消当前回合 + 停掉该会话所有在办用户任务。

    用户心里只有一个"停"——异步派出的执行体靠 session 取消信号穿不透，
    必须经 stop_user_task 的图级取消信号停到。
    """
    accepted = runtime.stop_session_all(
        session_id, run_id=request.runId if request else None
    )
    return AssistantStopResponse(accepted=accepted)


@router.get("/sessions/{session_id}/transcript", response_model=AssistantTranscriptResponse)
def get_transcript(
    session_id: str,
    subagentId: str | None = Query(default=None),
    afterSequence: int | None = Query(default=None),
    beforeSequence: int | None = Query(default=None),
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantTranscriptResponse:
    """取主助理或指定子任务的过程时间线（含工具，经 009 脱敏；已压缩回合带 compressed 标志）。"""
    try:
        return AssistantTranscriptResponse(
            **runtime.get_transcript(
                session_id,
                subagentId,
                after_sequence=afterSequence,
                before_sequence=beforeSequence,
            )
        )
    except (LookupError, PermissionError) as exc:
        # 归属拒绝（非己出会话的子任务）与缺失一并返回 404「not found」——不确认其存在、
        # 不暴露这是归属问题，符合 FR-030 不泄露他人会话子任务。
        raise HTTPException(status_code=404, detail="subagent transcript not found") from exc
    except Exception as exc:
        logger.error("Assistant transcript failed for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"}) from exc


@router.get("/sessions/{session_id}/subagents", response_model=AssistantSubagentListResponse)
def list_subagents(
    session_id: str,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantSubagentListResponse:
    """取会话子任务权威列表与状态（重连/重开会话兜底）。"""
    try:
        return AssistantSubagentListResponse(**runtime.list_subagents(session_id))
    except Exception as exc:
        logger.error("Assistant subagent list failed for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"}) from exc


@router.get("/sessions/{session_id}/executor-detail", response_model=ExecutorDetailResponse)
def get_executor_detail(
    session_id: str,
    executorSessionId: str = Query(...),
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> ExecutorDetailResponse:
    """取某执行体会话的聚合详情（⑦ 递归抽屉用）：summary + transcript + children。"""
    try:
        return ExecutorDetailResponse(
            **runtime.get_executor_detail(session_id, executorSessionId)
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="executor not found") from exc
    except Exception as exc:
        logger.error(
            "Executor detail failed for session %s executor %s: %s",
            session_id,
            executorSessionId,
            exc,
        )
        raise HTTPException(status_code=500, detail={"error": "internal_error"}) from exc


@router.post(
    "/confirmations/{request_id}/decision",
    response_model=AssistantConfirmationDecisionResponse,
)
def decide_confirmation(
    request_id: str,
    request: AssistantConfirmationDecisionRequest,
) -> AssistantConfirmationDecisionResponse:
    result = record_confirmation_decision(request_id, request.decision)
    return AssistantConfirmationDecisionResponse(
        requestId=result.request_id,
        decision=result.decision,
        accepted=result.accepted,
    )


@router.get(
    "/sessions/{session_id}/clarifications/pending",
    response_model=AssistantClarificationPendingResponse,
)
def get_pending_clarification(session_id: str) -> AssistantClarificationPendingResponse:
    """返回该会话当前 pending 澄清快照（重连 / 会话打开 / resync 兜底）；无则 clarification=null。"""
    snapshot = pending_clarification_snapshot(session_id)
    return AssistantClarificationPendingResponse(
        clarification=AssistantClarificationSnapshot(**snapshot) if snapshot else None
    )


@router.post(
    "/sessions/{session_id}/clarifications/{request_id}/decision",
    response_model=AssistantClarificationDecisionResponse,
)
def decide_clarification(
    session_id: str,
    request_id: str,
    request: AssistantClarificationDecisionRequest,
) -> AssistantClarificationDecisionResponse:
    try:
        result = record_clarification_decision(
            session_id,
            request_id,
            request.decision,
            [a.model_dump() for a in request.answers],
        )
    except LookupError as exc:
        # 归属错配/缺失一并 404，不泄漏存在性
        raise HTTPException(status_code=404, detail="clarification not found") from exc
    except ClarificationValidationError as exc:
        # 答案校验失败：422，不结算，前端保留卡片可重试
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssistantClarificationDecisionResponse(
        requestId=result["requestId"],
        status=result["status"],
        accepted=result["accepted"],
    )


@router.post(
    "/confirmations/auto-approve",
    response_model=AssistantAutoApproveResponse,
)
def set_auto_approve(
    request: AssistantAutoApproveRequest,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> AssistantAutoApproveResponse:
    return AssistantAutoApproveResponse(enabled=runtime.set_auto_approve(request.enabled))


@router.post("/sessions/{session_id}/segment-idle")
def trigger_segment_idle(session_id: str):
    """前端空闲计时器触发后调用，封存当前 Segment"""
    from src.business.brain.segment_service import SegmentService

    try:
        segment_id = SegmentService().handle_idle_and_cleanup(session_id)
    except Exception as exc:
        logger.error("Segment idle trigger failed for session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"}) from exc
    if segment_id is None:
        return {"segment_id": None, "status": None}
    return {"segment_id": segment_id, "status": "pending"}


@router.post("/segment-boundary")
def trigger_segment_boundary(body: SegmentBoundaryRequest):
    """通用 Segment 边界触发端点（window_close / new_session / token_limit）"""
    from src.business.brain.segment_service import SegmentService

    try:
        segment_id = SegmentService().seal_and_cleanup(body.session_id, boundary_reason=body.reason)
    except Exception as exc:
        logger.error("Segment boundary trigger failed for session %s: %s", body.session_id, exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"}) from exc
    return (
        {"segment_id": segment_id, "status": "pending"}
        if segment_id
        else {"segment_id": None, "status": None}
    )
