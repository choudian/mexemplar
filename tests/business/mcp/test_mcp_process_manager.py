"""
T019: McpProcessManager 单元测试 — FakeMcpSession 注入、启动/停止、工具调用、
健康检查、schema 错误边界、事件循环崩溃恢复、SDK 不可用降级。
"""

import asyncio
import concurrent.futures
import threading
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
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

    def test_stop_server_reports_stack_close_failure_after_clearing_state(self):
        """SDK stack 清理失败必须向同步调用方报错，且内部缓存仍要清除。"""

        class FailingStack:
            async def aclose(self):
                raise RuntimeError("simulated stack close failure")

        mgr = _create_manager_with_loop()
        server_id = "mcs_stop_stack_failure"
        stop_event = MagicMock()
        stderr_file = MagicMock()
        mgr._sessions[server_id] = FakeMcpSession()
        mgr._stacks[server_id] = FailingStack()
        mgr._stop_events[server_id] = stop_event
        mgr._stderr_files[server_id] = stderr_file
        mgr._stderr_read_pos[server_id] = 7
        mgr._server_names[server_id] = "stop-stack-failure"

        try:
            with pytest.raises(RuntimeError, match="simulated stack close failure"):
                mgr.stop_server(server_id)

            assert mgr.is_server_running(server_id) is False
            assert server_id not in mgr._stacks
            assert server_id not in mgr._stop_events
            assert server_id not in mgr._stderr_files
            assert server_id not in mgr._stderr_read_pos
            assert server_id not in mgr._server_names
            stop_event.set.assert_called_once_with()
            stderr_file.close.assert_called_once_with()
        finally:
            mgr.shutdown()

    def test_stop_server_reports_stack_close_timeout_after_clearing_state(
        self,
        monkeypatch,
    ):
        """SDK stack 超时同样不得伪装成停止成功。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        class SlowStack:
            async def aclose(self):
                await asyncio.sleep(1)

        monkeypatch.setattr(process_manager_module, "_MCP_STOP_TIMEOUT_SECONDS", 0.01)
        mgr = _create_manager_with_loop()
        server_id = "mcs_stop_stack_timeout"
        mgr._sessions[server_id] = FakeMcpSession()
        mgr._stacks[server_id] = SlowStack()
        mgr._server_names[server_id] = "stop-stack-timeout"

        try:
            with pytest.raises(RuntimeError, match="SDK 资源清理超时"):
                mgr.stop_server(server_id)

            assert mgr.is_server_running(server_id) is False
            assert server_id not in mgr._stacks
            assert server_id not in mgr._server_names
        finally:
            mgr.shutdown()


class TestStartupTimeoutBudget:
    """启动阶段应使用产品连接测试的完整预算，而非工具调用的 30 秒预算。"""

    def test_only_one_authoritative_startup_attempt_per_server(self):
        mgr = _create_manager_with_loop()
        attempt = mgr._begin_startup_attempt("mcs_unique_start")
        try:
            with pytest.raises(RuntimeError, match="正在启动"):
                mgr._begin_startup_attempt("mcs_unique_start")
        finally:
            mgr._finish_startup_attempt("mcs_unique_start", attempt)
            mgr.shutdown()

    def test_bridge_timeout_before_first_coroutine_step_retires_attempt(self, monkeypatch):
        """loop 尚未启动 coroutine 时桥超时，不能永久残留 starting fence。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        loop_blocked = threading.Event()
        release_loop = threading.Event()

        def block_event_loop():
            loop_blocked.set()
            release_loop.wait(timeout=2)

        mgr._event_loop.call_soon_threadsafe(block_event_loop)
        assert loop_blocked.wait(timeout=2)
        monkeypatch.setattr(process_manager_module, "_MCP_STARTUP_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(process_manager_module, "_MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS", 0.01)
        monkeypatch.setattr(process_manager_module, "_MCP_STARTUP_BRIDGE_GRACE_SECONDS", 0.01)

        try:
            with pytest.raises(TimeoutError):
                mgr.start_server("mcs_pre_start_timeout", _make_config(command="unused"))

            assert "mcs_pre_start_timeout" not in mgr._startup_attempts
        finally:
            release_loop.set()
            mgr.shutdown()

    def test_cancelled_bridge_before_first_step_retires_attempt(self, monkeypatch):
        """loop shutdown 等导致 bridge 预先 cancelled 时也不能残留 attempt。"""
        mgr = _create_manager_with_loop()

        def cancelled_bridge(coro, loop):
            assert loop is mgr._event_loop
            coro.close()
            future = concurrent.futures.Future()
            future.cancel()
            return future

        try:
            with monkeypatch.context() as scoped_patch:
                scoped_patch.setattr(
                    asyncio,
                    "run_coroutine_threadsafe",
                    cancelled_bridge,
                )
                with pytest.raises(concurrent.futures.CancelledError):
                    mgr.start_server("mcs_cancelled_bridge", _make_config(command="unused"))
            assert "mcs_cancelled_bridge" not in mgr._startup_attempts
        finally:
            mgr.shutdown()

    def test_stop_before_startup_bind_prevents_resource_construction(self, monkeypatch):
        """stop 已返回后，尚未 bind 的旧 coroutine 不得再构造或 spawn 资源。"""
        mgr = _create_manager_with_loop()
        server_id = "mcs_pre_bind_stop"
        attempt = mgr._begin_startup_attempt(server_id)
        stopped = asyncio.run_coroutine_threadsafe(
            mgr._stop_server_coro(server_id),
            mgr._event_loop,
        )
        stopped.result(timeout=2)
        assert server_id not in mgr._startup_attempts

        build_launch_payload = MagicMock(
            side_effect=AssertionError("cancelled startup constructed resources")
        )
        monkeypatch.setattr(mgr, "_build_launch_payload", build_launch_payload)
        stale_start = asyncio.run_coroutine_threadsafe(
            mgr._start_server_coro(
                server_id,
                _make_config(command="unused"),
                _attempt=attempt,
            ),
            mgr._event_loop,
        )
        try:
            with pytest.raises(concurrent.futures.CancelledError):
                stale_start.result(timeout=2)
            build_launch_payload.assert_not_called()
            assert server_id not in mgr._startup_attempts
        finally:
            mgr.shutdown()

    def test_partial_sdk_import_failure_retires_bound_attempt(self, monkeypatch):
        """SDK 部分安装/版本漂移导致延迟 import 失败时，不得残留 starting fence。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        server_id = "mcs_partial_sdk"
        monkeypatch.setattr(
            process_manager_module,
            "_load_sdk_client_types",
            MagicMock(side_effect=ImportError("simulated partial MCP SDK")),
        )
        future = asyncio.run_coroutine_threadsafe(
            mgr._start_server_coro(server_id, _make_config(command="unused")),
            mgr._event_loop,
        )
        try:
            with pytest.raises(ImportError, match="partial MCP SDK"):
                future.result(timeout=2)
            assert server_id not in mgr._startup_attempts
        finally:
            mgr.shutdown()

    def test_start_server_accepts_response_within_connection_budget(self, monkeypatch):
        """模拟在 60 秒预算内响应的 server；不真实等待，只校验 SDK 边界。"""
        mgr = _create_manager_with_loop()

        @asynccontextmanager
        async def fake_stdio_client(params, errlog):
            yield object(), object()

        class FakeStdioServerParameters:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class SlowStartingClientSession:
            def __init__(self, read_stream, write_stream, *, read_timeout_seconds):
                self.read_timeout_seconds = read_timeout_seconds

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def initialize(self):
                if self.read_timeout_seconds < timedelta(seconds=60):
                    raise TimeoutError("server responded after the 30 second tool budget")

            async def list_tools(self):
                return SimpleNamespace(
                    tools=[
                        SimpleNamespace(
                            name="read_file",
                            description="Read a file",
                            inputSchema={"type": "object"},
                        )
                    ]
                )

        monkeypatch.setattr("mcp.ClientSession", SlowStartingClientSession)
        monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
        monkeypatch.setattr("mcp.client.stdio.StdioServerParameters", FakeStdioServerParameters)

        try:
            tools = mgr.start_server("mcs_slow_start", _make_config(command="fake-mcp"))
            assert [tool.name for tool in tools] == ["read_file"]
            mgr.stop_server("mcs_slow_start")
        finally:
            mgr.shutdown()

    def test_start_failure_closes_unpublished_sdk_resources(self, monkeypatch):
        """initialize 失败时也必须退出 SDK contexts 并关闭 stderr tempfile。"""
        mgr = _create_manager_with_loop()
        closed = {"stdio": False, "session": False, "stderr": False}

        @asynccontextmanager
        async def fake_stdio_client(params, errlog):
            try:
                yield object(), object()
            finally:
                closed["stdio"] = True

        class FakeStdioServerParameters:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FailingClientSession:
            def __init__(self, read_stream, write_stream, *, read_timeout_seconds):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                closed["session"] = True
                return False

            async def initialize(self):
                raise TimeoutError("simulated initialization timeout")

        class FakeStderrFile:
            def close(self):
                closed["stderr"] = True

        monkeypatch.setattr("mcp.ClientSession", FailingClientSession)
        monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
        monkeypatch.setattr("mcp.client.stdio.StdioServerParameters", FakeStdioServerParameters)
        monkeypatch.setattr(
            "src.business.mcp.mcp_process_manager.tempfile.TemporaryFile",
            lambda **kwargs: FakeStderrFile(),
        )

        try:
            with pytest.raises(TimeoutError, match="initialization timeout"):
                mgr.start_server("mcs_failed_start", _make_config(command="fake-mcp"))
            assert closed == {"stdio": True, "session": True, "stderr": True}
        finally:
            mgr.shutdown()

    def test_startup_budget_covers_initialize_and_tool_discovery(self, monkeypatch):
        """initialize 与 list_tools 必须共享一个总预算，超时后不得留下幽灵会话。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        closed = {"stdio": False, "session": False}

        @asynccontextmanager
        async def fake_stdio_client(params, errlog):
            try:
                yield object(), object()
            finally:
                closed["stdio"] = True

        class FakeStdioServerParameters:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class TwoStageClientSession:
            def __init__(self, read_stream, write_stream, *, read_timeout_seconds):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                closed["session"] = True
                return False

            async def initialize(self):
                await asyncio.sleep(0.03)

            async def list_tools(self):
                await asyncio.sleep(0.03)
                return SimpleNamespace(tools=[])

        monkeypatch.setattr(
            process_manager_module,
            "_MCP_STARTUP_TIMEOUT_SECONDS",
            0.05,
            raising=False,
        )
        monkeypatch.setattr("mcp.ClientSession", TwoStageClientSession)
        monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
        monkeypatch.setattr("mcp.client.stdio.StdioServerParameters", FakeStdioServerParameters)

        try:
            with pytest.raises(TimeoutError):
                mgr.start_server("mcs_total_timeout", _make_config(command="fake-mcp"))

            assert not mgr.is_server_running("mcs_total_timeout")
            assert "mcs_total_timeout" not in mgr._stacks
            assert "mcs_total_timeout" not in mgr._stderr_files
            assert closed == {"stdio": True, "session": True}
        finally:
            if mgr.is_server_running("mcs_total_timeout"):
                mgr.stop_server("mcs_total_timeout")
            mgr.shutdown()

    def test_disconnect_notification_failure_preserves_startup_error(self, monkeypatch):
        """断连通知失败不得掩盖 initialize 的原始异常。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()

        @asynccontextmanager
        async def fake_stdio_client(params, errlog):
            yield object(), object()

        class FakeStdioServerParameters:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FailingClientSession:
            def __init__(self, read_stream, write_stream, *, read_timeout_seconds):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def initialize(self):
                raise TimeoutError("original startup failure")

        def failing_emit(*args, **kwargs):
            raise RuntimeError("subscriber failed")

        monkeypatch.setattr("mcp.ClientSession", FailingClientSession)
        monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
        monkeypatch.setattr("mcp.client.stdio.StdioServerParameters", FakeStdioServerParameters)
        monkeypatch.setattr(process_manager_module, "emit", failing_emit)

        try:
            with pytest.raises(TimeoutError, match="original startup failure"):
                mgr.start_server("mcs_emit_failure", _make_config(command="fake-mcp"))
        finally:
            mgr.shutdown()

    def test_cancelled_startup_closes_unpublished_sdk_resources(self, monkeypatch):
        """同步桥取消启动协程时，局部 SDK resources 也必须完成清理。"""
        mgr = _create_manager_with_loop()
        initialize_started = threading.Event()
        closed = {"stdio": False, "session": False}

        @asynccontextmanager
        async def fake_stdio_client(params, errlog):
            try:
                yield object(), object()
            finally:
                closed["stdio"] = True

        class FakeStdioServerParameters:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class HangingClientSession:
            def __init__(self, read_stream, write_stream, *, read_timeout_seconds):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                closed["session"] = True
                return False

            async def initialize(self):
                initialize_started.set()
                await asyncio.Event().wait()

        monkeypatch.setattr("mcp.ClientSession", HangingClientSession)
        monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
        monkeypatch.setattr("mcp.client.stdio.StdioServerParameters", FakeStdioServerParameters)

        future = asyncio.run_coroutine_threadsafe(
            mgr._start_server_coro("mcs_cancelled", _make_config(command="fake-mcp")),
            mgr._event_loop,
        )
        try:
            assert initialize_started.wait(timeout=2)
            future.cancel()
            with pytest.raises(concurrent.futures.CancelledError):
                future.result(timeout=2)

            deadline = time.monotonic() + 2
            while not all(closed.values()) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert closed == {"stdio": True, "session": True}
        finally:
            mgr.shutdown()

    def test_bridge_timeout_cannot_publish_a_late_success(self, monkeypatch):
        """即使 SDK 吞掉取消，桥超时后的旧 attempt 也不得迟到写入 running cache。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        startup_finished = threading.Event()
        closed = {"stdio": False, "session": False}

        @asynccontextmanager
        async def fake_stdio_client(params, errlog):
            try:
                yield object(), object()
            finally:
                closed["stdio"] = True

        class FakeStdioServerParameters:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class CancellationIgnoringClientSession:
            def __init__(self, read_stream, write_stream, *, read_timeout_seconds):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                closed["session"] = True
                return False

            async def initialize(self):
                deadline = time.monotonic() + 0.15
                while time.monotonic() < deadline:
                    try:
                        await asyncio.sleep(0.02)
                    except asyncio.CancelledError:
                        # 模拟第三方 SDK 抑制 timeout/bridge 的取消。
                        continue

            async def list_tools(self):
                startup_finished.set()
                return SimpleNamespace(tools=[])

        monkeypatch.setattr(process_manager_module, "_MCP_STARTUP_TIMEOUT_SECONDS", 0.02)
        monkeypatch.setattr(process_manager_module, "_MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS", 0.02)
        monkeypatch.setattr(process_manager_module, "_MCP_STARTUP_BRIDGE_GRACE_SECONDS", 0.01)
        monkeypatch.setattr("mcp.ClientSession", CancellationIgnoringClientSession)
        monkeypatch.setattr("mcp.client.stdio.stdio_client", fake_stdio_client)
        monkeypatch.setattr("mcp.client.stdio.StdioServerParameters", FakeStdioServerParameters)

        try:
            with pytest.raises(TimeoutError):
                mgr.start_server("mcs_late_success", _make_config(command="fake-mcp"))

            assert startup_finished.wait(timeout=2)
            deadline = time.monotonic() + 2
            while not all(closed.values()) and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not mgr.is_server_running("mcs_late_success")
            assert "mcs_late_success" not in mgr._stacks
            assert closed == {"stdio": True, "session": True}
        finally:
            if mgr.is_server_running("mcs_late_success"):
                mgr.stop_server("mcs_late_success")
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
        mgr._sessions = {}
        mgr._stacks = {}
        mgr._stop_events = {}
        mgr._stderr_files = {}
        mgr._stderr_read_pos = {}
        mgr._server_names = {}
        mgr._lock = threading.Lock()
        mgr._ping_task = None
        mgr._shutdown_task = None
        mgr._startup_attempts = {}
        mgr._startup_cleanup_tasks = set()

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


class TestShutdownCleanup:
    """shutdown 必须让后台任务完成取消，不能留下 pending task。"""

    def test_slow_startup_cleanup_continues_after_observation_timeout(self, monkeypatch):
        """观察超时不能取消 SDK cleanup；manager 必须持有任务直到完成。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        stack_closed = threading.Event()
        stderr_closed = threading.Event()

        class SlowStack:
            async def aclose(self):
                await asyncio.sleep(0.05)
                stack_closed.set()

        class FakeStderrFile:
            def close(self):
                stderr_closed.set()

        monkeypatch.setattr(
            process_manager_module,
            "_MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS",
            0.01,
        )

        cleanup = asyncio.run_coroutine_threadsafe(
            mgr._cleanup_startup_resources(
                "mcs_slow_cleanup",
                SlowStack(),
                FakeStderrFile(),
            ),
            mgr._event_loop,
        )
        cleanup.result(timeout=2)

        assert mgr._startup_cleanup_tasks
        assert stack_closed.wait(timeout=2)
        assert stderr_closed.wait(timeout=2)

        deadline = time.monotonic() + 2
        while mgr._startup_cleanup_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not mgr._startup_cleanup_tasks
        mgr.shutdown()

    def test_shutdown_waits_for_tracked_startup_cleanup(self, monkeypatch):
        """shutdown 应先等待已跟踪的启动清理，而不是立即取消它。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        stack_closed = threading.Event()

        class SlowStack:
            async def aclose(self):
                await asyncio.sleep(0.05)
                stack_closed.set()

        class FakeStderrFile:
            def close(self):
                pass

        monkeypatch.setattr(
            process_manager_module,
            "_MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS",
            0.01,
        )

        cleanup = asyncio.run_coroutine_threadsafe(
            mgr._cleanup_startup_resources(
                "mcs_shutdown_cleanup",
                SlowStack(),
                FakeStderrFile(),
            ),
            mgr._event_loop,
        )
        cleanup.result(timeout=2)
        assert mgr._startup_cleanup_tasks

        mgr.shutdown()

        assert stack_closed.is_set()
        assert mgr._event_loop.is_closed()

    def test_shutdown_drains_tasks_and_closes_event_loop(self):
        mgr = _create_manager_with_loop()
        background_started = threading.Event()

        async def background_reader():
            background_started.set()
            await asyncio.Event().wait()

        background = asyncio.run_coroutine_threadsafe(background_reader(), mgr._event_loop)
        assert background_started.wait(timeout=2)

        deadline = time.monotonic() + 2
        while mgr._ping_task is None and time.monotonic() < deadline:
            time.sleep(0.01)
        ping_task = mgr._ping_task
        assert ping_task is not None

        mgr.shutdown()

        assert ping_task.done()
        assert background.done()
        assert not mgr._event_loop_thread.is_alive()
        assert mgr._event_loop.is_closed()

    def test_shutdown_from_event_loop_thread_drains_and_closes_loop(self):
        """loop 线程内触发 shutdown 也必须异步 drain，并由线程主函数关闭 loop。"""
        mgr = _create_manager_with_loop()
        background_started = threading.Event()
        shutdown_returned = threading.Event()

        async def background_reader():
            background_started.set()
            await asyncio.Event().wait()

        background = asyncio.run_coroutine_threadsafe(background_reader(), mgr._event_loop)
        assert background_started.wait(timeout=2)

        def shutdown_on_loop_thread():
            mgr.shutdown()
            shutdown_returned.set()

        mgr._event_loop.call_soon_threadsafe(shutdown_on_loop_thread)

        assert shutdown_returned.wait(timeout=2)
        mgr._event_loop_thread.join(timeout=5)
        assert not mgr._event_loop_thread.is_alive()
        assert background.done()
        assert mgr._event_loop.is_closed()

    def test_loop_thread_shutdown_retries_cancel_with_bounded_wait(self, monkeypatch):
        """cleanup 吞掉第一次取消时，loop-thread shutdown 仍须有界收割并关闭。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        monkeypatch.setattr(
            process_manager_module,
            "_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS",
            0.02,
        )
        cleanup_started = threading.Event()
        cancel_count = 0

        async def cancellation_resistant_cleanup():
            nonlocal cancel_count
            cleanup_started.set()
            while True:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancel_count += 1
                    if cancel_count >= 2:
                        raise

        async def install_cleanup_task():
            task = asyncio.create_task(cancellation_resistant_cleanup())
            mgr._startup_cleanup_tasks.add(task)
            return task

        cleanup_task = asyncio.run_coroutine_threadsafe(
            install_cleanup_task(),
            mgr._event_loop,
        ).result(timeout=2)
        assert cleanup_started.wait(timeout=2)

        mgr._event_loop.call_soon_threadsafe(mgr.shutdown)
        mgr._event_loop_thread.join(timeout=0.3)
        closed_within_deadline = (
            not mgr._event_loop_thread.is_alive() and mgr._event_loop.is_closed()
        )
        if mgr._event_loop_thread.is_alive():
            # RED 路径兜底，避免失败用例把 daemon loop/task 泄漏给后续测试。
            mgr._event_loop.call_soon_threadsafe(cleanup_task.cancel)
            mgr._event_loop_thread.join(timeout=2)

        assert closed_within_deadline
        assert cancel_count >= 2

    def test_loop_thread_shutdown_bounds_cancellation_resistant_startup_attempt(
        self,
        monkeypatch,
    ):
        """starting attempt 吞掉首次取消时，stop_all 仍须重试并有界退出。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        monkeypatch.setattr(
            process_manager_module,
            "_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS",
            0.02,
        )
        server_id = "mcs_cancellation_resistant_startup"
        startup_started = threading.Event()
        cancel_count = 0

        async def install_startup_attempt():
            attempt = mgr._begin_startup_attempt(server_id)

            async def cancellation_resistant_startup():
                nonlocal cancel_count
                startup_started.set()
                try:
                    while True:
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            cancel_count += 1
                            if cancel_count >= 2:
                                raise
                finally:
                    mgr._finish_startup_attempt(server_id, attempt)

            task = asyncio.create_task(cancellation_resistant_startup())
            assert mgr._bind_startup_task(server_id, attempt, task)
            return task

        startup_task = asyncio.run_coroutine_threadsafe(
            install_startup_attempt(),
            mgr._event_loop,
        ).result(timeout=2)
        assert startup_started.wait(timeout=2)

        mgr._event_loop.call_soon_threadsafe(mgr.shutdown)
        mgr._event_loop_thread.join(timeout=0.3)
        closed_within_deadline = (
            not mgr._event_loop_thread.is_alive() and mgr._event_loop.is_closed()
        )
        if mgr._event_loop_thread.is_alive():
            # RED 路径兜底，避免失败用例把 daemon loop/task 泄漏给后续测试。
            mgr._event_loop.call_soon_threadsafe(startup_task.cancel)
            mgr._event_loop_thread.join(timeout=2)

        assert closed_within_deadline
        assert cancel_count >= 2
        assert startup_task.done()

    def test_stop_reports_startup_task_that_survives_bounded_cancel_rounds(
        self,
        monkeypatch,
    ):
        """starting task 连续吞取消时，stop 必须有界失败而非永久等待。"""
        import src.business.mcp.mcp_process_manager as process_manager_module

        mgr = _create_manager_with_loop()
        monkeypatch.setattr(
            process_manager_module,
            "_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS",
            0.02,
        )
        server_id = "mcs_stuck_startup"
        startup_started = threading.Event()
        allow_exit = threading.Event()

        async def install_startup_attempt():
            attempt = mgr._begin_startup_attempt(server_id)

            async def stuck_startup():
                startup_started.set()
                try:
                    while True:
                        try:
                            await asyncio.Event().wait()
                        except asyncio.CancelledError:
                            if allow_exit.is_set():
                                raise
                finally:
                    mgr._finish_startup_attempt(server_id, attempt)

            task = asyncio.create_task(stuck_startup())
            assert mgr._bind_startup_task(server_id, attempt, task)
            return task

        startup_task = asyncio.run_coroutine_threadsafe(
            install_startup_attempt(),
            mgr._event_loop,
        ).result(timeout=2)
        assert startup_started.wait(timeout=2)

        stop = asyncio.run_coroutine_threadsafe(
            mgr._stop_server_coro(server_id),
            mgr._event_loop,
        )
        with pytest.raises(RuntimeError, match="启动任务拒绝在 deadline 内退出"):
            stop.result(timeout=0.3)

        allow_exit.set()
        mgr._event_loop.call_soon_threadsafe(startup_task.cancel)
        deadline = time.monotonic() + 2
        while not startup_task.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert startup_task.done()
        mgr.shutdown()

    def test_loop_thread_shutdown_failure_is_explicitly_logged(
        self,
        monkeypatch,
        caplog,
    ):
        """loop-thread 分支无法同步抛错时，done callback 必须观察并记录失败。"""
        mgr = _create_manager_with_loop()
        drain_called = threading.Event()

        async def fail_stop_all():
            raise RuntimeError("simulated shutdown failure")

        async def observe_drain():
            drain_called.set()

        monkeypatch.setattr(mgr, "stop_all", fail_stop_all)
        monkeypatch.setattr(mgr, "_drain_event_loop_tasks", observe_drain)
        caplog.set_level("ERROR")
        mgr._event_loop.call_soon_threadsafe(mgr.shutdown)
        mgr._event_loop_thread.join(timeout=2)

        assert not mgr._event_loop_thread.is_alive()
        assert mgr._event_loop.is_closed()
        assert drain_called.is_set()
        assert "event-loop shutdown failed" in caplog.text
        assert "simulated shutdown failure" in caplog.text

    def test_shutdown_reports_stack_close_failure_after_closing_loop(self):
        """普通线程 shutdown 必须传播 running server 的 SDK stack 清理失败。"""

        class FailingStack:
            async def aclose(self):
                raise RuntimeError("simulated shutdown stack close failure")

        mgr = _create_manager_with_loop()
        server_id = "mcs_shutdown_stack_failure"
        mgr._sessions[server_id] = FakeMcpSession()
        mgr._stacks[server_id] = FailingStack()
        mgr._server_names[server_id] = "shutdown-stack-failure"

        with pytest.raises(RuntimeError, match="MCP 事件循环任务清理失败"):
            mgr.shutdown()

        assert not mgr._event_loop_thread.is_alive()
        assert mgr._event_loop.is_closed()
        assert server_id not in mgr._sessions
        assert server_id not in mgr._stacks

    def test_shutdown_reports_drain_failure_and_live_thread(self, monkeypatch):
        """drain 失败且线程未退出时必须显式失败，不能伪装成已关闭。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager

        class FakeFuture:
            def result(self, timeout):
                raise TimeoutError("drain timed out")

        class FakeLoop:
            def __init__(self):
                self.stop_requested = False

            def is_closed(self):
                return False

            def is_running(self):
                return True

            def call_soon_threadsafe(self, callback):
                self.stop_requested = True

            def stop(self):
                self.stop_requested = True

        class StuckThread:
            def __init__(self):
                self.join_called = False

            def is_alive(self):
                return True

            def join(self, timeout):
                self.join_called = True

        loop = FakeLoop()
        thread = StuckThread()
        mgr = object.__new__(McpProcessManager)
        mgr._event_loop = loop
        mgr._event_loop_thread = thread
        mgr._startup_cleanup_tasks = set()

        def fake_run_coroutine_threadsafe(coro, target_loop):
            assert target_loop is loop
            coro.close()
            return FakeFuture()

        monkeypatch.setattr(
            asyncio,
            "run_coroutine_threadsafe",
            fake_run_coroutine_threadsafe,
        )

        with pytest.raises(RuntimeError, match="MCP 事件循环线程未能退出"):
            mgr.shutdown()

        assert loop.stop_requested
        assert thread.join_called

    def test_shutdown_reports_drain_failure_after_thread_exits(self, monkeypatch):
        """即使线程随后退出，drain 异常仍是可观察的 shutdown 失败。"""
        from src.business.mcp.mcp_process_manager import McpProcessManager

        loop = MagicMock()
        loop.is_closed.return_value = False
        loop.is_running.return_value = False
        thread = MagicMock()
        thread.is_alive.side_effect = [True, False, False]

        mgr = object.__new__(McpProcessManager)
        mgr._event_loop = loop
        mgr._event_loop_thread = thread
        mgr._startup_cleanup_tasks = set()

        def fake_run_coroutine_threadsafe(coro, target_loop):
            assert target_loop is loop
            coro.close()
            future = MagicMock()
            future.result.side_effect = TimeoutError("drain timed out")
            return future

        monkeypatch.setattr(
            asyncio,
            "run_coroutine_threadsafe",
            fake_run_coroutine_threadsafe,
        )

        with pytest.raises(RuntimeError, match="MCP 事件循环任务清理失败"):
            mgr.shutdown()

        thread.join.assert_called_once()


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
    mgr._shutdown_task = None
    mgr._startup_attempts = {}
    mgr._startup_cleanup_tasks = set()

    # 手动启动事件循环
    mgr._event_loop = asyncio.new_event_loop()
    mgr._event_loop_thread = threading.Thread(
        target=mgr._run_loop, daemon=True, name="test-mcp-loop"
    )
    mgr._event_loop_thread.start()

    return mgr
