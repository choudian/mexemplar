"""
工具确认节点

等待用户确认工具调用（使用 interrupt）。
"""

from typing import Dict, Any
from langgraph.types import interrupt
from langchain_core.messages import AIMessage

from ..state import AgentState


def tool_confirmation_node(state: AgentState) -> Dict[str, Any]:
    """
    工具确认节点

    展示匹配到的工具和参数，等待用户确认。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取匹配的工具
    matched_tool = state.get("matched_tool")
    if not matched_tool:
        return {
            "error_info": {
                "code": "NO_MATCHED_TOOL",
                "message": "No matched tool"
            }
        }

    # 暂停，等待用户确认
    user_response = interrupt({
        "type": "tool_confirmation",
        "tool": matched_tool,
        "message": f"是否执行工具「{matched_tool.get('tool_name')}」？"
    })

    # 用户恢复后，处理响应
    if user_response.get("action") == "confirm":
        # 用户确认
        tool_parameters = user_response.get("params", {})
        return {
            "tool_parameters": tool_parameters,
            "messages": [AIMessage(content="用户确认执行工具")]
        }
    else:
        # 用户取消
        return {
            "error_info": {
                "code": "USER_CANCELLED",
                "message": "User cancelled tool execution"
            }
        }
