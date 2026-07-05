# Implementation Plan: MCP Management

**Branch**: `027-mcp-management` | **Date**: 2026-07-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/027-mcp-management/spec.md`

## Summary

通过 MCP（Model Context Protocol）协议接入第三方工具和 AI agent，合并进现有 skills/tools 屏管理。核心路径：用户在工具屏"MCP 工具"tab 添加/配置 MCP server → 后端以独立子进程(stdio)拉起 server → 自动发现工具并以 `mcp__` 前缀注册进 agent 能力目录 → AI 对话中自动调用 MCP 工具完成任务。MVP 先支持 stdio 传输，凭证走 `UnifiedConfigManager`，高危操作穿透现有确认协议，大输出走统一 envelope + output governance。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）、TypeScript 5.x（前端）
**Primary Dependencies**: FastAPI（sidecar bridge）、SQLAlchemy（ORM/migration）、Zustand（前端状态）、Python MCP SDK v1.x（`mcp` 包，待添加）、blinker（跨模块事件）
**Storage**: SQLite（`mcp_servers` 表 + `app_settings` 凭证）、无 DuckDB 涉及
**Testing**: pytest（后端单元/集成）、Vitest + React Testing Library（前端单元）、Playwright（E2E）
**Target Platform**: Windows 11 桌面（Tauri 2 shell + localhost FastAPI sidecar）
**Project Type**: desktop-app
**Performance Goals**: 已缓存 npx 启动 MCP server <5s（首次下载可能 30s+，SC-006）；工具调用延迟 <2s（不含 LLM 推理）；UI 操作响应 <500ms
**Constraints**: MCP server 以独立子进程运行，不嵌入 sidecar；凭证不进前端/日志/明文 DTO；MCP SDK v1.x（`mcp>=1.27,<2`，v2 待稳定后升级）；stdio 传输优先，HTTP 后续扩展；MCP SDK import 失败时降级（CRUD 可用，启动/测试不可用）；MCP 工具走 deferred loading（不全量注入）
**Scale/Scope**: 预计 3-10 个 MCP server 配置；每个 server 暴露 1-50 个工具；单用户桌面应用

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. 分层边界与事件协调 | MCP 功能是否保持 `UI → business → execution → data` 方向？跨模块通知是否走 blinker？ | UI 只调 typed API → `McpServerService` → `McpServerRepository`；工具注册复用 `tools.changed`；server 状态变更走 `backend.resync_required`；无新 blinker 事件 |
| II. 数据边界与持久化纪律 | `mcp_servers` 是否经 Repository 访问？凭证是否走 `UnifiedConfigManager`？ | 新增 `McpServerRepository` 继承 `BaseRepository`；secret env/header 值经 `UnifiedConfigManager.set()` 存 `app_settings`；无 DuckDB 涉及 |
| III. 统一配置与密钥安全 | MCP 凭证是否全部走 `UnifiedConfigManager`？是否遮罩输出和日志脱敏？ | 凭证键格式 `mcp.servers.<server_id>.env.<key>` / `mcp.servers.<server_id>.headers.<key>`；DTO 只返回遮罩值；日志脱敏走现有 `_log_value` 机制 |
| IV. 可验证交付 | 是否覆盖确定性逻辑测试和架构接线冒烟/门卫测试？ | 单元：Repository CRUD、Service 生命周期、JSON 解析、`${VAR}` 替换（注入 `FakeMcpSession` mock SDK，E14）；集成：server 启停+工具发现（真实 filesystem server，`@pytest.mark.integration`）；线程安全：Barrier 同步测试 + 事件循环崩溃恢复（E15）；门卫：MCP 工具走 deferred loading、高危确认穿透、凭证不泄漏、`McpServerConfig.__repr__` 遮罩、McpToolRegistry snapshot 语义 |
| V. 活文档与规格驱动交付 | 受影响的活文档是否已识别？临时材料是否限 `docs/local/`？ | 需更新 `docs/ARCHITECTURE.md`（新增 MCP 节）、`CLAUDE.md`/`AGENTS.md`（Recent Changes + Known Issues）、`src/CLAUDE.md`（新增 MCP 约束）、`frontend/CLAUDE.md`（新增 MCP tab 约束） |

**Gate 结果**: 全部通过。无 Constitution 违反。

## 关键技术风险与缓解

### MCP SDK API 兼容性（E1/E19/E22，已通过 Spike 验证）

- **已确认**：`mcp v1.28.1` + `anyio v4.14.1` 兼容；`ClientSession` 接受 anyio MemoryObjectStream（由 `stdio_client` 生成），不支持裸 subprocess 管道 → 用 `stdio_client` + `AsyncExitStack` 管理长连接
- **已确认**：`call_tool` 支持 `read_timeout_seconds` 参数（注意：参数名是 `read_timeout_seconds`）
- **CI 冒烟测试**：增加 `import mcp` 冒烟测试，捕获 anyio 版本冲突

### 事件循环崩溃恢复（E6）

- MCP 事件循环线程加全局 `try/except`：异常后记录日志并重建循环
- `call_tool_sync` 检测事件循环不运行时尝试自动重建，重建失败才返回错误 envelope
- 断路器（E8）：每个 server 连续失败超 3 次直接返回错误，手动 reconnect 重置

### MCP 工具双轨注册（N8/X1/E13，关键架构决策）

DynamicToolManager 无 MCP 注入点（9 处横切改动风险大），MVP 采用双轨制：
- **预置 server（GitHub/filesystem）全量注入** `tool_factory()`：工具数可控（~10-30），保住"配置即可用"核心承诺
- **用户自定义 server 走独立 `McpToolRegistry` 路径**：独立 LRU（不争用 DynamicToolManager），通过 `search_tools(kind="mcp")` + `get_tool_detail(selector="mcp:...")` 按需发现激活
- `search_tools`/`get_tool_detail` 增 MCP 分支直接查 `McpToolRegistry`，不碰 DynamicToolManager
- 未来如需统一可在独立路径稳定后再合并

### ClientSession 长连接稳定性（E20）

- SDK 的 `ClientSession` 主要为短生命周期设计，长连接稳定性需验证
- **缓解**：实现完成后做长连接稳定性测试（启动 filesystem server，每 30s 调用一次，持续 1 小时，观察内存/延迟）
- **备选**：如发现泄漏，增加 session 定期重建机制（每 30 分钟 stop + start）
- 在 Known Issues 中记录此风险

### MCP SDK import 隔离（E7）

- 所有 `from mcp import ...` 必须在函数内部延迟导入，不放模块顶层
- FastAPI lifespan 中 MCP 启动逻辑整体 try/except，失败只记日志不影响 sidecar
- SDK 不可用时降级：CRUD API 仍可工作，启动/测试连接返回明确错误

## Project Structure

### Documentation (this feature)

```text
specs/027-mcp-management/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── mcp-server-lifecycle.md
│   ├── mcp-tool-registration.md
│   └── mcp-api-endpoints.md
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── api/
│   │   └── mcpServers.ts           # MCP server typed API client
│   ├── screens/
│   │   └── skills/
│   │       ├── McpServerTab.tsx     # MCP 工具 tab（与现有 SkillListScreen 并列）
│   │       ├── McpServerCard.tsx    # 单个 server 卡片
│   │       └── McpServerDialog.tsx  # 添加/编辑 server 弹层
│   └── state/
│       └── mcpStore.ts             # MCP server Zustand store
└── tests/
    └── unit/
        └── mcpStore.test.ts        # 前端 store 单测

src/
├── business/
│   ├── mcp/                         # MCP 业务层（新增）
│   │   ├── __init__.py
│   │   ├── mcp_server_service.py    # Server 生命周期管理 + 同步桥接 + 事件循环崩溃恢复
│   │   ├── mcp_tool_registry.py     # 进程级 MCP 工具注册表（双轨：预置全量 + 自定义独立 LRU，线程安全 snapshot）+ NullRegistry（RC10）
│   │   ├── mcp_process_manager.py   # stdio_client + AsyncExitStack + _SdkSessionAdapter（RC4）+ _convert_sdk_*（RC8）+ stderr tempfile reader（RC1）
│   │   ├── mcp_session_protocol.py  # McpSessionProtocol（Protocol，返回业务类型，N9/RC4）
│   │   ├── mcp_search_tools.py      # create_mcp_aware_search_tools（RC6 路 A：独立 wrapper，kind 含 mcp，不碰 DynamicToolManager）
│   │   ├── mcp_json_import.py       # JSON 配置解析（三种格式）+ secret 自动检测
│   │   ├── mcp_env_resolver.py      # ${VAR} 环境变量解析（每次 start/reconnect 重新解析）
│   │   ├── mcp_errors.py            # 错误分类映射 → suggestion（启动 + 运行时，N14/RC3）
│   │   ├── mcp_presets.py           # 预置 server 默认配置（N19 引导种子数据）
│   │   └── models.py               # 业务模型（McpServerConfigPublic/McpLaunchPayload repr=False RC5/McpToolInfo/McpCallResult，N17/N9）
│   └── agents/
│       └── tools/
│           └── capability_catalog.py    # 修改：CapabilityKind/_KIND_ORDER/search 校验加 "mcp"（RC6 小改动，非 DynamicToolManager）
├── desktop_api/
│   ├── routers/
│   │   └── mcp_servers.py           # MCP server CRUD API
│   └── ui_events.py                 # 无修改（复用 tools.changed）
├── data/
│   ├── repos/
│   │   └── mcp_server_repository.py # MCP server Repository
│   ├── migrations.py                # v24: mcp_servers 表
│   └── models_sqlite.py             # McpServer ORM 模型
└── utils/
    └── events.py                    # 无修改（无新事件）

tests/
├── business/
│   └── mcp/                         # MCP 业务层测试（注入 FakeMcpSession，RC4 可注入）
│       ├── test_mcp_server_service.py
│       ├── test_mcp_tool_registry.py        # 线程安全 + snapshot 语义 + 双轨
│       ├── test_mcp_process_manager.py      # _SdkSessionAdapter + RC3 schema 错误匹配 + RC4 Protocol 注入
│       ├── test_mcp_json_import.py          # 含 fuzz 测试
│       ├── test_mcp_env_resolver.py
│       ├── test_mcp_errors.py               # 错误分类映射（启动 + 运行时）
│       ├── test_mcp_search_tools.py         # RC6 路 A wrapper + kind=mcp + server_slug 过滤（P3-R2）
│       ├── test_sync_bridge_threading.py    # Barrier 同步 + 事件循环崩溃恢复（E15）
│       └── test_mcp_config_repr.py          # RC5: assert secret not in repr(McpLaunchPayload)
├── data/
│   └── test_mcp_server_repository.py
├── desktop_api/
│   └── test_mcp_servers_router.py
├── integration/
│   └── test_mcp_filesystem_server.py        # 真实 filesystem server（@pytest.mark.integration，含 RC2 async with / RC1 stderr / RC3 schema 边界）
└── guardrails/
    └── test_mcp_guardrails.py       # MCP 架构门卫测试（双轨注册 + SDK 类型不穿业务层 + deferred loading）
```

**Structure Decision**: MCP 功能作为 `src/business/mcp/` 独立业务模块，与 `brain/`、`task_collaboration/`、`user_todos/`、`self_improvement/` 同级。前端 MCP 组件嵌入现有 `skills/` 屏幕作为新 tab，不新建独立屏幕。数据层新增 `McpServerRepository` 和 v24 迁移（含 downgrade）。API 层新增 `mcp_servers.py` router。MCP 工具走 deferred loading（不全量注入），通过 `McpToolRegistry` + 扩展 `search_tools`/`get_tool_detail` 暴露。

## Constitution Check（R3 Critique 后复核）

| Principle | 复核结果 |
|-----------|----------|
| I. 分层边界 | ✅ MCP 工具双轨注册；`McpToolRegistry` 进程级单例 + 自定义独立 LRU；SDK 类型不穿业务层（RC4 `_SdkSessionAdapter` 在 process_manager 内，`_convert_sdk_*` 即时转业务类型 RC8/RC9）；`_sessions: dict[str, McpSessionProtocol]` FakeMcpSession 可注入 |
| II. 数据边界 | ✅ `mcp_servers` 表含 secret key 列表；凭证走 `UnifiedConfigManager`；预置引导在 lifespan（N19） |
| III. 统一配置与密钥 | ✅ `McpServerConfigPublic` + `McpLaunchPayload`（RC5 `field(repr=False)` + class-level `__repr__`，门卫测试验证 secret 不泄漏）；secret 自动检测启发式；API 不直接接收含 secret 对象 |
| IV. 可验证交付 | ✅ SDK 兼容性测试（RC2 async with / RC1 stderr tempfile / RC3 schema 错误匹配）、RC4 FakeMcpSession 注入测试、RC5 repr 门卫、线程安全、fuzz、真实 server 集成测试（含边界）、事件循环崩溃恢复、双轨注册门卫 |
| V. 活文档 | ✅ 已识别需更新的活文档清单 |

**复核结论**: 无 Constitution 违反。R3 Must-Address（5 SDK 实测 bug RC1-RC5 + 3 产品承诺 P3-MA1-MA3）已全部解决。SDK 兼容性已通过 `.venv/` 源码 + 实测验证。

## Complexity Tracking

> 无 Constitution 违反，此表为空。
