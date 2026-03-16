"""
Agent Loop 事件系统

集成 blinker 事件系统，允许外部监听 Agent Loop 的状态变化。
"""

from blinker import Namespace
import logging

logger = logging.getLogger(__name__)

# 创建命名空间
_signals = Namespace()

# =============================================================================
# Agent Loop 事件定义
# =============================================================================

agent_iteration_started = _signals.signal("agent_iteration_started")
"""Agent 迭代开始事件"""

agent_iteration_completed = _signals.signal("agent_iteration_completed")
"""Agent 迭代完成事件"""

agent_tool_executed = _signals.signal("agent_tool_executed")
"""Agent 工具执行成功事件"""

agent_tool_failed = _signals.signal("agent_tool_failed")
"""Agent 工具执行失败事件"""

agent_needs_user_input = _signals.signal("agent_needs_user_input")
"""Agent 需要用户输入事件"""

agent_completed = _signals.signal("agent_completed")
"""Agent 完成事件"""

agent_error = _signals.signal("agent_error")
"""Agent 错误事件"""


# =============================================================================
# 便捷函数
# =============================================================================

def emit_event(event_name: str, session_id: str, **kwargs):
    """
    发送 Agent 事件

    Args:
        event_name: 事件名称
        session_id: 会话 ID
        **kwargs: 额外的事件数据
    """
    signal = _signals.signal(event_name)

    # 添加 session_id 到 kwargs
    kwargs["session_id"] = session_id

    # 记录日志
    if logger.isEnabledFor(logging.DEBUG):
        receiver_count = len(signal.receivers_for(session_id))
        logger.debug(
            f"[Agent 事件] 发送 '{event_name}' "
            f"(session_id={session_id}, receiver_count={receiver_count})"
        )

    signal.send(sender=session_id, **kwargs)


# =============================================================================
# 导出
# =============================================================================

__all__ = [
    # 信号
    "agent_iteration_started",
    "agent_iteration_completed",
    "agent_tool_executed",
    "agent_tool_failed",
    "agent_needs_user_input",
    "agent_completed",
    "agent_error",
    # 函数
    "emit_event",
]