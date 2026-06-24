"""Typed backend event registry built on blinker."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, fields, make_dataclass
from typing import Any, Callable, Literal, Optional, TypeAlias, get_args

from blinker import Namespace

logger = logging.getLogger(__name__)

# 创建命名空间
_signals = Namespace()

EventName: TypeAlias = Literal[
    "recording_started",
    "recording_stopped",
    "recording_completed",
    "desktop_action_count_changed",
    "desktop_recorder_start_failed",
    "desktop_recording_degraded",
    "desktop_stop_requested",
    "desktop_syntax_gate_retry_failed",
    "desktop_trial_preview_ready",
    "desktop_trial_finished",
    "agent_needs_user_input",
    "agent_error",
    "requirement_confirmed",
    "code_completed",
    "review_passed",
    "review_failed",
    "tool_saved",
    "trial_success",
    "trial_failed",
    "triage_completed",
    "tool_published",
    "teaching_failure_updated",
    "teaching_failure_resolved",
    "teaching_failure_retrying",
    "settings_changed",
    "tools_changed",
    "composition_review_needed",
    "trial_requested",
    "brain_zone_changed",
    "brain_specialist_changed",
    "segment_boundary_triggered",
    "segment_idle_trigger",
    "brain_specialist_recruited",
    "brain_context_ready",
    "brain_skill_changed",
    "brain_skill_equipment_changed",
    "brain_skill_supersede_completed",
    "brain_skill_bootstrap_fallback_used",
    "assistant_agent_step",
    "assistant_subagent_started",
    "assistant_subagent_finished",
    "assistant_subagent_paused",
    "assistant_task_graph_changed",
    "assistant_task_board_changed",
    "assistant_task_question_changed",
    "assistant_meeting_changed",
    "assistant_todo_changed",
    "assistant_task_adjudication_changed",
    "assistant_task_root_failed",
]

_EVENT_NAMES: tuple[EventName, ...] = get_args(EventName)


class EventValidationError(ValueError):
    """Raised when a backend event name or payload does not match the registry."""


@dataclass
class RecordingEventData:
    """录制事件数据"""

    session_id: str
    recording_mode: str
    start_time: float
    end_time: Optional[float] = None
    action_count: int = 0
    error: Optional[str] = None


_EVENT_FIELDS: dict[EventName, tuple[str, ...]] = {
    "recording_started": ("event_data", "workflow_id", "recording_mode"),
    "recording_stopped": (
        "event_data",
        "workflow_id",
        "recording_id",
        "recording_mode",
        "action_count",
    ),
    "recording_completed": ("event_data",),
    "desktop_action_count_changed": ("recording_id", "action_count"),
    "desktop_recorder_start_failed": ("recording_id", "reason"),
    "desktop_recording_degraded": ("recording_id", "workflow_id", "reason", "subsystem", "message"),
    "desktop_stop_requested": (),
    "desktop_syntax_gate_retry_failed": (
        "workflow_id",
        "session_id",
        "feedback",
        "lineno",
        "message",
    ),
    "desktop_trial_preview_ready": (
        "workflow_id",
        "trial_id",
        "code",
        "code_preview",
        "timeout_seconds",
    ),
    "desktop_trial_finished": ("workflow_id", "trial_id", "result"),
    "agent_needs_user_input": ("workflow_id", "session_id", "agent_type", "question"),
    "agent_error": ("workflow_id", "session_id", "agent_type", "error", "error_type"),
    "requirement_confirmed": ("workflow_id", "session_id", "requirements_json"),
    "code_completed": ("workflow_id", "session_id", "code"),
    "review_passed": ("workflow_id", "session_id", "code"),
    "review_failed": (
        "workflow_id",
        "session_id",
        "code",
        "feedback",
        "retry_count",
        "forced_save",
    ),
    "tool_saved": ("workflow_id", "session_id", "tool_id", "from_triage"),
    "trial_success": ("workflow_id", "session_id", "tool_id", "published", "success_count"),
    "trial_failed": ("workflow_id", "session_id", "tool_id", "user_feedback", "error"),
    "triage_completed": (
        "workflow_id",
        "session_id",
        "decision",
        "triage_result",
        "feedback",
    ),
    "tool_published": ("workflow_id", "session_id", "tool_id"),
    "teaching_failure_updated": (
        "workflow_id",
        "failed_stage",
        "error_type",
        "is_new",
        "status",
    ),
    "teaching_failure_resolved": ("workflow_id",),
    "teaching_failure_retrying": ("workflow_id", "failed_stage"),
    "settings_changed": ("key", "keys"),
    "tools_changed": ("tool_id", "action"),
    "composition_review_needed": ("tool_id", "composition_id"),
    "trial_requested": ("tool_id", "workflow_id"),
    "brain_zone_changed": ("zone", "entry_id", "operation", "change_type"),
    "brain_specialist_changed": ("specialist_id", "operation"),
    "segment_boundary_triggered": ("session_id", "segment_id", "reason"),
    "segment_idle_trigger": ("session_id",),
    "brain_specialist_recruited": ("specialist_id", "name", "reason"),
    "brain_context_ready": ("session_id",),
    "brain_skill_changed": (
        "skill_id",
        "operation",
        "chain_root_id",
        "new_skill_id",
        "caller_type",
        "caller_id",
    ),
    "brain_skill_equipment_changed": (
        "change_type",
        "entity_type",
        "entity_id",
        "skill_id",
        "unequipped_reason",
    ),
    "brain_skill_supersede_completed": (
        "old_skill_id",
        "new_skill_id",
        "version",
        "equipment_count_migrated",
    ),
    "brain_skill_bootstrap_fallback_used": ("skill_id", "reason", "seed_file_path"),
    "assistant_agent_step": (
        "session_id",
        "subagent_id",
        "agent_type",
        "kind",
        "tool_name",
        "text",
        "seq",
    ),
    "assistant_subagent_started": ("session_id", "subagent_id", "label", "task", "status"),
    "assistant_subagent_finished": ("session_id", "subagent_id", "status", "last_output"),
    "assistant_subagent_paused": ("session_id", "subagent_id", "status", "reason"),
    "assistant_task_graph_changed": (
        "session_id",
        "graph_id",
        "task_id",
        "status",
        "change_type",
        "display_phase",
        "requires_review",
        "safe_explanation",
        "suspend_reason",
    ),
    "assistant_task_board_changed": (
        "change_type",
        "claim_status",
        "session_id",
        "graph_id",
        "task_id",
        "updated_at",
    ),
    "assistant_task_question_changed": (
        "session_id",
        "graph_id",
        "task_id",
        "question_id",
        "kind",
        "status",
        "change_type",
    ),
    "assistant_meeting_changed": (
        "session_id",
        "graph_id",
        "task_id",
        "channel_id",
        "change_type",
        "status",
        "sequence",
    ),
    "assistant_todo_changed": (
        "session_id",
        "task_id",
        "todo_id",
        "change_type",
        "status",
        "sort_order",
    ),
    "assistant_task_adjudication_changed": (
        "session_id",
        "graph_id",
        "task_id",
        "change_type",
        "status",
        "display_phase",
        "requires_review",
        "safe_explanation",
    ),
    "assistant_task_root_failed": (
        "session_id",
        "graph_id",
        "task_id",
        "change_type",
        "status",
        "display_phase",
        "safe_explanation",
    ),
}


def _event_class_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_")) + "Event"


_EVENT_PAYLOAD_TYPES = {
    name: make_dataclass(
        _event_class_name(name),
        [(field_name, Any, field(default=None)) for field_name in field_names],
        frozen=True,
    )
    for name, field_names in _EVENT_FIELDS.items()
}


class TypedEventRegistry:
    """Registry for known backend events and their payload dataclasses."""

    def __init__(
        self, namespace: Namespace, event_fields: dict[EventName, tuple[str, ...]]
    ) -> None:
        self._namespace = namespace
        self._event_fields = event_fields
        self._signals = {name: namespace.signal(name) for name in event_fields}
        self._payload_types = _EVENT_PAYLOAD_TYPES

    @property
    def names(self) -> tuple[EventName, ...]:
        return tuple(self._event_fields)

    def signal(self, name: EventName):
        self._validate_name(name)
        return self._signals[name]

    def payload_type(self, name: EventName):
        self._validate_name(name)
        return self._payload_types[name]

    def validate_payload(self, name: EventName, payload: dict[str, Any]) -> Any:
        self._validate_name(name)
        allowed = set(self._event_fields[name])
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise EventValidationError(f"unknown payload field(s) for {name}: {', '.join(unknown)}")
        payload_type = self._payload_types[name]
        event_payload = payload_type(**payload)
        valid_fields = {item.name for item in fields(event_payload)}
        if valid_fields != allowed:
            raise EventValidationError(f"event registry mismatch for {name}")
        return event_payload

    def _validate_name(self, name: str) -> None:
        if name not in self._event_fields:
            raise EventValidationError(f"unknown backend event: {name}")


_registry = TypedEventRegistry(_signals, _EVENT_FIELDS)

# 录制相关事件
recording_started = _registry.signal("recording_started")
recording_stopped = _registry.signal("recording_stopped")
recording_completed = _registry.signal("recording_completed")
desktop_action_count_changed = _registry.signal("desktop_action_count_changed")
desktop_recorder_start_failed = _registry.signal("desktop_recorder_start_failed")
desktop_recording_degraded = _registry.signal("desktop_recording_degraded")
desktop_stop_requested = _registry.signal("desktop_stop_requested")
desktop_syntax_gate_retry_failed = _registry.signal("desktop_syntax_gate_retry_failed")
desktop_trial_preview_ready = _registry.signal("desktop_trial_preview_ready")
desktop_trial_finished = _registry.signal("desktop_trial_finished")

# Agent 交互与协作事件
agent_needs_user_input = _registry.signal("agent_needs_user_input")
agent_error = _registry.signal("agent_error")
requirement_confirmed = _registry.signal("requirement_confirmed")
code_completed = _registry.signal("code_completed")
review_passed = _registry.signal("review_passed")
review_failed = _registry.signal("review_failed")
tool_saved = _registry.signal("tool_saved")
trial_success = _registry.signal("trial_success")
trial_failed = _registry.signal("trial_failed")
triage_completed = _registry.signal("triage_completed")
tool_published = _registry.signal("tool_published")

# 教学、设置与工具事件
teaching_failure_updated = _registry.signal("teaching_failure_updated")
teaching_failure_resolved = _registry.signal("teaching_failure_resolved")
teaching_failure_retrying = _registry.signal("teaching_failure_retrying")
settings_changed = _registry.signal("settings_changed")
tools_changed = _registry.signal("tools_changed")
composition_review_needed = _registry.signal("composition_review_needed")
trial_requested = _registry.signal("trial_requested")

# 大脑架构事件
brain_zone_changed = _registry.signal("brain_zone_changed")
brain_specialist_changed = _registry.signal("brain_specialist_changed")
segment_boundary_triggered = _registry.signal("segment_boundary_triggered")
segment_idle_trigger = _registry.signal("segment_idle_trigger")
brain_specialist_recruited = _registry.signal("brain_specialist_recruited")
brain_context_ready = _registry.signal("brain_context_ready")
brain_skill_changed = _registry.signal("brain_skill_changed")
brain_skill_equipment_changed = _registry.signal("brain_skill_equipment_changed")
brain_skill_supersede_completed = _registry.signal("brain_skill_supersede_completed")
brain_skill_bootstrap_fallback_used = _registry.signal("brain_skill_bootstrap_fallback_used")

# Assistant UI projection source events
assistant_agent_step = _registry.signal("assistant_agent_step")
assistant_subagent_started = _registry.signal("assistant_subagent_started")
assistant_subagent_finished = _registry.signal("assistant_subagent_finished")
assistant_subagent_paused = _registry.signal("assistant_subagent_paused")
assistant_task_graph_changed = _registry.signal("assistant_task_graph_changed")
assistant_task_board_changed = _registry.signal("assistant_task_board_changed")
assistant_task_question_changed = _registry.signal("assistant_task_question_changed")
assistant_meeting_changed = _registry.signal("assistant_meeting_changed")
assistant_todo_changed = _registry.signal("assistant_todo_changed")
assistant_task_adjudication_changed = _registry.signal("assistant_task_adjudication_changed")
assistant_task_root_failed = _registry.signal("assistant_task_root_failed")


# =============================================================================
# 便捷函数
# =============================================================================


def event_value(event_data, *keys):
    """从 blinker 事件数据中提取值，兼容 dict 和 dataclass/对象两种格式。

    Args:
        event_data: 事件数据（dict 或对象）
        *keys: 按优先级尝试的键名列表

    Returns:
        第一个非 None 的值，或 None
    """
    if event_data is None:
        return None
    if isinstance(event_data, dict):
        for key in keys:
            if key in event_data:
                return event_data.get(key)
        return None
    for key in keys:
        value = getattr(event_data, key, None)
        if value is not None:
            return value
    return None


def connect(signal_name: EventName, callback: Callable, *, weak: bool = True) -> Callable:
    """
    连接信号和回调函数

    Args:
        signal_name: 信号名称
        callback: 回调函数
        weak: 是否使用 blinker 默认的弱引用绑定

    Returns:
        取消连接的函数
    """
    signal = _registry.signal(signal_name)
    return signal.connect(callback, weak=weak)


def disconnect(signal_name: EventName, callback: Callable) -> None:
    """
    断开信号和回调函数的连接

    Args:
        signal_name: 信号名称
        callback: 之前注册的回调函数
    """
    signal = _registry.signal(signal_name)
    signal.disconnect(callback)


def emit(signal_name: EventName, sender: Any = None, **kwargs) -> None:
    """
    发送信号

    Args:
        signal_name: 信号名称
        sender: 发送者对象
        **kwargs: 事件数据
    """
    _registry.validate_payload(signal_name, kwargs)
    signal = _registry.signal(signal_name)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"发送事件 '{signal_name}'")
    signal.send(sender, event_name=signal_name, **kwargs)


def emit_collect(signal_name: EventName, sender: Any = None, **kwargs) -> list[tuple[Any, Any]]:
    """
    发送信号并收集监听器返回值。

    用于少数需要同步审批结果的业务路径；普通通知仍使用 emit()。
    """
    _registry.validate_payload(signal_name, kwargs)
    signal = _registry.signal(signal_name)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"发送事件 '{signal_name}' 并收集返回值")
    try:
        return signal.send(sender, event_name=signal_name, **kwargs)
    except Exception as exc:
        logger.error(f"[Events] 监听器处理 {signal_name} 时异常: {exc}", exc_info=True)
        return []


# =============================================================================
# 测试辅助
# =============================================================================

_signal_names = list(_EVENT_NAMES)


def clear_all() -> None:
    """
    清除所有信号的监听器（主要用于测试）
    """
    for name in _signal_names:
        signal = _registry.signal(name)
        signal._clear_state()


# =============================================================================
# 导出
# =============================================================================

__all__ = [
    # 信号
    "recording_started",
    "recording_stopped",
    "recording_completed",
    "desktop_action_count_changed",
    "desktop_recorder_start_failed",
    "desktop_recording_degraded",
    "desktop_stop_requested",
    "desktop_syntax_gate_retry_failed",
    "desktop_trial_preview_ready",
    "desktop_trial_finished",
    "agent_needs_user_input",
    "agent_error",
    "requirement_confirmed",
    "code_completed",
    "review_passed",
    "review_failed",
    "tool_saved",
    "trial_success",
    "trial_failed",
    "triage_completed",
    "tool_published",
    "teaching_failure_updated",
    "teaching_failure_resolved",
    "teaching_failure_retrying",
    "settings_changed",
    "tools_changed",
    "composition_review_needed",
    "trial_requested",
    "brain_zone_changed",
    "brain_specialist_changed",
    "segment_boundary_triggered",
    "segment_idle_trigger",
    "brain_specialist_recruited",
    "brain_context_ready",
    "brain_skill_changed",
    "brain_skill_equipment_changed",
    "brain_skill_supersede_completed",
    "brain_skill_bootstrap_fallback_used",
    "assistant_agent_step",
    "assistant_subagent_started",
    "assistant_subagent_finished",
    "assistant_subagent_paused",
    "assistant_task_graph_changed",
    "assistant_task_board_changed",
    "assistant_task_question_changed",
    "assistant_meeting_changed",
    "assistant_todo_changed",
    "assistant_task_adjudication_changed",
    "assistant_task_root_failed",
    # 数据类
    "EventName",
    "EventValidationError",
    "TypedEventRegistry",
    "RecordingEventData",
    # 函数
    "event_value",
    "connect",
    "disconnect",
    "emit",
    "emit_collect",
    # 测试辅助
    "clear_all",
]
