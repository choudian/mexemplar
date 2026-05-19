from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

from src.business.services.recording_startup_service import RecordingStartupService
from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.desktop_api.routers import assistant, compositions, health, settings, skills, teaching
from src.desktop_api.schemas import ErrorDetail, ErrorResponse

SESSION_HEADER = "X-Mexemplar-Session"
logger = logging.getLogger(__name__)


def create_app(session_token: str | None = None) -> FastAPI:
    token = session_token or os.environ.get("MEXEMPLAR_DESKTOP_TOKEN", "")
    install_blinker_event_adapter()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        RecordingStartupService().ensure_recovered()
        try:
            yield
        finally:
            event_queue.shutdown()

    app = FastAPI(title="Mexemplar Desktop API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["tauri://localhost", "http://localhost", "http://127.0.0.1"],
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=[SESSION_HEADER, "Content-Type"],
    )

    @app.middleware("http")
    async def require_session(request: Request, call_next: Callable):
        if request.method == "OPTIONS":
            return await call_next(request)
        if token and request.headers.get(SESSION_HEADER) != token:
            payload = ErrorResponse(
                error=ErrorDetail(
                    code="desktop_api_unauthorized",
                    message="Desktop API session is not authorized.",
                )
            )
            return JSONResponse(status_code=401, content=payload.model_dump(mode="json"))
        return await call_next(request)

    app.include_router(health.router)
    app.include_router(assistant.router)
    app.include_router(teaching.router)
    app.include_router(skills.router)
    app.include_router(compositions.router)
    app.include_router(settings.router)

    @app.get("/api/events", tags=["events"])
    async def events(request: Request) -> StreamingResponse:
        last_seen_raw = request.query_params.get("lastSeenSequence")
        event_session_id = request.query_params.get("eventSessionId")
        force_resync_reason: str | None = None
        if last_seen_raw is None:
            last_event_id = request.headers.get("Last-Event-ID", "")
            if ":" in last_event_id:
                event_session_id, last_seen_raw = last_event_id.split(":", 1)
            elif last_event_id:
                force_resync_reason = "invalid_cursor"
        try:
            last_seen_sequence = int(last_seen_raw) if last_seen_raw else None
            if last_seen_sequence is not None and last_seen_sequence < 0:
                force_resync_reason = "invalid_cursor"
        except ValueError:
            last_seen_sequence = None
            force_resync_reason = "invalid_cursor"

        has_sequence = bool(last_seen_raw)
        has_session = bool(event_session_id)
        if force_resync_reason is None and has_sequence != has_session:
            force_resync_reason = "invalid_cursor"

        async def stream():
            async for event in event_queue.stream(
                last_seen_sequence=last_seen_sequence,
                event_session_id=event_session_id,
                force_resync_reason=force_resync_reason,
            ):
                payload = event.model_dump_json()
                yield f"id: {event.sessionId}:{event.sequence}\nevent: {event.type}\ndata: {payload}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.exception_handler(Exception)
    async def desktop_api_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        error_id = f"desktop_err_{uuid4().hex[:12]}"
        logger.error(
            "Desktop API request failed",
            extra={
                "error_id": error_id,
                "method": request.method,
                "path": request.url.path,
            },
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        payload = ErrorResponse(
            error=ErrorDetail(
                code="desktop_api_error",
                message="Desktop backend failed to complete the request.",
                details={"type": type(exc).__name__, "errorId": error_id},
            )
        )
        return JSONResponse(status_code=500, content=json.loads(payload.model_dump_json()))

    return app
