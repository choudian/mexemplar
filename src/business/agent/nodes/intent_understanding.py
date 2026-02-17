"""
意图理解节点

理解用户的任务意图。
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage

from ..state import AgentState


def intent_understanding_node(state: AgentState) -> Dict[str, Any]:
    """
    意图理解节点

    分析用户消息，理解用户想要执行的任务。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取最新用户消息
    messages = state.get("messages", [])
    if not messages:
        return {
            "error_info": {
                "code": "NO_MESSAGE",
                "message": "No user message"
            }
        }

    last_message = messages[-1]
    user_input = getattr(last_message, "content", str(last_message))

    # TODO: 调用 LLM 理解意图
    # 这里先用占位实现
    return {
        "messages": [AIMessage(content=f"理解用户意图：{user_input}")]
    }
