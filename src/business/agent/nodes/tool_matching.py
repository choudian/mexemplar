"""
工具匹配节点

从工具库中匹配适合的工具。
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage

from ..state import AgentState


def tool_matching_node(state: AgentState) -> Dict[str, Any]:
    """
    工具匹配节点

    根据用户意图，从工具库中匹配最合适的工具。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取可用工具
    available_tools = state.get("available_tools", [])
    if not available_tools:
        return {
            "error_info": {
                "code": "NO_TOOLS",
                "message": "No tools available"
            }
        }

    # TODO: 实现工具匹配逻辑（向量搜索 / LLM 匹配）
    # 这里先用占位实现
    matched_tool = available_tools[0] if available_tools else None

    # 判断置信度，决定是否需要用户确认
    requires_confirmation = True  # 默认需要确认
    confidence = 0.7

    if confidence >= 0.8:
        requires_confirmation = False

    return {
        "matched_tool": matched_tool,
        "requires_user_confirmation": requires_confirmation,
        "messages": [AIMessage(
            content=f"匹配到工具：{matched_tool.get('tool_name') if matched_tool else 'None'}\n"
                    f"置信度：{confidence}"
        )]
    }
