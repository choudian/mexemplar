"""Business models and validators for Assistant task collaboration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from src.business.services.ui_event_safety_service import redact_public_ui_event_text


class TaskStatus(StrEnum):
    PENDING_DISPATCH = "pending_dispatch"
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SuspendReason(StrEnum):
    WAITING_USER = "waiting_user"
    WAITING_SYSTEM = "waiting_system"
    USER_STOP = "user_stop"
    # 执行体跑到轮次预算但工作完整保留：与"等外部条件"不同，父侧可追加预算续跑。
    # 落进 WAITING_SYSTEM 会让父侧误以为在等外部，从而无限期干等。
    BUDGET_EXHAUSTED = "budget_exhausted"
    # 执行体异常中断，工作保留但最后一步副作用可能未知；续跑前需要先核对现场。
    INTERRUPTED = "interrupted"


class WaitingOn(StrEnum):
    """暂停时球在谁手上——谁能让这个活继续。

    这是**持久化的通知意图**，不只是描述：状态落库就等于通知已发出，派发通知时
    直接读这个字段，不做第二次判断。

    在此之前，落库写的是 ``suspend_reason``，而决定"要不要通知父侧"的代码查的
    是另一套 ``reentry_type`` 白名单——两套独立判断对不上，撞轮次预算暂停的任务
    状态全部正确落库，却永远没有人被告知，主助理和用户两边互等。
    """

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# suspend_reason → waiting_on 的单一事实来源：业务写入、迁移回填、测试共用这一份。
_SUSPEND_REASON_WAITING_ON: dict[SuspendReason, WaitingOn] = {
    SuspendReason.WAITING_USER: WaitingOn.USER,
    SuspendReason.USER_STOP: WaitingOn.USER,
    SuspendReason.BUDGET_EXHAUSTED: WaitingOn.ASSISTANT,
    # WAITING_SYSTEM 的实际生产者是 ask_parent（执行体求助，等主助理答复）和
    # _map_to_outcome 的兜底（未知情形）。映射成 SYSTEM 会让它进 recovery 自动
    # 重试，那是错的；映射成 ASSISTANT 最坏只是多叫醒主助理一次。
    SuspendReason.WAITING_SYSTEM: WaitingOn.ASSISTANT,
    # INTERRUPTED 目前零生产者。启动对账落地后它才会被真正写入，届时改成 USER
    # ——重启是一次新的开工，得有人拍板，不能自动烧 token。
    SuspendReason.INTERRUPTED: WaitingOn.SYSTEM,
}


class TaskEdgeType(StrEnum):
    DEPENDENCY = "dependency"
    DELEGATION = "delegation"
    QUESTION = "question"
    MEETING_CHANNEL = "meeting_channel"
    RESOURCE_REQUEST = "resource_request"


class TaskQuestionKind(StrEnum):
    CLARIFICATION = "clarification"
    RESOURCE_REQUEST = "resource_request"
    CAPABILITY_REQUEST = "capability_request"


class TaskQuestionStatus(StrEnum):
    OPEN = "open"
    ESCALATED_TO_PARENT = "escalated_to_parent"
    ESCALATED_TO_USER = "escalated_to_user"
    ANSWERED = "answered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AttemptStatus(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"
    FENCED = "fenced"


class OperationStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    UNSAFE_TO_RETRY = "unsafe_to_retry"


class AdjudicationDecision(StrEnum):
    ACCEPTED = "accepted"
    RETURNED = "returned"
    ABANDONED = "abandoned"


class AdjudicationStatus(StrEnum):
    PENDING = "pending"
    DECIDED = "decided"


class DeliveredStatus(StrEnum):
    DONE = "done"
    STUCK = "stuck"
    FAILED_INPUT = "failed_input"


# Re-export RoleKind from the data layer (canonical definition lives there to
# avoid circular imports). Business code imports from this module for consistency.
from src.data.repos.specialist_repository import RoleKind  # noqa: E402,F401


class ClaimStatus(StrEnum):
    CLAIMED = "claimed"
    RELEASED = "released"
    REJECTED = "rejected"
    COMPLETED = "completed"
    EXPIRED = "expired"


class MeetingChannelStatus(StrEnum):
    OPEN = "open"
    CONCLUDED = "concluded"
    CLOSED_TIMEOUT = "closed_timeout"
    CLOSED_ABANDONED = "closed_abandoned"


class TodoStatus(StrEnum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"
    SKIPPED = "skipped"


# ⚠️ 这里**刻意不含 SUSPENDED**，不是漏网之鱼。它的语义是"这个活结束了"——活停着当然
# 不算结束，图里有节点暂停时 all_terminal 为假、不发全图完成通知，是正确行为。排查
# "暂停后没人被通知"时这一处曾被列为疑似缺陷；真正的缺口在通知那一环（task.waiting_on），
# 通知修好之后活会继续走，图最终自然收口。
TERMINAL_TASK_STATUSES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)


@dataclass(frozen=True)
class TaskAssignee:
    type: Literal["ephemeral_subagent", "specialist"]
    id: str
    label: str | None = None


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    graph_id: str
    parent_task_id: str | None
    title: str
    description_preview: str
    status: TaskStatus
    display_phase: Literal["running", "reviewing", "needs_attention", "paused", "done"]
    requires_review: bool
    requires_confirmation: bool = False
    safe_explanation: str = ""
    suspend_reason: SuspendReason | None = None
    waiting_on: WaitingOn | None = None
    assignee: TaskAssignee | None = None
    adjudication_id: str | None = None
    updated_at: datetime | None = None
    external_coding_sessions: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class TaskEdgeSnapshot:
    source_task_id: str
    target_task_id: str
    type: TaskEdgeType


@dataclass(frozen=True)
class TaskAdjudicationSnapshot:
    adjudication_id: str
    task_id: str
    safe_summary: str
    delivered_status: DeliveredStatus
    raw_result_ref: str | None = None


@dataclass(frozen=True)
class TaskGraphSnapshot:
    graph_id: str
    session_id: str
    user_message_sequence: int | None
    version: int
    tasks: list[TaskSnapshot] = field(default_factory=list)
    edges: list[TaskEdgeSnapshot] = field(default_factory=list)
    adjudications: list[TaskAdjudicationSnapshot] = field(default_factory=list)


def coerce_task_status(value: str | TaskStatus) -> TaskStatus:
    return value if isinstance(value, TaskStatus) else TaskStatus(str(value))


def coerce_suspend_reason(value: str | SuspendReason | None) -> SuspendReason | None:
    if value is None:
        return None
    return value if isinstance(value, SuspendReason) else SuspendReason(str(value))


def coerce_waiting_on(value: str | WaitingOn | None) -> WaitingOn | None:
    if value is None:
        return None
    return value if isinstance(value, WaitingOn) else WaitingOn(str(value))


def waiting_on_for_reason(reason: str | SuspendReason | None) -> WaitingOn | None:
    """按暂停原因推出球在谁手上。

    ``SuspendReason`` 之外的值仍按既有约定抛 ``ValueError``（非法输入要当场炸）。
    那句 ``.get`` 兜底防的是另一件事：**将来往枚举里加了新原因、却忘了在映射表
    里登记**——这时归给主助理，宁可多叫醒它一次，也不要让活停在那儿没人知道。
    """
    coerced = coerce_suspend_reason(reason)
    if coerced is None:
        return None
    return _SUSPEND_REASON_WAITING_ON.get(coerced, WaitingOn.ASSISTANT)


def validate_task_transition(
    current: str | TaskStatus,
    target: str | TaskStatus,
    *,
    suspend_reason: str | SuspendReason | None = None,
) -> None:
    current_status = coerce_task_status(current)
    target_status = coerce_task_status(target)
    reason = coerce_suspend_reason(suspend_reason)
    if current_status in TERMINAL_TASK_STATUSES and target_status != current_status:
        raise ValueError(
            f"terminal task status cannot transition: {current_status}->{target_status}"
        )
    if target_status == TaskStatus.SUSPENDED and reason is None:
        raise ValueError("suspended task requires suspend_reason")
    if target_status != TaskStatus.SUSPENDED and reason is not None:
        raise ValueError("suspend_reason is only valid for suspended tasks")


def derive_display_phase(
    status: str | TaskStatus,
    *,
    has_pending_adjudication: bool = False,
) -> Literal["running", "reviewing", "needs_attention", "paused", "done"]:
    task_status = coerce_task_status(status)
    if has_pending_adjudication:
        return "reviewing"
    if task_status == TaskStatus.SUSPENDED:
        return "paused"
    if task_status in TERMINAL_TASK_STATUSES:
        return "done" if task_status == TaskStatus.COMPLETED else "needs_attention"
    return "running"


def safe_preview(value: str | None, *, max_chars: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def safe_public_preview(value: str | None, *, key: str = "text", max_chars: int = 160) -> str:
    """脱敏后再做预览截断，用于进入权威 REST 快照 / transcript 的用户或 agent 文本。

    任务标题、描述、会议消息和裁定摘要可能含密钥 / traceback / 本地 DB 路径，单纯
    截断（``safe_preview``）会把它们原样带进 DTO。这里先按 009 payload safety 口径
    （``redact_public_ui_event_text``）判定：命中敏感规则的整段替换为占位符，否则按
    ``max_chars`` 截断。与实时 UI event 的脱敏口径一致，确保 REST 快照不泄漏 secret。
    """
    redacted = redact_public_ui_event_text(key, value, max_preview_chars=max_chars)
    return safe_preview(redacted, max_chars=max_chars)
