# Feature Specification: MCP Management

**Feature Branch**: `027-mcp-management`
**Created**: 2026-07-04
**Status**: Draft
**Input**: User description: "通过 MCP 协议接入第三方工具和 AI agent,合并进现有工具(skills/tools)屏管理"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - AI 自动调用 MCP 工具完成任务 (Priority: P1)

用户配置一个 MCP server(如 GitHub)后,在 AI 助手对话中提及相关任务(如"看最新 PR"),AI 自动发现并调用 `mcp__github__list_prs`,将结果呈现给用户。用户无需手动选择工具或 server。

**Why this priority**: 这是 MCP 功能的核心价值——"一次配置,AI 自动使用"。没有这条,MCP 只是配置界面,不产生用户价值。

**Independent Test**: 可通过配置一个预置 server(文件系统),对话中请求"列出当前目录文件",验证 AI 调用 `mcp__filesystem__list_directory` 并返回结果来独立测试。

**Acceptance Scenarios**:

1. **Given** 用户已配置并启用 GitHub MCP server, **When** 用户在对话中说"帮我看看最新的 PR", **Then** AI 自动调用 `mcp__github__list_prs` 并将结果呈现给用户
2. **Given** 用户未配置任何 MCP server, **When** 用户请求需要 MCP 工具的任务, **Then** AI 使用内置工具回答,或告知用户可配置 MCP server 扩展能力
3. **Given** 已配置的 MCP server 断连, **When** AI 尝试调用该 server 的工具, **Then** 返回明确错误信息而非静默失败

---

### User Story 2 - 在工具屏添加和配置 MCP server (Priority: P2)

用户在 skills/tools 屏的"MCP 工具"tab 中添加 server——可以是预置一键启用,也可以是粘贴一段从外部复制的 JSON 配置。配置完成后看到连接状态和暴露的工具数。

**Why this priority**: 配置是 P1 的前置条件,但单独看它只是 UI 操作,不直接产生"AI 自动用"的价值。P1 先跑通最小链路,P2 再接配置界面。

**Independent Test**: 可通过在 MCP 工具 tab 中添加预置文件系统 server、填写必要凭证(无)、验证显示"✓ 连通,暴露 N 个工具"来独立测试。

**Acceptance Scenarios**:

1. **Given** 用户在 skills/tools 屏选择"MCP 工具"tab, **When** 点击 ➕ 添加 server, **Then** 弹层出现,可选预置 server 或自定义
2. **Given** 用户选择预置 GitHub server, **When** 填入 Personal Access Token, **Then** 点击测试连接后显示"✓ 连通,暴露 N 个工具"
3. **Given** 用户从外部(Claude Desktop 等)复制了一段 `mcpServers` JSON 配置, **When** 粘贴到"粘贴配置"框并点击解析, **Then** 表单自动回填 server 字段,用户确认后保存
4. **Given** 已添加的 server, **When** server 断连, **Then** server 卡片显示断连状态(标灰),工具数不可见

---

### User Story 3 - 管理已配置的 MCP server (Priority: P3)

用户在 MCP 工具 tab 中查看已配置 server 的列表(名称/工具数/连接状态),可启用/禁用/删除 server,可重新编辑配置。

**Why this priority**: 管理是运维需求,低频。配置一次后很少动。

**Independent Test**: 可通过添加一个 server 后禁用它、验证 AI 不再调用其工具来独立测试。

**Acceptance Scenarios**:

1. **Given** 用户有多个已配置 server, **When** 查看 MCP 工具 tab, **Then** 看到所有 server 的名称、暴露工具数和连接状态
2. **Given** 一个已启用的 server, **When** 用户禁用它, **Then** AI 不再能调用该 server 的工具
3. **Given** 一个已配置的 server, **When** 用户删除它, **Then** server 及其工具从能力目录中移除

---

### Edge Cases

- 用户粘贴的 JSON 包含多个 server(`mcpServers` 嵌套)——批量导入
- 用户粘贴的 JSON 中环境变量值为 `${GITHUB_TOKEN}` 占位符而非真实 token——优先读系统环境变量,读不到标"待补"
- MCP server 启动后中途崩溃——agent 调用时返回错误,server 卡片标灰
- MCP server 工具名与内置工具名冲突(如 `mcp__github__search_code` vs 内置 `search_code`)——`mcp__` 前缀天然隔离,不冲突
- 用户在同一对话中同时使用内置工具和 MCP 工具——两者并列,统一调度
- MCP 工具返回超大输出——走现有统一 envelope + output governance(复用 016/015)
- MCP 工具执行高危操作(如 GitHub 写操作)——穿透现有确认协议
- sidecar 进程重启后 MCP server 需要重新连接——启动时自动重连
- stdio server 的子进程被杀或僵死——需要超时检测和清理

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 用户 MUST 能在 skills/tools 屏的"MCP 工具"来源 tab 中添加、编辑、禁用和删除 MCP server
- **FR-002**: 添加 server MUST 支持三种路径:预置一键启用、手动填写表单、粘贴 JSON 配置自动解析回填,三路径 MUST 统一到同一张表单界面
- **FR-003**: 粘贴导入 MUST 兼容三种格式:Claude Desktop/Code 嵌套 `mcpServers` 格式(可能含多个 server,批量导入)、裸 stdio server 对象、HTTP server 对象
- **FR-004**: 每个 MCP server MUST 有以下字段:name(显示名+唯一标识)、transport(stdio/http)、enabled(启用开关);stdio 类 MUST 有 command/args/env;http 类 MUST 有 url/headers
- **FR-005**: env 和 headers 中标记为 secret 的值 MUST 走 `UnifiedConfigManager` → SQLite `app_settings` 存储,不进前端持久化状态、普通配置文件或普通日志
- **FR-006**: 粘贴导入中 `${VAR}` 占位符 MUST 优先读取系统环境变量;读不到 MUST 标记为"待补"并在保存时拦截提示用户填写
- **FR-007**: 保存 server 配置前 MUST 提供"测试连接"功能,后端拉起子进程(stdio)或发请求(http)、调用一次 `tools/list`,返回"✓ 连通,暴露 N 个工具"或具体错误
- **FR-008**: MCP 工具 MUST 带 `mcp__` 前缀自动注册进 agent 能力目录,与内置工具/技能工具并列,复用现有 `tools.changed` 事件域,不新增独立事件域
- **FR-009**: AI MUST 能自动发现并调用 MCP 工具,无需用户手动选择 server 或工具
- **FR-010**: MCP 工具的高危操作 MUST 穿透现有确认协议,与内置高危工具确认流程一致
- **FR-011**: MCP 工具的返回值 MUST 适配现有统一 envelope + output governance(复用 016/015)
- **FR-012**: MCP server MUST 以独立子进程(stdio)方式运行,不嵌入 FastAPI sidecar,规避 MCP SDK 嵌入已知 bug(#883/#737)
- **FR-013**: MCP server 断连 MUST 在 UI 上标灰(连接状态不可用),调用时返回明确错误信息,不静默失败
- **FR-014**: 预置 server MUST 先提供 GitHub 和文件系统两个,其余后补
- **FR-015**: MCP 工具 MUST 全部暴露给 AI,不在 UI 让用户逐个勾选启用/禁用单个工具;启用/禁用只在 server 级别操作

### Key Entities

- **McpServer**: 一个配置的 MCP server 实例。属性:唯一 ID、显示名、transport 类型(stdio/http)、command/args/env(stdio)或 url/headers(http)、启用状态、连接状态、暴露工具列表(缓存)
- **McpTool**: server 暴露的一个工具。属性:工具名(带 `mcp__` 前缀)、描述、输入 schema、所属 server ID
- **McpServerCredential**: server 配置中的敏感值(token/API key)。属性:所属 server ID、字段路径(env key 或 header key)、存储位置(app_settings)

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: MCP server MUST 以独立子进程运行,不嵌入 FastAPI——这与现有 Tauri 受管子进程架构(Python sidecar)同模式;MCP 子进程由后端统一生命周期管理
- **CC-002**: MCP 工具 MUST 复用现有能力目录注册机制(021 deferred loading / dynamic_tool_manager),`mcp__` 前缀天然与内置工具隔离,不引入独立注册路径
- **CC-003**: 凭证存储 MUST 走 `UnifiedConfigManager` → SQLite `app_settings`,与现有 API key 存储同路径;MCP 凭证是同一类"接外部服务的凭证"
- **CC-004**: MCP 工具 MUST 走现有高危确认协议——写操作穿透确认,读操作免确认;与内置工具确认标准一致
- **CC-005**: MCP 工具大输出 MUST 现有统一 envelope + output governance——`ToolOutputRepository` artifact + `load_tool_output` 授权恢复;不另辟大输出处理路径
- **CC-006**: skills/tools 屏 MUST 保留现有"教学工具"tab(pending/published/failed)完全不动;新增"MCP 工具"tab 与之并列,不改动已有卡片和生命周期
- **CC-007**: MCP 功能 MUST 不新增公开 UI 事件类型——工具注册/状态变更复用现有 `tools.changed`;server 连接状态变更可走 `backend.resync_required` 兜底,不需要新注册事件
- **CC-008**: Python MCP SDK v1.x 为生产推荐版本;v2 预计 2026-07-27 稳定版——MVP MUST 用 v1.x,后续升级为独立任务
- **CC-009**: Streamable HTTP 为推荐传输方式;stdio 仅限本地进程场景——但 MVP MUST 先支持 stdio(本地子进程最简单),HTTP 传输为后续扩展
- **CC-010**: MCP 工具调用 MUST 不破坏现有 agent 100% 调度架构——MCP 工具是临时执行体可用的工具之一,不引入主助理直接执行路径

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **UI** (`frontend/src/`, `src-tauri/`) — skills/tools 屏新增来源 tab、MCP server 配置弹层、连接状态展示
- [x] **Desktop API Bridge** (`src/desktop_api/`) — 新增 MCP server CRUD typed API endpoint
- [x] **Business** (`src/business/`) — 新增 MCP server 生命周期管理 service、工具注册适配、子进程管理
- [x] **Execution** (`src/execution/`) — MCP 工具调用需要适配现有工具执行框架
- [x] **Data** (`src/data/`) — 新增 `mcp_servers` 表(MCP server 配置)、凭证走 `app_settings`
- [x] **Utils** (`src/utils/`) — 可能需要进程管理辅助工具

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: Assistant(主助理)——调度时能力目录新增 MCP 工具;临时执行体——实际调用 MCP 工具
- New tools or modified tool handlers: MCP 工具作为动态注册工具,走现有 `DynamicToolManager` 机制;不需要新增内置工具
- System prompt changes needed: 主助理 prompt 中能力目录自动包含 MCP 工具(走现有目录生成);无需专门修改 prompt
- Orchestrator dispatch changes: 无——MCP 工具是执行体可用工具之一,调度流程不变

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): 新增 `mcp_servers` 表(server 配置:name/transport/command/args/url/enabled 等);`app_settings` 存凭证(secret 字段值)
- **Config** (`src/data/unified_config.py`): MCP 凭证走 `UnifiedConfigManager` 读写,不新增 config.json 专属键;预置 server 配置可放 config.json 默认值
- **Secrets** (`UnifiedConfigManager` only): 每个 MCP server 的 secret env/header 值作为独立 app_settings 条目存储,读取走 UnifiedConfigManager,空值行为=待补拦截

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: 无新事件——MCP 工具注册复用 `tools.changed`;server 状态变更通过 `backend.resync_required` 兜底
- Modified event payloads: 无修改
- New event listeners: 无新监听器

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 用户配置一个 MCP server(文件系统预置,无需填凭证)后,在对话中请求"列出目录文件",AI 在 3 次迭代内自动调用 MCP 工具并返回正确结果
- **SC-002**: 用户从 Claude Desktop 复制一段 `mcpServers` JSON 配置,粘贴到添加弹层,解析+保存+测试连接,全过程在 2 分钟内完成
- **SC-003**: MCP server 断连时,UI 在 10 秒内标灰显示断连状态,调用该工具时返回明确错误而非静默失败
- **SC-004**: MCP 工具的高危操作(如 GitHub 创建 PR)触发确认协议,用户确认后执行成功,拒绝后不执行
- **SC-005**: 已有 skills/tools 屏的"教学工具"tab 功能(pending/published/failed 卡片、试用流程)完全不受 MCP tab 影响,零回归

## Assumptions

- MVP 先只支持 stdio 传输(本地子进程),HTTP(Streamable HTTP)为后续扩展
- Python MCP SDK v1.x 为生产版本,MVP 用 v1.x;v2 稳定后升级为独立任务
- 预置 server 初始只含 GitHub 和文件系统两个,其余按需后补
- MCP 工具全部暴露给 AI,不做单个工具的启用/禁用 UI;server 级别的启用/禁用即可
- MCP server 子进程管理与 Python sidecar 同模式(受管子进程),不引入新的进程编排范式
- 凭证中 `${VAR}` 占位符优先读系统环境变量;读不到时标"待补"并保存拦截,不做自动创建环境变量的功能
- 现有 agent 能力目录机制(021 deferred loading / dynamic_tool_manager)足够支撑 MCP 工具注册,不需要独立的 MCP 工具注册路径
- skills/tools 屏现有教学工具 tab 完全不动;MCP 工具 tab 独立呈现,两类卡片结构不同(tab 分离而非混排)
