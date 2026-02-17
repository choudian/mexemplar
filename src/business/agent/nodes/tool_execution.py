"""
工具执行节点

执行匹配到的工具。
"""

from typing import Dict, Any
from langchain_core.messages import AIMessage

from ..state import AgentState


def tool_execution_node(state: AgentState) -> Dict[str, Any]:
    """
    工具执行节点

    执行工具并返回结果。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取匹配的工具和参数
    matched_tool = state.get("matched_tool")
    tool_parameters = state.get("tool_parameters", {})

    if not matched_tool:
        return {
            "error_info": {
                "code": "NO_MATCHED_TOOL",
                "message": "No matched tool to execute"
            }
        }

    # TODO: 实际执行工具代码
    # 需要调用 CodeExecutor
    execution_result = {
        "success": True,
        "output": f"执行工具 {matched_tool.get('tool_name')} 成功",
        "params": tool_parameters
    }

    # 返回状态更新
    return {
        "execution_result": execution_result,
        "messages": [AIMessage(
            content=f"工具执行结果：{execution_result['output']}"
        )]
    }
