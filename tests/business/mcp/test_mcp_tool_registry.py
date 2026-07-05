"""
T020: McpToolRegistry 单元测试 — dual-track + preset full injection + custom LRU + unregister。
"""

import pytest

from src.business.mcp.mcp_tool_registry import McpToolRegistry, NullRegistry, McpCatalogItem
from src.business.mcp.models import McpToolInfo


def _make_tool(name: str, description: str = "") -> McpToolInfo:
    return McpToolInfo(name=name, description=description, input_schema={"type": "object"})


class TestMcpToolRegistry:
    """McpToolRegistry 双轨注册测试。"""

    def test_register_preset_tools(self):
        """预置 server 工具全量注册。"""
        registry = McpToolRegistry()
        tools = [_make_tool("list_prs"), _make_tool("create_issue")]
        registry.register_server_tools("srv1", "github", tools, is_preset=True)

        preset = registry.get_preset_tools()
        # 预置工具注册后需要 ToolDefinition 才能被 get_preset_tools 获取
        # register_server_tools 只注册了 catalog items，ToolDefinition 需通过 register_tool_definition
        catalog = registry.get_catalog_items()
        assert len(catalog) == 2
        names = [c.name for c in catalog]
        assert "mcp__github__list_prs" in names
        assert "mcp__github__create_issue" in names

    def test_unregister_by_server_id(self):
        """按 server_id 注销工具（不依赖前缀匹配）。"""
        registry = McpToolRegistry()
        tools = [_make_tool("tool_a"), _make_tool("tool_b")]
        registry.register_server_tools("srv1", "myserver", tools, is_preset=False)

        removed = registry.unregister_server_tools("srv1")
        assert len(removed) == 2
        assert registry.get_catalog_items() == []

    def test_unregister_nonexistent_server(self):
        """注销不存在的 server 返回空 set。"""
        registry = McpToolRegistry()
        result = registry.unregister_server_tools("nonexistent")
        assert result == set()

    def test_custom_tool_lru_activation(self):
        """自定义 server 工具 LRU 激活/淘汰。"""
        registry = McpToolRegistry()

        # 注册 15 个自定义工具（超过 MAX_ACTIVATED_CUSTOM=10）
        tools = [_make_tool(f"tool_{i}") for i in range(15)]
        registry.register_server_tools("srv1", "custom", tools, is_preset=False)

        # 先注册 ToolDefinition（activate 需要 _all_tools 中存在）
        from src.business.agents.config import ToolDefinition
        for i in range(15):
            full_name = f"mcp__custom__tool_{i}"
            tool_def = ToolDefinition(
                name=full_name,
                schema={"name": full_name, "parameters": {"type": "object"}},
                handler=lambda **kw: "ok",
            )
            registry.register_tool_definition(full_name, tool_def, "srv1", is_preset=False)

        # 激活前 12 个
        for i in range(12):
            result = registry.activate_custom_tool(f"mcp__custom__tool_{i}")
            assert result is True

        # 验证 LRU 淘汰：只有最近 10 个在 activated 中
        activated = registry.get_activated_custom_tools()
        assert len(activated) <= 10

    def test_preset_tool_no_need_activate(self):
        """预置工具激活直接返回 True（已全量注入）。"""
        registry = McpToolRegistry()
        tools = [_make_tool("tool_a")]
        registry.register_server_tools("srv1", "preset", tools, is_preset=True)

        result = registry.activate_custom_tool("mcp__preset__tool_a")
        assert result is True

    def test_activate_nonexistent_tool(self):
        """激活不存在的工具返回 False。"""
        registry = McpToolRegistry()
        result = registry.activate_custom_tool("mcp__nonexistent__tool")
        assert result is False

    def test_get_catalog_items_snapshot(self):
        """get_catalog_items 返回 snapshot。"""
        registry = McpToolRegistry()
        tools = [_make_tool("tool_a")]
        registry.register_server_tools("srv1", "srv", tools, is_preset=False)

        snapshot = registry.get_catalog_items()
        # 修改原 registry 不影响 snapshot
        registry.unregister_server_tools("srv1")
        assert len(snapshot) == 1

    def test_find_tool(self):
        """find_tool 查找。"""
        registry = McpToolRegistry()
        tools = [_make_tool("my_tool")]
        registry.register_server_tools("srv1", "test", tools, is_preset=False)

        # 未注册 ToolDefinition 时返回 None
        result = registry.find_tool("mcp__test__my_tool")
        assert result is None

    def test_get_tool_count(self):
        """preset/custom 工具计数。"""
        registry = McpToolRegistry()
        preset_tools = [_make_tool("preset_tool")]
        custom_tools = [_make_tool("custom_tool")]

        registry.register_server_tools("srv1", "preset", preset_tools, is_preset=True)
        registry.register_server_tools("srv2", "custom", custom_tools, is_preset=False)

        # register_server_tools 注册了 catalog items
        # ToolDefinition 通过 register_tool_definition 注册到 _all_tools
        from src.business.agents.config import ToolDefinition
        for tools, server_id, slug, is_preset in [
            (preset_tools, "srv1", "preset", True),
            (custom_tools, "srv2", "custom", False),
        ]:
            for tool in tools:
                full_name = f"mcp__{slug}__{tool.name}"
                tool_def = ToolDefinition(
                    name=full_name,
                    schema={"name": full_name, "parameters": {"type": "object"}},
                    handler=lambda **kw: "ok",
                )
                registry.register_tool_definition(full_name, tool_def, server_id, is_preset=is_preset)

        preset_count, custom_count = registry.get_tool_count()
        assert preset_count == 1
        assert custom_count == 1

    def test_re_register_clears_old(self):
        """重新注册同一 server 先清旧工具。"""
        registry = McpToolRegistry()
        tools_v1 = [_make_tool("tool_v1")]
        registry.register_server_tools("srv1", "srv", tools_v1, is_preset=False)

        tools_v2 = [_make_tool("tool_v2"), _make_tool("tool_v3")]
        registry.register_server_tools("srv1", "srv", tools_v2, is_preset=False)

        catalog = registry.get_catalog_items()
        names = [c.name for c in catalog]
        assert "mcp__srv__tool_v1" not in names
        assert "mcp__srv__tool_v2" in names
        assert "mcp__srv__tool_v3" in names


class TestNullRegistry:
    """NullRegistry 降级测试。"""

    def test_null_registry_returns_empty(self):
        """所有方法返回空。"""
        registry = NullRegistry()
        assert registry.get_preset_tools() == []
        assert registry.get_activated_custom_tools() == []
        assert registry.get_catalog_items() == []
        assert registry.find_tool("anything") is None
        assert registry.get_tool_count() == (0, 0)
        assert registry.activate_custom_tool("anything") is False

    def test_null_registry_no_error(self):
        """NullRegistry 所有操作不抛异常。"""
        registry = NullRegistry()
        registry.register_server_tools("srv", "slug", [], False)
        registry.unregister_server_tools("srv")
        registry.register_tool_definition("name", None, "srv", False)
