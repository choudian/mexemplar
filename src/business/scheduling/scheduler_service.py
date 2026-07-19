"""``SchedulerService`` —— 调度中心业务入口（CRUD + 触发时机判定 + fire_now + 接管）。

仿 ``UserTodoService`` 的 with-context manager + normalize + ``project_*`` 风格。承载
033 的核心业务语义：

- ``create_from_draft``：经确认卡确认后的落库入口（CC-002 todo 来源恒 one_shot 门卫）。
- ``list_tasks`` / ``get_task`` / ``update_display`` / ``pause`` / ``resume`` /
  ``set_unattended`` / ``soft_delete``：CRUD（仅 ``unattended_auto_approve`` 走 set_unattended）。
- ``fire_now``：行内「现在跑一次」立即触发（不经确认卡，经 SessionLauncher 点燃 + 建 run）。
- ``list_runs`` / ``get_run`` / ``takeover``：run 账目与接管。
- ``rollover``：触发后滚动 ``next_fire_at``（one_shot → completed，recurring → 滚动到下个未来时点）。

严格分层：business 不 import desktop_api；``SessionLauncher`` 经 ``set_launcher`` 或构造参注入。
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from typing import Any, Optional

from src.business.scheduling.models import ScheduledTaskStatus
from src.business.scheduling.schedule_calc import (
    compute_next_interval_from_anchor,
    describe_schedule,
    validate_schedule_payload,
)
from src.data.models_sqlite import ScheduledTask, ScheduledTaskRun
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.scheduling_types import (
    RUN_TAKEOVER_STATUS_VALUES,
    RUN_TERMINAL_STATUS_VALUES,
)
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

TITLE_LIMIT = 120
INSTRUCTION_LIMIT = 4000
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500
SUMMARY_MAX_CHARS = 500
FAILURE_REASON_SAFE = "scheduled session failed to complete successfully"

_DEFAULT_LAUNCHER_LOCK = threading.Lock()
_default_launcher: Any = None
_UNATTENDED_MUTATION_LOCK = threading.Lock()
_SCHEDULE_TASK_MUTATION_LOCK = threading.RLock()


class SchedulerRuntimeUnavailable(RuntimeError):
    """desktop lifespan 尚未装配 scheduled session launcher。"""


class ScheduledTakeoverUnavailable(RuntimeError):
    """failed/waiting run 的真实 scheduled session 无法恢复。"""


def configure_default_scheduler_launcher(launcher: Any) -> None:
    """注册供短生命周期 API service 复用的进程级 launcher。"""
    global _default_launcher
    with _DEFAULT_LAUNCHER_LOCK:
        _default_launcher = launcher


def clear_default_scheduler_launcher(launcher: Any | None = None) -> None:
    """shutdown 时撤销 launcher；传入实例可防迟到 teardown 清掉新实例。"""
    global _default_launcher
    with _DEFAULT_LAUNCHER_LOCK:
        if launcher is None or _default_launcher is launcher:
            _default_launcher = None


def _get_default_scheduler_launcher() -> Any:
    with _DEFAULT_LAUNCHER_LOCK:
        return _default_launcher


@contextmanager
def scheduler_task_trigger_guard():
    """Serialize a trigger with pause/resume/delete and require a fresh row read.

    ``list_due`` is only a candidate snapshot.  The worker holds this guard while
    re-reading and launching; user mutations use the same guard, so whichever side
    wins determines whether that occurrence may start.
    """
    with _SCHEDULE_TASK_MUTATION_LOCK:
        yield


class SchedulerService:
    """调度中心业务服务。"""

    def __init__(
        self,
        repo: ScheduledTaskRepository | None = None,
        run_repo: ScheduledTaskRunRepository | None = None,
        *,
        launcher: Any = None,
        chat_service: Any = None,
    ) -> None:
        self._repo = repo or ScheduledTaskRepository()
        self._owns_repo = repo is None
        self._run_repo = run_repo or ScheduledTaskRunRepository()
        self._owns_run_repo = run_repo is None
        self._launcher = launcher
        self._chat_service = chat_service

    def close(self) -> None:
        if self._owns_repo:
            self._repo.close()
        if self._owns_run_repo:
            self._run_repo.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def set_launcher(self, launcher: Any) -> None:
        """注入 SessionLauncher（desktop lifespan 装配时调用）。"""
        self._launcher = launcher

    # -- Create（确认卡 confirm 后的唯一落库入口）----------------------------

    def create_from_draft(
        self, draft: dict[str, Any], *, unattended_auto_approve: bool = False
    ) -> dict[str, Any]:
        """从确认卡 draft 落库（CC-002 todo 恒 one_shot 门卫）。

        draft 期望字段：``source_type`` / ``source_ref`` / ``title`` / ``schedule_kind``
        / ``schedule_payload`` / ``instruction`` / ``scheduleDescription`` /
        ``next_fire_at``（试算）。缺字段时按安全默认补齐并记日志。
        """
        if not isinstance(draft, dict):
            raise ValueError("draft must be a dict")

        source_type = _normalize_source_type(draft.get("source_type"))
        schedule_kind = _normalize_schedule_kind(draft.get("schedule_kind"))
        # CC-002 门卫：todo 来源恒 one_shot
        if source_type == "todo" and schedule_kind != "one_shot":
            raise ValueError("todo-sourced scheduled tasks must be one_shot")

        schedule_payload = draft.get("schedule_payload")
        if schedule_payload is None:
            schedule_payload = {}
        if isinstance(schedule_payload, str):
            try:
                schedule_payload = json.loads(schedule_payload)
            except json.JSONDecodeError:
                raise ValueError("schedule_payload is not valid JSON")
        if not isinstance(schedule_payload, dict):
            raise ValueError("schedule_payload must be an object")

        source_ref = _resolve_source_ref(source_type, draft)
        title = _normalize_title(draft.get("title"))
        instruction = _normalize_instruction(
            draft.get("instruction") or (source_ref if source_type == "direct" else None)
        )

        # confirm 时以后端 payload 重新权威计算，不信任可陈旧或可篡改的 draft 试算值。
        next_fire_at = validate_schedule_payload(
            schedule_kind,
            schedule_payload,
            after=utc_now_naive(),
        )

        row = self._repo.create(
            source_type=source_type,
            source_ref=source_ref,
            title=title,
            instruction=instruction,
            schedule_kind=schedule_kind,
            schedule_payload=schedule_payload,
            unattended_auto_approve=bool(unattended_auto_approve),
            next_fire_at=next_fire_at,
        )
        # 确认卡勾选落库后增量刷新 UnattendedConfirmationManager 授权集（CC-005）。
        try:
            self._refresh_unattended_in_manager(
                row.scheduled_task_id,
                bool(unattended_auto_approve),
            )
        except Exception:
            # 新任务尚不可能命中旧授权；enabled 刷新失败时把持久开关补偿回 false，
            # 并显式回收可能已被 manager 部分写入的内存授权，避免 fail-open。
            logger.error(
                "scheduler_service: initialize unattended state failed for %s",
                row.scheduled_task_id,
                exc_info=True,
            )
            if unattended_auto_approve:
                row = self._compensate_failed_unattended_enable(row.scheduled_task_id)
        self._emit_task_changed(row.scheduled_task_id, "created")
        return self.project_scheduled_task(row)

    # -- Read ----------------------------------------------------------------

    def list_tasks(
        self,
        *,
        status_filter: str | None = None,
        limit: int = DEFAULT_LIST_LIMIT,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        normalized_offset = max(0, int(offset))
        rows, total = self._repo.list_tasks(
            status_filter=status_filter,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return [self.project_scheduled_task(row) for row in rows], total

    def get_task(self, scheduled_task_id: str) -> dict[str, Any]:
        row = self._repo.get(_normalize_id(scheduled_task_id))
        if row is None or row.is_deleted:
            raise LookupError("scheduled_task_not_found")
        return self.project_scheduled_task(row)

    # -- Update（白名单 + CAS）----------------------------------------------

    def update_display(self, scheduled_task_id: str, *, title: str | None = None) -> dict[str, Any]:
        """仅展示字段（白名单：title）。调度核心字段不可经此改。"""
        row = self._repo.update_display(
            _normalize_id(scheduled_task_id),
            title=_normalize_title(title) if title is not None else None,
        )
        if row is None:
            raise LookupError("scheduled_task_not_found")
        return self.project_scheduled_task(row)

    def pause(self, scheduled_task_id: str) -> dict[str, Any]:
        with scheduler_task_trigger_guard():
            row = self._repo.cas_status(
                _normalize_id(scheduled_task_id),
                from_status=str(ScheduledTaskStatus.ACTIVE),
                to_status=str(ScheduledTaskStatus.PAUSED),
            )
            if row is None:
                raise LookupError("scheduled_task_not_found")
            self._emit_task_changed(row.scheduled_task_id, "paused")
            return self.project_scheduled_task(row)

    def resume(self, scheduled_task_id: str) -> dict[str, Any]:
        with scheduler_task_trigger_guard():
            return self._resume_locked(scheduled_task_id)

    def _resume_locked(self, scheduled_task_id: str) -> dict[str, Any]:
        task_id = _normalize_id(scheduled_task_id)
        current = self._repo.get(task_id)
        if (
            current is None
            or current.is_deleted
            or current.status != str(ScheduledTaskStatus.PAUSED)
        ):
            raise LookupError("scheduled_task_not_found")

        now = utc_now_naive()
        is_overdue = current.next_fire_at is None or current.next_fire_at <= now
        if is_overdue and current.schedule_kind == "one_shot":
            # 暂停期间过点的一次性任务不补跑（FR-010）。
            if not self.expire_task(task_id):
                raise LookupError("scheduled_task_not_found")
            return self.get_task(task_id)

        if is_overdue:
            payload = _safe_loads_payload(current.schedule_payload)
            try:
                next_fire = validate_schedule_payload("recurring", payload, after=now)
            except ValueError:
                logger.error(
                    "scheduler_service: paused recurring task %s has invalid payload; expiring",
                    task_id,
                    exc_info=True,
                )
                if not self.expire_task(task_id):
                    raise LookupError("scheduled_task_not_found")
                return self.get_task(task_id)
            row = self._repo.cas_resume_with_next_fire(task_id, next_fire_at=next_fire)
        else:
            row = self._repo.cas_status(
                task_id,
                from_status=str(ScheduledTaskStatus.PAUSED),
                to_status=str(ScheduledTaskStatus.ACTIVE),
            )
        if row is None:
            raise LookupError("scheduled_task_not_found")
        self._emit_task_changed(row.scheduled_task_id, "resumed")
        return self.project_scheduled_task(row)

    def set_unattended(self, scheduled_task_id: str, enabled: bool) -> dict[str, Any]:
        """详情页 PATCH 开关：per-task 免确认写入（CC-005 唯一 UI 写入路径之一）。"""
        task_id = _normalize_id(scheduled_task_id)
        enabled_flag = bool(enabled)
        # 跨短生命周期 service 串行化 DB + runtime 双写，避免 enable 与 soft-delete
        # 交错后把已删除任务重新塞回授权集。
        with _UNATTENDED_MUTATION_LOCK:
            if not enabled_flag:
                # 撤销先落内存：若 manager 不可用则本次操作显式失败，绝不能先把 DB
                # 改成 false 却让旧授权在当前进程继续生效。
                self._refresh_unattended_in_manager(task_id, False)
            row = self._repo.set_unattended_auto_approve(task_id, enabled_flag)
            if row is None:
                raise LookupError("scheduled_task_not_found")
            if enabled_flag:
                try:
                    self._refresh_unattended_in_manager(row.scheduled_task_id, True)
                except Exception as exc:
                    # 授权启用必须 DB + runtime 同时成功；runtime 失败时补偿持久位，
                    # 并回收 manager 可能“先 add 后抛错”的部分写入，保持默认拒绝。
                    self._compensate_failed_unattended_enable(task_id)
                    raise RuntimeError("unattended authorization could not be enabled") from exc
        self._emit_task_changed(row.scheduled_task_id, "status_changed")
        return self.project_scheduled_task(row)

    def soft_delete(self, scheduled_task_id: str) -> None:
        task_id = _normalize_id(scheduled_task_id)
        with scheduler_task_trigger_guard():
            with _UNATTENDED_MUTATION_LOCK:
                # 回收授权先于软删；任何 manager 异常都会阻止“已删除但仍获授权”的分裂状态。
                self._refresh_unattended_in_manager(task_id, False)
                if not self._repo.soft_delete(task_id):
                    raise LookupError("scheduled_task_not_found")
        self._emit_task_changed(task_id, "deleted")

    def expire_task(self, scheduled_task_id: str) -> bool:
        """把 active 任务作废为 ``expired``（待办悬空 / 触发时读不到指令等；FR-016/T058）。

        CAS ``active`` / ``paused`` → ``expired``；返回是否成功转移。不读不写 ``user_todos``
        （仅由调用方在触发前校验 todo_id 存在性）。
        """
        from src.business.scheduling.models import task_status_sources_for, ScheduledTaskStatus

        new_row = self._repo.cas_status(
            _normalize_id(scheduled_task_id),
            from_status=task_status_sources_for(ScheduledTaskStatus.EXPIRED),
            to_status=str(ScheduledTaskStatus.EXPIRED),
        )
        if new_row is None:
            return False
        self._emit_task_changed(new_row.scheduled_task_id, "status_changed")
        return True

    # -- Fire / Rollover / Takeover -----------------------------------------

    def fire_now(self, scheduled_task_id: str) -> dict[str, Any]:
        """行内「现在跑一次」立即触发（FR-018，不经确认卡）。

        reentry 检查：同任务存在 running/waiting_user 的 run 时，本次记 ``skipped``。
        """
        with scheduler_task_trigger_guard():
            return self._fire_now_locked(scheduled_task_id)

    def _fire_now_locked(self, scheduled_task_id: str) -> dict[str, Any]:
        task_id = _normalize_id(scheduled_task_id)
        row = self._repo.get(task_id)
        if row is None or row.is_deleted:
            raise LookupError("scheduled_task_not_found")

        instruction = self.prepare_instruction_for_trigger(row)
        if instruction is None:
            raise ValueError("referenced todo is unavailable; scheduled task expired")

        # 快速路径；真正的并发硬保证由 run partial unique index + launcher 原子占槽承担。
        if self._run_repo.has_active_run(task_id):
            return self._record_skipped_run(task_id)

        launcher = self._require_launcher()
        from src.business.scheduling.session_launcher import ScheduledRunAlreadyActive

        try:
            run_id = launcher.launch(
                scheduled_task_id=task_id,
                instruction=instruction,
                started_at=utc_now_naive(),
            )
        except ScheduledRunAlreadyActive:
            return self._record_skipped_run(task_id)
        run = self._run_repo.get(run_id)
        if run is None:  # pragma: no cover - 防御性
            raise RuntimeError("run disappeared immediately after launch")
        self._emit_task_changed(task_id, "fired")
        return self.project_run(run)

    def prepare_instruction_for_trigger(self, row: ScheduledTask) -> str | None:
        """校验来源并返回用户在确认卡核定后的实际指令。

        todo 来源在每次触发前只读权威待办：删除/完成时把 scheduled task 置 expired；
        Repository 读取异常向上抛出，让 worker 本轮不触发并在下一轮重试。用户编辑后的
        ``row.instruction`` 始终优先，旧草稿数据缺失时才用当前 todo 标题+描述兜底。
        """
        if row.source_type == "direct":
            return _compose_instruction(row)

        from src.data.repos.user_todo_repository import UserTodoRepository

        with UserTodoRepository() as repo:
            todo = repo.get(row.source_ref)
        if todo is None or todo.status == "done":
            self.expire_task(row.scheduled_task_id)
            return None
        persisted = (getattr(row, "instruction", "") or "").strip()
        if persisted:
            return persisted
        description = (todo.description or "").strip()
        return f"{todo.title}{('：' + description) if description else ''}".strip()

    def rollover(self, scheduled_task_id: str) -> None:
        """触发后滚动 ``next_fire_at``：one_shot → completed，recurring → 滚到下个未来时点。

        由 SchedulerWorker 在 launch 之后调用。
        """
        task_id = _normalize_id(scheduled_task_id)
        row = self._repo.get(task_id)
        if row is None or row.is_deleted:
            return
        payload = _safe_loads_payload(row.schedule_payload)
        if row.schedule_kind == "one_shot":
            new_row = self._repo.cas_status(
                task_id,
                from_status=str(ScheduledTaskStatus.ACTIVE),
                to_status=str(ScheduledTaskStatus.COMPLETED),
            )
            if new_row is not None:
                self._repo.cas_next_fire(task_id, next_fire_at=None, last_fired_at=utc_now_naive())
                self._emit_task_changed(task_id, "status_changed")
            return
        # recurring：滚动到严格晚于当前时刻的下个未来点。存量非法 payload
        # fail-closed 作废，不能把已过时刻写回造成 0.5s 洪泛。
        now = utc_now_naive()
        try:
            next_fire = validate_schedule_payload("recurring", payload, after=now)
            if "interval_seconds" in payload and row.next_fire_at is not None:
                next_fire = compute_next_interval_from_anchor(
                    payload,
                    anchor=row.next_fire_at,
                    after=now,
                )
                if next_fire is None:
                    raise ValueError("interval schedule cannot advance from its prior trigger")
        except ValueError:
            logger.error(
                "scheduler_service: recurring task %s has invalid payload during rollover; expiring",
                task_id,
                exc_info=True,
            )
            self.expire_task(task_id)
            return
        self._repo.cas_next_fire(
            task_id,
            next_fire_at=next_fire,
            last_fired_at=now,
        )
        self._emit_task_changed(task_id, "fired")

    def list_runs(
        self, scheduled_task_id: str, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        normalized_limit = max(1, min(int(limit), MAX_LIST_LIMIT))
        normalized_offset = max(0, int(offset))
        # 校验任务存在
        self.get_task(scheduled_task_id)
        rows, total = self._run_repo.list_by_task(
            _normalize_id(scheduled_task_id),
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return [self.project_run(row) for row in rows], total

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self._run_repo.get(_normalize_id(run_id))
        if row is None:
            raise LookupError("scheduled_run_not_found")
        return self.project_run(row)

    def takeover(
        self,
        run_id: str,
        *,
        scheduled_task_id: str | None = None,
    ) -> dict[str, Any]:
        """接管 ``waiting_user`` / ``failed`` run，返回真实 sessionId。

        失败的 run 接管 = 用户从历史点进接着聊（不复活 failed run）。
        waiting_user 的 run 直接回 running，让 ``RunCompletionMonitor`` 在会话静默后再置终态。
        其他状态不存在「接管」语义，显式拒绝，避免 running/succeeded/skipped 被误报成功。
        """
        normalized_run_id = _normalize_id(run_id)
        with scheduler_task_trigger_guard():
            row = self._run_repo.get_fresh(normalized_run_id)
            if row is None:
                raise LookupError("scheduled_run_not_found")
            if scheduled_task_id is not None and row.scheduled_task_id != _normalize_id(
                scheduled_task_id
            ):
                # 所有权必须在 waiting_user -> running CAS 前校验，避免错误 path 先改状态后 404。
                raise LookupError("scheduled_run_not_found")
            if row.status not in RUN_TAKEOVER_STATUS_VALUES:
                raise ValueError("scheduled run is not available for takeover")

            task = self._repo.get(row.scheduled_task_id)
            if task is None:
                raise LookupError("scheduled_run_not_found")
            try:
                needs_recovery_draft = self._get_chat_service().ensure_scheduled_takeover_session(
                    row.scheduled_task_id,
                    session_id=row.session_id,
                    title=task.title,
                )
            except Exception as exc:
                logger.error(
                    "scheduler_service: failed to recover takeover session for run %s",
                    normalized_run_id,
                    exc_info=True,
                )
                raise ScheduledTakeoverUnavailable(
                    "scheduled takeover session is unavailable"
                ) from exc

            result: dict[str, Any] = {"sessionId": row.session_id}
            if needs_recovery_draft:
                result["recoveryDraft"] = _compose_instruction(task)
            if row.status == "waiting_user":
                updated = self._run_repo.cas_transition(
                    normalized_run_id,
                    from_status="waiting_user",
                    to_status="running",
                )
                if updated is None:  # pragma: no cover - 并发终态
                    raise LookupError("scheduled_run_not_found")
                result["sessionId"] = updated.session_id
            return result

    # -- Projection ---------------------------------------------------------

    def project_scheduled_task(self, row: ScheduledTask) -> dict[str, Any]:
        """camelCase DTO（对齐 rest-api.md ScheduledTaskItem）。"""
        payload = _safe_loads_payload(row.schedule_payload)
        tz_name = payload.get("tz") if isinstance(payload, dict) else None
        schedule_description = describe_schedule(row.schedule_kind, payload, tz_name)
        # 从最近一条 run 派生 lastRunOutcome / lastRunAt
        last_outcome, last_run_at = self._last_run_projection(row.scheduled_task_id)
        return {
            "scheduledTaskId": row.scheduled_task_id,
            "sourceType": row.source_type,
            "sourceRef": row.source_ref,
            "title": row.title,
            "scheduleKind": row.schedule_kind,
            "scheduleDescription": schedule_description,
            "status": row.status,
            "unattendedAutoApprove": bool(row.unattended_auto_approve),
            "nextFireAt": row.next_fire_at.isoformat() if row.next_fire_at else None,
            "lastFireAt": row.last_fired_at.isoformat() if row.last_fired_at else None,
            "lastRunOutcome": last_outcome,
            "lastRunAt": last_run_at,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    def project_run(self, row: ScheduledTaskRun) -> dict[str, Any]:
        """camelCase DTO（对齐 rest-api.md ScheduledTaskRunItem）。"""
        return {
            "runId": row.run_id,
            "scheduledTaskId": row.scheduled_task_id,
            # skipped 记录没有启动会话；内部 NOT NULL 占位不得泄漏成可导航 session。
            "sessionId": None if row.status == "skipped" else row.session_id,
            "startedAt": row.started_at.isoformat(),
            "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
            "status": row.status,
            "summary": row.summary,
            "failureReason": row.failure_reason,
        }

    # -- 内部 ----------------------------------------------------------------

    def _require_launcher(self):
        if self._launcher is None:
            self._launcher = _get_default_scheduler_launcher()
        if self._launcher is None:
            raise SchedulerRuntimeUnavailable("scheduler runtime is not ready")
        return self._launcher

    def _get_chat_service(self):
        if self._chat_service is None:
            from src.business.services.chat_service import ChatService

            self._chat_service = ChatService()
        return self._chat_service

    def _record_skipped_run(self, task_id: str) -> dict[str, Any]:
        skipped = self._run_repo.create_skipped(
            scheduled_task_id=task_id,
            started_at=utc_now_naive(),
        )
        self._emit_run_terminal(skipped, outcome="skipped")
        return self.project_run(skipped)

    def _last_run_projection(self, scheduled_task_id: str) -> tuple[Optional[str], Optional[str]]:
        try:
            rows, _ = self._run_repo.list_by_task(scheduled_task_id, limit=1, offset=0)
        except Exception:
            logger.warning(
                "scheduler_service: latest run lookup failed for %s",
                scheduled_task_id,
                exc_info=True,
            )
            return None, None
        if not rows:
            return None, None
        latest = rows[0]
        outcome = latest.status if latest.status in RUN_TERMINAL_STATUS_VALUES else None
        return outcome, latest.started_at.isoformat() if latest.started_at else None

    def _emit_task_changed(self, scheduled_task_id: str, change_type: str) -> None:
        from src.utils.events import emit

        try:
            emit(
                "scheduler_task_changed",
                None,
                scheduled_task_id=scheduled_task_id,
                change_type=change_type,
            )
        except Exception:
            logger.warning(
                "scheduler_service: emit scheduler_task_changed failed for %s",
                scheduled_task_id,
                exc_info=True,
            )
        finally:
            # UI 事件失败不得阻断调度；同进程 worker 仍要立即重算 wait deadline。
            try:
                from src.business.scheduling.scheduler_worker import notify_scheduler_worker

                notify_scheduler_worker()
            except Exception:
                logger.error(
                    "scheduler_service: failed to notify scheduler worker for %s",
                    scheduled_task_id,
                    exc_info=True,
                )

    def _emit_run_terminal(self, run: ScheduledTaskRun, *, outcome: str) -> None:
        from src.utils.events import emit

        try:
            emit(
                "scheduler_run_terminal",
                None,
                scheduled_task_id=run.scheduled_task_id,
                run_id=run.run_id,
                session_id=run.session_id,
                status=outcome,
            )
        except Exception:
            logger.warning(
                "scheduler_service: emit scheduler_run_terminal failed for %s",
                run.run_id,
                exc_info=True,
            )

    def _refresh_unattended_in_manager(self, scheduled_task_id: str, enabled: bool) -> None:
        """增量刷新 UnattendedConfirmationManager（CC-005）。

        调用方按启用/撤销方向决定写入顺序与补偿；本方法不得吞异常，否则撤销路径
        可能形成“DB 已关闭、runtime 仍放行”的 fail-open 状态。
        """
        from src.business.scheduling.unattended_confirmation_manager import (
            get_unattended_confirmation_manager,
        )

        get_unattended_confirmation_manager().set(scheduled_task_id, bool(enabled))

    def _compensate_failed_unattended_enable(self, scheduled_task_id: str) -> ScheduledTask:
        """撤销一次失败的 enable 双写，包括 manager 的潜在部分写入。

        manager 的 ``set(True)`` 理论上很小，但日志 handler 等异常仍可能发生在授权集
        已 add 之后。补偿不能只改 SQLite，否则当前进程会继续免确认。先把持久位改回
        false，再以 ``set(False)`` 回收内存；若增量回收也异常，则用 ``load_all`` 的
        fail-closed 契约从数据库重建授权集。
        """
        task_id = _normalize_id(scheduled_task_id)
        compensated = self._repo.set_unattended_auto_approve(task_id, False)

        try:
            self._refresh_unattended_in_manager(task_id, False)
        except Exception:
            logger.critical(
                "scheduler_service: incremental unattended compensation failed for %s; "
                "reloading authorization set",
                task_id,
                exc_info=True,
            )
            from src.business.scheduling.unattended_confirmation_manager import (
                get_unattended_confirmation_manager,
            )

            manager = get_unattended_confirmation_manager()
            manager.load_all()
            if manager.is_authorized(task_id):
                raise RuntimeError("unattended runtime authorization compensation failed")

        if compensated is None:
            raise RuntimeError("unattended persistent authorization compensation failed")
        return compensated


# =============================================================================
# normalize helpers（安全字面量校验，失败抛 ValueError）
# =============================================================================


def _normalize_id(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("id is required")
    return text


def _normalize_title(value: Any) -> str:
    title = str(value or "").strip()
    if not title:
        raise ValueError("title is required")
    if len(title) > TITLE_LIMIT:
        raise ValueError(f"title must be at most {TITLE_LIMIT} characters")
    return title


def _normalize_instruction(value: Any) -> str:
    instruction = str(value or "").strip()
    if not instruction:
        raise ValueError("instruction is required")
    if len(instruction) > INSTRUCTION_LIMIT:
        raise ValueError(f"instruction must be at most {INSTRUCTION_LIMIT} characters")
    return instruction


def _normalize_source_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text not in {"direct", "todo"}:
        raise ValueError("source_type must be direct or todo")
    return text


def _normalize_schedule_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text not in {"one_shot", "recurring"}:
        raise ValueError("schedule_kind must be one_shot or recurring")
    return text


def _resolve_source_ref(source_type: str, draft: dict[str, Any]) -> str:
    if source_type == "todo":
        ref = str(draft.get("todo_id") or draft.get("source_ref") or "").strip()
        if not ref:
            raise ValueError("todo_id is required for todo-sourced scheduled tasks")
        return ref
    # direct：source_ref = 指令文本
    ref = str(draft.get("source_ref") or draft.get("instruction") or "").strip()
    if not ref:
        raise ValueError("instruction is required for direct-sourced scheduled tasks")
    return ref


def _compose_instruction(row: ScheduledTask) -> str:
    """从 task 行读取用户确认后的指令；兼容早期草稿行的确定性兜底。"""
    persisted = (getattr(row, "instruction", "") or "").strip()
    if persisted:
        return persisted
    return row.source_ref if row.source_type == "direct" else row.title


def _safe_loads_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            result = json.loads(value)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
