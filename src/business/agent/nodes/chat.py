"""
普通对话节点

处理普通对话场景。
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage

from ..state import AgentState


def chat_node(state: AgentState) -> Dict[str, Any]:
    """
    普通对话节点

    与用户进行对话交互。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取最新用户消息
    messages = state.get("messages", [])
    if not messages:
        return {
            "messages": [AIMessage(content="你好，有什么我可以帮助你的吗？")]
        }

    last_message = messages[-1]
    user_input = getattr(last_message, "content", str(last_message))

    # TODO: 调用 LLM 生成回复
    # 这里先用占位实现
    response = f"收到您的消息：{user_input}"

    return {
        "messages": [AIMessage(content=response)]
    }
