"""Keep a running attempt's lease alive while its executor works.

The lease was written once at attempt creation and never renewed, so recovery
fenced anything that ran longer than the lease and dispatched it again — while
the original executor was still working. An external coding session takes tens
of minutes against a two-minute lease, which produced one new attempt (and one
new CLI process) every two minutes until the app was closed.

The heartbeat deliberately stops the moment the executor returns or raises: a
lease that outlives its executor is exactly the failure recovery exists to
catch.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

# Renew well before expiry so one slow or failed renewal does not lose the
# lease. A third leaves room for two consecutive misses.
_RENEW_FRACTION = 3


class AttemptHeartbeat:
    """Renews one attempt's lease on a background thread."""

    def __init__(
        self,
        attempt_id: str,
        *,
        lease_seconds: int,
        renew: "callable",
    ) -> None:
        self._attempt_id = attempt_id
        self._lease_seconds = max(1, int(lease_seconds))
        self._renew = renew
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def interval_seconds(self) -> float:
        return max(1.0, self._lease_seconds / _RENEW_FRACTION)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop,
            name=f"attempt-heartbeat-{self._attempt_id[-8:]}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            # Bounded: the loop only ever waits on the stop event.
            thread.join(timeout=5.0)
        self._thread = None

    def __enter__(self) -> "AttemptHeartbeat":
        # 立即续一次租：线程池排队期间租约一直在倒计时（submit 到 worker 真正
        # 开始跑之间没有人心跳），多任务并发排队超过 lease 就会被 recovery 误
        # fence → 重派 → 再排队——死循环（真机验证踩中：max_workers=4 一次派 7 个）。
        # 开始执行的时刻才是租约的正确起点。续约被拒（已被 fence/终态）只记日志：
        # worker 继续跑完，记账时 CAS 自会拒绝，不与 recovery 抢。
        try:
            expires_at = utc_now_naive() + timedelta(seconds=self._lease_seconds)
            self._renew(self._attempt_id, lease_expires_at=expires_at)
        except Exception:
            logger.warning(
                "[task attempt] initial lease renewal failed: %s",
                self._attempt_id,
                exc_info=True,
            )
        self.start()
        return self

    def __exit__(self, *_exc_info) -> None:
        self.stop()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                expires_at = utc_now_naive() + timedelta(seconds=self._lease_seconds)
                if not self._renew(self._attempt_id, lease_expires_at=expires_at):
                    # The attempt is no longer active — fenced, completed or
                    # failed elsewhere. Renewing further would fight recovery.
                    logger.info(
                        "[task attempt] lease renewal declined; attempt no longer active: %s",
                        self._attempt_id,
                    )
                    return
            except Exception:
                # A failed renewal is survivable: the next tick retries, and if
                # they all fail the lease expires and recovery takes over —
                # which is the correct outcome for an executor we cannot vouch
                # for. Never let this kill the executor thread.
                logger.warning(
                    "[task attempt] lease renewal failed: %s",
                    self._attempt_id,
                    exc_info=True,
                )
