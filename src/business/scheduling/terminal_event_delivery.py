"""Durable delivery for scheduled run terminal events.

The run status is the business fact.  ``scheduler_run_terminal`` is the notification
projection of that fact and may fail after the status transaction commits.  v31 keeps
``terminal_event_delivered_at`` plus a monotonic ``terminal_event_version`` on the run
row; failed deliveries remain pending and are retried by ``RunCompletionMonitor`` on
startup and every scheduler tick.  Acknowledgements are generation-bound, so a stale
event cannot acknowledge a newer terminal transition.

Delivery is at-least-once across a process crash.  A process-local lock prevents two
threads in the desktop sidecar from emitting the same pending row concurrently.
"""

from __future__ import annotations

import logging
import threading
from contextlib import nullcontext

from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.scheduling_types import RUN_EVENT_DELIVERABLE_STATUS_VALUES

logger = logging.getLogger(__name__)

_DELIVERY_LOCK = threading.RLock()


def deliver_terminal_event(
    run_id: str,
    *,
    run_repo: ScheduledTaskRunRepository | None = None,
    task_repo: ScheduledTaskRepository | None = None,
) -> bool:
    """Deliver one pending terminal event and persist acknowledgement.

    Returns ``True`` when the row was already acknowledged or this call emitted and
    acknowledged it.  Any lookup, event, or acknowledgement failure is logged and
    leaves the row pending for a later retry.
    """

    rid = (run_id or "").strip()
    if not rid:
        return False
    with _DELIVERY_LOCK:
        try:
            with _run_repo_scope(run_repo) as scoped_run_repo:
                row = scoped_run_repo.get_fresh(rid)
                if row is None or row.status not in RUN_EVENT_DELIVERABLE_STATUS_VALUES:
                    return False
                if row.terminal_event_delivered_at is not None:
                    return True
                event_version = int(row.terminal_event_version)

                task_title = _lookup_task_title(
                    row.scheduled_task_id,
                    task_repo=task_repo,
                )
                from src.utils.events import emit

                emit(
                    "scheduler_run_terminal",
                    None,
                    scheduled_task_id=row.scheduled_task_id,
                    run_id=row.run_id,
                    session_id=row.session_id,
                    status=row.status,
                    summary=row.summary,
                    failure_reason=row.failure_reason,
                    task_title=task_title,
                    reason="needs_user_input" if row.status == "waiting_user" else None,
                )
                acknowledged = scoped_run_repo.mark_terminal_event_delivered(
                    row.run_id,
                    event_version=event_version,
                )
                if not acknowledged:
                    logger.error(
                        "Scheduled terminal event acknowledgement lost for run %s "
                        "generation %s; current generation remains pending",
                        row.run_id,
                        event_version,
                    )
                    return False
                return True
        except Exception:
            logger.error(
                "Scheduled terminal event delivery failed for run %s; will retry",
                rid,
                exc_info=True,
            )
            return False


def retry_pending_terminal_events(
    *,
    limit: int = 100,
    run_repo: ScheduledTaskRunRepository | None = None,
    task_repo: ScheduledTaskRepository | None = None,
) -> int:
    """Retry a bounded batch and return the number acknowledged this pass."""

    bounded_limit = max(1, min(int(limit), 500))
    with _DELIVERY_LOCK:
        with _run_repo_scope(run_repo) as scoped_run_repo:
            pending_ids = [
                row.run_id
                for row in scoped_run_repo.list_pending_terminal_events(limit=bounded_limit)
            ]
        delivered = 0
        for run_id in pending_ids:
            if deliver_terminal_event(
                run_id,
                run_repo=run_repo,
                task_repo=task_repo,
            ):
                delivered += 1
        return delivered


def _lookup_task_title(
    scheduled_task_id: str,
    *,
    task_repo: ScheduledTaskRepository | None,
) -> str | None:
    try:
        with _task_repo_scope(task_repo) as scoped_task_repo:
            row = scoped_task_repo.get(scheduled_task_id)
        return row.title if row is not None else None
    except Exception:
        logger.warning(
            "Scheduled terminal event task title lookup failed for %s",
            scheduled_task_id,
            exc_info=True,
        )
        return None


def _run_repo_scope(run_repo: ScheduledTaskRunRepository | None):
    if run_repo is not None:
        return nullcontext(run_repo)
    return ScheduledTaskRunRepository()


def _task_repo_scope(task_repo: ScheduledTaskRepository | None):
    if task_repo is not None:
        return nullcontext(task_repo)
    return ScheduledTaskRepository()
