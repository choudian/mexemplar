"""
测试工具注册机制
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.business.agents.tool_registry import (
    agent_tool,
    get_tool_schemas,
    execute_tool,
    get_registered_tools,
    clear_registry,
)


class TestToolRegistry:
    """工具注册机制测试"""

    def setup_method(self):
        """每个测试前清空注册表"""
        clear_registry()

    def test_decorator_registration(self):
        """测试装饰器注册"""

        @agent_tool(
            name="test_tool",
            description="测试工具",
            parameters_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]
            }
        )
        def test_tool(name: str) -> str:
            return f"Hello, {name}!"

        # 验证注册
        assert "test_tool" in get_registered_tools()
        assert len(get_tool_schemas()) == 1

    def test_schema_generation(self):
        """测试 schema 生成"""

        @agent_tool(
            name="query_tool",
            description="查询工具",
            parameters_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "limit": {"type": "integer"}
                },
                "required": ["id"]
            }
        )
        def query_tool(id: str, limit: int = 10) -> str:
            return f"Query {id} with limit {limit}"

        schemas = get_tool_schemas()
        assert len(schemas) == 1
        assert schemas[0]["type"] == "function"
        assert schemas[0]["function"]["name"] == "query_tool"
        assert schemas[0]["function"]["description"] == "查询工具"
        assert "id" in schemas[0]["function"]["parameters"]["required"]

    def test_tool_execution(self):
        """测试工具执行"""

        @agent_tool(
            name="add_numbers",
            description="加法工具",
            parameters_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"}
                },
                "required": ["a", "b"]
            }
        )
        def add_numbers(a: int, b: int) -> str:
            return str(a + b)

        result = execute_tool("add_numbers", {"a": 2, "b": 3})
        assert result == "5"

    def test_unknown_tool(self):
        """测试未知工具处理"""
        result = execute_tool("nonexistent_tool", {})
        assert "错误" in result
        assert "未知工具" in result

    def test_execution_error(self):
        """测试工具执行错误处理"""

        @agent_tool(
            name="error_tool",
            description="会报错的工具",
            parameters_schema={"type": "object", "properties": {}}
        )
        def error_tool() -> str:
            raise ValueError("测试错误")

        result = execute_tool("error_tool", {})
        assert "错误" in result
        assert "测试错误" in result

    def test_multiple_tools(self):
        """测试多个工具注册"""

        @agent_tool(
            name="tool1",
            description="工具1",
            parameters_schema={"type": "object", "properties": {}}
        )
        def tool1() -> str:
            return "tool1"

        @agent_tool(
            name="tool2",
            description="工具2",
            parameters_schema={"type": "object", "properties": {}}
        )
        def tool2() -> str:
            return "tool2"

        assert len(get_registered_tools()) == 2
        assert "tool1" in get_registered_tools()
        assert "tool2" in get_registered_tools()

    def test_clear_registry(self):
        """测试清空注册表"""

        @agent_tool(
            name="temp_tool",
            description="临时工具",
            parameters_schema={"type": "object", "properties": {}}
        )
        def temp_tool() -> str:
            return "temp"

        assert "temp_tool" in get_registered_tools()

        clear_registry()

        assert len(get_registered_tools()) == 0