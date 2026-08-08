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

from src.business.services.desktop_health_service import DesktopHealthCheck
from src.business.services.recording_startup_service import RecordingStartupService
from src.desktop_api.confirmations import install_confirmation_signal
from src.desktop_api.events import event_queue, install_blinker_event_adapter
from src.desktop_api.routers import (
    assistant,
    assistant_tasks,
    brain,
    compositions,
    debug,
    execution_reviews,
    external_coding_sessions,
    health,
    mcp_servers,
    proposals,
    scheduled_tasks,
    settings,
    skill_store,
    skills,
    skills_methodology,
    teaching,
    user_todos,
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
        # 必须最先执行：此后构造的 LLM client、启动的子进程都从 os.environ 取值，
        # 晚一步设置就有东西已经拿着空环境跑了。
        try:
            from src.data.unified_config import get_unified_config
            from src.utils.process_env import apply_process_env

            apply_process_env(get_unified_config().get_process_env())
        except Exception:
            # 环境变量缺失只让部分功能不可用；启动失败会让整个应用起不来。
            logger.warning("Process environment setup failed", exc_info=True)
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
        # ⑤ 状态对齐半·启动栅栏：在任何后台 worker .start() 之前，把上一代进程遗留的
        # 假状态一次性对齐。判据是进程级全局事实——重启 = 上一代执行体线程物理全死。
        # 失败用 WARNING：退化为现状（worker 周期清 lease 过期的 / external coding 卡住
        # 等用户手动 abandon），不比现在更糟；比 worker 起不来（整条恢复链路废）轻一档。
        try:
            from src.business.task_collaboration.recovery import TaskRecoveryService

            with TaskRecoveryService() as service:
                interrupted = service.mark_interrupted_after_restart()
            if interrupted:
                logger.info(
                    "Marked interrupted attempts after restart",
                    extra={"count": interrupted},
                )
        except Exception:
            logger.warning(
                "Post-restart task collaboration interruption scan failed",
                exc_info=True,
            )
        try:
            from src.business.external_coding.service import (
                ExternalCodingSessionService,
            )

            with ExternalCodingSessionService() as coding_service:
                coding_service.recover_interrupted_after_restart()
        except Exception:
            logger.warning(
                "Post-restart external coding interruption scan failed",
                exc_info=True,
            )
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
            from src.business.self_improvement.execution_review_trigger import register
        except Exception as e:
            logger.warning("Brain startup imports failed: %s", e)
        else:
            try:
                register()
            except Exception:
                logger.warning("Execution review trigger registration failed", exc_info=True)
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
            from src.business.brain.specialist_service import SpecialistService

            SpecialistService().seed_builtin_specialists()
        except Exception:
            # 缺内置专员只影响相关能力可用性，不该阻断启动。
            logger.warning("[Specialist] 内置专员种子失败", exc_info=True)

        mcp_service = None
        try:
            from src.business.mcp import get_mcp_server_service

            mcp_service = get_mcp_server_service()
            mcp_service.seed_preset_servers()  # N19: upsert preset defaults
            mcp_service.start_all_enabled()  # E7: non-blocking, failures→failed status
        except Exception:
            logger.warning("[MCP] MCP service startup failed", exc_info=True)
        else:
            # start_all_enabled 成功时也记录
            if mcp_service and mcp_service.sdk_available:
                logger.info("[MCP] MCP service started, SDK available")
            elif mcp_service:
                logger.info("[MCP] MCP service started, SDK unavailable (NullRegistry)")
        # 033 调度中心：SessionLauncher + SchedulerWorker + RunCompletionMonitor
        scheduler_worker = None
        scheduler_launcher = None
        _app.state.scheduling_health_check = DesktopHealthCheck(
            name="scheduling",
            status="degraded",
            message="Scheduling runtime is still initializing.",
            critical=False,
        )
        try:
            from src.business.scheduling.run_completion_monitor import (
                install_run_completion_monitor,
            )
            from src.business.scheduling.scheduler_service import (
                configure_default_scheduler_launcher,
            )
            from src.business.scheduling.scheduler_worker import SchedulerWorker
            from src.business.scheduling.session_launcher import SessionLauncher
            from src.business.scheduling.unattended_confirmation_manager import (
                get_unattended_confirmation_manager,
            )

            runtime = assistant.get_assistant_runtime()
            scheduler_launcher = SessionLauncher(
                dispatch_callback=lambda sid, instr, run_id, reservation_id: bool(
                    runtime.dispatch_reserved_message(
                        sid,
                        instr,
                        scheduled_run_id=run_id,
                        reservation_id=reservation_id,
                    )
                ),
                reserve_callback=runtime.reserve_scheduled_session,
                release_callback=runtime.release_scheduled_session_reservation,
                session_quiescent_callback=runtime.is_scheduled_session_quiescent,
            )
            configure_default_scheduler_launcher(scheduler_launcher)
            # per-task 免确认授权集：启动时全量加载（CC-005；独立于进程级
            # ``_auto_approve_enabled``，纯内存，shutdown 无特殊处理）
            get_unattended_confirmation_manager().load_all()
            # 授权与完成监听器必须先就绪，最后才允许 worker 处理启动即到期的 misfire。
            run_completion_monitor = install_run_completion_monitor(
                has_active_worker=runtime.has_active_worker,
                has_pending_reentry=runtime.has_pending_reentry,
            )
            scheduler_worker = SchedulerWorker(
                None,
                scheduler_launcher,
                retry_terminal_events=run_completion_monitor.retry_pending_terminal_events,
            )
            scheduler_worker.start()
            _app.state.scheduling_health_check = DesktopHealthCheck(
                name="scheduling",
                status="ok",
                message="Scheduling runtime is available.",
                critical=False,
            )
        except Exception:
            if scheduler_worker is not None:
                try:
                    scheduler_worker.stop()
                except Exception:
                    logger.warning(
                        "SchedulerWorker cleanup after startup failure failed",
                        exc_info=True,
                    )
            try:
                from src.business.scheduling.scheduler_service import (
                    clear_default_scheduler_launcher,
                )

                clear_default_scheduler_launcher(scheduler_launcher)
            except Exception:
                logger.warning(
                    "Scheduler launcher cleanup after startup failure failed",
                    exc_info=True,
                )
            try:
                from src.business.scheduling.run_completion_monitor import (
                    shutdown_run_completion_monitor,
                )

                shutdown_run_completion_monitor()
            except Exception:
                logger.warning(
                    "RunCompletionMonitor cleanup after startup failure failed",
                    exc_info=True,
                )
            if scheduler_launcher is not None:
                try:
                    scheduler_launcher.close()
                except Exception:
                    logger.warning(
                        "Scheduler launcher cleanup after startup failure failed",
                        exc_info=True,
                    )
                scheduler_launcher = None
            scheduler_worker = None
            _app.state.scheduling_health_check = DesktopHealthCheck(
                name="scheduling",
                status="degraded",
                message=(
                    "Scheduling runtime is unavailable; automatic triggers are disabled. "
                    "Restart the desktop app to retry initialization."
                ),
                critical=False,
            )
            logger.error(
                "SchedulerWorker / RunCompletionMonitor failed to start; "
                "scheduled task triggering is DISABLED for this process",
                exc_info=True,
            )
        try:
            yield
        finally:
            if brain_worker is not None:
                brain_worker.stop()
            if task_worker is not None:
                task_worker.stop()
            # 033 调度中心：worker 停 + monitor 断开 + pending 确认卡 fail-closed
            if scheduler_worker is not None:
                try:
                    scheduler_worker.stop()
                except Exception:
                    logger.warning("SchedulerWorker stop failed", exc_info=True)
            try:
                from src.business.scheduling.run_completion_monitor import (
                    shutdown_run_completion_monitor,
                )

                shutdown_run_completion_monitor()
            except Exception:
                logger.warning("RunCompletionMonitor shutdown failed", exc_info=True)
            try:
                from src.business.scheduling.scheduling_confirmation_manager import (
                    get_scheduling_confirmation_manager,
                )

                get_scheduling_confirmation_manager().settle_all_for_shutdown()
            except Exception:
                logger.warning("Scheduling confirmation shutdown settle failed", exc_info=True)
            try:
                from src.business.scheduling.scheduler_service import (
                    clear_default_scheduler_launcher,
                )

                clear_default_scheduler_launcher(scheduler_launcher)
            except Exception:
                logger.warning("Scheduler launcher unregister failed", exc_info=True)
            if scheduler_launcher is not None:
                try:
                    scheduler_launcher.close()
                except Exception:
                    logger.warning("Scheduler launcher shutdown close failed", exc_info=True)
            # MCP shutdown 走业务 facade：stop running/starting、drain、join 并关闭 loop。
            if mcp_service is not None:
                try:
                    mcp_service.shutdown()
                except Exception:
                    logger.warning("[MCP] MCP service shutdown failed", exc_info=True)
            # 关闭前把所有仍 pending 的澄清结算为 shutdown 并唤醒阻塞 worker（FR-013）。
            try:
                from src.desktop_api.clarifications import settle_all_clarifications_shutdown

                settle_all_clarifications_shutdown()
            except Exception:
                logger.warning("Clarification shutdown settle failed", exc_info=True)
            event_queue.shutdown()

    app = FastAPI(title="Mexemplar Desktop API", version="0.1.0", lifespan=lifespan)
    # webview 的 origin 随平台/模式变化，请求要过 CORS 预检才能到达：
    # - 开发模式：devUrl，即 http://127.0.0.1:1420（命中下方正则）
    # - 打包 Windows：http://tauri.localhost（Tauri 2 默认，v1 是 https）
    # - 打包 macOS/Linux：tauri://localhost
    # 少了打包 Windows 的 tauri.localhost，开发能连、装机后一律 CORS 预检失败，
    # 表现为"连不上后端"，而裸 socket（不走 CORS）却正常——正是本 bug。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
            "http://localhost",
            "http://127.0.0.1",
        ],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
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
    app.include_router(execution_reviews.router)
    app.include_router(external_coding_sessions.router)
    app.include_router(proposals.router)
    app.include_router(user_todos.router)
    app.include_router(mcp_servers.router)
    app.include_router(skill_store.router)
    app.include_router(scheduled_tasks.router)
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
