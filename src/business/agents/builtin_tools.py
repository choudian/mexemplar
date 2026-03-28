"""
内置工具定义

定义所有 Agent 共享的内置工具。
talk_to_user 和 load_reference 由 AgentLoop 自动追加到每次请求的工具列表中。
talk_to_user handler 返回 ToolSignal，与业务工具（如 submit_requirements）使用同一套机制。
"""

from .config import ToolSignal, ResultType

# talk_to_user 向用户提问或展示信息，handler 返回 ToolSignal 中断循环
TALK_TO_USER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "talk_to_user",
        "description": "向用户提问，等待用户回复。这是一个中断信号，不会实际执行。",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "要向用户提出的问题"}},
            "required": ["message"],
        },
    },
}

# load_reference 由 AgentLoop 内部处理，不在注册表中
LOAD_REFERENCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_reference",
        "description": "加载被引用替换的原始消息内容。当工具结果被引用替换时，使用此工具获取完整内容。",
        "parameters": {
            "type": "object",
            "properties": {"reference_id": {"type": "string", "description": "要加载的引用 ID（消息 ID 或摘要 ID）"}},
            "required": ["reference_id"],
        },
    },
}


def talk_to_user(message: str) -> ToolSignal:
    """
    talk_to_user handler — 返回 ToolSignal 中断循环，等待用户回复。

    Args:
        message: 向用户展示的消息或问题

    Returns:
        ToolSignal，result_type=NEEDS_USER_INPUT
    """
    return ToolSignal(
        result_type=ResultType.NEEDS_USER_INPUT,
        display_text="[等待用户回复]",
    )


__all__ = [
    "TALK_TO_USER_SCHEMA",
    "LOAD_REFERENCE_SCHEMA",
    "talk_to_user",
]
