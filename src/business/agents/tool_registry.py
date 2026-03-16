"""
工具注册机制

使用装饰器模式注册 Agent 工具，简化工具管理。
"""

from typing import Dict, Any, Callable, List
import logging

logger = logging.getLogger(__name__)

# 全局工具注册表
# 格式: {tool_name: {"handler": callable, "schema": {...}}}
_tool_registry: Dict[str, Dict[str, Any]] = {}


def agent_tool(name: str, description: str, parameters_schema: Dict[str, Any]):
    """
    工具注册装饰器

    Args:
        name: 工具名称
        description: 工具描述
        parameters_schema: 参数 schema（JSON Schema 格式）

    Returns:
        装饰器函数

    Example:
        >>> @agent_tool(
        ...     name="query_data",
        ...     description="查询数据",
        ...     parameters_schema={
        ...         "type": "object",
        ...         "properties": {"id": {"type": "string"}},
        ...         "required": ["id"]
        ...     }
        ... )
        ... def query_data(id: str) -> str:
        ...     return f"Data for {id}"
    """
    def decorator(func: Callable):
        _tool_registry[name] = {
            "handler": func,
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters_schema
                }
            }
        }
        logger.debug(f"[工具注册] 已注册工具: {name}")
        return func
    return decorator


def get_tool_schemas() -> List[Dict[str, Any]]:
    """
    获取所有已注册工具的 schema

    Returns:
        工具 schema 列表
    """
    return [tool["schema"] for tool in _tool_registry.values()]


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """
    执行工具，返回字符串结果

    Args:
        name: 工具名称
        args: 工具参数

    Returns:
        工具执行结果（字符串格式）
    """
    if name not in _tool_registry:
        logger.warning(f"[工具执行] 未知工具: {name}")
        return f"错误：未知工具 '{name}'"

    try:
        handler = _tool_registry[name]["handler"]
        result = handler(**args)
        return str(result)
    except Exception as e:
        logger.error(f"[工具执行] 执行失败: {name}, 错误: {e}")
        return f"错误：{str(e)}"


def get_registered_tools() -> List[str]:
    """
    获取所有已注册工具的名称列表

    Returns:
        工具名称列表
    """
    return list(_tool_registry.keys())


def clear_registry():
    """
    清空工具注册表（主要用于测试）
    """
    global _tool_registry
    _tool_registry = {}
    logger.debug("[工具注册] 已清空注册表")