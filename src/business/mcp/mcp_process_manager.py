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
import re
import tempfile
import threading
from contextlib import AsyncExitStack
from dataclasses import dataclass
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
    McpToolInfo,
)
from src.utils.events import emit

logger = logging.getLogger(__name__)

_MCP_STARTUP_TIMEOUT_SECONDS = 60
_MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS = 15
_MCP_STARTUP_BRIDGE_GRACE_SECONDS = 10
_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS = 5
_MCP_STOP_TIMEOUT_SECONDS = 15
_MCP_SHUTDOWN_BRIDGE_GRACE_SECONDS = 5

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


def _load_sdk_client_types() -> tuple[Any, Any, Any]:
    """延迟加载 MCP SDK 启动类型，保持 sidecar 可降级且提供可测试边界。"""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    return ClientSession, stdio_client, StdioServerParameters


@dataclass(slots=True)
class _StartupAttempt:
    """单个 server 启动尝试的权威取消状态。"""

    task: asyncio.Task[Any] | None = None
    cancelled: bool = False


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
            if "structured content" in msg or "invalid schema" in msg or "output schema" in msg:
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
        self._shutdown_task: asyncio.Task[None] | None = None
        self._startup_attempts: dict[str, _StartupAttempt] = {}
        self._startup_cleanup_tasks: set[asyncio.Task[None]] = set()

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
        try:
            while True:
                active_loop = self._event_loop
                if active_loop is None:
                    return
                asyncio.set_event_loop(active_loop)
                try:
                    # 启动 ping loop 后进入事件循环
                    self._ping_task = active_loop.create_task(self._ping_loop())
                    active_loop.run_forever()
                    break  # 正常 stop
                except Exception:
                    crash_count += 1
                    logger.exception(
                        "[MCP] event loop crashed (attempt %d), rebuilding",
                        crash_count,
                    )
                    self._close_event_loop(active_loop)
                    if crash_count >= 5:
                        logger.critical("[MCP] event loop crashed 5+ times, giving up recovery")
                        break
                    self._event_loop = asyncio.new_event_loop()
                    import time

                    time.sleep(min(crash_count, 3))
        finally:
            final_loop = self._event_loop
            if final_loop is not None:
                self._close_event_loop(final_loop)

    @staticmethod
    def _close_event_loop(loop: asyncio.AbstractEventLoop) -> None:
        """在所属线程中有界收割残留 Task 并关闭 loop。"""
        if loop.is_closed() or loop.is_running():
            return
        survivors = {task for task in asyncio.all_tasks(loop) if not task.done()}
        for _ in range(2):
            if not survivors:
                break
            survivors = loop.run_until_complete(
                McpProcessManager._cancel_tasks_with_deadline(
                    survivors,
                    timeout=_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS,
                )
            )
        if survivors:
            logger.error(
                "[MCP] force-closing event loop with %d cancellation-resistant task(s)",
                len(survivors),
            )
        loop.close()

    def get_or_create_event_loop(self) -> asyncio.AbstractEventLoop:
        """获取事件循环，如果线程死了则重建。"""
        if self._event_loop_thread is None or not self._event_loop_thread.is_alive():
            self._start_event_loop()
        return self._event_loop  # type: ignore

    def _begin_startup_attempt(self, server_id: str) -> _StartupAttempt:
        """为 server 建立唯一启动 attempt，拒绝重复启动和覆盖运行实例。"""
        with self._lock:
            if server_id in self._startup_attempts:
                raise RuntimeError(f"MCP server {server_id} 正在启动")
            if server_id in self._sessions:
                raise RuntimeError(f"MCP server {server_id} 已在运行")
            attempt = _StartupAttempt()
            self._startup_attempts[server_id] = attempt
            return attempt

    def _bind_startup_task(
        self,
        server_id: str,
        attempt: _StartupAttempt,
        task: asyncio.Task[Any] | None,
    ) -> bool:
        """原子认领 attempt；已取消/被替换时禁止进入任何资源构造。"""
        with self._lock:
            if (
                task is None
                or attempt.cancelled
                or self._startup_attempts.get(server_id) is not attempt
            ):
                return False
            attempt.task = task
            return True

    def _cancel_startup_attempt(self, server_id: str, attempt: _StartupAttempt) -> None:
        with self._lock:
            if self._startup_attempts.get(server_id) is attempt:
                attempt.cancelled = True

    def _finish_startup_attempt(self, server_id: str, attempt: _StartupAttempt) -> None:
        with self._lock:
            if self._startup_attempts.get(server_id) is attempt:
                self._startup_attempts.pop(server_id, None)

    def _retire_unbound_startup_attempt(
        self,
        server_id: str,
        attempt: _StartupAttempt,
    ) -> bool:
        """退休尚未进入 coroutine 主体的 attempt，避免永久 starting fence。"""
        with self._lock:
            if self._startup_attempts.get(server_id) is not attempt or attempt.task is not None:
                return False
            attempt.cancelled = True
            self._startup_attempts.pop(server_id, None)
            return True

    def _publish_started_server(
        self,
        server_id: str,
        attempt: _StartupAttempt,
        *,
        session: McpSessionProtocol,
        stack: AsyncExitStack,
        stop_event: asyncio.Event,
        stderr_file: Any,
        server_name: str,
    ) -> bool:
        """仅让仍为权威且未取消的 attempt 原子发布运行实例。"""
        with self._lock:
            if (
                attempt.cancelled
                or self._startup_attempts.get(server_id) is not attempt
                or server_id in self._sessions
            ):
                return False
            self._sessions[server_id] = session
            self._stacks[server_id] = stack
            self._stop_events[server_id] = stop_event
            self._stderr_files[server_id] = stderr_file
            self._server_names[server_id] = server_name
            return True

    # ─── 同步入口 ───

    def start_server(self, server_id: str, config: McpServerConfigPublic) -> list[McpToolInfo]:
        """同步启动 server（可从任意线程调用）。

        Returns:
            启动后发现的工具列表。
        """
        if not self._sdk_available:
            raise RuntimeError("MCP SDK 不可用，无法启动 server")

        loop = self.get_or_create_event_loop()
        attempt = self._begin_startup_attempt(server_id)
        startup_finished = threading.Event()

        async def start_with_completion_signal():
            try:
                return await self._start_server_coro(server_id, config, _attempt=attempt)
            finally:
                startup_finished.set()

        try:
            future = asyncio.run_coroutine_threadsafe(start_with_completion_signal(), loop)
        except Exception:
            self._finish_startup_attempt(server_id, attempt)
            raise
        try:
            # 整体启动 deadline 在协程内部执行；同步桥多留出资源清理与调度余量，
            # 避免桥先返回超时而启动协程随后写入“幽灵”会话。
            return future.result(
                timeout=(
                    _MCP_STARTUP_TIMEOUT_SECONDS
                    + _MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS
                    + _MCP_STARTUP_BRIDGE_GRACE_SECONDS
                )
            )
        except Exception as exc:
            if isinstance(exc, TimeoutError) and not future.done():
                # 防御性兜底：正常情况下协程内 deadline 会先完成清理；若同步桥
                # 仍先超时，则取消协程并等待其 finally 回收局部 SDK resources。
                self._cancel_startup_attempt(server_id, attempt)
                future.cancel()
                retired_before_start = self._retire_unbound_startup_attempt(server_id, attempt)
                if not retired_before_start and not startup_finished.wait(
                    timeout=(
                        _MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS + _MCP_STARTUP_BRIDGE_GRACE_SECONDS
                    )
                ):
                    logger.warning(
                        "[MCP] cancelled startup cleanup did not finish for %s",
                        server_id,
                    )
            # Cancelled bridge / scheduling teardown may report a done Future before
            # the coroutine ever binds. Bound/finished attempts make this a no-op.
            self._retire_unbound_startup_attempt(server_id, attempt)
            logger.error("[MCP] start_server %s failed: %s", server_id, exc)
            raise

    def stop_server(self, server_id: str) -> None:
        """同步停止 server（可从任意线程调用，N5 明确超时）。

        Raises:
            RuntimeError: stop 超时或失败（子进程可能残留为孤儿）。
        """
        loop = self.get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(self._stop_server_coro(server_id), loop)
        try:
            future.result(timeout=15)
        except asyncio.TimeoutError:
            logger.warning("[MCP] stop_server %s timed out", server_id)
            raise RuntimeError(f"停止 MCP server {server_id} 超时，子进程可能残留")
        except Exception as exc:
            logger.warning("[MCP] stop_server %s failed: %s", server_id, exc)
            raise RuntimeError(f"停止 MCP server {server_id} 失败: {exc}") from exc

    def call_tool_sync(self, server_id: str, tool_name: str, args: dict) -> McpCallResult:
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

    def reconnect_server(self, server_id: str, config: McpServerConfigPublic) -> list[McpToolInfo]:
        """重连 = stop + start。

        Returns:
            重连后发现的工具列表。
        """
        self.stop_server(server_id)
        return self.start_server(server_id, config)

    def is_server_running(self, server_id: str) -> bool:
        """检查 server 是否处于运行态。"""
        with self._lock:
            return server_id in self._sessions

    def health_check(self, server_id: str) -> bool:
        """同步健康检查。"""
        loop = self.get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(self._health_check_coro(server_id), loop)
        try:
            return future.result(timeout=10)
        except Exception:
            return False

    # ─── 异步核心 ───

    async def _start_server_coro(
        self,
        server_id: str,
        public_config: McpServerConfigPublic,
        *,
        _attempt: _StartupAttempt | None = None,
    ):
        """在 MCP 事件循环上执行的实际启动逻辑。"""
        attempt = _attempt or self._begin_startup_attempt(server_id)
        if not self._bind_startup_task(server_id, attempt, asyncio.current_task()):
            self._finish_startup_attempt(server_id, attempt)
            raise asyncio.CancelledError()

        try:
            ClientSession, stdio_client, StdioServerParameters = _load_sdk_client_types()

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
            stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
            stop_event = asyncio.Event()
            stack = AsyncExitStack()
        except BaseException:
            self._finish_startup_attempt(server_id, attempt)
            raise

        try:
            # spawn、initialize 与工具发现共享同一个 60s 产品 deadline；SDK 的
            # 单次读取预算与其一致，工具调用仍由 Adapter 保持独立的 30s 超时。
            async with asyncio.timeout(_MCP_STARTUP_TIMEOUT_SECONDS):
                # 3. stdio_client 自己 spawn 子进程
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(params, errlog=stderr_file)
                )

                # 4. RC2: ClientSession MUST 进 async with
                session = await stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(seconds=_MCP_STARTUP_TIMEOUT_SECONDS),
                    )
                )
                await session.initialize()

                # 5. RC4: 用 _SdkSessionAdapter 包装
                adapter = _SdkSessionAdapter(session)
                sdk_tools_result = await adapter.list_tools()

                # 6. 原子发布；桥超时/stop 已取消的 attempt 不得迟到写入 cache。
                published = self._publish_started_server(
                    server_id,
                    attempt,
                    session=adapter,
                    stack=stack,
                    stop_event=stop_event,
                    stderr_file=stderr_file,
                    server_name=public_config.name,
                )
                if not published:
                    raise asyncio.CancelledError()

                # 7. 启动 stderr reader（RC1）
                self._event_loop.create_task(self._stderr_reader(server_id))

                # 8. 更新 DB 状态 + 注册工具（回调由 McpServerService 处理）
                # 返回工具列表供 Service 使用
                return sdk_tools_result

        except asyncio.CancelledError:
            # run_coroutine_threadsafe 的桥接超时/调用方取消也必须退出本地 contexts。
            try:
                await self._stop_server_coro(server_id)
            finally:
                await self._cleanup_startup_resources(server_id, stack, stderr_file)
            raise
        except Exception as exc:
            # N15: 启动失败
            try:
                await self._mark_disconnected(server_id, exc)
            except Exception as disconnect_exc:
                # 事件监听器或断连清理异常不能覆盖真正的启动失败。
                logger.debug(
                    "[MCP] marking failed startup disconnected failed for %s: %s",
                    server_id,
                    disconnect_exc,
                )
            finally:
                await self._cleanup_startup_resources(server_id, stack, stderr_file)
            raise
        finally:
            self._finish_startup_attempt(server_id, attempt)

    async def _cleanup_startup_resources(
        self,
        server_id: str,
        stack: AsyncExitStack,
        stderr_file: Any,
    ) -> None:
        """兜底回收尚未发布到 manager 缓存的启动期资源。"""
        # initialize/list_tools 失败发生在缓存写入前时，常规断连清理看不到这些
        # 局部资源。AsyncExitStack/tempfile 允许重复关闭，因此成功写入缓存后也安全。

        async def close_stack_and_stderr() -> None:
            try:
                await stack.aclose()
            finally:
                stderr_file.close()

        cleanup_task = asyncio.create_task(
            close_stack_and_stderr(),
            name=f"mcp-startup-cleanup-{server_id}",
        )
        self._startup_cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(lambda task: self._on_startup_cleanup_done(server_id, task))

        try:
            # shield 确保观察超时不会取消 SDK 自带的 graceful-exit/Job Object 清理。
            await asyncio.wait_for(
                asyncio.shield(cleanup_task),
                timeout=_MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            if not cleanup_task.done():
                logger.warning(
                    "[MCP] startup cleanup still running for %s; retaining task "
                    "(orphan-process risk if cleanup never completes)",
                    server_id,
                )
        except Exception:
            # done callback 统一消费并记录 cleanup 异常，避免未检索的 Task exception。
            return

    def _on_startup_cleanup_done(
        self,
        server_id: str,
        task: asyncio.Task[None],
    ) -> None:
        """释放强引用并显式报告 SDK cleanup 失败。"""
        self._startup_cleanup_tasks.discard(task)
        if task.cancelled():
            logger.warning(
                "[MCP] startup cleanup cancelled for %s (orphan-process risk)",
                server_id,
            )
            return
        cleanup_error = task.exception()
        if cleanup_error is not None:
            logger.warning(
                "[MCP] startup cleanup failed for %s (%s; orphan-process risk)",
                server_id,
                type(cleanup_error).__name__,
            )

    async def _stop_server_coro(self, server_id: str):
        """停止 server；本地状态始终收口，SDK/startup 清理失败汇总上抛。"""
        current_task = asyncio.current_task()
        stop_errors: list[Exception] = []
        with self._lock:
            startup_attempt = self._startup_attempts.get(server_id)
            if startup_attempt is not None:
                startup_attempt.cancelled = True
                startup_task = startup_attempt.task
            else:
                startup_task = None
        if startup_attempt is not None and startup_task is None:
            self._retire_unbound_startup_attempt(server_id, startup_attempt)

        if (
            startup_task is not None
            and startup_task is not current_task
            and not startup_task.done()
        ):
            survivors = {startup_task}
            for cancel_round in range(1, 3):
                survivors = await self._cancel_tasks_with_deadline(
                    survivors,
                    timeout=_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS,
                )
                if not survivors:
                    break
                logger.warning(
                    "[MCP] startup task for %s survived stop cancellation round %d",
                    server_id,
                    cancel_round,
                )
            if survivors:
                stop_errors.append(
                    RuntimeError(f"MCP server {server_id} 的启动任务拒绝在 deadline 内退出")
                )

        stop_event = self._stop_events.pop(server_id, None)
        stack = self._stacks.pop(server_id, None)

        if stop_event is not None:
            stop_event.set()

        if stack is not None:
            try:
                await asyncio.wait_for(stack.aclose(), timeout=_MCP_STOP_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                logger.warning("[MCP] stack.aclose() timeout for %s", server_id)
                cleanup_error = RuntimeError(f"MCP server {server_id} 的 SDK 资源清理超时")
                cleanup_error.__cause__ = exc
                stop_errors.append(cleanup_error)
            except Exception as exc:
                logger.warning("[MCP] stack.aclose() failed for %s: %s", server_id, exc)
                stop_errors.append(exc)

        # 清理缓存
        with self._lock:
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
        if len(stop_errors) == 1:
            raise stop_errors[0]
        if stop_errors:
            for secondary_error in stop_errors[1:]:
                logger.error(
                    "[MCP] additional stop failure for %s: %s",
                    server_id,
                    secondary_error,
                    exc_info=(
                        type(secondary_error),
                        secondary_error,
                        secondary_error.__traceback__,
                    ),
                )
            raise RuntimeError(
                f"MCP server {server_id} 停止时有 {len(stop_errors)} 个清理阶段失败"
            ) from stop_errors[0]

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
                            await self._mark_disconnected(sid, RuntimeError("ping failed"))
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
                logger.debug(
                    "[MCP] stack.aclose() in _mark_disconnected for %s: %s", server_id, exc
                )
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
                    logger.info("[MCP] server=%s stderr: %s", server_name, masked.strip())
            except Exception as exc:
                logger.debug("[MCP] stderr reader error for %s: %s", server_id, exc)
            await asyncio.sleep(5)

    # ─── 启停所有 server ───

    async def start_all_enabled(self, configs: list[tuple[str, McpServerConfigPublic]]):
        """并发启动所有 enabled server，失败标 failed 但不阻塞（E7 try/except）。"""
        results = await asyncio.gather(
            *[self._safe_start(server_id, config) for server_id, config in configs],
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
        """并发停止所有 running 或 starting server。"""
        with self._lock:
            server_ids = list(set(self._sessions) | set(self._startup_attempts))
        results = await asyncio.gather(
            *[self._stop_server_coro(sid) for sid in server_ids],
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError(f"停止 {len(failures)} 个 MCP server 失败") from failures[0]

    def shutdown(self):
        """停止 server、排空后台任务并关闭事件循环线程。

        Raises:
            RuntimeError: 清理失败，或事件循环线程在 deadline 后仍未退出。
        """
        loop = self._event_loop
        thread = self._event_loop_thread
        drain_error: Exception | None = None
        if loop is None or loop.is_closed():
            return

        if thread is not None and thread.is_alive():
            if threading.current_thread() is thread:
                # 不能同步等待自身；安排有序 shutdown，协程完成后再 stop。
                if self._shutdown_task is None or self._shutdown_task.done():
                    self._shutdown_task = loop.create_task(
                        self._shutdown_on_event_loop(),
                        name="mcp-event-loop-shutdown",
                    )
                    self._shutdown_task.add_done_callback(self._on_event_loop_shutdown_done)
                return

            drain_future = asyncio.run_coroutine_threadsafe(
                self._shutdown_on_event_loop(),
                loop,
            )
            try:
                drain_future.result(
                    timeout=(
                        _MCP_STOP_TIMEOUT_SECONDS
                        + _MCP_STARTUP_CLEANUP_TIMEOUT_SECONDS
                        + 3 * _MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS
                        + _MCP_SHUTDOWN_BRIDGE_GRACE_SECONDS
                    )
                )
            except Exception as exc:
                drain_error = exc
                logger.warning("[MCP] draining event loop tasks failed: %s", exc)

            if thread.is_alive():
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except RuntimeError:
                    # loop 可能刚由所属线程关闭。
                    pass
            thread.join(timeout=5)
            if thread.is_alive():
                logger.error("[MCP] event loop thread did not exit during shutdown")
                raise RuntimeError("MCP 事件循环线程未能退出") from drain_error

        if not loop.is_running() and not loop.is_closed():
            loop.close()
        if drain_error is not None:
            raise RuntimeError("MCP 事件循环任务清理失败") from drain_error

    async def _shutdown_on_event_loop(self) -> None:
        """在 MCP loop 内按 stop → drain → stop-loop 顺序完成关闭。"""
        shutdown_errors: list[Exception] = []
        try:
            try:
                await self.stop_all()
            except Exception as exc:
                shutdown_errors.append(exc)
            try:
                await self._drain_event_loop_tasks()
            except Exception as exc:
                shutdown_errors.append(exc)
            if len(shutdown_errors) == 1:
                raise shutdown_errors[0]
            if shutdown_errors:
                for secondary_error in shutdown_errors[1:]:
                    logger.error(
                        "[MCP] additional shutdown failure: %s",
                        secondary_error,
                        exc_info=(
                            type(secondary_error),
                            secondary_error,
                            secondary_error.__traceback__,
                        ),
                    )
                raise RuntimeError(
                    f"MCP shutdown 的 {len(shutdown_errors)} 个阶段失败"
                ) from shutdown_errors[0]
        finally:
            loop = asyncio.get_running_loop()
            # 排到下一轮，让当前 Task 的 done callback（含线程桥 Future）先落地。
            loop.call_soon(loop.stop)

    @staticmethod
    def _on_event_loop_shutdown_done(task: asyncio.Task[None]) -> None:
        """显式观察 loop-thread shutdown 的异步失败，避免未检索异常。"""
        if task.cancelled():
            logger.error("[MCP] event-loop shutdown task was cancelled")
            return
        error = task.exception()
        if error is not None:
            logger.error(
                "[MCP] event-loop shutdown failed: %s",
                error,
                exc_info=(type(error), error, error.__traceback__),
            )

    @staticmethod
    async def _cancel_tasks_with_deadline(
        tasks: set[asyncio.Task[Any]],
        *,
        timeout: float,
    ) -> set[asyncio.Task[Any]]:
        """取消并有界收割一批 Task，返回仍拒绝退出的 survivor。"""
        active = {task for task in tasks if not task.done()}
        for task in active:
            task.cancel()
        if not active:
            return set()
        done, pending = await asyncio.wait(active, timeout=timeout)
        if done:
            await asyncio.gather(*done, return_exceptions=True)
        return set(pending)

    async def _drain_event_loop_tasks(self) -> None:
        """取消并等待当前 MCP loop 上的后台任务，避免 pending task 被销毁。"""
        current = asyncio.current_task()
        startup_cleanups = [task for task in self._startup_cleanup_tasks if not task.done()]
        if startup_cleanups:
            _, still_pending = await asyncio.wait(
                startup_cleanups,
                timeout=_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS,
            )
            if still_pending:
                logger.warning(
                    "[MCP] %d startup cleanup task(s) still pending at shutdown "
                    "(orphan-process risk)",
                    len(still_pending),
                )

        survivors = {
            task for task in asyncio.all_tasks() if task is not current and not task.done()
        }
        for cancel_round in range(1, 3):
            if not survivors:
                break
            survivors = await self._cancel_tasks_with_deadline(
                survivors,
                timeout=_MCP_SHUTDOWN_CLEANUP_WAIT_SECONDS,
            )
            if survivors:
                logger.warning(
                    "[MCP] %d task(s) survived shutdown cancellation round %d",
                    len(survivors),
                    cancel_round,
                )
        if survivors:
            raise RuntimeError(f"MCP shutdown 有 {len(survivors)} 个后台任务拒绝在 deadline 内退出")
