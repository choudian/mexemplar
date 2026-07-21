"""``SessionLauncher`` —— 复用 task 常驻 scheduled session 并启动独立 run（034）。

业务层不 import ``desktop_api``；
``dispatch_callback(session_id, instruction, run_id, reservation_id) -> bool`` 由 desktop
层注入（实际调 ``AssistantRuntime.dispatch_reserved_message``），仿
``TaskCollaborationBackgroundWorker(resume_callback=...)`` 先例。

职责（一次 launch 完成 4 件事）：

1. 读取 task 的 current session；首次触发才构造新 scheduled session；
2. 预约 runtime session，阻止用户消息/reentry/另一触发抢在 run worker 前启动；
3. 用数据库唯一索引裁定 first-wins；首次绑定 + session + run 同事务提交；
4. ``dispatch_callback(session_id, instruction, run_id, reservation_id)`` 把预约转换成 worker。

原子创建失败会整体回滚，不留下 session 或 run；只有原子提交成功后的 dispatch 缺失、
抛错或返回 false 时，已创建 run 才立即显式置 ``failed`` 并发布终态事件，避免无人消费
的 ``running`` 账目永久悬挂。生产路径每次 launch 创建独立 Repository scope，允许
worker 与 REST fire-now 并发复用同一个 launcher。
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager, nullcontext
from typing import Any, Callable

from src.data.repos.message_repository import MessageRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.session_repository import SESSION_STATUSES, SessionRepository
from src.data.scheduling_types import SessionSource
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

DispatchCallback = Callable[[str, str, str, str], bool]
ReserveCallback = Callable[[str, str], bool]
ReleaseCallback = Callable[[str, str], None]
SessionQuiescentCallback = Callable[[str], bool]
_FAIL_RUN_MAX_ATTEMPTS = 3


def build_scheduled_execution_message(instruction: str) -> str:
    """把任务原文包成“既有计划到点执行”消息，避免被误解为再次登记计划。"""
    return (
        "[系统调度触发：立即执行]\n\n"
        "这是已存在定时任务的一次到点执行，不是创建或管理定时任务的请求。\n"
        "调度系统已经处理触发时间与周期；下方指令中的时间、日期或频率措辞只是原任务背景。\n"
        "请把下方指令视为当前必须执行的任务型请求，立即按 100% 调度规则委派或建图并完成。\n"
        "不得再次创建、修改、暂停或删除定时任务，也不要把本回合解释为让你登记新计划。\n\n"
        "<scheduled-task-instruction>\n"
        f"{instruction}\n"
        "</scheduled-task-instruction>"
    )


class ScheduledRunAlreadyActive(RuntimeError):
    """同一 scheduled task 的 active-run 槽已被并发触发占用。"""


class ScheduledSessionCreationFailed(RuntimeError):
    """scheduled session + run 的原子落库失败。"""


class SessionLauncher:
    """启动 scheduled 会话 + 建 run 账目 + 投递指令。

    Args:
        dispatch_callback: 接收 ``session_id / instruction / run_id / reservation_id``，
            原子把预约转换成 pinned-run worker。为 None 时 fail-closed：会话与 run
            仍留作审计，run 立即置 ``failed``。
        run_repo: 可选 ``ScheduledTaskRunRepository``（默认自建，自管生命周期）。
        chat_service: 可选 ``ChatService``（默认自建）。
    """

    def __init__(
        self,
        dispatch_callback: DispatchCallback | None = None,
        *,
        run_repo: ScheduledTaskRunRepository | None = None,
        chat_service: Any = None,
        reserve_callback: ReserveCallback | None = None,
        release_callback: ReleaseCallback | None = None,
        session_quiescent_callback: SessionQuiescentCallback | None = None,
    ) -> None:
        if (reserve_callback is None) != (release_callback is None):
            raise ValueError("reserve_callback and release_callback must be configured together")
        self._dispatch_callback = dispatch_callback
        self._run_repo = run_repo
        self._chat_service = chat_service
        self._owns_chat_service = chat_service is None
        self._reserve_callback = reserve_callback
        self._release_callback = release_callback
        self._session_quiescent_callback = session_quiescent_callback

    def close(self) -> None:
        if self._owns_chat_service and self._chat_service is not None:
            close = getattr(self._chat_service, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    logger.warning("SessionLauncher: chat_service close failed", exc_info=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _get_chat_service(self):
        if self._chat_service is None:
            from src.business.services.chat_service import ChatService

            self._chat_service = ChatService()
        return self._chat_service

    def _run_repo_scope(self):
        if self._run_repo is not None:
            return nullcontext(self._run_repo)
        return ScheduledTaskRunRepository()

    def launch(
        self,
        *,
        scheduled_task_id: str,
        instruction: str,
        started_at: Any = None,
    ) -> str:
        """建会话 + 建 run + 投递指令，返回 ``run_id``。

        Args:
            scheduled_task_id: 关联的定时任务 id（``sch_*``）。
            instruction: 任务指令原文（投递前会包装为既有计划的到点执行消息）。
            started_at: 可选触发时刻（默认 ``utc_now_naive``）。

        Returns:
            新建的 ``run_id``（``schr_*``）。

        Raises:
            ValueError: instruction 为空。
            ScheduledRunAlreadyActive: 同一任务已有 active run，占用 first-wins 槽。
            ScheduledSessionCreationFailed: scheduled session + run 无法原子落库。
        """
        instruction_text = (instruction or "").strip()
        if not instruction_text:
            raise ValueError("instruction must not be empty")

        chat_service = self._get_chat_service()
        try:
            with ScheduledTaskRepository() as task_repo:
                task = task_repo.get(scheduled_task_id)
                if task is None or task.is_deleted:
                    raise LookupError("scheduled_task_not_found")
                bound_session_id = (task.session_id or "").strip() or None

            bound_session = None
            if bound_session_id is not None:
                with SessionRepository() as session_repo:
                    bound_session = session_repo.get_by_id(bound_session_id)
                if bound_session is not None and not self._is_reusable_session(
                    bound_session,
                    scheduled_task_id=scheduled_task_id,
                ):
                    raise ValueError("bound scheduled session relationship is invalid")
        except Exception as exc:
            logger.exception(
                "SessionLauncher: failed to resolve current session for task %s",
                scheduled_task_id,
            )
            raise ScheduledSessionCreationFailed(
                "scheduled task current session could not be resolved"
            ) from exc

        reuse_existing = bound_session is not None
        session_id = bound_session_id if reuse_existing else chat_service.generate_session_id()
        assert session_id is not None
        reservation_id = f"schres_{uuid.uuid4().hex[:16]}"
        reserved = False
        if self._reserve_callback is not None:
            try:
                reserved = bool(self._reserve_callback(session_id, reservation_id))
            except Exception:
                logger.error(
                    "SessionLauncher: session reservation failed for %s",
                    session_id,
                    exc_info=True,
                )
                reserved = False
            if not reserved:
                raise ScheduledRunAlreadyActive(scheduled_task_id)

        run_id: str | None = None
        try:
            # The waterline belongs to the exclusive runtime window. Reading it
            # before reservation would let a just-finishing worker persist a
            # message between the read and run creation, assigning the wrong trigger.
            with MessageRepository() as message_repo:
                baseline_message_sequence = message_repo.get_next_sequence(session_id) - 1
            trigger_message_sequence = baseline_message_sequence + 1
            with self._run_repo_scope() as run_repo:
                if reuse_existing:
                    run = run_repo.try_create_active_for_bound_session(
                        scheduled_task_id=scheduled_task_id,
                        session_id=session_id,
                        baseline_message_sequence=baseline_message_sequence,
                        trigger_message_sequence=trigger_message_sequence,
                        started_at=started_at or utc_now_naive(),
                    )
                else:
                    build_scheduled_session = getattr(
                        chat_service,
                        "build_scheduled_session",
                    )
                    session = build_scheduled_session(
                        scheduled_task_id,
                        session_id=session_id,
                    )
                    run = run_repo.try_create_active_with_new_bound_session(
                        scheduled_task_id=scheduled_task_id,
                        session=session,
                        expected_session_id=bound_session_id,
                        baseline_message_sequence=baseline_message_sequence,
                        trigger_message_sequence=trigger_message_sequence,
                        started_at=started_at or utc_now_naive(),
                    )
                if run is not None:
                    # SQLAlchemy commit 会过期 ORM 属性；在 Repository 关闭前读取标量，
                    # 后续 dispatch/失败回填只携带 id，不依赖 detached entity。
                    run_id = run.run_id
        except Exception as exc:
            self._release_reservation(session_id, reservation_id, reserved=reserved)
            logger.exception(
                "SessionLauncher: scheduled session/run creation failed for task %s",
                scheduled_task_id,
            )
            raise ScheduledSessionCreationFailed(
                "scheduled session and run could not be created"
            ) from exc
        if run_id is None:
            self._release_reservation(session_id, reservation_id, reserved=reserved)
            raise ScheduledRunAlreadyActive(scheduled_task_id)

        # 投递指令（非阻塞：runtime 起 daemon worker 线程跑主助理）。
        dispatched = False
        if self._dispatch_callback is None:
            logger.warning(
                "SessionLauncher.dispatch_callback is None; run %s for task %s "
                "cannot be dispatched",
                run_id,
                scheduled_task_id,
            )
        else:
            try:
                dispatched = bool(
                    self._dispatch_callback(
                        session_id,
                        build_scheduled_execution_message(instruction_text),
                        run_id,
                        reservation_id,
                    )
                )
            except Exception:
                logger.exception(
                    "SessionLauncher: dispatch_callback failed for run %s session %s; "
                    "run will be marked failed",
                    run_id,
                    session_id,
                )
        if not dispatched:
            # 仍持有 runtime reservation 时先结束 run，避免 ordinary dispatch 在
            # running → failed 的间隙抢入同一 session。无 trigger 消息落库，因此同时
            # 释放预留序号，让下一次 run 能在同一 current session 重试。
            try:
                self._fail_run(
                    run_id,
                    failure_reason="scheduled session could not be started",
                    clear_trigger_message_sequence=True,
                )
            finally:
                self._release_reservation(
                    session_id,
                    reservation_id,
                    reserved=reserved,
                )
        return run_id

    @staticmethod
    def _is_reusable_session(session: Any, *, scheduled_task_id: str) -> bool:
        try:
            source = SessionSource(session.source)
        except (TypeError, ValueError):
            return False
        return (
            session.agent_type == "assistant"
            and session.status in SESSION_STATUSES
            and source is SessionSource.SCHEDULED
            and session.scheduled_task_id == scheduled_task_id
            and session.is_scheduled in (1, True)
        )

    def _release_reservation(
        self,
        session_id: str,
        reservation_id: str,
        *,
        reserved: bool,
    ) -> None:
        if not reserved or self._release_callback is None:
            return
        try:
            self._release_callback(session_id, reservation_id)
        except Exception:
            logger.error(
                "SessionLauncher: failed to release reservation for session %s",
                session_id,
                exc_info=True,
            )

    def can_reset_session(self, session_id: str) -> bool:
        """无 runtime 预约能力时的只读兜底；生产重置应使用 ``reserve_reset_session``。"""
        if self._session_quiescent_callback is None:
            return False
        try:
            return bool(self._session_quiescent_callback(session_id))
        except Exception:
            logger.error(
                "SessionLauncher: reset quiescence check failed for session %s",
                session_id,
                exc_info=True,
            )
            return False

    @contextmanager
    def reserve_reset_session(self, session_id: str):
        """在清绑定期间独占 session，返回是否成功取得安全重置资格。"""
        normalized_session_id = (session_id or "").strip()
        if not normalized_session_id:
            yield False
            return
        if self._reserve_callback is None:
            yield self.can_reset_session(normalized_session_id)
            return

        reservation_id = f"schreset_{uuid.uuid4().hex[:16]}"
        acquired = False
        try:
            acquired = bool(self._reserve_callback(normalized_session_id, reservation_id))
        except Exception:
            logger.error(
                "SessionLauncher: reset reservation failed for session %s",
                normalized_session_id,
                exc_info=True,
            )
        try:
            yield acquired
        finally:
            self._release_reservation(
                normalized_session_id,
                reservation_id,
                reserved=acquired,
            )

    def _fail_run(
        self,
        run_id: str,
        *,
        failure_reason: str,
        clear_trigger_message_sequence: bool = False,
    ) -> None:
        """启动链任一步失败时显式结束账目，避免永久 ``running`` 静默悬挂。"""
        updated = None
        for attempt in range(1, _FAIL_RUN_MAX_ATTEMPTS + 1):
            try:
                with self._run_repo_scope() as run_repo:
                    updated = run_repo.cas_transition(
                        run_id,
                        from_status="running",
                        to_status="failed",
                        failure_reason=failure_reason,
                        clear_trigger_message_sequence=clear_trigger_message_sequence,
                    )
                break
            except Exception:
                # 注入 repo 仅用于受控测试/组合；commit 异常可能把其 Session 留在
                # failed transaction。生产每次 attempt 用 fresh repo，注入路径则先回滚。
                if self._run_repo is not None:
                    session = getattr(self._run_repo, "session", None)
                    rollback = getattr(session, "rollback", None)
                    if callable(rollback):
                        try:
                            rollback()
                        except Exception:
                            logger.warning(
                                "SessionLauncher: injected run repository rollback failed",
                                exc_info=True,
                            )
                if attempt >= _FAIL_RUN_MAX_ATTEMPTS:
                    logger.critical(
                        "SessionLauncher: failed to terminate run %s after %d attempts",
                        run_id,
                        attempt,
                        exc_info=True,
                    )
                    raise
                logger.warning(
                    "SessionLauncher: failed to terminate run %s (attempt %d/%d); retrying",
                    run_id,
                    attempt,
                    _FAIL_RUN_MAX_ATTEMPTS,
                    exc_info=True,
                )
        if updated is None:
            return
        from src.business.scheduling.terminal_event_delivery import deliver_terminal_event

        deliver_terminal_event(updated.run_id, run_repo=self._run_repo)
