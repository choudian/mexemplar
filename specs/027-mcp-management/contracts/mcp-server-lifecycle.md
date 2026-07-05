# Contract: MCP Server Lifecycle

**Feature**: 027-mcp-management
**Date**: 2026-07-04
**Updated**: 2026-07-04 (R2 critique fixes: N1/N2/N3/N4/N7/N15 — 对齐 SDK 实际 API)

## 概述

MCP server 子进程的完整生命周期管理，包括启动、连接、健康检查、断连处理、重连和停止。

## 参与者

- **McpServerService**: 业务层编排，管理"配置 → 启动 → 运行 → 停止"全流程
- **McpProcessManager**: 进程级单例，管理所有 server 子进程的 asyncio 生命周期
- **McpServerRepository**: 数据层，持久化 server 配置和状态缓存
- **UnifiedConfigManager**: 凭证读写，合并 secret 值

## 核心设计决策（SDK API Spike + 源码验证）

基于 `mcp v1.28.1` 实际源码（`.venv/.../mcp/client/stdio/__init__.py` + `session.py` + `os/win32/utilities.py`）：

1. **SDK 拥有子进程完整生命周期**：`stdio_client(StdioServerParameters(command, args, env))` 内部自己 spawn 子进程，**不接受外部 subprocess**（N1）。我们只传 `StdioServerParameters`，不调 `create_subprocess_exec`。
2. **Windows 进程清理依赖 SDK Job Object**：SDK 在 spawn 前创建 Job Object（`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`），`stdio_client.__aexit__` 内部调 `TerminateJobObject`（N2）。我们的 `_terminate_tree` 仅作 `stack.aclose()` 失败时的 fallback。
3. **stderr 通过 `errlog` TextIO 接收**：`stdio_client(server, errlog=...)` 接受一个 TextIO-like 对象转发子进程 stderr，**不暴露 stderr 管道**（N3）。我们传入自定义 `_StderrCapture` 对象，不读管道。
4. **进程死亡检测靠 ping + call_tool 失败**：`stdio_client.__aexit__` 只在 `event.set()` 让控制流离开 `async with` 块时才执行，进程死了我们感知不到（N4）。改为 ping 60s + call_tool 失败即时标记。
5. **`read_timeout_seconds` 接受 `timedelta`**：`ClientSession.__init__` 和 `call_tool` 的 `read_timeout_seconds: timedelta | None`，传 int 会 raise TypeError（N7）。
6. **所有 `from mcp import ...` 延迟导入**：避免 SDK 不可用时阻塞 sidecar 启动（E7）。

## 状态机

```
                    ┌──────────────┐
                    │   created    │ (DB row, enabled=True)
                    └──────┬───────┘
                           │ start_server()
                           ▼
                    ┌──────────────┐
               ┌───│   starting   │───┐
               │   └──────┬───────┘   │
               │          │           │ initialize() 失败
               │          │ initialize() 成功
               │          ▼           │
               │   ┌──────────────┐   │
               │   │   running    │◀──┘ (ping/call 失败时也转 disconnected)
               │   └──────┬───────┘
               │          │
    ping/call 失败     用户停止
               │          │
               ▼          ▼
        ┌──────────────┐  ┌──────────────┐
        │ disconnected │  │    failed    │
        └──────┬───────┘  └──────────────┘
               │ 手动 reconnect (stop+start)
               ▼
           ┌──────────────┐
           │   stopped    │ (enabled=False 或删除)
           └──────────────┘
```

**断连即时检测**（N4 修正）：
- **call_tool 失败**：handler 捕获异常立即标记 disconnected + 返回错误 envelope（用户在对话中感知）
- **ping 失败**：60s 周期兜底（用户不在对话中也能检测）
- ~~子进程 exit 回调即时检测~~：SDK 限制不可行，列为 future work

## 操作契约

### 启动 Server

```python
from datetime import timedelta
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

async def _start_server_coro(self, server_id: str, public_config: McpServerConfigPublic):
    """在 MCP 事件循环上执行的实际启动逻辑。"""
    # 1. 在 McpProcessManager 内部完成 public config → launch payload 转换（N17）
    launch_payload = self._build_launch_payload(public_config)

    # 2. 构造 StdioServerParameters（SDK 自己 spawn 子进程，N1）
    params = StdioServerParameters(
        command=launch_payload.command,
        args=launch_payload.args,
        env=launch_payload.merged_env,  # 含 secret 的合并 env
        encoding="utf-8",
        encoding_error_handler="replace",  # N3/R6: Windows 中文容错
    )

    # RC1: stderr 用 tempfile（有 fileno，subprocess 接受），不用纯 TextIO
    stderr_file = tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace")
    stop_event = asyncio.Event()
    stack = AsyncExitStack()

    try:
        # 3. stdio_client 自己 spawn 子进程 + 提供 read/write 流（N1）
        #    RC1: errlog=stderr_file（必须是 file-like with fileno()）
        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(params, errlog=stderr_file)
        )
        # 4. RC2: ClientSession MUST 进 async with（__aenter__ 才 start_soon receive_loop）
        #    不进 async with → receive_loop 不启动 → send_request hang → initialize() timeout
        session = await stack.enter_async_context(
            ClientSession(
                read_stream, write_stream,
                read_timeout_seconds=timedelta(seconds=30),  # N7: timedelta
            )
        )
        await session.initialize()

        # 5. RC4: 用 _SdkSessionAdapter 包装，存 Protocol 类型（测试可注入 FakeMcpSession）
        adapter = _SdkSessionAdapter(session)
        sdk_tools_result = await adapter.list_tools()
        tools = [_convert_sdk_tool(t) for t in sdk_tools_result]  # RC9: SDK → 业务 McpToolInfo

        # 6. 缓存 adapter（Protocol 类型）+ stack + stop_event
        self._sessions[server_id] = adapter  # dict[str, McpSessionProtocol]
        self._stacks[server_id] = stack
        self._stop_events[server_id] = stop_event
        self._stderr_files[server_id] = stderr_file

        # 7. 更新 DB 状态 + 注册工具
        await self._on_server_started(server_id, tools)
        await self._registry.register_server_tools(server_id, slug, tools, is_preset)

        # 8. 启动 stderr 定时读取任务（RC1: 从 tempfile 提取脱敏记日志）
        self._event_loop.create_task(self._stderr_reader(server_id))

        # 9. 阻塞保持上下文（长连接）
        await stop_event.wait()
    except Exception as exc:
        # N15: task group 内部异常（server 崩溃/主动关 stdout）→ 标 disconnected
        await self._mark_disconnected(server_id, exc)
    finally:
        # 退出时清理 stack（SDK Job Object 终止子进程，N2）
        await stack.aclose()
        self._sessions.pop(server_id, None)
        self._stacks.pop(server_id, None)
        self._stop_events.pop(server_id, None)
        self._stderr_files.pop(server_id, None)
        stderr_file.close()
```

**前置条件**: server 存在且 enabled=True，无"待补"占位符
**后置条件**: 子进程运行（SDK 管理），ClientSession 已初始化（RC2 async with），工具已注册
**失败模式**: `initialize()` 失败 → status=failed + last_error_message + suggestion + emit `tools.changed`（RC11）；${VAR} 未填 → 拦截不启动

**SDK import 隔离**：所有 `from mcp import ...` 必须在函数内部延迟导入。如果 import 失败，`McpProcessManager` 初始化标记 `sdk_available=False`，CRUD API 仍可工作（只不能启动/测试连接），UI 显示"MCP 运行时不可用"。

### 停止 Server

```python
async def _stop_server_coro(self, server_id: str):
    """在 MCP 事件循环上执行的实际停止逻辑。"""
    stop_event = self._stop_events.get(server_id)
    stack = self._stacks.get(server_id)
    if stop_event is not None:
        stop_event.set()  # 让 _start_server_coro 的 event.wait() 解除阻塞
    if stack is not None:
        # SDK 的 stdio_client.__aexit__ 内部走 terminate_windows_process_tree（Job Object，N2）
        await stack.aclose()
    # 注销工具 + 更新状态
    await self._registry.unregister_server_tools(server_id)
    await self._on_server_stopped(server_id)
    # stderr_file 由 _start_server_coro 的 finally 关闭，这里不重复
```

**进程清理策略（N2）**：
- **主要**：`stack.aclose()` 触发 SDK `stdio_client.__aexit__` → Windows Job Object `TerminateJobObject` / POSIX 进程组终止
- **Fallback**：仅当 `stack.aclose()` 自身超时（15s）或抛异常时，用 SDK 暴露的 process.pid 调 `_terminate_tree`（taskkill /T /F）兜底
- **幂等性**：已停止的 server 重复调用不报错

**stop_server 时序（N5）**：
```python
def stop_server(self, server_id: str) -> None:
    """同步入口（可从任意线程调用）。"""
    try:
        future = asyncio.run_coroutine_threadsafe(
            self._stop_server_coro(server_id), self._event_loop
        )
        future.result(timeout=15)  # N5: 明确超时
    except Exception as exc:
        # stack.aclose() 超时/失败：标 failed + 记 warning，不强制 taskkill（SDK 会自清理）
        logger.warning("[MCP] stop_server %s timed out/failed: %s", server_id, exc)
```

### 健康检查

```python
async def _health_check_coro(self, server_id: str) -> bool:
    # RC4: session 是 McpSessionProtocol（send_ping 返回 bool，内部转 SDK EmptyResult）
    session = self._sessions.get(server_id)
    if session is None:
        return False
    return await session.send_ping()  # Protocol 方法，返回 bool
```

**检测机制**（N4 修正）：
1. **call_tool 失败即时检测**：handler 捕获连接异常立即标记 disconnected + 返回错误 envelope
2. **定时 ping 兜底**：每 60s 对所有 running server 执行一次 `send_ping()`

**失败处理**: 标记 disconnected + 调 `_stop_server_coro` 清理残留子进程（SDK Job Object），不等待手动 reconnect

### 重连 Server

```python
def reconnect_server(self, server_id: str):
    """stop + start。"""
    self.stop_server(server_id)
    return self.start_server(server_id)
```

**事件通知（P2-MA5）**：`reconnect_server()` 成功后 MUST emit `tools.changed`（工具重新注册，见 mcp-tool-registration.md 的触发条件）。前端通过此事件触发 toast"GitHub server 已重连"。

### 调用工具

```python
async def _call_tool_coro(self, server_id: str, tool_name: str, arguments: dict) -> McpCallResult:
    """在 MCP 事件循环上执行。返回业务层 McpCallResult（N9，不含 SDK 类型）。"""
    # RC4: _sessions 存的是 McpSessionProtocol（_SdkSessionAdapter），不是 raw ClientSession
    session = self._sessions.get(server_id)  # dict[str, McpSessionProtocol]
    if session is None:
        raise McpServerDisconnectedError(server_id)
    try:
        # session 是 McpSessionProtocol，call_tool 返回业务 McpCallResult（内部已转 SDK 类型）
        return await session.call_tool(tool_name, arguments)
    except McpToolSchemaValidationError:
        raise  # RC3: SDK schema 校验失败，直接向上抛（在 _SdkSessionAdapter 内部识别）
    except (asyncio.TimeoutError, McpError) as exc:
        # 连接断开/超时
        await self._mark_disconnected(server_id, exc)
        raise McpServerDisconnectedError(server_id) from exc
```

**前置条件**: server 处于 running 状态
**超时**: 30 秒（SDK 原生 `read_timeout_seconds=timedelta(seconds=30)`）
**串行语义（N16/RC7 修正）**：SDK 内部 send 步骤用 0-buffer memory stream 串行，但 response 等待并行（多 call_tool 可同时 in-flight）；MCP 工具的实际串行保证来自 N11 的 `is_concurrency_safe=False` + AgentLoop 不并发批次，不依赖 SDK 行为。

## 事件循环线程管理

### 初始化

```python
def __init__(self):
    self._sdk_available = self._check_sdk_available()  # 延迟 import 检测
    self._event_loop = asyncio.new_event_loop()
    self._event_loop_thread = threading.Thread(target=self._run_loop, daemon=True)
    self._event_loop_thread.start()

def _run_loop(self):
    while True:
        try:
            self._event_loop.run_forever()
            break  # 正常 stop
        except Exception:
            # E6/N15: 全局异常后重建循环
            logger.exception("[MCP] event loop crashed, rebuilding")
            self._event_loop = asyncio.new_event_loop()
```

### 线程安全不变式（E2）

1. **MCP 事件循环线程完全自包含**：只做 asyncio I/O，**绝不回调到主线程或等待主线程同步原语**
2. **pre_hook 在 handler 调用之前执行**（在 AgentLoop worker 线程侧），不在 MCP 事件循环线程中
3. **`run_coroutine_threadsafe` 提交的 coroutine 不回调到主线程**
4. **`future.result(timeout=30)` 必须处理 `CancelledError`/`TimeoutError`**

### 崩溃恢复（E6）

```python
def call_tool_sync(self, server_id, tool_name, args) -> McpCallResult:
    if not self._event_loop_thread.is_alive():
        self._rebuild_event_loop()
    future = asyncio.run_coroutine_threadsafe(
        self._call_tool_coro(server_id, tool_name, args), self._event_loop
    )
    return future.result(timeout=30)
```

## Sidecar 启动时行为

```python
# FastAPI lifespan startup
try:
    # start_all_enabled 在后台异步执行，不阻塞 sidecar 主界面
    asyncio.run_coroutine_threadsafe(
        mcp_service.start_all_enabled(), mcp_service._event_loop
    )
except Exception:
    logger.exception("[MCP] startup failed, MCP degraded")
    # MCP 功能降级模式，不影响 sidecar
```

**启动不阻塞**：`start_all_enabled()` 在后台异步执行（`asyncio.gather` 并发，非串行），sidecar 主界面立即可用。MCP 工具 tab 显示"正在连接..."状态，连接完成后通过 `tools.changed` 事件自动更新。

**预置 server 引导（N19）**：lifespan 启动时检查 `preset_slug IS NOT NULL` 的行数，缺失的从硬编码 default（`mcp_presets.py`）upsert。用户修改过的预置 server（`preset_slug` 不变但其他字段变了）不强制覆盖。

## Sidecar 关闭时行为

```python
# FastAPI lifespan shutdown
async def shutdown():
    # 并发停止所有 running server，超时 10s
    await asyncio.wait_for(mcp_service.stop_all(), timeout=10)
```

## stderr 收集（RC1 修正：tempfile 方案）

`stdio_client(errlog=...)` 要求 errlog 是 file-like 且**有 `fileno()`**（subprocess.Popen 在非 PIPE/DEVNULL 分支调 `stderr.fileno()`）。纯 Python TextIO（无 fileno）/ StringIO 会 spawn 阶段 TypeError。

**方案**：用 `tempfile.TemporaryFile()`（有 fileno）做 errlog，启动定时读取任务提取新内容脱敏记日志：

```python
async def _stderr_reader(self, server_id: str):
    """定时从 stderr tempfile 提取新内容，脱敏后记日志（RC1）。"""
    server_name = self._server_names.get(server_id, server_id)
    stderr_file = self._stderr_files.get(server_id)
    while server_id in self._sessions and stderr_file is not None:
        try:
            stderr_file.seek(0, 2)  # seek to end
            pos = stderr_file.tell()
            # 回退到上次读取位置
            last_pos = self._stderr_read_pos.get(server_id, 0)
            stderr_file.seek(last_pos)
            new_data = stderr_file.read()
            self._stderr_read_pos[server_id] = pos
            stderr_file.seek(pos)  # 恢复 write 位置
            if new_data.strip():
                masked = _mask_secrets(new_data)  # 脱敏 TOKEN/KEY/SECRET
                logger.info("[MCP] server=%s stderr: %s", server_name, masked.strip())
        except Exception:
            pass
        await asyncio.sleep(5)  # 每 5s 读一次
```

**为什么不用纯 TextIO（RC1）**：subprocess.Popen 透传 errlog 时调 `stderr.fileno()`，纯 Python TextIO 无 fileno → AttributeError；StringIO.fileno() raise UnsupportedOperation。`sys.stderr` 能用是因为它是 TextIOWrapper 包 OS fd 2。

**tempfile 位置**：`tempfile.gettempdir()` 下，随 server 停止自动 close + 删除。

**encoding（P2-R6）**：`StdioServerParameters(encoding="utf-8", encoding_error_handler="replace")` + tempfile `errors="replace"` 容错 Windows cp936 中文。

## 错误分类映射

后端将常见原始错误映射为用户可理解的操作指引，附在 `McpServerResponse.suggestion` 字段中（P11）。

### 启动阶段错误映射

| 原始错误模式 | 用户友好建议 |
|-------------|------------|
| `spawn ENOENT` / `FileNotFoundError` | "找不到命令，请确认已安装并添加到系统 PATH" |
| `ECONNREFUSED` / `ConnectionRefusedError` | "无法连接到 MCP server，请检查网络或配置" |
| `401 Unauthorized` / `authentication` | "API token 无效或已过期，请检查凭证设置" |
| `ETIMEDOUT` / `TimeoutError` | "连接超时，请检查网络或 server 是否可达" |
| `ModuleNotFoundError` / `ImportError` | "MCP server 运行时不可用，请确认依赖已安装" |
| 其他 | "MCP server 启动失败，请检查配置或查看日志" |

### 运行时错误映射（N14 + RC3 修正）

`_SdkSessionAdapter.call_tool` 内部识别 SDK schema 校验错误（RC3：实际消息前缀不是 "validate"）：

```python
# 在 mcp_process_manager.py 的 _SdkSessionAdapter 内部（RC3）
async def call_tool(self, name, arguments) -> McpCallResult:
    try:
        sdk_result = await self._sdk_session.call_tool(
            name, arguments=arguments, read_timeout_seconds=timedelta(seconds=30))
        return _convert_sdk_call_result(sdk_result)
    except RuntimeError as exc:
        msg = str(exc).lower()
        # RC3: SDK 实际错误消息前缀（源码验证），不含 "validate"
        if ("structured content" in msg or "invalid schema" in msg
                or "output schema" in msg):
            raise McpToolSchemaValidationError(name, str(exc))
        raise  # 其他 RuntimeError 按连接错误处理
```

| 原始错误 | suggestion |
|---------|------------|
| `McpServerDisconnectedError` | "server 连接已断开，去工具列表重连后重试" |
| `McpToolTimeoutError` | "工具调用超时（30s），server 可能过载或不可达" |
| `McpToolSchemaValidationError`（RC3/N10） | "工具执行成功但输出格式异常，可能是 server 版本不匹配" |
| `McpCircuitBreakerOpenError`（E8） | "server 连续失败，请重连后重试" |
| `CancelledError` | "调用被取消" |

### SDK 类型转换函数位置（RC8/RC9）

`_convert_sdk_call_result` / `_convert_sdk_tool` 定义在 `mcp_process_manager.py` 内部（SDK 适配层），延迟 import SDK types：

```python
# mcp_process_manager.py 内部（不暴露到业务层）
def _convert_sdk_call_result(sdk_result) -> McpCallResult:
    """SDK CallToolResult → 业务 McpCallResult。"""
    from mcp.types import TextContent, ImageContent  # 延迟 import
    text_parts = [c.text for c in sdk_result.content if isinstance(c, TextContent)]
    image_count = sum(1 for c in sdk_result.content if isinstance(c, ImageContent))
    return McpCallResult(
        is_error=sdk_result.isError,
        text_parts=text_parts,
        image_count=image_count,
        structured_data=sdk_result.structuredContent,
    )

def _convert_sdk_tool(sdk_tool) -> McpToolInfo:
    """SDK Tool → 业务 McpToolInfo。"""
    return McpToolInfo(name=sdk_tool.name, description=sdk_tool.description or "",
                       input_schema=sdk_tool.inputSchema or {})
```

**字段产生时机（N14）**：
- **启动失败**：`last_error_message`（脱敏摘要）+ `suggestion` + emit `tools.changed`（RC11）
- **调用失败**：`last_error_message` + `suggestion` + 进程级断路器计数 +1
- **ping 失败**：`last_known_status=disconnected` + `suggestion`
- **断路器状态 `circuit_breaker_open`**：进程级内存，DB 只存最后已知快照（重启后复位为 False，N14 标注）

### Sidecar 启动失败前端通知（RC11）

`start_all_enabled()` 中每个 server 的 `update_status(status="failed", ...)` 写 DB 后，**MUST emit `backend.resync_required`**（不是 `tools.changed`，因为工具列表为空不算工具变更），前端 MCP tab 据此刷新 server 状态列表，显示失败的 server + suggestion。
