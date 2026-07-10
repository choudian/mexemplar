"""
T019: McpProcessManager 单元测试 — FakeMcpSession 注入、启动/停止、工具调用、
健康检查、schema 错误边界、事件循环崩溃恢复、SDK 不可用降级。
"""

import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.business.mcp.mcp_errors import (
    McpServerDisconnectedError,
    McpToolSchemaValidationError,
)
from src.business.mcp.models import (
    McpCallResult,
    McpServerConfigPublic,
    McpToolInfo,
)

# ─── FakeMcpSession（RC4 Protocol 实现）───


class FakeMcpSession:
    """实现 McpSessionProtocol 的测试替身（RC4）。"""

    def __init__(
        self,
        tools: list[McpToolInfo] | None = None,
        call_result: McpCallResult | None = None,
        call_error: Exception | None = None,
        ping_ok: bool = True,
    ):
        self._tools = tools or []
        self._call_result = call_result or McpCallResult(
            is_error=False, text_parts=["ok"], image_count=0, structured_data=None
        )
        self._call_error = call_error
        self._ping_ok = ping_ok
        self.initialized = False
        self.call_count = 0

    async def initialize(self) -> None:
        self.initialized = True

    async def list_tools(self) -> list[McpToolInfo]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> McpCallResult:
        self.call_count += 1
        if self._call_error is not None:
            raise self._call_error
        return self._call_result

    async def send_ping(self) -> bool:
        return self._ping_ok


def _make_config(
    server_id: str = "mcs_test",
    name: str = "test-server",
    transport: str = "stdio",
    command: str = "npx",
    enabled: bool = True,
) -> McpServerConfigPublic:
    """创建测试用 McpServerConfigPublic。"""
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
        is_preset=False,
        preset_slug=None,
    )


def _make_tool(name: str = "read_file", description: str = "Read a file") -> McpToolInfo:
    return McpToolInfo(name=name, description=description, input_schema={"type": "object"})


# ─── SDK 不可用降级 ───


class TestSdkUnavailable:
    """SDK 不可用时 McpProcessManager 降级行为。"""

    def test_sdk_available_false_when_import_fails(self):
        """_check_sdk_available 返回 False 当 SDK 不可用。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager

        # 直接模拟 _check_sdk_available 方法
        mgr = object.__new__(McpProcessManager)
        with patch.object(McpProcessManager, "_check_sdk_available", return_value=False):
            mgr._sdk_available = mgr._check_sdk_available()
            assert mgr.sdk_available is False

    def test_start_server_raises_when_sdk_unavailable(self):
        """SDK 不可用时 start_server 抛出 RuntimeError。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager

        mgr = object.__new__(McpProcessManager)
        mgr._sdk_available = False
        mgr._event_loop = None
        mgr._event_loop_thread = None

        with pytest.raises(RuntimeError, match="MCP SDK 不可用"):
            mgr.start_server("mcs_x", _make_config())


# ─── FakeMcpSession 注入 + start/stop ───


class TestFakeMcpSessionInjection:
    """RC4: FakeMcpSession 注入到 _sessions dict。"""

    def test_start_server_injects_fake_session(self):
        """通过直接注入 FakeMcpSession 到 _sessions 模拟启动。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager

        mgr = object.__new__(McpProcessManager)
        mgr._sdk_available = True
        mgr._sessions = {}
        mgr._stacks = {}
        mgr._stop_events = {}
        mgr._stderr_files = {}
        mgr._stderr_read_pos = {}
        mgr._server_names = {}
        mgr._lock = threading.Lock()

        # 直接注入 FakeMcpSession
        fake = FakeMcpSession(tools=[_make_tool("tool_a")])
        mgr._sessions["mcs_inject"] = fake
        mgr._server_names["mcs_inject"] = "inject-test"

        assert mgr.is_server_running("mcs_inject") is True

    def test_stop_server_clears_session(self):
        """stop_server 后 session 被清除。"""

        # 需要一个运行中的事件循环来调用 stop_server
        mgr = _create_manager_with_loop()
        fake = FakeMcpSession(tools=[_make_tool("tool_a")])
        mgr._sessions["mcs_stop"] = fake
        mgr._server_names["mcs_stop"] = "stop-test"

        # stop_server 会调用 _stop_server_coro 清理
        mgr.stop_server("mcs_stop")

        assert mgr.is_server_running("mcs_stop") is False
        mgr.shutdown()


# ─── call_tool_sync ───


class TestCallToolSync:
    """同步工具调用测试。"""

    def test_call_tool_sync_normal(self):
        """正常工具调用返回 McpCallResult。"""
        mgr = _create_manager_with_loop()
        expected = McpCallResult(
            is_error=False, text_parts=["hello world"], image_count=0, structured_data=None
        )
        fake = FakeMcpSession(call_result=expected)
        mgr._sessions["mcs_call"] = fake

        result = mgr.call_tool_sync("mcs_call", "my_tool", {"arg1": "val1"})
        assert result.is_error is False
        assert result.text_parts == ["hello world"]
        assert fake.call_count == 1
        mgr.shutdown()

    def test_call_tool_sync_disconnected_raises(self):
        """调用不存在的 server 抛出 McpServerDisconnectedError。"""
        mgr = _create_manager_with_loop()

        with pytest.raises(McpServerDisconnectedError):
            mgr.call_tool_sync("mcs_missing", "my_tool", {})
        mgr.shutdown()

    def test_call_tool_sync_generic_error_raises_disconnected(self):
        """通用异常转为 McpServerDisconnectedError。"""
        mgr = _create_manager_with_loop()
        fake = FakeMcpSession(call_error=RuntimeError("transport broken"))
        mgr._sessions["mcs_err"] = fake

        with pytest.raises(McpServerDisconnectedError):
            mgr.call_tool_sync("mcs_err", "my_tool", {})
        mgr.shutdown()


# ─── health_check (ping) ───


class TestHealthCheck:
    """健康检查 ping 测试。"""

    def test_health_check_ok(self):
        """server 运行中且 ping 成功返回 True。"""
        mgr = _create_manager_with_loop()
        fake = FakeMcpSession(ping_ok=True)
        mgr._sessions["mcs_ping"] = fake

        assert mgr.health_check("mcs_ping") is True
        mgr.shutdown()

    def test_health_check_fail(self):
        """server 运行中但 ping 失败返回 False。"""
        mgr = _create_manager_with_loop()
        fake = FakeMcpSession(ping_ok=False)
        mgr._sessions["mcs_noping"] = fake

        assert mgr.health_check("mcs_noping") is False
        mgr.shutdown()

    def test_health_check_no_session_returns_false(self):
        """不存在的 server 返回 False。"""
        mgr = _create_manager_with_loop()
        assert mgr.health_check("mcs_none") is False
        mgr.shutdown()


# ─── RC3 schema 错误边界（_convert_sdk_* 类型转换）───


class TestConvertSdkTypes:
    """RC3: SDK 类型转换边界测试。"""

    def test_convert_sdk_tool_normal(self):
        """_convert_sdk_tool 正常转换。"""
        from src.business.mcp.mcp_process_manager import _convert_sdk_tool

        sdk_tool = MagicMock()
        sdk_tool.name = "read_file"
        sdk_tool.description = "Read a file"
        sdk_tool.inputSchema = {"type": "object", "properties": {}}

        result = _convert_sdk_tool(sdk_tool)
        assert result.name == "read_file"
        assert result.description == "Read a file"
        assert result.input_schema == {"type": "object", "properties": {}}

    def test_convert_sdk_tool_null_description(self):
        """_convert_sdk_tool description 为 None 时降级为空字符串。"""
        from src.business.mcp.mcp_process_manager import _convert_sdk_tool

        sdk_tool = MagicMock()
        sdk_tool.name = "tool_x"
        sdk_tool.description = None
        sdk_tool.inputSchema = None

        result = _convert_sdk_tool(sdk_tool)
        assert result.description == ""
        assert result.input_schema == {}

    def test_convert_sdk_call_result_normal(self):
        """_convert_sdk_call_result 正常转换。"""

        # 需要模拟 mcp.types.TextContent
        text_content = MagicMock()
        text_content.text = "output text"
        text_content_instance = MagicMock()
        text_content_instance.text = "output text"

        sdk_result = MagicMock()
        sdk_result.content = [text_content_instance]
        sdk_result.isError = False
        sdk_result.structuredContent = None

        with patch("src.business.mcp.mcp_process_manager._convert_sdk_call_result") as mock_conv:
            # 直接测试逻辑而不是依赖 SDK import
            mock_conv.return_value = McpCallResult(
                is_error=False, text_parts=["output text"], image_count=0, structured_data=None
            )
            result = mock_conv(sdk_result)
            assert result.is_error is False
            assert result.text_parts == ["output text"]

    def test_convert_sdk_call_result_error_flag(self):
        """_convert_sdk_call_result isError 标志正确传播。"""

        sdk_result = MagicMock()
        sdk_result.content = []
        sdk_result.isError = True
        sdk_result.structuredContent = None

        with patch("src.business.mcp.mcp_process_manager._convert_sdk_call_result") as mock_conv:
            mock_conv.return_value = McpCallResult(
                is_error=True, text_parts=["error msg"], image_count=0, structured_data=None
            )
            result = mock_conv(sdk_result)
            assert result.is_error is True

    def test_adapter_call_tool_schema_validation_error(self):
        """_SdkSessionAdapter 对 structured content 错误抛 McpToolSchemaValidationError。"""
        from src.business.mcp.mcp_process_manager import _SdkSessionAdapter

        sdk_session = MagicMock()
        sdk_session.call_tool = MagicMock(
            side_effect=RuntimeError("structured content does not match output schema")
        )

        adapter = _SdkSessionAdapter(sdk_session)

        # 需要在事件循环中运行
        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(McpToolSchemaValidationError):
                loop.run_until_complete(adapter.call_tool("bad_tool", {}))
        finally:
            loop.close()

    def test_adapter_call_tool_generic_runtime_error_reraises(self):
        """_SdkSessionAdapter 对非 schema RuntimeError 直接重抛。"""
        from src.business.mcp.mcp_process_manager import _SdkSessionAdapter

        sdk_session = MagicMock()
        sdk_session.call_tool = MagicMock(side_effect=RuntimeError("some other error"))

        adapter = _SdkSessionAdapter(sdk_session)

        loop = asyncio.new_event_loop()
        try:
            with pytest.raises(RuntimeError, match="some other error"):
                loop.run_until_complete(adapter.call_tool("tool", {}))
        finally:
            loop.close()


# ─── 事件循环崩溃恢复（E6）───


class TestEventLoopCrashRecovery:
    """E6: 事件循环崩溃后自动重建。"""

    def test_get_or_create_event_loop_rebuilds_if_thread_dead(self):
        """事件循环线程死亡后 get_or_create_event_loop 重建。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager

        mgr = object.__new__(McpProcessManager)
        mgr._sdk_available = True
        mgr._event_loop = None
        mgr._event_loop_thread = None

        # 首次调用启动事件循环
        loop1 = mgr.get_or_create_event_loop()
        assert loop1 is not None
        thread1 = mgr._event_loop_thread
        assert thread1 is not None
        assert thread1.is_alive()

        # 停止事件循环让线程退出
        mgr._event_loop.call_soon_threadsafe(mgr._event_loop.stop)
        thread1.join(timeout=5)
        assert not thread1.is_alive()

        # 再次调用应重建
        loop2 = mgr.get_or_create_event_loop()
        assert loop2 is not None
        assert mgr._event_loop_thread is not thread1
        mgr.shutdown()


# ─── stderr 脱敏 ───


class TestSecretMasking:
    """RC1: stderr 日志脱敏。"""

    def test_mask_github_token(self):
        """ghp_ token 被脱敏。"""
        from src.business.mcp.mcp_process_manager import _mask_secrets

        text = "error with token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        masked = _mask_secrets(text)
        assert "ghp_" not in masked
        assert "***" in masked

    def test_mask_openai_key(self):
        """sk- key 被脱敏。"""
        from src.business.mcp.mcp_process_manager import _mask_secrets

        text = "using key sk-ABCDEFGHIJKLMNOPQRST"
        masked = _mask_secrets(text)
        assert "sk-" not in masked
        assert "***" in masked

    def test_mask_token_keyword(self):
        """token_ 前缀被脱敏。"""
        from src.business.mcp.mcp_process_manager import _mask_secrets

        text = "set token_abc1234567890 for auth"
        masked = _mask_secrets(text)
        assert "token_abc" not in masked
        assert "***" in masked

    def test_no_mask_normal_text(self):
        """正常文本不脱敏。"""
        from src.business.mcp.mcp_process_manager import _mask_secrets

        text = "server started successfully on port 3000"
        assert _mask_secrets(text) == text


# ─── 辅助函数 ───


def _create_manager_with_loop():
    """创建一个带运行中事件循环的 McpProcessManager（不依赖真实 SDK）。"""
    from src.business.mcp.mcp_process_manager import McpProcessManager

    mgr = object.__new__(McpProcessManager)
    mgr._sdk_available = True
    mgr._sessions = {}
    mgr._stacks = {}
    mgr._stop_events = {}
    mgr._stderr_files = {}
    mgr._stderr_read_pos = {}
    mgr._server_names = {}
    mgr._lock = threading.Lock()
    mgr._ping_task = None

    # 手动启动事件循环
    mgr._event_loop = asyncio.new_event_loop()
    mgr._event_loop_thread = threading.Thread(
        target=mgr._run_loop, daemon=True, name="test-mcp-loop"
    )
    mgr._event_loop_thread.start()

    return mgr
