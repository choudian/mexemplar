# Contract: MCP API Endpoints

**Feature**: 027-mcp-management
**Date**: 2026-07-04

## 概述

MCP server 管理的 typed API endpoints，供前端 CRUD 操作和连接管理。

## Router

`src/desktop_api/routers/mcp_servers.py`，前缀 `/api/mcp-servers`

## Endpoints

### 列出所有 server

```
GET /api/mcp-servers
```

**Response 200**:
```json
[
  {
    "serverId": "mcs_abc123",
    "name": "GitHub",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-github"],
    "url": null,
    "envKeys": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
    "envMissingKeys": [],
    "headerKeys": [],
    "enabled": true,
    "status": "running",
    "toolCount": 15,
    "presetSlug": "github",
    "lastError": null,
    "createdAt": "2026-07-04T10:00:00",
    "updatedAt": "2026-07-04T10:00:00"
  }
]
```

**注意**:
- `envKeys` / `headerKeys` 只返回键名列表，不返回值
- secret 值在 response 中用遮罩表示（`"sk_***"`），通过独立字段 `envPresence` / `headerPresence` 标识存在性
- `envMissingKeys` 列出"待补"的占位符键

### 获取单个 server

```
GET /api/mcp-servers/{server_id}
```

**Response 200**: 同上单个对象
**Response 404**: `{"detail": "MCP server not found"}`

### 添加 server

```
POST /api/mcp-servers
```

**Request**:
```json
{
  "name": "GitHub",
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {
    "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"
  },
  "secretEnvKeys": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
  "presetSlug": null
}
```

**逻辑**:
1. 校验 name 唯一性
2. **secret 自动检测启发式**（E9）：后端对 env/headers 的每个 key 做启发式检测——key 名包含 `TOKEN/KEY/SECRET/PASSWORD/CREDENTIAL/AUTH`（不区分大小写）时自动标记为 secret，即使用户未在 `secretEnvKeys` 中显式声明
3. `secretEnvKeys` / `secretHeaderKeys`（显式声明 ∪ 启发式检测）中的值 → `UnifiedConfigManager.set()`
4. 其余 env/header 值 → `env_json` / `headers_json`
5. secret key 列表 → `secret_env_keys_json` / `secret_header_keys_json` 字段（用于后续合并）
6. `${VAR}` 占位符解析：读系统环境变量，读不到标"待补"
7. 有"待补"项 → 返回 422 + 缺失键列表
8. `transport="http"` → 返回 422（"HTTP transport 尚未支持"，E23）

**Response 201**: 创建的 server 对象
**Response 409**: name 已存在
**Response 422**: 有待补占位符 / HTTP transport / 格式错误

### 从 JSON 粘贴导入

```
POST /api/mcp-servers/import-json
```

**Request**:
```json
{
  "jsonText": "{\"mcpServers\":{\"github\":{\"command\":\"npx\",\"args\":[\"-y\",\"@modelcontextprotocol/server-github\"],\"env\":{\"GITHUB_PERSONAL_ACCESS_TOKEN\":\"ghp_xxx\"}}}}"
}
```

**逻辑**:
1. 解析 JSON，自动检测格式（嵌套 mcpServers / 裸 stdio / 裸 HTTP）
2. 返回解析结果预览（不落库），让用户在表单中确认/编辑

**Response 200**:
```json
{
  "servers": [
    {
      "name": "github",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"},
      "detectedSecretKeys": ["GITHUB_PERSONAL_ACCESS_TOKEN"],
      "placeholderKeys": []
    }
  ]
}
```

**说明**：`detectedSecretKeys` 由后端启发式检测（key 名含 `TOKEN/KEY/SECRET/PASSWORD/CREDENTIAL/AUTH`），返回给前端供用户确认/修改。用户粘贴的 JSON 中直接写了真实 token 的，会被自动识别为 secret 走安全存储。

**Response 422**: JSON 格式无效或不支持的结构

### 更新 server 配置

```
PATCH /api/mcp-servers/{server_id}
```

**Request**:
```json
{
  "name": "GitHub Pro",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_newxxx"},
  "secretEnvKeys": ["GITHUB_PERSONAL_ACCESS_TOKEN"]
}
```

**逻辑**:
1. 合并更新（只改传入的字段）
2. secret 值变更 → 更新 `app_settings`
3. 非 secret 值变更 → 更新 `env_json` / `headers_json`
4. 如果配置变更且 server 正在运行 → 自动重启

**Response 200**: 更新后的 server 对象

### 测试连接

```
POST /api/mcp-servers/{server_id}/test-connection
```

**逻辑**:
1. 临时启动子进程 + ClientSession（通过 `stdio_client` + `StdioServerParameters`，SDK 自己 spawn）
2. 凭证从 `UnifiedConfigManager` 读取并合并到 env，与 start_server 同路径（P2-R5）
3. 调用 `session.initialize()` + `session.list_tools()`
4. 不持久化连接，测试完即关闭（`stack.aclose()` 触发 SDK Job Object 清理）

**超时**：60 秒（P3-MA3：npx 首次下载可能需 30s+，15s 超时会让 GitHub 预置首次测试必失败）。UI 显示进度提示"首次启动可能需 30s+ 下载"。与 30 秒工具调用超时区分。

**Response 200**:
```json
{
  "success": true,
  "toolCount": 15,
  "tools": [
    {"name": "list_prs", "description": "List pull requests"},
    ...
  ]
}
```

**Response 200 (失败)**:
```json
{
  "success": false,
  "error": "Connection refused",
  "toolCount": 0,
  "tools": []
}
```

### 启用/禁用 server

```
POST /api/mcp-servers/{server_id}/enable
POST /api/mcp-servers/{server_id}/disable
```

**enable 逻辑**:
1. 设置 enabled=True
2. 调用 `McpServerService.start_server()`

**disable 逻辑**:
1. 调用 `McpServerService.stop_server()`
2. 设置 enabled=False

**Response 200**: 更新后的 server 对象

### 重连 server

```
POST /api/mcp-servers/{server_id}/reconnect
```

**逻辑**: `McpServerService.reconnect_server()` = stop + start

**Response 200**: 更新后的 server 对象

### 删除 server

```
DELETE /api/mcp-servers/{server_id}
```

**逻辑**:
1. 如果 server 正在运行 → 先停止
2. 清理 `app_settings` 中所有 `mcp.servers.<server_id>.*` 条目
3. 删除 `mcp_servers` 表行

**Response 204**: 无内容
**Response 404**: server 不存在

## Schema 定义

```python
class McpServerCreateRequest(BaseModel):
    name: str
    transport: Literal["stdio", "http"]
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    secretHeaderKeys: list[str] | None = None
    env: dict[str, str] | None = None
    secretEnvKeys: list[str] | None = None
    presetSlug: str | None = None

class McpServerUpdateRequest(BaseModel):
    name: str | None = None
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    secretHeaderKeys: list[str] | None = None
    env: dict[str, str] | None = None
    secretEnvKeys: list[str] | None = None

class McpServerJsonImportRequest(BaseModel):
    jsonText: str

class McpServerResponse(BaseModel):
    serverId: str
    name: str
    transport: str
    command: str | None
    args: list[str] | None
    url: str | None
    envKeys: list[str]
    envMissingKeys: list[str]
    envPresence: dict[str, str]  # key → "set" | "masked" | "placeholder"
    headerKeys: list[str]
    headerMissingKeys: list[str]
    headerPresence: dict[str, str]
    enabled: bool
    status: str | None
    toolCount: int | None
    tools: list[dict] | None  # [{name, description}]，仅 test-connection 返回完整
    presetSlug: str | None
    lastError: str | None
    suggestion: str | None  # 用户友好的错误修复建议（P11，由错误分类映射生成）
    circuitBreakerOpen: bool = False  # 断路器是否打开（E8，连续失败超阈值）
    createdAt: datetime
    updatedAt: datetime

class McpServerTestConnectionResponse(BaseModel):
    success: bool
    toolCount: int
    tools: list[dict]  # [{name, description}]
    error: str | None

class McpServerJsonImportResponse(BaseModel):
    servers: list[McpServerParsedPreview]

class McpServerParsedPreview(BaseModel):
    name: str
    transport: str
    command: str | None
    args: list[str] | None
    url: str | None
    headers: dict[str, str] | None
    env: dict[str, str] | None
    detectedSecretKeys: list[str]
    placeholderKeys: list[str]
```

## 凭证安全

- **请求**: `secretEnvKeys` / `secretHeaderKeys` 标记哪些键的值是 secret（前端可显式声明）
- **自动检测**（E9）：后端对 key 名做启发式检测（含 `TOKEN/KEY/SECRET/PASSWORD/CREDENTIAL/AUTH`），自动标记为 secret
- **存储**: secret 值写入 `UnifiedConfigManager`，不进入 `env_json` / `headers_json`；secret key 列表存入 `secret_env_keys_json` / `secret_header_keys_json`
- **响应**: 只返回键名列表 + 存在性（`envPresence`），不返回 secret 值
  - `set`: 非 secret 值已设置
  - `masked`: secret 值已存储（返回遮罩 `"***"`）
  - `placeholder`: `${VAR}` 占位符未解析
- **日志**: 凭证值不进入普通日志，走 `_log_value` 脱敏

## 测试策略（E14/E15/N13）

### 单元测试（mock SDK）

`McpSessionProtocol`（`typing.Protocol`）和业务层类型（`McpCallResult`/`McpToolInfo`）定义见 `mcp-tool-registration.md`（N9：返回业务类型，不泄漏 SDK 类型）。

- `McpProcessManager` 依赖 `McpSessionProtocol` 而非直接依赖 SDK `ClientSession`；内部用 `_SdkSessionAdapter` 适配
- 单元测试注入 `FakeMcpSession`，覆盖：启动/停止/调用/ping 的正常路径和失败路径
- **FakeMcpSession 限制（N13）**：只覆盖正常路径和显式失败；SDK 隐式行为（schema 校验/未初始化态/task group 异常）由集成测试覆盖
- 门卫测试不需要真实 MCP server，只验证架构约束（分层、凭证不泄漏、双轨注册）

### 集成测试（真实 server）

- 用真实 `filesystem MCP server`（`npx -y @modelcontextprotocol/server-filesystem`）
- 标记 `@pytest.mark.integration`，CI 中可选跳过（需要 Node.js + npx 环境）
- **不只测 happy path（N13）**：覆盖 schema 校验失败、server 崩溃、stdout 提前关闭等边界

### 线程安全测试（E15）

- 用 `threading.Barrier` 同步多线程同时提交 coroutine，验证所有 future 都完成
- 测试事件循环崩溃后的重建路径
- 测试 `future.result(timeout=30)` 超时后的事件循环状态
- 验证 `McpToolRegistry` snapshot 语义，注册/注销时不抛 `dictionary changed size during iteration`
