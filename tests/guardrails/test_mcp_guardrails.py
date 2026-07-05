"""
T024: MCP 架构门卫测试 — 验证关键架构约束。
"""

import ast
import pytest


class TestMcpGuardrails:
    """MCP 架构门卫测试。"""

    def test_mcp_tools_use_deferred_loading(self):
        """MCP 工具走 deferred loading（自定义 server 不全量注入）。"""
        from src.business.mcp.mcp_tool_registry import McpToolRegistry

        registry = McpToolRegistry()
        # 自定义 server 工具不应出现在 get_preset_tools 中
        from src.business.mcp.models import McpToolInfo

        tools = [McpToolInfo(name="custom_tool", description="", input_schema={})]
        registry.register_server_tools("srv1", "custom", tools, is_preset=False)

        # 自定义工具不在 preset 列表中
        assert registry.get_preset_tools() == []

        # 但在 catalog 中可见（走 search 发现）
        catalog = registry.get_catalog_items()
        assert len(catalog) == 1

    def test_sdk_types_not_in_business_layer(self):
        """SDK 类型不穿业务层（no `from mcp.types` in service/registry）。"""
        import src.business.mcp.mcp_server_service as service_mod
        import src.business.mcp.mcp_tool_registry as registry_mod

        # 检查源码不含 `from mcp.types` import
        for module in [service_mod, registry_mod]:
            source_file = module.__file__
            with open(source_file, "r", encoding="utf-8") as f:
                source = f.read()

            # 不允许 `from mcp.types import` 或 `from mcp import ...types...`
            assert "from mcp.types import" not in source, (
                f"{source_file}: SDK types 不应穿入业务层"
            )
            # 允许延迟 import `from mcp import ClientSession` 等（在 process_manager 内）
            # 但不允许 from mcp.types import

    def test_mcp_modules_no_top_level_sdk_import(self):
        """E7: MCP 业务模块不得在模块顶层 import MCP SDK。

        仅 mcp_process_manager 允许延迟导入（函数内），其余业务模块
        不得有任何 `from mcp import` 语句。
        """
        import importlib
        import os

        mcp_dir = os.path.dirname(
            importlib.import_module("src.business.mcp").__file__
        )
        # 这些模块完全不允许任何 MCP SDK import
        no_sdk_import_modules = {
            "mcp_server_service.py",
            "mcp_tool_registry.py",
            "mcp_search_tools.py",
            "mcp_json_import.py",
            "mcp_env_resolver.py",
            "mcp_errors.py",
            "mcp_presets.py",
            "models.py",
            "mcp_session_protocol.py",
            "__init__.py",
        }

        for filename in os.listdir(mcp_dir):
            if not filename.endswith(".py"):
                continue
            filepath = os.path.join(mcp_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()

            if filename in no_sdk_import_modules:
                # 完全不允许 from mcp import
                assert "from mcp " not in source and "from mcp." not in source, (
                    f"{filename}: 业务模块不得 import MCP SDK（E7）"
                )
            elif filename == "mcp_process_manager.py":
                # 允许延迟导入，但不允许模块级 from mcp import
                tree = ast.parse(source)
                top_level_imports = []
                for node in ast.iter_child_nodes(tree):
                    if isinstance(node, ast.ImportFrom) and node.module and (
                        node.module == "mcp" or node.module.startswith("mcp.")
                    ):
                        top_level_imports.append(node)
                assert len(top_level_imports) == 0, (
                    f"mcp_process_manager.py: MCP SDK import 必须在函数内延迟导入（E7），"
                    f"发现模块级 import: from {top_level_imports[0].module}"
                )

    def test_credentials_not_in_repr(self):
        """凭证不泄漏到 DTO/logs（McpServerConfigPublic + McpLaunchPayload repr）。"""
        from src.business.mcp.models import McpLaunchPayload

        payload = McpLaunchPayload(
            command="npx",
            args=[],
            merged_env={"GITHUB_TOKEN": "ghp_supersecret123"},
        )
        r = repr(payload)
        assert "ghp_supersecret123" not in r

    def test_parsed_preview_repr_masks_secrets(self):
        """McpServerParsedPreview __repr__ 遮罩 secret 值（RC5）。"""
        from src.business.mcp.mcp_json_import import McpServerParsedPreview

        preview = McpServerParsedPreview(
            name="github",
            transport="stdio",
            env={"GITHUB_TOKEN": "ghp_supersecret123", "PATH": "/usr/bin"},
            detected_secret_keys=["GITHUB_TOKEN"],
        )
        r = repr(preview)
        assert "ghp_supersecret123" not in r, (
            "McpServerParsedPreview.__repr__ 不得包含 secret 原始值"
        )
        # 非secret 值应可见
        assert "github" in r

    def test_mcp_tool_registry_snapshot_semantics(self):
        """McpToolRegistry snapshot 语义（no dictionary changed size during iteration）。"""
        from src.business.mcp.mcp_tool_registry import McpToolRegistry
        from src.business.mcp.models import McpToolInfo
        import threading

        registry = McpToolRegistry()
        errors = []

        def reader():
            try:
                for _ in range(50):
                    registry.get_catalog_items()
                    registry.get_preset_tools()
                    registry.get_activated_custom_tools()
            except RuntimeError as e:
                if "dictionary changed size" in str(e):
                    errors.append(e)

        def writer():
            for i in range(20):
                tools = [McpToolInfo(name=f"t{i}", description="", input_schema={})]
                registry.register_server_tools(f"srv{i}", f"slug{i}", tools, is_preset=False)
                registry.unregister_server_tools(f"srv{i}")

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=writer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert len(errors) == 0, f"Snapshot semantics violated: {errors}"

    def test_tool_factory_includes_mcp_tools(self):
        """tool_factory 包含 MCP preset + activated custom tools。"""
        from src.business.mcp.mcp_tool_registry import McpToolRegistry
        from src.business.mcp.models import McpToolInfo
        from src.business.agents.config import ToolDefinition

        registry = McpToolRegistry()

        # 注册预置工具
        preset_tools = [McpToolInfo(name="preset_tool", description="", input_schema={})]
        registry.register_server_tools("srv1", "preset", preset_tools, is_preset=True)

        # 注册 ToolDefinition
        tool_def = ToolDefinition(
            name="mcp__preset__preset_tool",
            schema={"name": "mcp__preset__preset_tool", "parameters": {"type": "object"}},
            handler=lambda **kw: "ok",
        )
        registry.register_tool_definition(
            "mcp__preset__preset_tool", tool_def, "srv1", is_preset=True
        )

        # 预置工具应在 get_preset_tools 中
        preset_result = registry.get_preset_tools()
        assert len(preset_result) == 1
        assert preset_result[0].name == "mcp__preset__preset_tool"

        # 注册自定义工具 + 激活
        custom_tools = [McpToolInfo(name="custom_tool", description="", input_schema={})]
        registry.register_server_tools("srv2", "custom", custom_tools, is_preset=False)
        custom_def = ToolDefinition(
            name="mcp__custom__custom_tool",
            schema={"name": "mcp__custom__custom_tool", "parameters": {"type": "object"}},
            handler=lambda **kw: "ok",
        )
        registry.register_tool_definition(
            "mcp__custom__custom_tool", custom_def, "srv2", is_preset=False
        )
        # 激活自定义工具
        activated = registry.activate_custom_tool("mcp__custom__custom_tool")
        assert activated is not None

        # activated custom tools 应在 get_activated_custom_tools 中
        activated_result = registry.get_activated_custom_tools()
        assert len(activated_result) == 1
        assert activated_result[0].name == "mcp__custom__custom_tool"

    def test_business_layer_no_direct_app_settings_sql(self):
        """业务层不直接操作 app_settings 表（Constitution II：业务代码不直接拼写 SQL）。"""
        import src.business.mcp.mcp_server_service as service_mod

        source_file = service_mod.__file__
        with open(source_file, "r", encoding="utf-8") as f:
            source = f.read()

        # 不允许直接 DELETE FROM app_settings（应走 UnifiedConfigManager.delete_by_prefix）
        assert "DELETE FROM app_settings" not in source, (
            f"{source_file}: 业务层不应直接执行 DELETE FROM app_settings SQL，"
            "应使用 UnifiedConfigManager.delete_by_prefix()"
        )

        # 不允许直接 import sqlalchemy_manager（应通过 UnifiedConfigManager 访问）
        assert "from src.data.sqlalchemy_manager import" not in source, (
            f"{source_file}: 业务层不应直接 import sqlalchemy_manager，"
            "应通过 UnifiedConfigManager 访问数据层"
        )

    def test_cleanup_secrets_uses_config_manager(self):
        """_cleanup_secrets 通过 UnifiedConfigManager 而非直接 SQL 删除凭证。"""
        import inspect
        import src.business.mcp.mcp_server_service as service_mod

        source = inspect.getsource(service_mod.McpServerService._cleanup_secrets)

        # 必须调用 UnifiedConfigManager.delete_by_prefix
        assert "delete_by_prefix" in source, (
            "_cleanup_secrets 应调用 UnifiedConfigManager.delete_by_prefix()"
        )

        # 不得直接操作 SQLAlchemy session
        assert "session.execute" not in source, (
            "_cleanup_secrets 不应直接操作 SQLAlchemy session"
        )
        assert "sqlalchemy" not in source, (
            "_cleanup_secrets 不应导入 sqlalchemy"
        )
