from __future__ import annotations

import json
import os
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import StreamingResponse

from src.business.services.recording_startup_service import RecordingStartupService
from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.desktop_api.routers import assistant, compositions, health, settings, skills, teaching
from src.desktop_api.schemas import ErrorDetail, ErrorResponse

SESSION_HEADER = "X-Mexemplar-Session"


def create_app(session_token: str | None = None) -> FastAPI:
    token = session_token or os.environ.get("MEXEMPLAR_DESKTOP_TOKEN", "")
    install_blinker_event_adapter()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        RecordingStartupService().ensure_recovered()
        yield

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
    async def events() -> StreamingResponse:
        async def stream():
            async for event in event_queue.stream():
                payload = event.model_dump_json()
                yield f"id: {event.eventId}\nevent: {event.type}\ndata: {payload}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.exception_handler(Exception)
    async def desktop_api_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
        payload = ErrorResponse(
            error=ErrorDetail(
                code="desktop_api_error",
                message="Desktop backend failed to complete the request.",
                details={"type": type(exc).__name__},
            )
        )
        return JSONResponse(status_code=500, content=json.loads(payload.model_dump_json()))

    return app
