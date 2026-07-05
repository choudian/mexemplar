"""
McpProcessManager — 管理所有 MCP server 子进程的 asyncio 生命周期。

核心职责：
- 独立事件循环线程 + crash recovery（E6/N15）
- stdio_client + AsyncExitStack 长连接管理（N1/N2）
- _SdkSessionAdapter 包装 SDK ClientSession → McpSessionProtocol（RC4）
- stderr tempfile 收集 + 脱敏日志（RC1）
- 同步入口桥接（start_server/stop_server/call_tool_sync/reconnect_server）
"""

import asyncio
import logging
import os
import re
import tempfile
import threading
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

from src.business.mcp.mcp_errors import (
    McpCircuitBreakerOpenError,
    McpServerDisconnectedError,
    McpToolSchemaValidationError,
    McpToolTimeoutError,
)
from src.business.mcp.mcp_env_resolver import (
    merge_with_config_secrets,
    merge_with_config_headers,
)
from src.business.mcp.mcp_session_protocol import McpSessionProtocol
from src.business.mcp.models import (
    McpCallResult,
    McpLaunchPayload,
    McpServerConfigPublic,
    McpServerStatus,
    McpToolInfo,
)
from src.utils.events import emit

logger = logging.getLogger(__name__)

# stderr 日志脱敏模式
_SECRET_MASK_PATTERNS = [
    re.compile(r"(ghp_[a-zA-Z0-9]{30,})", re.IGNORECASE),
    re.compile(r"(gho_[a-zA-Z0-9]{30,})", re.IGNORECASE),
    re.compile(r"(sk-[a-zA-Z0-9]{20,})", re.IGNORECASE),
    re.compile(r"(token[_\-]?[a-zA-Z0-9]{10,})", re.IGNORECASE),
]


def _mask_secrets(text: str) -> str:
    """脱敏 stderr 文本中的 secret 模式。"""
    for pattern in _SECRET_MASK_PATTERNS:
        text = pattern.sub("***", text)
    return text


class _SdkSessionAdapter:
    """SDK ClientSession → McpSessionProtocol 适配器。

    RC4: McpProcessManager._sessions 存此 Adapter（Protocol 类型），测试可注入 FakeMcpSession。
    """

    def __init__(self, sdk_session: Any):
        self._sdk_session = sdk_session

    async def initialize(self) -> None:
        await self._sdk_session.initialize()

    async def list_tools(self) -> list[McpToolInfo]:
        sdk_result = await self._sdk_session.list_tools()
        return [_convert_sdk_tool(t) for t in sdk_result.tools]

    async def call_tool(self, name: str, arguments: dict) -> McpCallResult:
        try:
            sdk_result = await self._sdk_session.call_tool(
                name,
                arguments=arguments,
                read_timeout_seconds=timedelta(seconds=30),
            )
            return _convert_sdk_call_result(sdk_result)
        except RuntimeError as exc:
            # RC3: SDK schema 校验错误
            msg = str(exc).lower()
            if ("structured content" in msg or "invalid schema" in msg
                    or "output schema" in msg):
                raise McpToolSchemaValidationError(name, str(exc)) from exc
            raise

    async def send_ping(self) -> bool:
        try:
            await self._sdk_session.send_ping()
            return True
        except Exception as exc:
            logger.debug("[MCP] ping failed for session: %s", exc)
            return False


def _convert_sdk_call_result(sdk_result: Any) -> McpCallResult:
    """SDK CallToolResult → 业务 McpCallResult（RC8）。"""
    from mcp.types import TextContent, ImageContent  # 延迟 import（E7）

    text_parts = [c.text for c in sdk_result.content if isinstance(c, TextContent)]
    image_count = sum(1 for c in sdk_result.content if isinstance(c, ImageContent))
    structured_data = None
    if hasattr(sdk_result, "structuredContent") and sdk_result.structuredContent:
        structured_data = sdk_result.structuredContent

    return McpCallResult(
        is_error=sdk_result.isError or False,
        text_parts=text_parts,
        image_count=image_count,
        structured_data=structured_data,
    )


def _convert_sdk_tool(sdk_tool: Any) -> McpToolInfo:
    """SDK Tool → 业务 McpToolInfo（RC9）。"""
    return McpToolInfo(
        name=sdk_tool.name,
        description=sdk_tool.description or "",
        input_schema=sdk_tool.inputSchema or {},
    )


class McpProcessManager:
    """管理所有 MCP server 子进程的 asyncio 生命周期。"""

    def __init__(self):
        self._sdk_available = self._check_sdk_available()
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._event_loop_thread: threading.Thread | None = None
        self._sessions: dict[str, McpSessionProtocol] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self._stderr_files: dict[str, tempfile._TemporaryFileWrapper] = {}
        self._stderr_read_pos: dict[str, int] = {}
        self._server_names: dict[str, str] = {}
        self._lock = threading.Lock()
        self._ping_task: asyncio.Task | None = None

        if self._sdk_available:
            self._start_event_loop()

    def _check_sdk_available(self) -> bool:
        """延迟 import 检测 MCP SDK 是否可用（E7）。"""
        try:
            from mcp import ClientSession  # noqa: F401
            return True
        except ImportError:
            logger.warning("[MCP] MCP SDK 不可用，MCP 启动/测试功能将降级")
            return False

    @property
    def sdk_available(self) -> bool:
        return self._sdk_available

    def _start_event_loop(self):
        """启动独立事件循环线程。"""
        self._event_loop = asyncio.new_event_loop()
        self._event_loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="mcp-event-loop"
        )
        self._event_loop_thread.start()

    def _run_loop(self):
        """事件循环线程主函数，含 crash recovery（E6/N15）。"""
        crash_count = 0
        while True:
            try:
                # 启动 ping loop 后进入事件循环
                self._ping_task = self._event_loop.create_task(self._ping_loop())
                self._event_loop.run_forever()
                break  # 正常 stop
            except Exception:
                crash_count += 1
                logger.exception("[MCP] event loop crashed (attempt %d), rebuilding", crash_count)
                self._event_loop = asyncio.new_event_loop()
                if crash_count >= 5:
                    logger.critical("[MCP] event loop crashed 5+ times, giving up recovery")
                    break
                import time
                time.sleep(min(crash_count, 3))

    def get_or_create_event_loop(self) -> asyncio.AbstractEventLoop:
        """获取事件循环，如果线程死了则重建。"""
        if (self._event_loop_thread is None
                or not self._event_loop_thread.is_alive()):
            self._start_event_loop()
        return self._event_loop  # type: ignore

    # ─── 同步入口 ───

    def start_server(
        self, server_id: str, config: McpServerConfigPublic
    ) -> list[McpToolInfo]:
        """同步启动 server（可从任意线程调用）。

        Returns:
            启动后发现的工具列表。
        """
        if not self._sdk_available:
            raise RuntimeError("MCP SDK 不可用，无法启动 server")

        loop = self.get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._start_server_coro(server_id, config), loop
        )
        try:
            return future.result(timeout=60)
        except Exception as exc:
            logger.error("[MCP] start_server %s failed: %s", server_id, exc)
            raise

    def stop_server(self, server_id: str) -> None:
        """同步停止 server（可从任意线程调用，N5 明确超时）。

        Raises:
            RuntimeError: stop 超时或失败（子进程可能残留为孤儿）。
        """
        loop = self.get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._stop_server_coro(server_id), loop
        )
        try:
            future.result(timeout=15)
        except asyncio.TimeoutError:
            logger.warning("[MCP] stop_server %s timed out", server_id)
            raise RuntimeError(f"停止 MCP server {server_id} 超时，子进程可能残留")
        except Exception as exc:
            logger.warning("[MCP] stop_server %s failed: %s", server_id, exc)
            raise RuntimeError(f"停止 MCP server {server_id} 失败: {exc}") from exc

    def call_tool_sync(
        self, server_id: str, tool_name: str, args: dict
    ) -> McpCallResult:
        """同步调用工具（可从任意线程调用）。"""
        if not self._event_loop_thread or not self._event_loop_thread.is_alive():
            self._start_event_loop()

        future = asyncio.run_coroutine_threadsafe(
            self._call_tool_coro(server_id, tool_name, args), self._event_loop
        )
        try:
            return future.result(timeout=30)
        except asyncio.TimeoutError as exc:
            raise McpToolTimeoutError(tool_name) from exc
        except McpServerDisconnectedError:
            raise
        except McpToolSchemaValidationError:
            raise
        except McpCircuitBreakerOpenError:
            raise
        except Exception as exc:
            raise McpServerDisconnectedError(server_id) from exc

    def reconnect_server(
        self, server_id: str, config: McpServerConfigPublic
    ) -> list[McpToolInfo]:
        """重连 = stop + start。

        Returns:
            重连后发现的工具列表。
        """
        self.stop_server(server_id)
        return self.start_server(server_id, config)

    def is_server_running(self, server_id: str) -> bool:
        """检查 server 是否处于运行态。"""
        return server_id in self._sessions

    def health_check(self, server_id: str) -> bool:
        """同步健康检查。"""
        loop = self.get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._health_check_coro(server_id), loop
        )
        try:
            return future.result(timeout=10)
        except Exception:
            return False

    # ─── 异步核心 ───

    async def _start_server_coro(
        self, server_id: str, public_config: McpServerConfigPublic
    ):
        """在 MCP 事件循环上执行的实际启动逻辑。"""
        from mcp import ClientSession  # 延迟 import（E7）
        from mcp.client.stdio import stdio_client, StdioServerParameters

        # 1. 构建 launch payload（合并 secret）
        launch_payload = self._build_launch_payload(public_config)

        # 2. 构造 StdioServerParameters（SDK 自己 spawn 子进程，N1）
        params = StdioServerParameters(
            command=launch_payload.command,
            args=launch_payload.args,
            env=launch_payload.merged_env or None,
            encoding="utf-8",
            encoding_error_handler="replace",
        )

        # RC1: stderr 用 tempfile（有 fileno，subprocess 接受）
        stderr_file = tempfile.TemporaryFile(
            mode="w+", encoding="utf-8", errors="replace"
        )
        stop_event = asyncio.Event()
        stack = AsyncExitStack()

        try:
            # 3. stdio_client 自己 spawn 子进程
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params, errlog=stderr_file)
            )

            # 4. RC2: ClientSession MUST 进 async with
            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(seconds=30),
                )
            )
            await session.initialize()

            # 5. RC4: 用 _SdkSessionAdapter 包装
            adapter = _SdkSessionAdapter(session)
            sdk_tools_result = await adapter.list_tools()

            # 6. 缓存
            self._sessions[server_id] = adapter
            self._stacks[server_id] = stack
            self._stop_events[server_id] = stop_event
            self._stderr_files[server_id] = stderr_file
            self._server_names[server_id] = public_config.name

            # 7. 启动 stderr reader（RC1）
            self._event_loop.create_task(self._stderr_reader(server_id))

            # 8. 更新 DB 状态 + 注册工具（回调由 McpServerService 处理）
            # 返回工具列表供 Service 使用
            return sdk_tools_result

        except Exception as exc:
            # N15: 启动失败
            await self._mark_disconnected(server_id, exc)
            raise

    async def _stop_server_coro(self, server_id: str):
        """在 MCP 事件循环上执行的实际停止逻辑。"""
        stop_event = self._stop_events.pop(server_id, None)
        stack = self._stacks.pop(server_id, None)

        if stop_event is not None:
            stop_event.set()

        if stack is not None:
            try:
                await asyncio.wait_for(stack.aclose(), timeout=15)
            except asyncio.TimeoutError:
                logger.warning("[MCP] stack.aclose() timeout for %s", server_id)
            except Exception as exc:
                logger.warning("[MCP] stack.aclose() failed for %s: %s", server_id, exc)

        # 清理缓存
        self._sessions.pop(server_id, None)
        self._stop_events.pop(server_id, None)
        stderr_file = self._stderr_files.pop(server_id, None)
        self._stderr_read_pos.pop(server_id, None)
        self._server_names.pop(server_id, None)
        self._stacks.pop(server_id, None)

        if stderr_file is not None:
            try:
                stderr_file.close()
            except Exception:
                pass

    async def _call_tool_coro(
        self, server_id: str, tool_name: str, arguments: dict
    ) -> McpCallResult:
        """在 MCP 事件循环上执行。返回业务层 McpCallResult（N9）。"""
        session = self._sessions.get(server_id)
        if session is None:
            raise McpServerDisconnectedError(server_id)
        try:
            return await session.call_tool(tool_name, arguments)
        except McpToolSchemaValidationError:
            raise
        except Exception as exc:
            await self._mark_disconnected(server_id, exc)
            raise McpServerDisconnectedError(server_id) from exc

    async def _health_check_coro(self, server_id: str) -> bool:
        """健康检查 ping。"""
        session = self._sessions.get(server_id)
        if session is None:
            return False
        return await session.send_ping()

    # ─── 周期性 ping loop（N4: 60s 间隔）───

    async def _ping_loop(self):
        """60s 周期性 ping 所有 running server（N4）。

        ping 失败 → 标记断连 + emit backend_resync_required。
        """
        try:
            while True:
                await asyncio.sleep(60)
                server_ids = list(self._sessions.keys())
                for sid in server_ids:
                    session = self._sessions.get(sid)
                    if session is None:
                        continue
                    try:
                        ok = await session.send_ping()
                        if not ok:
                            await self._mark_disconnected(
                                sid, RuntimeError("ping failed")
                            )
                    except Exception as exc:
                        await self._mark_disconnected(sid, exc)
        except asyncio.CancelledError:
            pass  # shutdown
        except Exception:
            logger.exception("[MCP] ping loop crashed")

    async def _mark_disconnected(self, server_id: str, error: Exception):
        """标记 server 断连 + 清理（RC11: emit backend_resync_required）。

        清理 ProcessManager 内部状态，并 emit 事件通知 Service 层
        注销工具和更新 DB 状态。
        """
        self._sessions.pop(server_id, None)
        # 清理 AsyncExitStack 防止资源泄漏
        stack = self._stacks.pop(server_id, None)
        if stack is not None:
            try:
                await asyncio.wait_for(stack.aclose(), timeout=5)
            except Exception as exc:
                logger.debug("[MCP] stack.aclose() in _mark_disconnected for %s: %s", server_id, exc)
        self._stop_events.pop(server_id, None)

        stderr_file = self._stderr_files.pop(server_id, None)
        self._stderr_read_pos.pop(server_id, None)
        self._server_names.pop(server_id, None)
        if stderr_file is not None:
            try:
                stderr_file.close()
            except Exception:
                pass

        logger.warning("[MCP] server %s disconnected: %s", server_id, error)
        # 通知 Service 层注销工具和更新 DB 状态
        emit("mcp_server_disconnected", server_id=server_id, error=str(error)[:500])
        # RC11: 通知前端刷新 server 状态
        emit("backend_resync_required", reason="mcp_server_disconnected")

    # ─── 辅助方法 ───

    def _build_launch_payload(self, config: McpServerConfigPublic) -> McpLaunchPayload:
        """McpServerConfigPublic → McpLaunchPayload（合并 secret，N17）。"""
        merged_env = merge_with_config_secrets(
            config.non_secret_env,
            config.secret_env_keys,
            config.server_id,
        )
        merged_headers = merge_with_config_headers(
            config.non_secret_headers,
            config.secret_header_keys,
            config.server_id,
        )

        return McpLaunchPayload(
            command=config.command or "",
            args=config.args,
            merged_env=merged_env,
            url=config.url,
            merged_headers=merged_headers,
        )

    async def _stderr_reader(self, server_id: str):
        """定时从 stderr tempfile 提取新内容，脱敏后记日志（RC1）。"""
        while server_id in self._sessions:
            try:
                stderr_file = self._stderr_files.get(server_id)
                if stderr_file is None:
                    await asyncio.sleep(5)
                    continue

                stderr_file.seek(0, 2)  # seek to end
                pos = stderr_file.tell()
                last_pos = self._stderr_read_pos.get(server_id, 0)
                stderr_file.seek(last_pos)
                new_data = stderr_file.read()
                self._stderr_read_pos[server_id] = pos
                stderr_file.seek(pos)

                if new_data and new_data.strip():
                    server_name = self._server_names.get(server_id, server_id)
                    masked = _mask_secrets(new_data)
                    logger.info(
                        "[MCP] server=%s stderr: %s", server_name, masked.strip()
                    )
            except Exception as exc:
                logger.debug("[MCP] stderr reader error for %s: %s", server_id, exc)
            await asyncio.sleep(5)

    # ─── 启停所有 server ───

    async def start_all_enabled(self, configs: list[tuple[str, McpServerConfigPublic]]):
        """并发启动所有 enabled server，失败标 failed 但不阻塞（E7 try/except）。"""
        results = await asyncio.gather(
            *[
                self._safe_start(server_id, config)
                for server_id, config in configs
            ],
            return_exceptions=True,
        )
        return results

    async def _safe_start(self, server_id: str, config: McpServerConfigPublic):
        """安全启动单个 server，异常不传播。"""
        try:
            return await self._start_server_coro(server_id, config)
        except Exception as exc:
            logger.error("[MCP] start_all: server %s failed: %s", server_id, exc)
            return exc

    def stop_all_sync(self):
        """同步停止所有 running server（可从任意线程调用）。"""
        try:
            loop = self.get_or_create_event_loop()
        except Exception:
            return
        future = asyncio.run_coroutine_threadsafe(self.stop_all(), loop)
        try:
            future.result(timeout=10)
        except Exception as exc:
            logger.warning("[MCP] stop_all failed: %s", exc)

    async def stop_all(self):
        """并发停止所有 running server。"""
        server_ids = list(self._sessions.keys())
        await asyncio.gather(
            *[self._stop_server_coro(sid) for sid in server_ids],
            return_exceptions=True,
        )

    def shutdown(self):
        """关闭事件循环线程。"""
        # 取消 ping loop task
        if self._ping_task is not None and self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._ping_task.cancel)
        if self._event_loop is not None:
            self._event_loop.call_soon_threadsafe(self._event_loop.stop)
        if self._event_loop_thread is not None:
            self._event_loop_thread.join(timeout=5)
