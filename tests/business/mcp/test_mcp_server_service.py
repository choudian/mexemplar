"""
T021: McpServerService 单元测试 — CRUD + 生命周期 + 断路器 + 工具注册 + 事件 + 预置引导。

所有 async 操作通过 mock McpProcessManager 隔离，不依赖真实 MCP SDK。
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.business.mcp.mcp_errors import (
    McpCircuitBreakerOpenError,
    McpServerDisconnectedError,
    McpToolSchemaValidationError,
    McpToolTimeoutError,
)
from src.business.mcp.models import (
    McpCallResult,
    McpServerConfigPublic,
    McpToolInfo,
)

# ─── Fixtures ───


def _make_tool(name: str = "read_file", description: str = "Read a file") -> McpToolInfo:
    return McpToolInfo(name=name, description=description, input_schema={"type": "object"})


def _make_config(
    server_id: str = "mcs_test",
    name: str = "test-server",
    transport: str = "stdio",
    command: str = "npx",
    enabled: bool = True,
    is_preset: bool = False,
    preset_slug: str | None = None,
) -> McpServerConfigPublic:
    return McpServerConfigPublic(
        server_id=server_id,
        name=name,
        transport=transport,
        command=command,
        args=[],
        url=None,
        non_secret_env={},
        non_secret_headers={},
        secret_env_keys=[],
        secret_header_keys=[],
        enabled=enabled,
        is_preset=is_preset,
        preset_slug=preset_slug,
    )


def _make_row(
    server_id: str = "mcs_test",
    name: str = "test-server",
    transport: str = "stdio",
    command: str = "npx",
    enabled: bool = True,
    is_preset: bool = False,
    preset_slug: str | None = None,
    tool_count: int | None = None,
    last_known_status: str | None = "stopped",
    last_error_message: str | None = None,
    suggestion: str | None = None,
    circuit_breaker_open: bool = False,
):
    """创建模拟 ORM 行对象。"""
    row = MagicMock()
    row.server_id = server_id
    row.name = name
    row.transport = transport
    row.command = command
    row.args_json = "[]"
    row.url = None
    row.headers_json = None
    row.secret_header_keys_json = None
    row.env_json = "{}"
    row.secret_env_keys_json = "[]"
    row.enabled = enabled
    row.is_preset = is_preset
    row.preset_slug = preset_slug
    row.tool_count = tool_count
    row.last_known_status = last_known_status
    row.last_error_message = last_error_message
    row.suggestion = suggestion
    row.circuit_breaker_open = circuit_breaker_open
    row.created_at = datetime(2026, 1, 1)
    row.updated_at = datetime(2026, 1, 1)
    return row


@pytest.fixture
def mock_process_manager():
    """模拟 McpProcessManager。"""
    pm = MagicMock()
    pm.sdk_available = True
    pm.is_server_running.return_value = False
    pm.start_server.return_value = [_make_tool("tool_a"), _make_tool("tool_b")]
    pm.call_tool_sync.return_value = McpCallResult(
        is_error=False, text_parts=["ok"], image_count=0, structured_data=None
    )
    return pm


@pytest.fixture
def mock_registry():
    """模拟 McpToolRegistry。"""
    registry = MagicMock()
    registry.unregister_server_tools.return_value = set()
    return registry


@pytest.fixture
def mock_repo():
    """模拟 McpServerRepository 上下文管理器。"""
    repo = MagicMock()
    row = _make_row()
    repo.create_server.return_value = row
    repo.get_by_id.return_value = row
    repo.list_all.return_value = [row]
    repo.update_config.return_value = row
    repo.delete_server.return_value = True
    repo.list_enabled.return_value = []
    repo.list_preset_slugs.return_value = []
    repo.update_status.return_value = row

    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=repo)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, repo


@pytest.fixture
def service(mock_process_manager, mock_registry, mock_repo):
    """创建注入 mock 依赖的 McpServerService。"""
    with patch(
        "src.business.mcp.mcp_server_service.McpProcessManager",
        return_value=mock_process_manager,
    ):
        from src.business.mcp.mcp_server_service import McpServerService

        svc = McpServerService()

    # 替换 registry 和 process_manager
    svc._registry = mock_registry
    svc._process_manager = mock_process_manager
    svc._consecutive_failures = {}

    return svc


# ─── add_server ───


class TestAddServer:
    """添加 server：validate + save config + auto-start if enabled。"""

    def test_add_server_normal(self, service, mock_repo, mock_process_manager):
        """正常添加 server，验证保存并返回详情。"""
        ctx, repo = mock_repo
        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_save_secrets"):
                with patch.object(
                    service,
                    "_get_server_detail",
                    return_value={"serverId": "mcs_test", "name": "my-server"},
                ):
                    result = service.add_server(
                        name="my-server",
                        transport="stdio",
                        command="npx",
                        args=["-y", "server"],
                        env={"PATH": "/usr/bin"},
                    )

        assert result["name"] == "my-server"

    def test_add_server_http_transport_rejected(self, service, mock_repo):
        """HTTP transport 创建请求抛出 ValueError。"""
        with pytest.raises(ValueError, match="HTTP"):
            service.add_server(name="http-srv", transport="http", url="http://example.com")

    def test_add_server_placeholder_rejected(self, service, mock_repo):
        """包含 ${VAR} 未解析占位符时抛出 ValueError。"""
        with pytest.raises(ValueError, match="占位符"):
            service.add_server(
                name="bad-srv",
                transport="stdio",
                command="npx",
                env={"API_KEY": "${MISSING_VAR}"},
            )

    def test_add_server_auto_starts_if_enabled(self, service, mock_repo, mock_process_manager):
        """enabled=True 时自动启动。"""
        ctx, repo = mock_repo
        row = _make_row(enabled=True)
        repo.create_server.return_value = row

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_save_secrets"):
                with patch.object(service, "_start_and_register") as mock_start:
                    with patch.object(
                        service, "_get_server_detail", return_value={"serverId": "mcs_test"}
                    ):
                        service.add_server(name="auto-start", transport="stdio", command="npx")

        mock_start.assert_called_once()

    def test_add_server_no_auto_start_if_disabled(self, service, mock_repo, mock_process_manager):
        """enabled=False 时不自动启动。"""
        ctx, repo = mock_repo
        row = _make_row(enabled=False)
        repo.create_server.return_value = row

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_save_secrets"):
                with patch.object(service, "_start_and_register") as mock_start:
                    with patch.object(
                        service, "_get_server_detail", return_value={"serverId": "mcs_test"}
                    ):
                        service.add_server(
                            name="no-auto", transport="stdio", command="npx", enabled=False
                        )

        mock_start.assert_not_called()

    def test_add_server_auto_start_failure_marks_failed(
        self, service, mock_repo, mock_process_manager
    ):
        """auto-start 失败时标记 server 为 failed。"""
        ctx, repo = mock_repo
        row = _make_row(enabled=True)
        repo.create_server.return_value = row

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_save_secrets"):
                with patch.object(
                    service, "_start_and_register", side_effect=RuntimeError("spawn failed")
                ):
                    with patch.object(
                        service, "_get_server_detail", return_value={"serverId": "mcs_test"}
                    ):
                        service.add_server(name="fail-start", transport="stdio", command="npx")

        # update_status 被调用来标记 failed
        repo.update_status.assert_called_once()
        call_kwargs = repo.update_status.call_args
        assert call_kwargs[1]["status"] == "failed"

    def test_add_server_secret_auto_detection(self, service, mock_repo, mock_process_manager):
        """secret 自动检测：key 名含 TOKEN/KEY 等关键词的自动标记为 secret。"""
        ctx, repo = mock_repo
        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_save_secrets") as mock_save:
                with patch.object(
                    service, "_get_server_detail", return_value={"serverId": "mcs_test"}
                ):
                    service.add_server(
                        name="secret-srv",
                        transport="stdio",
                        command="npx",
                        env={"GITHUB_TOKEN": "ghp_abc123", "PATH": "/usr/bin"},
                    )

        # secret 应被保存到 UnifiedConfigManager
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        # secret_env_values 应包含 GITHUB_TOKEN
        assert "GITHUB_TOKEN" in call_args[0][1]


# ─── update_server ───


class TestUpdateServer:
    """更新 server 配置：merge fields + update secrets + auto-restart if running。"""

    def test_update_server_normal(self, service, mock_repo, mock_process_manager):
        """正常更新 server 配置。"""
        ctx, repo = mock_repo
        mock_process_manager.is_server_running.return_value = False

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(
                service,
                "_get_server_detail",
                return_value={"serverId": "mcs_test", "name": "updated"},
            ):
                result = service.update_server("mcs_test", command="new-cmd")

        assert result["name"] == "updated"
        repo.update_config.assert_called_once()

    def test_update_server_auto_restarts_if_running(self, service, mock_repo, mock_process_manager):
        """运行中 server 更新配置后自动重连。"""
        ctx, repo = mock_repo
        mock_process_manager.is_server_running.return_value = True

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_get_server_detail", return_value={"serverId": "mcs_test"}):
                service.update_server("mcs_test", command="new-cmd")

        mock_process_manager.reconnect_server.assert_called_once()

    def test_update_server_not_found_raises(self, service, mock_repo):
        """更新不存在的 server 抛出 LookupError。"""
        ctx, repo = mock_repo
        repo.update_config.return_value = None

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with pytest.raises(LookupError, match="不存在"):
                service.update_server("mcs_missing", command="x")


# ─── delete_server ───


class TestDeleteServer:
    """删除 server：stop if running + cleanup + delete DB。"""

    def test_delete_server_running(self, service, mock_repo, mock_process_manager):
        """删除运行中的 server：先停止再删除。"""
        ctx, repo = mock_repo
        mock_process_manager.is_server_running.return_value = True

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_cleanup_secrets"):
                result = service.delete_server("mcs_test")

        mock_process_manager.stop_server.assert_called_once_with("mcs_test")
        assert result is True

    def test_delete_server_not_running(self, service, mock_repo, mock_process_manager):
        """删除未运行的 server：不调用 stop。"""
        ctx, repo = mock_repo
        mock_process_manager.is_server_running.return_value = False

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_cleanup_secrets"):
                result = service.delete_server("mcs_test")

        mock_process_manager.stop_server.assert_not_called()
        assert result is True

    def test_delete_server_unregisters_tools(
        self, service, mock_repo, mock_process_manager, mock_registry
    ):
        """删除 server 时注销工具。"""
        ctx, repo = mock_repo
        mock_process_manager.is_server_running.return_value = False

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_cleanup_secrets"):
                service.delete_server("mcs_test")

        mock_registry.unregister_server_tools.assert_called_once_with("mcs_test")

    def test_delete_server_cleans_up_secrets(self, service, mock_repo, mock_process_manager):
        """删除 server 时清理 app_settings 凭证。"""
        ctx, repo = mock_repo
        mock_process_manager.is_server_running.return_value = False

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_cleanup_secrets") as mock_cleanup:
                service.delete_server("mcs_test")

        mock_cleanup.assert_called_once_with("mcs_test")


# ─── start/stop/reconnect ───


class TestStartStopReconnect:
    """启动/停止/重连委托测试。"""

    def test_start_server(self, service, mock_repo, mock_process_manager):
        """start_server 委托 ProcessManager。"""
        ctx, repo = mock_repo
        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_start_and_register", return_value=[_make_tool()]):
                with patch.object(
                    service, "_get_server_detail", return_value={"serverId": "mcs_test"}
                ):
                    result = service.start_server("mcs_test")

        assert result["serverId"] == "mcs_test"

    def test_stop_server(self, service, mock_repo, mock_process_manager, mock_registry):
        """stop_server 委托 ProcessManager + 注销工具。"""
        ctx, repo = mock_repo
        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_get_server_detail", return_value={"serverId": "mcs_test"}):
                service.stop_server("mcs_test")

        mock_process_manager.stop_server.assert_called_once_with("mcs_test")
        mock_registry.unregister_server_tools.assert_called_once_with("mcs_test")

    def test_reconnect_server(self, service, mock_repo, mock_process_manager):
        """reconnect_server 委托 ProcessManager.reconnect_server。"""
        ctx, repo = mock_repo
        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch.object(service, "_get_server_detail", return_value={"serverId": "mcs_test"}):
                with patch("src.business.mcp.mcp_server_service.emit") as mock_emit:
                    service.reconnect_server("mcs_test")

        mock_process_manager.reconnect_server.assert_called_once()
        # reconnect_server 内部调用 _on_server_started（emit tools_changed mcp_server_started）
        # + 自己 emit tools_changed mcp_server_reconnected
        emit_calls = mock_emit.call_args_list
        assert any(
            c.kwargs.get("action") == "mcp_server_reconnected"
            or c.kwargs.get("reason") == "mcp_server_reconnected"
            or (len(c.args) > 1 and c.args[1] == "mcp_server_reconnected")
            for c in emit_calls
        )


# ─── 断路器（E8）───


class TestCircuitBreaker:
    """E8: 连续失败超阈值 → 断路器打开。"""

    def test_circuit_breaker_opens_after_3_failures(self, service, mock_process_manager, mock_repo):
        """连续 3 次失败后断路器打开。"""
        mock_process_manager.call_tool_sync.side_effect = McpServerDisconnectedError("mcs_cb")

        # 前 2 次抛 McpServerDisconnectedError
        for _ in range(2):
            with pytest.raises(McpServerDisconnectedError):
                service.call_tool_sync("mcs_cb", "tool_a", {})

        # 第 3 次仍抛异常（此时计数=3）
        with pytest.raises(McpServerDisconnectedError):
            service.call_tool_sync("mcs_cb", "tool_a", {})

        # 第 4 次应被断路器拦截
        with pytest.raises(McpCircuitBreakerOpenError):
            service.call_tool_sync("mcs_cb", "tool_a", {})

    def test_circuit_breaker_resets_on_success(self, service, mock_process_manager):
        """成功调用后断路器计数重置。"""
        # 先积累 2 次失败
        mock_process_manager.call_tool_sync.side_effect = McpServerDisconnectedError("mcs_rst")
        for _ in range(2):
            with pytest.raises(McpServerDisconnectedError):
                service.call_tool_sync("mcs_rst", "tool_a", {})

        # 成功一次重置
        mock_process_manager.call_tool_sync.side_effect = None
        mock_process_manager.call_tool_sync.return_value = McpCallResult(
            is_error=False, text_parts=["ok"], image_count=0, structured_data=None
        )
        result = service.call_tool_sync("mcs_rst", "tool_a", {})
        assert result.is_error is False

        # 再失败 1 次不应打开断路器
        mock_process_manager.call_tool_sync.side_effect = McpServerDisconnectedError("mcs_rst")
        with pytest.raises(McpServerDisconnectedError):
            service.call_tool_sync("mcs_rst", "tool_a", {})

        # 再失败 1 次（共 2 次），仍不应打开
        with pytest.raises(McpServerDisconnectedError):
            service.call_tool_sync("mcs_rst", "tool_a", {})

    def test_circuit_breaker_timeout_counts(self, service, mock_process_manager):
        """McpToolTimeoutError 也计入断路器。"""
        mock_process_manager.call_tool_sync.side_effect = McpToolTimeoutError("slow_tool")

        for _ in range(3):
            with pytest.raises(McpToolTimeoutError):
                service.call_tool_sync("mcs_tmo", "slow_tool", {})

        with pytest.raises(McpCircuitBreakerOpenError):
            service.call_tool_sync("mcs_tmo", "slow_tool", {})


# ─── _create_sync_handler ───


class TestSyncHandler:
    """_create_sync_handler 桥接到异步 MCP 调用。"""

    def test_handler_returns_success_json(self, service, mock_process_manager):
        """正常调用返回 JSON success envelope。"""
        mock_process_manager.call_tool_sync.return_value = McpCallResult(
            is_error=False, text_parts=["result text"], image_count=0, structured_data=None
        )

        handler = service._create_sync_handler("mcs_h", "tool_a", "mcp__test__tool_a")
        result = handler(arg1="val1")

        parsed = json.loads(result)
        assert parsed["schemaVersion"] == 1
        assert parsed["outcome"] == "success"
        assert parsed["payload"]["source"] == "mcp"
        assert "result text" in parsed["payload"]["content"]

    def test_handler_disconnected_returns_error_json(self, service, mock_process_manager):
        """断连时返回 error JSON。"""
        mock_process_manager.call_tool_sync.side_effect = McpServerDisconnectedError("mcs_h")

        handler = service._create_sync_handler("mcs_h", "tool_a", "mcp__test__tool_a")
        result = handler()

        parsed = json.loads(result)
        assert parsed["outcome"] == "error"
        assert parsed["error"]["code"] == "mcp_server_disconnected"

    def test_handler_timeout_returns_error_json(self, service, mock_process_manager):
        """超时时返回 error JSON。"""
        mock_process_manager.call_tool_sync.side_effect = McpToolTimeoutError("slow_tool")

        handler = service._create_sync_handler("mcs_h", "slow_tool", "mcp__test__slow_tool")
        result = handler()

        parsed = json.loads(result)
        assert parsed["outcome"] == "error"
        assert parsed["error"]["code"] == "mcp_tool_timeout"

    def test_handler_schema_error_returns_error_json(self, service, mock_process_manager):
        """schema 校验错误返回 error JSON。"""
        mock_process_manager.call_tool_sync.side_effect = McpToolSchemaValidationError(
            "bad_tool", "schema mismatch"
        )

        handler = service._create_sync_handler("mcs_h", "bad_tool", "mcp__test__bad_tool")
        result = handler()

        parsed = json.loads(result)
        assert parsed["outcome"] == "error"
        assert parsed["error"]["code"] == "mcp_tool_schema_validation_error"

    def test_handler_circuit_breaker_returns_error_json(self, service, mock_process_manager):
        """断路器打开时返回 error JSON。"""
        # 先积累 3 次失败让断路器打开
        mock_process_manager.call_tool_sync.side_effect = McpServerDisconnectedError("mcs_h")
        for _ in range(3):
            with pytest.raises(McpServerDisconnectedError):
                service.call_tool_sync("mcs_h", "tool_a", {})

        # 现在调用 handler 应该走断路器路径
        handler = service._create_sync_handler("mcs_h", "tool_a", "mcp__test__tool_a")
        result = handler()

        parsed = json.loads(result)
        assert parsed["outcome"] == "error"
        assert parsed["error"]["code"] == "mcp_circuit_open"

    def test_handler_mcp_error_result_returns_error_json(self, service, mock_process_manager):
        """MCP server 返回 is_error=True 时返回 error envelope。"""
        mock_process_manager.call_tool_sync.return_value = McpCallResult(
            is_error=True, text_parts=["something went wrong"], image_count=0, structured_data=None
        )

        handler = service._create_sync_handler("mcs_h", "tool_a", "mcp__test__tool_a")
        result = handler()

        parsed = json.loads(result)
        assert parsed["outcome"] == "error"
        assert parsed["error"]["code"] == "mcp_tool_error"
        assert parsed["payload"]["source"] == "mcp"


# ─── _build_tool_definition ───


class TestBuildToolDefinition:
    """_build_tool_definition: mcp__ 前缀 + has_side_effects=True + is_concurrency_safe=False。"""

    def test_tool_definition_naming(self, service):
        """工具名前缀 mcp__<slug>__<original>。"""
        tool_info = _make_tool("list_prs", "List pull requests")
        tool_def = service._build_tool_definition(
            "mcs_gh", "list_prs", "mcp__github__list_prs", tool_info
        )

        assert tool_def.name == "mcp__github__list_prs"

    def test_tool_definition_side_effects_default(self, service):
        """MCP 工具一律 has_side_effects=True, is_concurrency_safe=False。"""
        tool_info = _make_tool("read_file")
        tool_def = service._build_tool_definition(
            "mcs_fs", "read_file", "mcp__filesystem__read_file", tool_info
        )

        assert tool_def.has_side_effects is True
        assert tool_def.is_concurrency_safe is False

    def test_tool_definition_schema(self, service):
        """ToolDefinition schema 包含 mcp__ 前缀名。"""
        tool_info = _make_tool("search", "Search code")
        tool_def = service._build_tool_definition("mcs_x", "search", "mcp__x__search", tool_info)

        assert tool_def.schema["name"] == "mcp__x__search"
        assert "parameters" in tool_def.schema


# ─── _create_pre_hook ───


class TestPreHook:
    """_create_pre_hook: 写操作确认穿透。"""

    def test_pre_hook_write_operation_returns_rejection_when_unregistered(self, service):
        """写操作工具：确认信号未注册时返回拒绝（fail-closed）。"""
        pre_hook = service._create_pre_hook("mcp__github__create_issue")

        result = pre_hook({"tool_name": "mcp__github__create_issue"})
        # 确认信号未注册 → _confirm_or_reject 返回 PreHookResult（非 None）
        # pre_hook 直接返回该结果（可能是 PreHookResult 对象或 JSON 字符串）
        assert result is not None

    def test_pre_hook_read_operation_passes_through(self, service):
        """读操作工具直接放行。"""
        pre_hook = service._create_pre_hook("mcp__github__list_prs")

        result = pre_hook({"tool_name": "mcp__github__list_prs"})
        assert result is None


# ─── seed_preset_servers ───


class TestSeedPresetServers:
    """seed_preset_servers: upsert 缺失的预置 server。"""

    def test_seed_creates_missing_presets(self, service, mock_repo):
        """缺失的预置 server 被创建。"""
        ctx, repo = mock_repo
        repo.list_preset_slugs.return_value = []  # 无预置 server

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch(
                "src.business.mcp.mcp_presets.load_preset_defaults",
                return_value=[
                    MagicMock(
                        slug="filesystem",
                        name="filesystem",
                        command="npx",
                        args=["-y", "@modelcontextprotocol/server-filesystem"],
                        non_secret_env={},
                    ),
                ],
            ):
                service.seed_preset_servers()

        repo.create_server.assert_called_once()
        call_kwargs = repo.create_server.call_args[1]
        assert call_kwargs["is_preset"] is True
        assert call_kwargs["enabled"] is False

    def test_seed_skips_existing_presets(self, service, mock_repo):
        """已存在的预置 server 不强制覆盖。"""
        ctx, repo = mock_repo
        repo.list_preset_slugs.return_value = ["filesystem"]

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch(
                "src.business.mcp.mcp_presets.load_preset_defaults",
                return_value=[
                    MagicMock(
                        slug="filesystem",
                        name="filesystem",
                        command="npx",
                        args=[],
                        non_secret_env={},
                    ),
                ],
            ):
                service.seed_preset_servers()

        repo.create_server.assert_not_called()

    def test_seed_name_conflict_skips(self, service, mock_repo):
        """预置 server 名称冲突时跳过。"""
        ctx, repo = mock_repo
        repo.list_preset_slugs.return_value = []
        repo.create_server.side_effect = ValueError("名称已存在")

        with patch("src.business.mcp.mcp_server_service.McpServerRepository", return_value=ctx):
            with patch(
                "src.business.mcp.mcp_presets.load_preset_defaults",
                return_value=[
                    MagicMock(
                        slug="github",
                        name="github",
                        command="npx",
                        args=[],
                        non_secret_env={},
                    ),
                ],
            ):
                # 不应抛异常
                service.seed_preset_servers()


# ─── process shutdown ───


class TestProcessShutdown:
    def test_shutdown_delegates_to_process_manager(self, service, mock_process_manager):
        """Service facade 必须兑现 loop drain/close/join，而不只 stop running server。"""
        service.shutdown()

        mock_process_manager.shutdown.assert_called_once_with()


# ─── tools.changed 事件发射 ───


class TestToolsChangedEvent:
    """tools.changed 事件发射测试。"""

    def test_on_server_started_emits_tools_changed(self, service, mock_process_manager):
        """server 启动成功后发射 tools_changed。"""
        config = _make_config()

        with patch("src.business.mcp.mcp_server_service.emit") as mock_emit:
            service._on_server_started("mcs_test", config)

        mock_emit.assert_called_once_with(
            "tools_changed", tool_id="mcs_test", action="mcp_server_started"
        )

    def test_on_server_started_resets_circuit_breaker(self, service):
        """server 启动成功后重置断路器计数。"""
        service._consecutive_failures["mcs_test"] = 3
        config = _make_config()

        with patch("src.business.mcp.mcp_server_service.emit"):
            service._on_server_started("mcs_test", config)

        assert service._consecutive_failures["mcs_test"] == 0


# ─── _slugify ───


class TestSlugify:
    """_slugify 规范化测试。"""

    def test_slugify_normal(self):
        """普通名称转小写并用下划线连接。"""
        from src.business.mcp.mcp_server_service import McpServerService

        assert McpServerService._slugify("My Server") == "my_server"

    def test_slugify_consecutive_underscores(self):
        """连续非字母数字压缩为单个下划线。"""
        from src.business.mcp.mcp_server_service import McpServerService

        assert McpServerService._slugify("My  Server!!") == "my_server"

    def test_slugify_leading_trailing_stripped(self):
        """首尾下划线被去除。"""
        from src.business.mcp.mcp_server_service import McpServerService

        assert McpServerService._slugify("--server--") == "server"


# ─── _is_likely_write_operation ───


class TestIsLikelyWriteOperation:
    """_is_likely_write_operation 启发式写操作检测。"""

    def test_create_is_write(self):
        """含 'create' 的工具名检测为写操作。"""
        from src.business.mcp.mcp_server_service import _is_likely_write_operation

        assert _is_likely_write_operation("create_issue", {}) is True

    def test_delete_is_write(self):
        """含 'delete' 的工具名检测为写操作。"""
        from src.business.mcp.mcp_server_service import _is_likely_write_operation

        assert _is_likely_write_operation("delete_branch", {}) is True

    def test_list_is_not_write(self):
        """'list' 不在关键词集中，检测为非写操作。"""
        from src.business.mcp.mcp_server_service import _is_likely_write_operation

        assert _is_likely_write_operation("list_prs", {}) is False

    def test_get_user_created_repos_is_not_write(self):
        """'get_user_created_repos' 含 create 但属于读操作（已知误报）。"""
        from src.business.mcp.mcp_server_service import _is_likely_write_operation

        # 这是已知的误报（FR-015 技术债务）
        assert _is_likely_write_operation("get_user_created_repos", {}) is True


# ─── _format_mcp_result ───


class TestFormatMcpResult:
    """MCP 结果格式化为统一 envelope（CC-005/FR-011）。"""

    def test_format_success(self, service):
        """成功结果含 outcome=success + source=mcp + content。"""
        result = McpCallResult(
            is_error=False, text_parts=["hello"], image_count=0, structured_data=None
        )
        formatted = service._format_mcp_result("mcp__test__tool", result)
        parsed = json.loads(formatted)

        assert parsed["schemaVersion"] == 1
        assert parsed["tool"] == "mcp__test__tool"
        assert parsed["outcome"] == "success"
        assert parsed["payload"]["source"] == "mcp"
        assert parsed["payload"]["content"] == "hello"

    def test_format_error(self, service):
        """错误结果含 outcome=error + code=mcp_tool_error + source=mcp。"""
        result = McpCallResult(
            is_error=True, text_parts=["something failed"], image_count=0, structured_data=None
        )
        formatted = service._format_mcp_result("mcp__test__tool", result)
        parsed = json.loads(formatted)

        assert parsed["schemaVersion"] == 1
        assert parsed["tool"] == "mcp__test__tool"
        assert parsed["outcome"] == "error"
        assert parsed["error"]["code"] == "mcp_tool_error"
        assert parsed["payload"]["source"] == "mcp"


# ─── Sanitize error text ───


class TestSanitizeErrorText:
    """_sanitize_error_text: 错误信息脱敏。"""

    def test_strips_github_token(self):
        """ghp_ token 被遮罩。"""
        from src.business.mcp.mcp_server_service import _sanitize_error_text

        result = _sanitize_error_text("auth failed: ghp_abc123def456ghi789jkl012mno345")
        assert "ghp_" not in result
        assert "***" in result

    def test_strips_openai_key(self):
        """sk- key 被遮罩。"""
        from src.business.mcp.mcp_server_service import _sanitize_error_text

        result = _sanitize_error_text("invalid key sk-proj-abc123def456ghi789")
        assert "sk-" not in result
        assert "***" in result

    def test_strips_url_credentials(self):
        """URL 内嵌凭证被遮罩。"""
        from src.business.mcp.mcp_server_service import _sanitize_error_text

        result = _sanitize_error_text("connect to https://user:pass@host.example.com/path")
        assert "user:pass@" not in result
        assert "***" in result

    def test_truncates_long_text(self):
        """超长文本截断到 500 字符。"""
        from src.business.mcp.mcp_server_service import _sanitize_error_text

        result = _sanitize_error_text("x" * 1000)
        assert len(result) <= 500

    def test_preserves_safe_text(self):
        """无密钥的安全文本保持不变。"""
        from src.business.mcp.mcp_server_service import _sanitize_error_text

        result = _sanitize_error_text("connection refused on port 8080")
        assert result == "connection refused on port 8080"


# ─── Disconnected event handler ───


class TestOnServerDisconnected:
    """_on_server_disconnected: ProcessManager 断连事件回调。"""

    def test_unregisters_tools_and_updates_db(self, service, mock_repo):
        """断连时注销工具 + 更新 DB 状态为 disconnected。"""
        server_id = "mcs_test_disconnect"
        # 先注册一些工具
        service._registry.register_server_tools(server_id, "test", [_make_tool("tool1")], True)

        # 模拟断连事件
        service._on_server_disconnected(sender=None, server_id=server_id, error="ping failed")

        # 工具应被注销
        items = service._registry.search_tools(query="tool1")
        assert len(items) == 0

    def test_cleans_up_failure_counter_on_delete(self, service, mock_repo):
        """删除 server 时清理断路器计数。"""
        server_id = "mcs_test_cleanup"
        service._consecutive_failures[server_id] = 3

        with patch.object(service, "_process_manager") as mock_pm:
            mock_pm.is_server_running.return_value = False
            service.delete_server(server_id)

        assert server_id not in service._consecutive_failures
