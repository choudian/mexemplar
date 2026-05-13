from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.business.services.chat_service import ChatService, DisplayChatMessage
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.confirmations import record_confirmation_decision
from src.desktop_api.schemas import (
    AssistantConfirmationDecisionRequest,
    AssistantConfirmationDecisionResponse,
    AssistantCreateSessionRequest,
    AssistantCreateSessionResponse,
    AssistantMessage,
    AssistantMessagesResponse,
    AssistantRenameSessionRequest,
    AssistantSendMessageRequest,
    AssistantSendMessageResponse,
    AssistantSessionListResponse,
    AssistantSessionSummary,
)

router = APIRouter(prefix="/api/assistant", tags=["assistant"])
_runtime: AssistantRuntime | None = None


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
    role = "assistant" if message.role == "assistant" else "user"
    return AssistantMessage(
        sequence=message.sequence,
        role=role,
        content=message.content,
        createdAt=message.created_at,
        rendering="safe_markdown" if role == "assistant" else "plain_text",
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


@router.get("/sessions/{session_id}/messages", response_model=AssistantMessagesResponse)
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
        accepted = runtime.dispatch_message(session_id, request.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AssistantSendMessageResponse(accepted=accepted, sessionId=session_id)


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
