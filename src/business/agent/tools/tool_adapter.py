"""
工具适配器

将现有工具转换为 LangGraph Tools 格式。
"""

from typing import List, Dict, Any
from langchain_core.tools import tool

from src.data.repositories import ToolRepository


def load_tools_from_repository(repository: ToolRepository) -> List:
    """
    从工具仓库加载已发布工具

    Args:
        repository: 工具仓库实例

    Returns:
        LangGraph Tools 列表
    """
    # 加载所有工具（暂不支持按状态过滤）
    all_tools = repository.get_all()

    # 转换为 LangGraph Tools
    langgraph_tools = []
    for tool_data in all_tools:
        langgraph_tool = create_tool_adapter(tool_data)
        langgraph_tools.append(langgraph_tool)

    return langgraph_tools


def create_tool_adapter(tool_data: Dict[str, Any]):
    """
    将工具数据转换为 LangGraph Tool

    Args:
        tool_data: 工具数据（from ToolRepository）

    Returns:
        LangGraph Tool
    """
    @tool(tool_data.get("tool_name", "unnamed_tool"))
    def adapted_tool(**kwargs) -> str:
        """
        动态生成的工具包装器
        """
        # TODO: 实际执行工具代码
        # 需要调用 CodeExecutor
        return f"执行工具 {tool_data.get('tool_name')}，参数：{kwargs}"

    # 设置工具描述
    adapted_tool.description = tool_data.get("description", "")

    return adapted_tool
