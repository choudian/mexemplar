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
from src.desktop_api.confirmations import install_confirmation_signal
from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.desktop_api.routers import (
    assistant,
    assistant_tasks,
    brain,
    compositions,
    debug,
    health,
    settings,
    skills,
    skills_methodology,
    teaching,
)
from src.desktop_api.schemas import ErrorDetail, ErrorResponse
from src.execution.tool_executor import ensure_builtin_deps

SESSION_HEADER = "X-Mexemplar-Session"
logger = logging.getLogger(__name__)


def create_app(session_token: str | None = None) -> FastAPI:
    token = session_token or os.environ.get("MEXEMPLAR_DESKTOP_TOKEN", "")
    install_blinker_event_adapter()
    install_confirmation_signal()
    if token:
        try:
            from src.business.debug.service import get_debug_service

            get_debug_service().register_secret(token)
        except Exception:
            logger.debug("Debug runtime-token registration failed", exc_info=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        RecordingStartupService().ensure_recovered()
        try:
            from src.business.services.assistant_failure_service import AssistantFailureService

            recovered_failures = AssistantFailureService().recover_interrupted_retries()
            if recovered_failures:
                logger.info(
                    "Recovered interrupted Assistant retries",
                    extra={"count": recovered_failures},
                )
        except Exception:
            logger.warning("Assistant retry recovery failed", exc_info=True)
        ensure_builtin_deps()
        try:
            from src.data.real_tour_audit import ensure_initialized

            ensure_initialized()
        except Exception:
            logger.warning("Real tour audit initialization failed", exc_info=True)
        try:
            from src.business.services.grand_tour_fixture_service import ensure_fixture_skill

            ensure_fixture_skill()
        except Exception:
            logger.warning("Grand tour fixture skill injection failed", exc_info=True)
        brain_worker = None
        try:
            from src.business.brain.background_worker import BrainBackgroundWorker
            from src.business.brain.skill_bootstrap_service import SkillBootstrapService
        except Exception as e:
            logger.warning("Brain startup imports failed: %s", e)
        else:
            try:
                SkillBootstrapService().ensure_bootstrap_skill()
            except Exception as e:
                logger.warning("Skill methodology bootstrap failed: %s", e)

            try:
                brain_worker = BrainBackgroundWorker()
                brain_worker.start()
            except Exception as e:
                brain_worker = None
                logger.warning("BrainBackgroundWorker failed to start: %s", e)
        task_worker = None
        try:
            from src.business.task_collaboration.background_worker import (
                TaskCollaborationBackgroundWorker,
            )

            task_worker = TaskCollaborationBackgroundWorker(
                resume_callback=assistant.get_assistant_runtime().resume_recovered_task,
            )
            task_worker.start()
        except Exception:
            task_worker = None
            # I4：worker 起不来 = lease/fence 恢复、claim 过期、通道/问题超时全部静默空转，
            # 撞崩执行者的任务会永久卡在 running 无人回收。升到 ERROR + 堆栈，避免被当成
            # 一行 WARNING 在启动日志里漏掉。
            logger.error(
                "TaskCollaborationBackgroundWorker failed to start; "
                "recovery/timeout jobs are DISABLED for this process",
                exc_info=True,
            )
        try:
            yield
        finally:
            if brain_worker is not None:
                brain_worker.stop()
            if task_worker is not None:
                task_worker.stop()
            # 关闭前把所有仍 pending 的澄清结算为 shutdown 并唤醒阻塞 worker（FR-013）。
            try:
                from src.desktop_api.clarifications import settle_all_clarifications_shutdown

                settle_all_clarifications_shutdown()
            except Exception:
                logger.warning("Clarification shutdown settle failed", exc_info=True)
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
    app.include_router(assistant_tasks.router)
    app.include_router(teaching.router)
    app.include_router(skills.router)
    app.include_router(skills_methodology.router)
    app.include_router(compositions.router)
    app.include_router(settings.router)
    app.include_router(brain.router)
    app.include_router(debug.router)

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
