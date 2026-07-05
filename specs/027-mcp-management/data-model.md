# Data Model: MCP Management

**Feature**: 027-mcp-management
**Date**: 2026-07-04
**Spec**: [spec.md](./spec.md)

## ORM 模型

### McpServer（`mcp_servers` 表，v24 migration）

```python
class McpServer(Base):
    __tablename__ = "mcp_servers"

    server_id: Mapped[str]         # String(64), PK, 前缀 "mcs_"
    name: Mapped[str]              # String(100), NOT NULL, 显示名+唯一标识（规范化后禁含 __）
    transport: Mapped[str]         # String(20), NOT NULL, "stdio" | "http"
    command: Mapped[Optional[str]] # String(500), stdio 必填
    args_json: Mapped[Optional[str]] # Text, JSON string[]；stdin args
    url: Mapped[Optional[str]]     # String(500), http 必填
    headers_json: Mapped[Optional[str]] # Text, JSON object{}；非 secret HTTP headers
    secret_header_keys_json: Mapped[Optional[str]] # Text, JSON string[]；secret header key 列表（E4）
    # 非 secret 的 env 值（secret 走 app_settings）
    env_json: Mapped[Optional[str]] # Text, JSON object{}；非 secret env
    secret_env_keys_json: Mapped[Optional[str]] # Text, JSON string[]；secret env key 列表（E4）
    enabled: Mapped[bool]          # Boolean, default True
    # 连接状态缓存（进程级维护，DB 只存最后已知状态）
    last_known_status: Mapped[Optional[str]] # String(20), "running"|"failed"|"disconnected"|NULL
    last_error_message: Mapped[Optional[str]] # Text, 最后已知错误摘要（脱敏后）
    suggestion: Mapped[Optional[str]] # Text, 用户友好的错误修复建议（P11）
    circuit_breaker_open: Mapped[bool] # Boolean, default False；断路器状态（E8，进程级，DB 只存快照）
    tool_count: Mapped[Optional[int]] # Integer, 暴露工具数缓存
    tools_json: Mapped[Optional[str]]  # Text, 工具列表缓存（JSON array of {name, description, inputSchema}）
    is_preset: Mapped[bool]            # Boolean, default False；预置 server 标记（控制全量注入 vs deferred，N8）
    preset_slug: Mapped[Optional[str]] # String(50), 预置 server 标识（github / filesystem 等）
    created_at: Mapped[datetime]   # DateTime, NOT NULL
    updated_at: Mapped[datetime]   # DateTime, NOT NULL
```

#### ID 前缀

`ID_PREFIX_MCP_SERVER = "mcs_"`，与 `generate_id()` 配合使用。

#### 凭证存储

secret env 值和 secret header 值 **不在** `mcp_servers` 表中存储，而是走 `UnifiedConfigManager` → `app_settings`：

- 键格式：`mcp.servers.<server_id>.env.<env_key>` 和 `mcp.servers.<server_id>.headers.<header_key>`
- `env_json` 和 `headers_json` 只存**非 secret** 的值
- `secret_env_keys_json` / `secret_header_keys_json` 显式记录哪些 key 的值在 `app_settings` 中（E4）——比遍历 app_settings 前缀匹配更可靠，支持 key 重命名场景
- secret 值在保存时从表字段中移除，转为 `app_settings` 条目
- 读取时合并：`secret_env_keys_json` 列表 → 逐个从 `UnifiedConfigManager` 读 → 与 `env_json` 合并

#### McpServerConfig 凭证安全（E10）

合并后的 `McpServerConfig.env` / `headers` dict 含 secret 值：
- `__repr__` 必须遮罩：`env` 和 `headers` 中的值显示为 `***`
- 合并后 env dict 只传给 `asyncio.create_subprocess_exec`，不缓存到实例变量
- 门卫测试：`McpServerConfig.__repr__()` 不含 secret 值

#### 字段约束

- `transport` 只允许 `"stdio"` 或 `"http"`（CHECK 约束）
- `command` 在 `transport="stdio"` 时必填（应用层校验，非 CHECK 约束——SQLite CHECK 对跨行条件支持弱）
- `url` 在 `transport="http"` 时必填
- `name` 有唯一索引 `uq_mcp_servers_name`
- `args_json` / `headers_json` / `env_json` / `tools_json` 都是 JSON text

### 不新增的表

- **不需要 `mcp_server_credentials` 表**: 凭证走 `app_settings`，与现有 API key 存储同路径
- **不需要 `mcp_tools` 表**: 工具列表缓存在 `mcp_servers.tools_json` 中，不做独立表——工具是 server 的运行态产物，不需要独立 CRUD

## 业务模型

### McpServerConfigPublic（可缓存可日志，不含 secret，N17）

```python
@dataclass
class McpServerConfigPublic:
    """不含 secret 的 server 配置，可安全缓存、日志、序列化。"""
    server_id: str
    name: str
    transport: str  # "stdio" | "http"
    command: str | None
    args: list[str]
    url: str | None
    non_secret_env: dict[str, str]       # 仅非 secret 的 env 值
    non_secret_headers: dict[str, str]   # 仅非 secret 的 header 值
    secret_env_keys: list[str]           # secret 键名列表（不含值）
    secret_header_keys: list[str]
    enabled: bool
    is_preset: bool
    preset_slug: str | None

    @classmethod
    def from_row(cls, row: McpServer) -> McpServerConfigPublic:
        """从 ORM 行构建（不查 UnifiedConfigManager，不含 secret 值）。"""
        ...
```

### McpLaunchPayload（含合并 secret，只在 spawn 那刻构造，用完丢弃，N17/RC5）

```python
from dataclasses import dataclass, field

@dataclass
class McpLaunchPayload:
    """启动子进程用的完整配置（含合并后的 secret env）。
    生命周期严格限定在 McpProcessManager.start_server 内部，绝不暴露给上层、不缓存。"""
    command: str
    args: list[str]
    merged_env: dict[str, str] = field(repr=False)  # RC5: dataclass repr 不显示
    url: str | None = None
    merged_headers: dict[str, str] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        # RC5: class-level __repr__（dunder 在 type 上查，实例属性 override 不生效）
        return (f"McpLaunchPayload(command={self.command!r}, args={self.args!r}, "
                f"<{len(self.merged_env)} env vars masked>)")
```

**RC5 关键**：Python dunder 方法在 `type(obj)` 上查找，**不在实例上查找**。之前的 `__post_init__` + `object.__setattr__(self, "__repr__", ...)` 写法**不生效**——`repr(payload)` 仍走 dataclass 自动生成的 class-level `__repr__`，暴露 secret。正确做法是 `field(repr=False)` + class-level `__repr__` 方法 + 门卫测试 `assert "ghp_xxx" not in repr(payload)`。

`McpProcessManager.start_server` 内部完成 `McpServerConfigPublic → McpLaunchPayload` 转换（从 `UnifiedConfigManager` 读 secret 合并），**绝不把 McpLaunchPayload 暴露给上层业务代码**。

### McpToolInfo（缓存工具信息）

```python
@dataclass
class McpToolInfo:
    """单个 MCP 工具的缓存信息（业务层类型，N9）。"""
    name: str            # 原始工具名（如 "list_prs"）
    description: str
    input_schema: dict   # JSON Schema
```

### McpCallResult（业务层调用结果，N9）

```python
@dataclass
class McpCallResult:
    """业务层工具调用结果（不含 SDK 类型，N9）。"""
    is_error: bool
    text_parts: list[str]
    image_count: int
    structured_data: dict | None
```

### McpServerStatus（连接状态）

```python
class McpServerStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    STOPPED = "stopped"
```

### McpToolInfo / McpCallResult / McpServerStatus

见上文"业务模型"段（N9：业务层类型，不含 SDK 类型）。

## Repository

### McpServerRepository（继承 BaseRepository）

```python
class McpServerRepository(BaseRepository):
    """MCP server 配置仓库。"""

    def create_server(
        self, *,
        name: str,
        transport: str,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        headers: dict[str, str] | None = None,  # 非 secret 部分
        secret_header_keys: list[str] | None = None,
        env: dict[str, str] | None = None,        # 非 secret 部分
        secret_env_keys: list[str] | None = None,
        is_preset: bool = False,
        preset_slug: str | None = None,
        enabled: bool = True,
    ) -> McpServer: ...

    def get_by_id(self, server_id: str) -> McpServer | None: ...
    def get_by_name(self, name: str) -> McpServer | None: ...
    def list_all(self) -> list[McpServer]: ...
    def list_enabled(self) -> list[McpServer]: ...
    def list_preset_slugs(self) -> list[str]: ...  # N19: 预置引导用

    def update_config(self, server_id: str, **fields) -> McpServer: ...
    def set_enabled(self, server_id: str, enabled: bool) -> McpServer: ...
    def update_status(self, server_id: str, status: str, error: str | None = None, suggestion: str | None = None, tool_count: int | None = None, tools_json: str | None = None) -> McpServer: ...
    def delete_server(self, server_id: str) -> None: ...
```

## Migration

### v24: `mcp_servers` 表

```sql
CREATE TABLE mcp_servers (
    server_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    transport TEXT NOT NULL CHECK (transport IN ('stdio', 'http')),
    command TEXT,
    args_json TEXT,
    url TEXT,
    headers_json TEXT,
    secret_header_keys_json TEXT,
    env_json TEXT,
    secret_env_keys_json TEXT,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    last_known_status TEXT,
    last_error_message TEXT,
    suggestion TEXT,
    circuit_breaker_open BOOLEAN NOT NULL DEFAULT 0,
    tool_count INTEGER,
    tools_json TEXT,
    is_preset BOOLEAN NOT NULL DEFAULT 0,
    preset_slug TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

CREATE UNIQUE INDEX uq_mcp_servers_name ON mcp_servers(name);
```

**注意**：`disabled_tools_json`（单工具禁用）已从 MVP 移除（P2-R2，YAGNI）；未来需要时再加 migration。

### Downgrade（E17）

v24 migration 提供 downgrade 逻辑：

```sql
-- downgrade
DROP TABLE IF EXISTS mcp_servers;
DELETE FROM app_settings WHERE setting_key LIKE 'mcp.servers.%';
```

清理 `app_settings` 中所有 `mcp.servers.*` 前缀的凭证条目（用 `LIKE` 匹配）。

### 预置 server 引导（N19）

migration 只建表，不 seed。预置 server（GitHub/filesystem）的种子数据在 **lifespan 启动时**从硬编码 default（`src/business/mcp/mcp_presets.py`）upsert：

```python
# lifespan startup（在 start_all_enabled 之前）
def seed_preset_servers():
    defaults = load_preset_defaults()  # 从 mcp_presets.py
    existing_slugs = repo.list_preset_slugs()
    for preset in defaults:
        if preset.slug not in existing_slugs:
            repo.create_server(
                name=preset.name, transport="stdio",
                command=preset.command, args=preset.args,
                env=preset.non_secret_env,
                secret_env_keys=[],  # 预置 server 不预填 secret
                is_preset=True, preset_slug=preset.slug,
                enabled=False,  # 默认不启用，用户在 UI 一键启用
            )
        # 用户修改过的预置 server（preset_slug 不变但其他字段变了）不强制覆盖
```

### 凭证 app_settings 条目

凭证以独立 `app_settings` 条目存储，键格式为 `mcp.servers.<server_id>.env.<key>` / `mcp.servers.<server_id>.headers.<key>`。不需要迁移——删除 server 时同步清理这些条目（`DELETE FROM app_settings WHERE setting_key LIKE 'mcp.servers.<server_id>.%'`）。

## 状态转换

### Server 配置生命周期

```
created (DB row, enabled=True)
    → McpProcessManager.start_server()
    → starting → running (session.initialize() 成功, tools_json 更新)
    → starting → failed (session.initialize() 失败, last_error_message 更新)

running → disconnected (ping 失败 / 子进程崩溃)
    → UI 标灰, 手动 reconnect → starting → running / failed

running → stopped (用户禁用 / 删除)
    → McpProcessManager.stop_server() → 子进程终止
```

### 凭证生命周期

```
保存 server 配置 → secret env/header 值写入 app_settings
删除 server → 清理所有 mcp.servers.<server_id>.* app_settings 条目
更新 secret → 更新 app_settings 条目（不走表字段）
```

## ${VAR} 占位符追踪

`env_json` 中 `${VAR}` 占位符的值标记为特殊字段 `"__placeholder__": "VAR"`，用于追踪"待补"项：

```json
{
  "PATH": "/usr/bin",
  "GITHUB_TOKEN": {"__placeholder__": "GITHUB_TOKEN"}
}
```

- 读取时：`McpEnvResolver` 解析 `${VAR}`，读系统环境变量，读不到标"待补"
- 保存时：有 `"__placeholder__"` 项则拦截提示用户填写
- 前端展示：secret 字段显示遮罩值（`sk_***`），placeholder 字段显示"待填写"
