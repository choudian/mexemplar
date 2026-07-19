"""Persisted scheduling enums and lifecycle transition contracts.

This module is deliberately owned by the data boundary: both Repository guards and
the business scheduling facade import the same values, so a caller cannot bypass a
business-only transition table by invoking a Repository directly.
"""

from __future__ import annotations

from enum import StrEnum


class SessionSource(StrEnum):
    USER = "user"
    SCHEDULED = "scheduled"


class ScheduledTaskSourceType(StrEnum):
    DIRECT = "direct"
    TODO = "todo"


class ScheduleKind(StrEnum):
    ONE_SHOT = "one_shot"
    RECURRING = "recurring"


class ScheduledTaskStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    EXPIRED = "expired"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WAITING_USER = "waiting_user"
    SKIPPED = "skipped"


TASK_STATUS_TRANSITIONS: frozenset[tuple[ScheduledTaskStatus, ScheduledTaskStatus]] = frozenset(
    {
        (ScheduledTaskStatus.ACTIVE, ScheduledTaskStatus.PAUSED),
        (ScheduledTaskStatus.PAUSED, ScheduledTaskStatus.ACTIVE),
        (ScheduledTaskStatus.ACTIVE, ScheduledTaskStatus.COMPLETED),
        (ScheduledTaskStatus.ACTIVE, ScheduledTaskStatus.EXPIRED),
        (ScheduledTaskStatus.PAUSED, ScheduledTaskStatus.EXPIRED),
    }
)

TASK_ACTIVE_STATUSES: frozenset[ScheduledTaskStatus] = frozenset(
    {ScheduledTaskStatus.ACTIVE, ScheduledTaskStatus.PAUSED}
)

RUN_STATUS_TRANSITIONS: frozenset[tuple[RunStatus, RunStatus]] = frozenset(
    {
        (RunStatus.RUNNING, RunStatus.SUCCEEDED),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.WAITING_USER),
        (RunStatus.WAITING_USER, RunStatus.RUNNING),
        (RunStatus.WAITING_USER, RunStatus.FAILED),
    }
)

RUN_ACTIVE_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.RUNNING, RunStatus.WAITING_USER})

RUN_TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.SKIPPED}
)

RUN_EVENT_DELIVERABLE_STATUSES: frozenset[RunStatus] = frozenset(
    (RUN_TERMINAL_STATUSES - {RunStatus.SKIPPED}) | {RunStatus.WAITING_USER}
)

RUN_TAKEOVER_STATUSES: frozenset[RunStatus] = frozenset({RunStatus.WAITING_USER, RunStatus.FAILED})

# ORM / persisted DTO boundaries use strings.  Derive them once from the enum sets
# so SQL filters and business projections cannot drift from the lifecycle contract.
RUN_ACTIVE_STATUS_VALUES: frozenset[str] = frozenset(status.value for status in RUN_ACTIVE_STATUSES)
RUN_TERMINAL_STATUS_VALUES: frozenset[str] = frozenset(
    status.value for status in RUN_TERMINAL_STATUSES
)
RUN_EVENT_DELIVERABLE_STATUS_VALUES: frozenset[str] = frozenset(
    status.value for status in RUN_EVENT_DELIVERABLE_STATUSES
)
RUN_TAKEOVER_STATUS_VALUES: frozenset[str] = frozenset(
    status.value for status in RUN_TAKEOVER_STATUSES
)


def task_status_sources_for(
    to_status: ScheduledTaskStatus,
) -> frozenset[ScheduledTaskStatus]:
    return frozenset(src for src, target in TASK_STATUS_TRANSITIONS if target == to_status)


def run_status_sources_for(to_status: RunStatus) -> frozenset[RunStatus]:
    return frozenset(src for src, target in RUN_STATUS_TRANSITIONS if target == to_status)
