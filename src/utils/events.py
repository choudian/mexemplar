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


def connect(signal_name: str, callback: Callable) -> Callable:
    """
    连接信号和回调函数

    Args:
        signal_name: 信号名称
        callback: 回调函数

    Returns:
        取消连接的函数
    """
    signal = _signals.signal(signal_name)
    return signal.connect(callback)


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
        logger.error(f"[Events] 监听器处理 {signal_name} 时异常: {exc}")


# =============================================================================
# 测试辅助
# =============================================================================

_signal_names = [
    "recording_started",
    "recording_stopped",
    "recording_completed",
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
    # 数据类
    "RecordingEventData",
    # 函数
    "connect",
    "emit",
    # 测试辅助
    "clear_all",
]
