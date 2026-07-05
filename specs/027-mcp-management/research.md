# Research: MCP Management

**Feature**: 027-mcp-management
**Date**: 2026-07-04
**Status**: Complete（SDK API Spike 已验证，2026-07-04 更新）

## SDK API Spike 确认（2026-07-04）

通过 `uv add "mcp>=1.27,<2"` 安装 `mcp v1.28.1` + `anyio v4.14.1` 并验证 API 签名：

| 项目 | Spike 结果 |
|------|-----------|
| `ClientSession.__init__` | `(read_stream, write_stream, read_timeout_seconds, sampling_callback, elicitation_callback, list_roots_callback, logging_callback, ...)` — 接受 anyio MemoryObjectStream，**不支持裸 subprocess 管道** |
| `stdio_client` + `StdioServerParameters` | 可用 ✅ — 这是生成 anyio 流的正确方式 |
| `call_tool` | `(name, arguments, read_timeout_seconds, progress_callback, meta)` — **支持 `read_timeout_seconds`**（不是 `read_transport_timeout_seconds`） |
| `list_tools` | `(cursor, params)` |
| `send_ping` | 无额外参数 |
| `anyio` 版本 | `4.14.1`（与 FastAPI/httpx 间接引入的 anyio 兼容） |

**结论**：必须用 `stdio_client` 上下文管理器（通过 `AsyncExitStack` 管理长连接生命周期），不能用裸 `asyncio.create_subprocess_exec` + `StdioReadWriter`（此 API 不存在）。

## R1: Python MCP SDK v1.x Client API

### Decision

使用 Python MCP SDK v1.x（`mcp>=1.27,<2`）的 `ClientSession` + `stdio_client` 异步 API 连接 MCP server 子进程。

### Rationale

- v1.x 是当前唯一稳定的生产版本线（最新 v1.28.1，2026-06-26）
- v2 仍为 alpha/beta，官方明确说 "Do not use v2 in production"，稳定版目标 2026-07-27
- v1.x 在 `v1.x` 分支继续接收关键 bug 修复
- 必须在依赖中 pin `<2` 上界

### 核心用法

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

server_params = StdioServerParameters(
    command="npx",
    args=["-y", "@modelcontextprotocol/server-filesystem", "/path"],
    env={"KEY": "value"},
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("tool_name", arguments={"a": 1})
        if result.isError:
            # 处理错误
            pass
```

### 关键发现

1. **全异步**: `ClientSession` 是 `async with` 上下文管理器，`list_tools` / `call_tool` 都是 `await` 调用
2. **双重上下文**: 外层 `stdio_client` 管理子进程 + 读写流，内层 `ClientSession` 管理协议会话
3. **错误处理**: `call_tool` 返回 `CallToolResult`，`isError=True` 表示工具执行错误
4. **内容类型**: 结果 `content` 列表可含 `TextContent`、`ImageContent`、`EmbeddedResource`
5. **Ping**: `session.send_ping()` 可用于活性检测，超时抛异常
6. **日志回调**: `ClientSession` 支持 `logging_callback` 接收 server 日志

### 与现有框架的适配挑战

- **异步 vs 同步**: 现有 `ToolDefinition.handler` 是同步函数；MCP SDK 是纯异步。需要 `asyncio.run()` 或独立事件循环桥接。
- **子进程生命周期**: `stdio_client` 是上下文管理器，退出时自动关闭子进程；但 MCP server 需要"配置后持续运行"，不能随工具调用开关。需要自定义长期运行的子进程管理。
- **工具 schema 格式**: MCP 的 `Tool.inputSchema` 兼容 JSON Schema，与 OpenAI function calling 的 `parameters` 格式基本一致，可直接映射。

### Alternatives Considered

- **v2 SDK**: 生产不可用，排除
- **直接 subprocess + JSON-RPC**: 绕过 SDK 自己实现 MCP 协议，维护成本高且不必要
- **mcp-proxy 或其他 wrapper**: 引入额外依赖，不如直接用官方 SDK

---

## R2: MCP JSON 配置格式

### Decision

支持三种粘贴导入格式：Claude Desktop 嵌套 `mcpServers` 格式、裸 stdio server 对象、裸 HTTP server 对象。

### Rationale

用户最可能从 Claude Desktop / Claude Code / 其他 MCP 客户端复制配置，格式多样需兼容。

### 格式规范

#### 格式 1: Claude Desktop 嵌套 `mcpServers` 格式（可能含多个 server）

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
      "env": {"KEY": "value"}
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"}
    }
  }
}
```

#### 格式 2: 裸 stdio server 对象

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
  "env": {"KEY": "value"}
}
```

#### 格式 3: 裸 HTTP/streamable HTTP server 对象（MVP 后续扩展）

```json
{
  "url": "http://localhost:8000/mcp",
  "headers": {"Authorization": "Bearer xxx"}
}
```

### 关键字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `command` | stdio 必填 | 可执行命令 |
| `args` | 否 | 命令参数数组 |
| `env` | 否 | 环境变量对象；secret 值走 `UnifiedConfigManager` |
| `url` | HTTP 必填 | Server URL |
| `headers` | 否 | HTTP 请求头；secret 值走 `UnifiedConfigManager` |

### `${VAR}` 占位符

Claude Desktop 配置中常见 `${VAR}` 占位符引用系统环境变量。解析规则：
1. 优先读系统环境变量 `os.environ.get("VAR")`
2. 读不到标"待补"（`pending_env` 状态）
3. 保存时拦截：有"待补"项则提示用户填写，不落库

### Alternatives Considered

- **只支持 mcpServers 格式**: 过于严格，用户粘贴裸对象时需手动包裹
- **自动猜测 URL vs command**: 不可靠，用 `url` 字段有无区分 HTTP vs stdio

---

## R3: MCP 工具映射到 ToolDefinition

### Decision

MCP 工具在 `McpServerService` 启动时自动发现并注册为 `ToolDefinition`，工具名带 `mcp__<server_slug>__<tool_name>` 前缀，handler 通过同步桥接调用异步 MCP SDK。**双轨注册**：预置 server 全量注入 `tool_factory()`（保住"配置即可用"），用户自定义 server 走独立 `McpToolRegistry` 路径 + `search_tools(kind="mcp")` 按需发现。

### Rationale

- 复用现有 `ToolDefinition` + `AgentLoop` 工具执行框架，不引入独立调用路径
- `mcp__` 前缀天然与内置工具/用户技能隔离，避免名称冲突
- 同步桥接是因为 `ToolDefinition.handler` 是同步函数，而 MCP SDK 是异步的
- **双轨制（N8/X1/P2-MA1 修正）**：DynamicToolManager 无 MCP 注入点（9 处横切改动），MVP 避开；预置 server（工具数少）全量注入保住核心承诺，自定义 server 走独立 LRU 不争用 DynamicToolManager
- `server_slug` 规范化压缩连续 `_`，禁止 `__` 出现，避免工具名解析歧义（E21）

### 映射方案

```
MCP Tool (server-side)           ToolDefinition (Exemplar-side)
─────────────────────           ──────────────────────────────
name: "list_prs"          →     name: "mcp__github__list_prs"
description: "List PRs"   →     schema.parameters.description
inputSchema: {type:object}→     schema.parameters (JSON Schema → FC)
handler: [MCP call_tool]  →     handler: sync_bridge(mcp_call)
                                 has_side_effects: True (保守默认)
                                 is_concurrency_safe: False
                                 pre_hook: mcp_risk_check (高危确认穿透)
```

### 注册路径

MCP 工具 **不走** `DynamicToolManager` 的懒加载/搜索路径（那是用户技能的），而是直接注入 `tool_factory()` 返回的工具列表：

1. `McpServerService.start_all()` → 发现所有 enabled server 的工具
2. 构建 `ToolDefinition` 列表，存入进程级 `McpToolRegistry`
3. `ToolRegistry.build_assistant_tools()` 和 `build_delegated_executor_tools()` 中追加 `McpToolRegistry.get_all_tools()`
4. `search_tools` / `get_tool_detail` 扩展 kind 支持 `"mcp"`，从 `McpToolRegistry` 搜索

### 异步桥接方案

```python
def _create_sync_handler(server_id: str, tool_name: str):
    """为 MCP 工具创建同步 handler，内部桥接到异步 MCP 调用。"""
    def handler(**kwargs) -> str:
        mcp_service = get_mcp_server_service()
        loop = mcp_service.get_or_create_event_loop()
        result = loop.run_until_complete(
            mcp_service.call_tool(server_id, tool_name, kwargs)
        )
        return result  # 返回统一 envelope JSON 字符串
    return handler
```

- 使用 `McpServerService` 管理的独立事件循环（`asyncio.new_event_loop()`），不在主线程事件循环上运行
- `call_tool` 内部复用已建立的 `ClientSession`，不需要每次重建连接
- 超时保护：工具调用设 30s 超时，超时返回错误 envelope

### Alternatives Considered

- **MCP 工具走 DynamicToolManager 懒加载**: 不合适——用户技能是"搜索+按需激活"，MCP 工具是"server 启用就全量暴露"，生命周期管理完全不同
- **每个 MCP 工具一个子进程连接**: 资源浪费，同 server 的工具共享一个连接
- **用 `asyncio.run()` 每次创建新循环**: 有风险，`asyncio.run()` 不能嵌套在已有事件循环内

---

## R4: MCP Server 子进程生命周期管理

### Decision

使用 MCP SDK 的 `stdio_client` + `StdioServerParameters` + `AsyncExitStack` 管理长连接子进程。在独立后台线程的事件循环中持有 `stdio_client` 上下文（通过 `asyncio.Event` 阻塞保持上下文不退出），实现"配置后持续运行"。

### Rationale

- **SDK API Spike 确认**：`ClientSession` 接受 anyio MemoryObjectStream（由 `stdio_client` 生成），不支持裸 subprocess 管道 → 必须用 `stdio_client`
- `AsyncExitStack` 管理长连接生命周期：进入时建立子进程 + session，退出时自动清理
- 在后台线程事件循环中 `await` 一个永不完成的 `asyncio.Event`，保持上下文不退出，实现长连接
- 自定义管理支持：进程健康检查、断连重连、优雅停止、超时检测、进程树清理

### 生命周期状态机

```
配置(created) → 启动中(starting) → 运行中(running) ↔ 重连中(reconnecting)
                                    ↓                    ↓
                               停止(stopped)        失败(failed)
```

### 核心设计

```python
class McpProcessManager:
    """管理所有 MCP server 子进程的生命周期。"""

    async def start_server(self, server_id: str, config: McpServerConfig) -> None:
        """启动 MCP server 子进程并建立 ClientSession。"""
        process = await asyncio.create_subprocess_exec(
            config.command, *config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **resolved_env},
        )
        session = ClientSession(
            StdioReadWriter(process.stdout, process.stdin)
        )
        await session.initialize()
        # 缓存 process + session

    async def stop_server(self, server_id: str) -> None:
        """优雅停止：关闭 session → 终止子进程。"""

    async def health_check(self, server_id: str) -> bool:
        """通过 session.send_ping() 检测活性。"""

    async def call_tool(self, server_id: str, tool_name: str, args: dict) -> str:
        """调用工具，含超时保护和错误处理。"""
```

### 健康检查与重连

- **定时 ping**: 每 60s 对 running server 发一次 `send_ping()`，失败标记 disconnected
- **断连标记**: UI 上 server 卡片标灰，工具调用返回错误
- **自动重连**: 不做自动重连（避免静默重试导致状态不一致），用户在 UI 上手动触发"重新连接"
- **sidecar 启动时**: 对所有 enabled server 执行 `start_server`，失败标 failed 但不阻塞启动

### Alternatives Considered

- **复用 ProcessManager**: ProcessManager 是同步 `subprocess.Popen` + 线程读取，不支持异步协议交互
- **用 MCP SDK stdio_client 管理整个生命周期**: 上下文管理器退出即关闭，无法支持长连接
- **自动重连**: 静默重连可能导致工具调用在重连过程中丢失，不如显式手动重连安全

---

## R5: 高危确认穿透

### Decision

MCP 工具的高危操作穿透现有 `_confirm_or_reject` 机制，通过 `pre_hook` 在写操作前触发确认。

### Rationale

- 现有确认协议已经完善：`PendingConfirmation` + `threading.Event` + 非模态浮层 + fail-closed
- MCP 工具没有内置的读写分类，需要启发式判断或保守策略
- 与内置工具确认标准一致，不引入独立的确认路径

### 实现方案

```python
def mcp_tool_pre_hook(context: ToolCallContext) -> PreHookResult | None:
    """MCP 工具 pre-hook：启发式判断高危操作并触发确认。"""
    tool_name = context.tool_name
    # 启发式判断：工具名含写操作关键词 → 需确认
    if _is_likely_write_operation(tool_name, context.args):
        decision = _confirm_or_reject(...)
        if decision != CONFIRM_DECISION_ACCEPTED:
            return PreHookResult(error="User rejected", error_code="confirmation_rejected")
    return None  # 放行

def _is_likely_write_operation(tool_name: str, args: Mapping) -> bool:
    """启发式判断：工具名含写操作关键词视为高危。"""
    write_keywords = {"create", "delete", "update", "write", "push", "merge",
                      "remove", "add", "close", "deploy", "execute"}
    name_lower = tool_name.lower()
    return any(kw in name_lower for kw in write_keywords)
```

### 保守策略

- **默认 `has_side_effects=True`**: 所有 MCP 工具默认标记为有副作用
- **启发式而非确定性**: MCP 工具没有标准化的读写分类，只能靠工具名启发式判断
- **权威关键词集合**（唯一来源在 `contracts/mcp-tool-registration.md` 的 `_is_likely_write_operation`，research.md 引用此处）：`{create, delete, update, write, push, merge, remove, add, close, deploy, execute, fork}`
- **已知误报**：`get_user_created_repos`（含 "create"）会触发不必要的确认
- **已知漏报**：`star_repository`/`follow_user`/`move_file` 是写操作但不含任何关键词——后续改进方向：利用 MCP Tool `annotations.readOnlyHint` 和预置 server 读写分类元数据
- **用户可通过 server 级别禁用**: 不提供单个工具的启用/禁用，但可禁用整个 server
- **免确认场景**: 会话级 `auto_approve` 仍然适用，与内置工具一致

### Alternatives Considered

- **所有 MCP 工具都需确认**: 过于严格，读操作也要确认会严重影响用户体验
- **MCP 工具自带 annotations 判断**: MCP 规范的 `Tool.annotations.readOnlyHint` 是可选的，不能依赖
- **用户手动标记读写分类**: 增加配置负担，MVP 不做

---

## R6: 能力目录集成（双轨制）

### Decision

MCP 工具采用双轨注册（见 contracts/mcp-tool-registration.md）：预置 server 全量注入 `tool_factory()`；用户自定义 server 在能力目录中作为独立 kind `"mcp"` 出现，`search_tools` 扩展支持 `"mcp"` 过滤，`get_tool_detail(selector="mcp:...")` 激活。

### Rationale

- DynamicToolManager 为用户技能/组合设计，无 MCP 注入点（9 处横切改动风险大）
- 双轨制让 MVP 避开 DynamicToolManager 改动：预置 server 直接全量注入 `tool_factory()`，自定义 server 走 `McpToolRegistry` 独立路径
- 自定义 server 的 `search_tools` 分支直接查 `McpToolRegistry`，不碰 DynamicToolManager

### 实现方案

1. `McpToolRegistry`（进程级单例）维护所有 MCP 工具，区分预置（`_preset_tool_names`）和自定义（`_activated_custom` 独立 LRU）
2. `tool_factory()` 末尾追加 `get_preset_tools()` + `get_activated_custom_tools()`
3. `search_tools` handler 增 MCP 分支：kind="all" 合并 MCP 目录项，kind="mcp" 只返回 MCP
4. `get_tool_detail` 增 `mcp:` selector 解析，激活自定义工具到 `_activated_custom`（预置已全量注入无需激活）
5. 能力目录 prompt 段重写：含 MCP 工具计数、deferred 触发引导、result 不可信警告（见 contracts prompt 文案）

### Alternatives Considered

- **全量注入所有 MCP 工具**: 10 server × 50 工具 = 100k token，不可接受
- **MCP 工具走 DynamicToolManager 激活**: 9 处横切改动 + LRU 争用 + 授权过滤缺失，MVP 风险过大
- **预置也走 deferred**: 破坏"配置即可用"核心承诺，预置工具数可控应直接注入

---

## R7: ClientSession 长连接稳定性（E20，已知风险）

### Decision

实现完成后做长连接稳定性验证；如发现泄漏，增加 session 定期重建机制。

### Rationale

- MCP SDK 的 `ClientSession` 主要为短生命周期设计（配合 `async with` 使用），长期持有 session 是否会导致内存泄漏、read buffer 积压或 heartbeat 超时，尚未在生产环境验证
- Exemplar 桌面应用是长期运行进程，MCP server 配置后预期持续可用数小时到数天

### 验证计划

1. 启动 filesystem server，每 30s 调用一次工具，持续 1 小时
2. 观察内存增长、调用延迟变化、ping 响应时间
3. 如发现泄漏：增加 session 定期重建（每 30 分钟主动 stop + start）

### Alternatives Considered

- **完全按需启动**（每次调用拉起，空闲超时关闭）：MVP 首选长连接因为 npx 冷启动慢（首次 30s+）；按需启动适合预编译二进制 server（启动 <2s），后续考虑
- **不验证直接上线**：风险过高，长连接泄漏会导致用户使用一段时间后 MCP 工具逐渐失效

## Summary of Resolved Unknowns

| Unknown | Resolution |
|---------|-----------|
| MCP SDK 版本选择 | v1.x（`mcp>=1.27,<2`），v2 稳定后升级为独立任务；Spike + 源码验证 v1.28.1 + anyio 4.14.1 兼容 |
| SDK 异步 vs 框架同步 | 独立事件循环 + `run_coroutine_threadsafe` 桥接 + `future.result(timeout=30)` |
| 子进程管理方式 | `stdio_client(StdioServerParameters, errlog=_StderrCapture)` + `AsyncExitStack`（SDK 自己 spawn 子进程，不接受外部 subprocess；Windows 用 Job Object 清理） |
| call_tool 超时参数 | `read_timeout_seconds=timedelta(seconds=30)`（源码验证：接受 timedelta 不是 int） |
| 进程死亡检测 | ping 60s + call_tool 失败即时标记（exit 回调不可行，SDK 的 `__aexit__` 只在 event.set() 后执行） |
| stderr 收集 | `stdio_client(errlog=_StderrCapture)` TextIO 对象（SDK 不暴露 stderr 管道） |
| JSON 配置兼容格式 | 三种：嵌套 mcpServers、裸 stdio、裸 HTTP；secret 自动检测启发式 |
| MCP 工具注册路径 | **双轨制**：预置 server 全量注入 `tool_factory()` + 自定义 server 走独立 `McpToolRegistry` 路径（避开 DynamicToolManager 9 处横切改动） |
| SDK 类型隔离 | 业务层 `McpCallResult`/`McpToolInfo` + `McpSessionProtocol`（返回业务类型）；`_SdkSessionAdapter` 在 process_manager 内部做 SDK↔业务适配 |
| 高危确认方案 | pre_hook 启发式判断 + 穿透现有 `_confirm_or_reject`；权威关键词集合在 contracts（research 引用）；标注误报/漏报为有意技术债务 |
| 工具名冲突 | `mcp__<server_slug>__<tool_name>` 前缀天然隔离；slug 规范化禁 `__`；注销按 server_tool_map 映射表 |
| 健康检查 | ping 60s + call_tool 失败即时检测 + 断连清理子进程（SDK Job Object）+ 手动重连 |
| 长连接稳定性 | 实现后做 1 小时稳定性测试，泄漏则加定期重建（E20，已知风险） |
