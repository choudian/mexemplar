"""Background worker for Assistant task collaboration recovery scans.

周期性回收过期 TaskAttempt（lease 围栏）、过期看板认领、超预算会议通道，让
FR-005（无永久 running 僵任务）、FR-014（认领租约超时释放）、FR-016（会议时长预算关闭）
的超时/恢复语义在运行态真正生效，而不只是停在"可调用但无人调度"的原语。

随 desktop API sidecar 生命周期启动/停止；统一任务派发默认关闭时整轮 no-op。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable

from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)


class TaskCollaborationBackgroundWorker:
    """周期扫描线程，跑 TaskAttempt/看板/会议三类恢复原语。"""

    def __init__(self, config=None, resume_callback: Callable[[str, str], bool] | None = None) -> None:
        self._config = config
        self._resume_callback = resume_callback
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _get_config(self):
        if self._config is None:
            from src.data.unified_config import get_unified_config

            self._config = get_unified_config()
        return self._config

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="task-collaboration-worker",
        )
        self._thread.start()
        logger.info("TaskCollaborationBackgroundWorker started")

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("TaskCollaborationBackgroundWorker is still stopping")
        logger.info("TaskCollaborationBackgroundWorker stopping")

    def run_recovery_cycle(self, now: datetime | None = None) -> dict[str, int]:
        """跑一轮恢复扫描并返回各项处理计数。

        单次、确定性、可在测试中直接调用（不依赖线程或配置开关）。单个 job 失败被隔离，
        不影响其余 job——恢复链路属硬规则点名的静默失败路径，必须容错并记录。
        """
        current = now or utc_now_naive()
        return {
            "fenced_attempts": self._run_job(
                "fence_expired_attempts",
                lambda now: _fence_expired_attempts(now, self._resume_callback),
                current,
            ),
            "expired_claims": self._run_job("expire_claims", _expire_claims, current),
            "closed_channels": self._run_job("close_expired_channels", _close_expired_channels, current),
            "expired_questions": self._run_job("expire_stale_questions", _expire_stale_questions, current),
        }

    def _run_job(self, name: str, fn, now: datetime) -> int:
        try:
            count = fn(now)
            if count:
                logger.info("Task recovery %s handled %d item(s)", name, count)
            return count
        except Exception:
            logger.error("Task recovery job %s failed", name, exc_info=True)
            return 0

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if self._get_config().get_assistant_tasks_unified_dispatch_enabled():
                    self.run_recovery_cycle()
            except Exception:
                logger.error("Task recovery tick failed", exc_info=True)
            interval = self._get_config().get_assistant_tasks_recovery_scan_interval_seconds()
            self._stop_event.wait(timeout=interval)


# 每个 job 用对应 service 自持 session 的 context manager：不注入 repo 时 service 自建共享
# session，恢复方法内部 `_atomic()` 负责提交，`__exit__` 关闭 session——和过去手工 wire
# `task_session_scope` + 三个 Repository 等价，但去掉了每个 job 重复的接线样板。
def _fence_expired_attempts(
    now: datetime,
    resume_callback: Callable[[str, str], bool] | None = None,
) -> int:
    from src.business.task_collaboration.recovery import TaskRecoveryService

    with TaskRecoveryService(resume_callback=resume_callback) as service:
        return service.fence_expired_attempts(now)


def _expire_claims(now: datetime) -> int:
    from src.business.task_collaboration.board import TaskBoardService

    with TaskBoardService() as service:
        return service.expire_claims(now)


def _expire_stale_questions(now: datetime) -> int:
    from src.business.task_collaboration.questions import TaskQuestionService

    with TaskQuestionService() as service:
        return service.expire_stale_questions(now)


def _close_expired_channels(now: datetime) -> int:
    from src.business.task_collaboration.meetings import TaskMeetingService

    with TaskMeetingService() as service:
        return service.close_expired_channels(now)
