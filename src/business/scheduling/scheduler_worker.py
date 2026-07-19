"""``SchedulerWorker`` —— 后台值守线程：周期扫描 + 立即唤醒（033 US1）。

仿 ``BrainBackgroundWorker``：``threading.Thread`` + ``_stop_event`` + loop。双 Event：

- ``_stop_event.wait(timeout=...)``：周期兜底（``scheduler.scan_interval_seconds``，bounded
  ``[5, 600]``，默认 30），动态缩短为 ``min(scan_interval, max(0, soonest_next_fire - now))``；
- ``notify_scheduler_worker()``：立即唤醒（fire_now / 任务创建 / 状态变更后调用）。

每轮：

1. ``now = utc_now_naive()``；
2. 扫 ``service._repo.list_due(now)``（active ∧ next_fire_at <= now）；
3. 对每个到期任务：reentry 检查（``has_active_run`` → CAS run skipped，
   emit scheduler_run_terminal skipped，continue）；这是 FR-011 不可关闭的安全不变量；
4. ``launcher.launch(task, instruction)`` 点燃；
5. ``service.rollover(task)``：one_shot → completed + next_fire=NULL，recurring → 滚到下个未来时点。

到期扫描同时承担 misfire：app 恢复后仅执行当前仍到期的一次，随后由 ``rollover``
把周期任务推进到未来首点；暂停任务不进入 ``list_due``，恢复语义由 service 处理。
"""

from __future__ import annotations

import logging
import threading
from contextlib import nullcontext
from typing import Any, Callable, Optional

from src.business.scheduling.scheduler_service import (
    SchedulerService,
    scheduler_task_trigger_guard,
)
from src.business.scheduling.session_launcher import (
    ScheduledRunAlreadyActive,
    SessionLauncher,
)
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

_WORKER_LOCK = threading.Lock()
_worker: Optional["SchedulerWorker"] = None
_ERROR_RETRY_SECONDS = 1.0


class SchedulerWorker:
    """后台值守线程：周期扫描到期任务 + 立即唤醒。"""

    def __init__(
        self,
        service: SchedulerService | None,
        launcher: SessionLauncher,
        *,
        run_repo: ScheduledTaskRunRepository | None = None,
        config: Any = None,
        retry_terminal_events: Callable[[], int] | None = None,
    ) -> None:
        # 注入 service 仅供单线程测试；生产传 None，每个 tick / deadline 查询创建
        # fresh service scope，避免任一 Repository 事务失败永久毒化后台 worker。
        self._service = service
        self._launcher = launcher
        # 注入 repo 仅供单线程测试；生产每次访问创建 fresh scope，避免一次 DB 异常
        # 把长生命周期 Session 留在 failed transaction 后永久毒化 worker。
        self._run_repo = run_repo
        self._config = config
        self._retry_terminal_events = retry_terminal_events
        self._tick_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- 生命周期 -------------------------------------------------------------

    def start(self) -> None:
        global _worker
        with _WORKER_LOCK:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._tick_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="scheduler-worker",
            )
            _worker = self
            try:
                self._thread.start()
            except Exception:
                if _worker is self:
                    _worker = None
                self._thread = None
                raise
            logger.info("SchedulerWorker started")

    def stop(self) -> None:
        global _worker
        thread = self._thread
        self._stop_event.set()
        self._tick_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("SchedulerWorker still stopping; join timed out")
        with _WORKER_LOCK:
            if _worker is self:
                _worker = None
        logger.info("SchedulerWorker stopped")

    def notify(self) -> None:
        """立即唤醒（fire_now / 任务创建 / 状态变更后调用）。"""
        self._tick_event.set()

    # -- 主循环 ---------------------------------------------------------------

    def _worker_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    self._tick()
                except Exception:
                    logger.error("SchedulerWorker tick failed", exc_info=True)
                try:
                    timeout = self._compute_wait_timeout()
                except Exception:
                    # 配置/Repository 暂时不可用不能让后台线程静默死亡；1s 只是错误重试
                    # backoff，不是调度扫描配置的替代值。
                    logger.error(
                        "SchedulerWorker wait deadline calculation failed; retrying",
                        exc_info=True,
                    )
                    timeout = _ERROR_RETRY_SECONDS
                self._tick_event.wait(timeout=timeout)
                self._tick_event.clear()
        finally:
            logger.debug("SchedulerWorker loop exited")

    def _tick(self) -> None:
        """一轮扫描：到期任务 → launch → rollover。"""
        if self._retry_terminal_events is not None:
            try:
                self._retry_terminal_events()
            except Exception:
                logger.error(
                    "SchedulerWorker: terminal event retry scan failed",
                    exc_info=True,
                )
        # 创建确认卡与调度扫描共用值守线程；提交路径还会再次原子校验 expires_at，
        # 因而即使 tick 延迟也不会让过期卡落库。
        try:
            from src.business.scheduling.scheduling_confirmation_manager import (
                get_scheduling_confirmation_manager,
            )

            get_scheduling_confirmation_manager().expire_due()
        except Exception:
            logger.error(
                "SchedulerWorker: scheduling confirmation expiry scan failed", exc_info=True
            )

        with self._service_scope() as service:
            now = utc_now_naive()
            due_tasks = service._repo.list_due(now, limit=100)
            if not due_tasks:
                return
            for task in due_tasks:
                if self._stop_event.is_set():
                    break
                try:
                    with scheduler_task_trigger_guard():
                        # list_due 只是候选快照；暂停/删除可能在扫描后发生。临界区内
                        # 重读权威行，确保只有仍 active、未删且仍到期的任务会 launch。
                        current = service._repo.get(task.scheduled_task_id)
                        if (
                            current is None
                            or current.is_deleted
                            or current.status != "active"
                            or current.next_fire_at is None
                            or current.next_fire_at > now
                        ):
                            continue
                        task = current
                        # reentry：同任务有活跃 run（running / waiting_user）→ 本次跳过、
                        # 记一条 skipped run（历史可见，不通知用户）+ rollover。
                        with self._run_repo_scope() as run_repo:
                            has_active_run = run_repo.has_active_run(task.scheduled_task_id)
                        if has_active_run:
                            if not self._record_skipped(task, now):
                                # FR-011 要求“跳过并记 skipped”。账目写失败时不能
                                # 悄悄推进 next_fire；保留 due 让下一 tick 重试。
                                continue
                            try:
                                service.rollover(task.scheduled_task_id)
                            except Exception:
                                logger.warning(
                                    "SchedulerWorker: rollover after skip failed for %s",
                                    task.scheduled_task_id,
                                    exc_info=True,
                                )
                            logger.info(
                                "SchedulerWorker: skip due task %s "
                                "(active run exists); recorded skipped",
                                task.scheduled_task_id,
                            )
                            continue
                        # T058：todo 来源每次触发前读取权威待办；悬空时原子作废任务。
                        instruction = service.prepare_instruction_for_trigger(task)
                        if instruction is None:
                            logger.info(
                                "SchedulerWorker: expire due todo-task %s (todo dangling)",
                                task.scheduled_task_id,
                            )
                            continue
                        try:
                            self._launcher.launch(
                                scheduled_task_id=task.scheduled_task_id,
                                instruction=instruction,
                                started_at=now,
                            )
                        except ScheduledRunAlreadyActive:
                            # fire-now 与 worker（或两个迟到 tick）并发时，数据库唯一槽
                            # 决定 first-wins；失败方只记 skipped。
                            if self._record_skipped(task, now):
                                service.rollover(task.scheduled_task_id)
                            continue
                        # rollover：one_shot → completed；recurring → 未来点
                        service.rollover(task.scheduled_task_id)
                except Exception:
                    logger.error(
                        "SchedulerWorker: process task %s failed",
                        task.scheduled_task_id,
                        exc_info=True,
                    )

    def _record_skipped(self, task, now) -> bool:
        """reentry 跳过时记一条 ``skipped`` run（不启动会话；历史可见、不打扰用户）。

        占位 ``session_id`` 标识它是不启动会话的纯账目记录（前端历史展示「跳过」）。
        返回是否成功持久化；失败时调用方必须保留 due 供下一轮重试。
        """
        try:
            with self._run_repo_scope() as run_repo:
                run_repo.create_skipped(
                    scheduled_task_id=task.scheduled_task_id,
                    started_at=now,
                )
        except Exception:
            logger.warning(
                "SchedulerWorker: record skipped failed for %s",
                task.scheduled_task_id,
                exc_info=True,
            )
            return False
        return True

    def _run_repo_scope(self):
        if self._run_repo is not None:
            return nullcontext(self._run_repo)
        return ScheduledTaskRunRepository()

    def _service_scope(self):
        if self._service is not None:
            return nullcontext(self._service)
        return SchedulerService(launcher=self._launcher)

    def _compute_wait_timeout(self) -> float:
        """``max(0.5, min(scan_interval, max(0, soonest_next_fire - now)))``。"""
        scan_interval = self._get_scan_interval()
        try:
            with self._service_scope() as service:
                soonest = service._repo.soonest_next_fire()
        except Exception:
            logger.error(
                "SchedulerWorker: soonest trigger lookup failed; using bounded scan interval",
                exc_info=True,
            )
            soonest = None
        if soonest is None:
            return float(scan_interval)
        now = utc_now_naive()
        try:
            delta = (soonest - now).total_seconds()
        except Exception:
            logger.error(
                "SchedulerWorker: invalid soonest trigger value %r; using bounded scan interval",
                soonest,
                exc_info=True,
            )
            return float(scan_interval)
        dynamic = max(0.0, min(float(scan_interval), delta))
        # 0.5s 是防空转下限；scan_interval 是无更早任务时的兜底等待上限。
        return max(0.5, dynamic)

    # -- 配置 -----------------------------------------------------------------

    def _get_config(self):
        if self._config is None:
            from src.data.unified_config import get_unified_config

            self._config = get_unified_config()
        return self._config

    def _get_scan_interval(self) -> int:
        return int(self._get_config().get_scheduler_scan_interval_seconds())


def notify_scheduler_worker() -> None:
    """模块级便利函数：唤醒单例 worker（若已启动）。"""
    with _WORKER_LOCK:
        worker = _worker
    if worker is not None:
        worker.notify()


def get_scheduler_worker() -> Optional[SchedulerWorker]:
    with _WORKER_LOCK:
        return _worker
