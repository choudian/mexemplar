"""
事件系统 - 基于 blinker 的事件总线

提供解耦的事件驱动架构，用于模块间通信。
"""

from blinker import Namespace
from typing import Any, Callable, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

# 创建命名空间
_signals = Namespace()

# =============================================================================
# 事件定义
# =============================================================================

# 录制相关事件
recording_started = _signals.signal("recording_started")
"""录制开始事件"""

recording_stopped = _signals.signal("recording_stopped")
"""录制停止事件"""

recording_completed = _signals.signal("recording_completed")
"""录制完成事件 - 当录制数据准备就绪时触发"""

desktop_action_count_changed = _signals.signal("desktop_action_count_changed")
"""桌面录制动作计数变化事件"""

desktop_recorder_start_failed = _signals.signal("desktop_recorder_start_failed")
"""桌面录制启动失败事件"""

desktop_recording_degraded = _signals.signal("desktop_recording_degraded")
"""桌面录制降级事件"""

desktop_stop_requested = _signals.signal("desktop_stop_requested")
"""桌面录制停止请求事件（由热键等非 API 入口触发，需由 desktop API adapter 接入正式停止流程）"""

desktop_syntax_gate_retry_failed = _signals.signal("desktop_syntax_gate_retry_failed")
"""桌面 Programmer 语法门卫重试失败事件"""

desktop_trial_preview_ready = _signals.signal("desktop_trial_preview_ready")
"""桌面 Trial 事前提示准备事件"""

desktop_trial_finished = _signals.signal("desktop_trial_finished")
"""桌面 Trial 完成事件"""

# Agent 交互事件
agent_needs_user_input = _signals.signal("agent_needs_user_input")
"""Agent 需要用户输入事件"""

agent_error = _signals.signal("agent_error")
"""Agent 执行错误事件"""

# Agent 协作事件
requirement_confirmed = _signals.signal("requirement_confirmed")
"""PM 需求确认完成事件"""

code_completed = _signals.signal("code_completed")
"""程序员代码完成事件"""

review_passed = _signals.signal("review_passed")
"""LLM Review 通过事件"""

review_failed = _signals.signal("review_failed")
"""LLM Review 失败事件"""

tool_saved = _signals.signal("tool_saved")
"""工具入库事件"""

trial_success = _signals.signal("trial_success")
"""工具试用成功事件"""

trial_failed = _signals.signal("trial_failed")
"""工具试用失败事件"""

triage_completed = _signals.signal("triage_completed")
"""PM 分诊完成（代码问题）事件"""

tool_published = _signals.signal("tool_published")
"""工具发布事件（试用成功3次后自动发布）"""

# 教学失败追踪事件
teaching_failure_updated = _signals.signal("teaching_failure_updated")
"""失败记录新增/更新/dismiss"""

teaching_failure_resolved = _signals.signal("teaching_failure_resolved")
"""失败记录已解决"""

teaching_failure_retrying = _signals.signal("teaching_failure_retrying")
"""开始重试"""

settings_changed = _signals.signal("settings_changed")
"""设置变更事件"""

tools_changed = _signals.signal("tools_changed")
"""工具增删变更事件"""

composition_review_needed = _signals.signal("composition_review_needed")
"""技能组合需要审核事件"""

trial_requested = _signals.signal("trial_requested")
"""工具试用请求事件"""

# 大脑架构事件
brain_zone_changed = _signals.signal("brain_zone_changed")
"""大脑分区条目状态变化事件"""

brain_specialist_changed = _signals.signal("brain_specialist_changed")
"""专员列表变化事件"""

segment_boundary_triggered = _signals.signal("segment_boundary_triggered")
"""Segment 边界事件：open segment 被封存"""

segment_idle_trigger = _signals.signal("segment_idle_trigger")
"""前端空闲计时器触发"""

brain_specialist_recruited = _signals.signal("brain_specialist_recruited")
"""自动招募完成：新专员已创建"""

brain_context_ready = _signals.signal("brain_context_ready")
"""助理大脑上下文构建完成"""

brain_skill_changed = _signals.signal("brain_skill_changed")
"""方法论资产状态变化事件"""

brain_skill_equipment_changed = _signals.signal("brain_skill_equipment_changed")
"""方法论装备关系变化事件"""

brain_skill_supersede_completed = _signals.signal("brain_skill_supersede_completed")
"""方法论 supersede 事务完成事件"""

brain_skill_bootstrap_fallback_used = _signals.signal("brain_skill_bootstrap_fallback_used")
"""内置方法论 seed 读取失败并启用 fallback"""

# 助理对话透明化事件（014-assistant-chat-transparency）
# 仅由可观测的助理 / 子代理 / 专员运行链路 emit（AgentLoop 仅在 run_context 存在时发出），
# 经 ui_event_projector 投影为 assistant.activity / assistant.subagent typed UI 事件。
assistant_agent_step = _signals.signal("assistant_agent_step")
"""助理/子代理逐步活动事件：reasoning / tool_call / tool_result（best-effort，仅可观测运行时）"""

assistant_subagent_started = _signals.signal("assistant_subagent_started")
"""子任务委派开始事件（卡片壳 + running 状态，session_id=父助理会话）"""

assistant_subagent_finished = _signals.signal("assistant_subagent_finished")
"""子任务委派结束事件（status∈{done,failed}，session_id=父助理会话）"""

assistant_subagent_paused = _signals.signal("assistant_subagent_paused")
"""子任务委派暂停事件（用户停止/取消，status=suspended，session_id=父助理会话）"""

# =============================================================================
# 事件数据类
# =============================================================================


@dataclass
class RecordingEventData:
    """录制事件数据"""

    session_id: str
    recording_mode: str
    start_time: float
    end_time: Optional[float] = None
    action_count: int = 0
    error: Optional[str] = None


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


def connect(signal_name: str, callback: Callable, *, weak: bool = True) -> Callable:
    """
    连接信号和回调函数

    Args:
        signal_name: 信号名称
        callback: 回调函数
        weak: 是否使用 blinker 默认的弱引用绑定

    Returns:
        取消连接的函数
    """
    signal = _signals.signal(signal_name)
    return signal.connect(callback, weak=weak)


def disconnect(signal_name: str, callback: Callable) -> None:
    """
    断开信号和回调函数的连接

    Args:
        signal_name: 信号名称
        callback: 之前注册的回调函数
    """
    signal = _signals.signal(signal_name)
    signal.disconnect(callback)


def emit(signal_name: str, sender: Any = None, **kwargs) -> None:
    """
    发送信号

    Args:
        signal_name: 信号名称
        sender: 发送者对象
        **kwargs: 事件数据
    """
    signal = _signals.signal(signal_name)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"发送事件 '{signal_name}'")
    try:
        signal.send(sender, event_name=signal_name, **kwargs)
    except Exception as exc:
        logger.error(f"[Events] 监听器处理 {signal_name} 时异常: {exc}", exc_info=True)


def emit_collect(signal_name: str, sender: Any = None, **kwargs) -> list[tuple[Any, Any]]:
    """
    发送信号并收集监听器返回值。

    用于少数需要同步审批结果的业务路径；普通通知仍使用 emit()。
    """
    signal = _signals.signal(signal_name)
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

_signal_names = [
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
]


def clear_all() -> None:
    """
    清除所有信号的监听器（主要用于测试）
    """
    for name in _signal_names:
        signal = _signals.signal(name)
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
    # 数据类
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
