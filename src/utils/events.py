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

recording_failed = _signals.signal("recording_failed")
"""录制失败事件"""

# 工作流相关事件
workflow_processing_started = _signals.signal("workflow_processing_started")
"""工作流处理开始事件"""

workflow_processing_progress = _signals.signal("workflow_processing_progress")
"""工作流处理进度事件"""

workflow_processing_completed = _signals.signal("workflow_processing_completed")
"""工作流处理完成事件"""

workflow_processing_failed = _signals.signal("workflow_processing_failed")
"""工作流处理失败事件"""

# 工具相关事件
tool_created = _signals.signal("tool_created")
"""工具创建事件"""

tool_updated = _signals.signal("tool_updated")
"""工具更新事件"""

tool_executed = _signals.signal("tool_executed")
"""工具执行事件"""

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


@dataclass
class WorkflowProcessingEventData:
    """工作流处理事件数据"""

    session_id: str
    current_step: int
    total_steps: int
    step_name: str
    message: str
    percent: int
    tool_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ToolEventData:
    """工具事件数据"""

    tool_id: str
    tool_name: str
    description: str


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

    Example:
        >>> def on_recording_completed(sender, **kwargs):
        ...     print(f"Recording completed: {kwargs}")
        >>> disconnect = connect('recording_completed', on_recording_completed)
        >>> # 取消连接
        ... disconnect()
    """
    signal = _signals.signal(signal_name)
    return signal.connect(callback)


def disconnect(signal_name: str, callback: Callable) -> None:
    """
    断开信号和回调函数的连接

    Args:
        signal_name: 信号名称
        callback: 回调函数
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

    Example:
        >>> emit('recording_completed', session_id='123', action_count=5)
    """
    signal = _signals.signal(signal_name)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"发送事件 '{signal_name}'")
    try:
        signal.send(sender, event_name=signal_name, **kwargs)
    except Exception as exc:
        logger.error(f"[Events] 监听器处理 {signal_name} 时异常: {exc}")


def list_signals() -> dict:
    """
    列出所有已注册的信号及其监听器数量

    Returns:
        字典，键为信号名称，值为监听器数量
    """
    result = {}
    for name in [
        "recording_started",
        "recording_stopped",
        "recording_completed",
        "recording_failed",
        "workflow_processing_started",
        "workflow_processing_progress",
        "workflow_processing_completed",
        "workflow_processing_failed",
        "tool_created",
        "tool_updated",
        "tool_executed",
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
    ]:
        signal = _signals.signal(name)
        # 获取所有接收器数量（简化计算）
        try:
            count = len(signal.receivers_for(None))
            result[name] = count
        except AttributeError as e:
            logger.warning(f"获取信号监听器数量失败: {name}, 错误: {e}")
            result[name] = 0
        except Exception as e:
            logger.error(f"获取信号监听器数量时发生未预期错误: {name}, 错误: {e}")
            result[name] = 0

    return result


def clear_all() -> None:
    """
    清除所有信号的监听器（主要用于测试）
    """
    for name in [
        "recording_started",
        "recording_stopped",
        "recording_completed",
        "recording_failed",
        "workflow_processing_started",
        "workflow_processing_progress",
        "workflow_processing_completed",
        "workflow_processing_failed",
        "tool_created",
        "tool_updated",
        "tool_executed",
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
    ]:
        signal = _signals.signal(name)
        # 清空所有接收器
        signal._clear_state()


# =============================================================================
# 装饰器
# =============================================================================


def listen_to(signal_name: str):
    """
    监听事件的装饰器

    Args:
        signal_name: 信号名称

    Example:
        >>> @listen_to('recording_completed')
        ... def handle_recording_completed(sender, **kwargs):
        ...     print(f"Handling: {kwargs}")
    """

    def decorator(func: Callable):
        signal = _signals.signal(signal_name)
        signal.connect(func)
        return func

    return decorator


# =============================================================================
# 导出
# =============================================================================

__all__ = [
    # 信号
    "recording_started",
    "recording_stopped",
    "recording_completed",
    "recording_failed",
    "workflow_processing_started",
    "workflow_processing_progress",
    "workflow_processing_completed",
    "workflow_processing_failed",
    "tool_created",
    "tool_updated",
    "tool_executed",
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
    "WorkflowProcessingEventData",
    "ToolEventData",
    # 函数
    "connect",
    "disconnect",
    "emit",
    "list_signals",
    "clear_all",
    "listen_to",
]
