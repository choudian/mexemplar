"""
T033: mcp_search_tools 单元测试 — RC6 wrapper + kind="mcp" filter + server_slug filter。
"""

import json

from src.business.mcp.mcp_search_tools import create_mcp_aware_search_tools
from src.business.mcp.mcp_tool_registry import McpToolRegistry, NullRegistry
from src.business.mcp.models import McpToolInfo
from src.business.agents.config import ToolDefinition


def _make_mcp_tool(name: str) -> McpToolInfo:
    return McpToolInfo(name=name, description=f"MCP tool {name}", input_schema={"type": "object"})


def _setup_registry_with_tools() -> McpToolRegistry:
    """创建包含预置和自定义工具的 registry。"""
    registry = McpToolRegistry()

    # 预置 server: github
    preset_tools = [_make_mcp_tool("list_prs"), _make_mcp_tool("create_issue")]
    registry.register_server_tools("srv_github", "github", preset_tools, is_preset=True)

    # 自定义 server: custom
    custom_tools = [_make_mcp_tool("search_data"), _make_mcp_tool("write_data")]
    registry.register_server_tools("srv_custom", "customdb", custom_tools, is_preset=False)

    # 注册 ToolDefinition
    for server_id, slug, tools, is_preset in [
        ("srv_github", "github", preset_tools, True),
        ("srv_custom", "customdb", custom_tools, False),
    ]:
        for tool in tools:
            full_name = f"mcp__{slug}__{tool.name}"
            tool_def = ToolDefinition(
                name=full_name,
                schema={
                    "name": full_name,
                    "description": tool.description,
                    "parameters": {"type": "object"},
                },
                handler=lambda **kw: "ok",
            )
            registry.register_tool_definition(full_name, tool_def, server_id, is_preset=is_preset)

    return registry


class TestMcpSearchTools:
    """MCP-aware search_tools 测试。"""

    def test_search_tools_with_null_registry(self):
        """NullRegistry 不崩溃。"""
        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        dynamic_manager = DynamicToolManager(allowed_tool_ids=None)
        null_registry = NullRegistry()

        tools = create_mcp_aware_search_tools(dynamic_manager, null_registry)
        assert len(tools) == 2  # search_tools + get_tool_detail

    def test_search_tools_kind_mcp(self):
        """kind="mcp" 只返回 MCP 工具。"""
        registry = _setup_registry_with_tools()

        # 用 Null DynamicToolManager（无用户技能）
        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        dynamic_manager = DynamicToolManager(allowed_tool_ids=None)

        search_tools = create_mcp_aware_search_tools(dynamic_manager, registry)
        search_handler = search_tools[0].handler  # search_tools handler

        result_json = search_handler(kind="mcp")
        result = json.loads(result_json)

        assert "items" in result
        # 应该只包含 MCP 工具
        for item in result["items"]:
            assert item["kind"] == "mcp"

    def test_search_tools_server_slug_filter(self):
        """server_slug 过滤 MCP 工具（P3-R2）。"""
        registry = _setup_registry_with_tools()

        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        dynamic_manager = DynamicToolManager(allowed_tool_ids=None)

        search_tools = create_mcp_aware_search_tools(dynamic_manager, registry)
        search_handler = search_tools[0].handler

        result_json = search_handler(kind="mcp", server_slug="github")
        result = json.loads(result_json)

        # 只应包含 github server 的工具
        for item in result["items"]:
            assert "mcp__github__" in item["name"]

    def test_get_tool_detail_mcp_selector(self):
        """get_tool_detail "mcp:" selector 解析 + 激活。"""
        registry = _setup_registry_with_tools()

        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        dynamic_manager = DynamicToolManager(allowed_tool_ids=None)

        search_tools = create_mcp_aware_search_tools(dynamic_manager, registry)
        detail_handler = search_tools[1].handler  # get_tool_detail handler

        result_json = detail_handler("mcp:mcp__github__list_prs")
        result = json.loads(result_json)

        assert result.get("kind") == "mcp"
        assert result.get("name") == "mcp__github__list_prs"

    def test_get_tool_detail_mcp_not_found(self):
        """MCP 工具不存在返回错误。"""
        registry = McpToolRegistry()

        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        dynamic_manager = DynamicToolManager(allowed_tool_ids=None)

        search_tools = create_mcp_aware_search_tools(dynamic_manager, registry)
        detail_handler = search_tools[1].handler

        result_json = detail_handler("mcp:mcp__nonexistent__tool")
        result = json.loads(result_json)

        assert "error" in result

    def test_search_tools_schema_has_mcp_kind(self):
        """search_tools schema kind enum 含 "mcp"。"""
        registry = NullRegistry()
        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        dynamic_manager = DynamicToolManager(allowed_tool_ids=None)

        tools = create_mcp_aware_search_tools(dynamic_manager, registry)
        search_schema = tools[0].schema

        kind_enum = search_schema["function"]["parameters"]["properties"]["kind"]["enum"]
        assert "mcp" in kind_enum
