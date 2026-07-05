# Feature Specification: MCP Management

**Feature Branch**: `027-mcp-management`
**Created**: 2026-07-04
**Status**: Completed
**Input**: User description: "通过 MCP 协议接入第三方工具和 AI agent,合并进现有工具(skills/tools)屏管理"

## 问题背景

当前 Exemplar 用户扩展 AI 能力的唯一路径是"教学工具"——录制浏览器/桌面操作或手动写 Python 代码。这覆盖了自动化场景，但无法快速接入已有的第三方服务（如 GitHub、Slack、Jira）。

三个最常见的外部工具需求场景：
1. **代码协作**：查看/创建 PR、搜索代码、管理 Issue（GitHub/GitLab）
2. **信息检索**：搜索网页、查询知识库、读取文件系统
3. **团队协作**：发消息、查日程、管理任务（Slack/Notion/飞书）

这些场景当前的解决方式：用户手动在浏览器操作，然后复制粘贴信息到对话中。MCP 协议提供了一种标准化的"配置一次、AI 自动调用"路径，免去为每个服务写 Python 适配代码。

替代方案对比：
1. **不做 MCP**：用户只能用内置工具和手动教学的技能，无法快速接入第三方服务 → 每个新服务需要手写 Python 适配代码
2. **只做"工具市场"**：预打包一组常用服务工具，不需要 MCP 协议 → 每增加一个服务需要手写适配代码，用户无法自行接入非预打包的服务
3. **当前方案（MCP 协议）**：一次实现协议适配，用户自行接入任何兼容 MCP 的服务 → 投入稍大但扩展性最优

## User Scenarios & Testing *(mandatory)*

### User Story 1 - AI 自动调用 MCP 工具完成任务 (Priority: P1)

用户配置一个 MCP server(如 GitHub)后,在 AI 助手对话中提及相关任务(如"看最新 PR"),AI 自动发现并调用 `mcp__github__list_prs`,将结果呈现给用户。用户无需手动选择工具或 server。

**Why this priority**: 这是 MCP 功能的核心价值——"一次配置,AI 自动使用"。没有这条,MCP 只是配置界面,不产生用户价值。

**Independent Test**: 可通过配置一个预置 server(文件系统),对话中请求"列出当前目录文件",验证 AI 调用任意 `mcp__filesystem__*` 工具（工具名随 server 版本可能为 `list_directory`/`list-dir`/`read_directory` 等）并返回结果来独立测试。

**Acceptance Scenarios**:

1. **Given** 用户已配置并启用 GitHub MCP server（预置 server,工具全量注入）, **When** 用户在对话中说"帮我看看最新的 PR", **Then** AI 自动调用 `mcp__github__list_prs` 并将结果呈现给用户（预置 server 配置即可用,无需先 search_tools）
2. **Given** 用户未配置任何 MCP server, **When** 用户主动询问 AI 是否能扩展能力（如"你能访问 GitHub 吗"）, **Then** AI 介绍可配置 MCP server 扩展能力；AI 不在无关对话里主动推销 MCP（避免噪声）。MCP 工具数为 0 时 prompt 不含 MCP 提示；配置第一个 server 后 prompt 含 MCP 引导。
3. **Given** 已配置的 MCP server 断连, **When** AI 尝试调用该 server 的工具, **Then** 返回明确错误信息（含"去工具列表重连后重试"指引）而非静默失败；重连成功后通过 `tools.changed` 事件触发 toast 通知

---

### User Story 2 - 在工具屏添加和配置 MCP server (Priority: P2)

用户在 skills/tools 屏的"MCP 工具"tab 中添加 server——可以是预置一键启用,也可以是粘贴一段从外部复制的 JSON 配置。配置完成后看到连接状态和暴露的工具数。

**Why this priority**: 配置是 P1 的前置条件,但单独看它只是 UI 操作,不直接产生"AI 自动用"的价值。P1 先跑通最小链路,P2 再接配置界面。

**Independent Test**: 可通过在 MCP 工具 tab 中添加预置文件系统 server、填写必要凭证(无)、验证显示"✓ 连通,暴露 N 个工具"来独立测试。

**Acceptance Scenarios**:

1. **Given** 用户在 skills/tools 屏选择"MCP 工具"tab, **When** 点击 ➕ 添加 server, **Then** 弹层出现,可选预置 server 或自定义
2. **Given** 用户选择预置 GitHub server, **When** 填入 Personal Access Token 后点击测试连接, **Then** 显示"✓ 连通,暴露 N 个工具"（测试超时 60s 容忍 npx 首次下载 30s+,UI 显示进度提示）
3. **Given** 用户从外部(Claude Desktop 等)复制了一段 `mcpServers` JSON 配置, **When** 粘贴到"粘贴配置"框并点击解析, **Then** 表单自动回填 server 字段,用户确认后保存
4. **Given** 已添加的 server, **When** server 断连, **Then** server 卡片显示断连状态(标灰),工具数不可见
5. **Given** 用户添加完 server（P3-MA2）, **When** 查看 server 卡片, **Then** 卡片状态徽章区分 dual-track 行为：预置 server 显示"✓ AI 可直接调用",自定义 server 显示"AI 通过 search 按需发现"；自定义 server 首次添加成功后显示一次性 tooltip:"工具较多,AI 会在需要时搜索发现。如未触发,可在对话中提到 server 名称（如 'Jira'）"

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
- 用户粘贴的 JSON 中环境变量值为 `${GITHUB_TOKEN}` 占位符而非真实 token——优先读系统环境变量,读不到标"待补"；解析后表单显示为输入框+说明："将读取系统环境变量 GITHUB_TOKEN；或直接输入 token"
- MCP server 启动后中途崩溃——agent 调用时返回错误,server 卡片标灰
- MCP server 工具名与内置工具名冲突(如 `mcp__github__search_code` vs 内置 `search_code`)——`mcp__` 前缀天然隔离,不冲突
- 用户在同一对话中同时使用内置工具和 MCP 工具——两者并列,统一调度
- MCP 工具返回超大输出——走现有统一 envelope + output governance(复用 016/015)
- MCP 工具执行高危操作(如 GitHub 写操作)——穿透现有确认协议
- sidecar 进程重启后 MCP server 需要重新连接——启动时异步自动重连，不阻塞主界面
- stdio server 的子进程被杀或僵死——需要超时检测和进程树清理
- MCP server 启动失败——错误信息需映射为用户可理解的操作指引（如"spawn npx ENOENT"→"找不到 npx 命令，请确认已安装 Node.js"），API 响应中附 `suggestion` 字段
- 用户在对话中遇到 MCP 工具调用失败——错误信息须含操作指引（如"GitHub server 连接已断开，去工具列表重连后重试"），重连成功后主动通知
- 预置 server 首次使用——MCP 工具 tab 空状态展示 2 个预置 server 卡片（GitHub / 文件系统）及一键启用入口，引导文案："添加 MCP server 后，AI 助手可以自动使用这些工具完成任务"
- 删除正在被 AI 使用的 server——UI 显示影响提示（"AI 助手正在使用此 server 的工具，删除后相关功能将不可用"），不弹二次确认框

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
- **FR-009**: AI MUST 能自动发现并调用 MCP 工具,无需用户手动选择 server 或工具。预置 server（工具全量注入）配置启用后 AI 立即可用；用户自定义 server 通过 `search_tools(kind="mcp")` 发现 + `get_tool_detail` 激活。主助理能力目录 prompt MUST 在 deferred 模式下含 MCP 工具计数和触发引导（见 contracts/mcp-tool-registration.md 的 prompt 文案段）。
- **FR-010**: MCP 工具的高危操作 MUST 穿透现有确认协议,与内置高危工具确认流程一致
- **FR-011**: MCP 工具的返回值 MUST 适配现有统一 envelope + output governance(复用 016/015)
- **FR-012**: MCP server MUST 以独立子进程(stdio)方式运行,不嵌入 FastAPI sidecar,规避 MCP SDK 嵌入已知 bug(#883/#737)
- **FR-013**: MCP server 断连 MUST 在 UI 上标灰(连接状态不可用),调用时返回明确错误信息,不静默失败
- **FR-014**: 预置 server MUST 先提供 GitHub 和文件系统两个,其余后补
- **FR-015**: MCP 工具 MUST 全部暴露给 AI,不在 UI 让用户逐个勾选启用/禁用单个工具;启用/禁用只在 server 级别操作。[有意技术债务：MVP 不做单工具开关以简化 UI。启发式高危判断（见 contracts/mcp-tool-registration.md 的权威关键词集合）存在误报（如 `get_user_created_repos` 含"create"关键词）和漏报（如 `star_repository`/`follow_user`/`move_file` 是写操作但不含任何关键词）；后续改进方向：利用 MCP Tool `annotations.readOnlyHint` 和预置 server 读写分类元数据减少对启发式的依赖]

### Key Entities

- **McpServer**: 一个配置的 MCP server 实例。属性:唯一 ID、显示名、transport 类型(stdio/http)、command/args/env(stdio)或 url/headers(http)、启用状态、连接状态、暴露工具列表(缓存)
- **McpTool**: server 暴露的一个工具。属性:工具名(带 `mcp__` 前缀)、描述、输入 schema、所属 server ID
- **McpServerCredential**: server 配置中的敏感值(token/API key)。属性:所属 server ID、字段路径(env key 或 header key)、存储位置(app_settings)

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: MCP server MUST 以独立子进程运行,不嵌入 FastAPI——这与现有 Tauri 受管子进程架构(Python sidecar)同模式;MCP 子进程由后端统一生命周期管理
- **CC-002**: MCP 工具采用双轨注册（见 contracts/mcp-tool-registration.md）：预置 server（GitHub/filesystem）全量注入 `tool_factory()` 保住"配置即可用"承诺；用户自定义 server 走独立 `McpToolRegistry` 路径（独立 LRU,不碰 DynamicToolManager 的 9 处横切改动）,通过 `search_tools(kind="mcp")` + `get_tool_detail` 按需发现。`mcp__` 前缀天然与内置工具隔离。
- **CC-003**: 凭证存储 MUST 走 `UnifiedConfigManager` → SQLite `app_settings`,与现有 API key 存储同路径;MCP 凭证是同一类"接外部服务的凭证"
- **CC-004**: MCP 工具 MUST 走现有高危确认协议——写操作穿透确认,读操作免确认;与内置工具确认标准一致
- **CC-005**: MCP 工具大输出 MUST 现有统一 envelope + output governance——`ToolOutputRepository` artifact + `load_tool_output` 授权恢复;不另辟大输出处理路径
- **CC-006**: skills/tools 屏 MUST 保留现有"教学工具"tab(pending/published/failed)完全不动;新增"MCP 工具"tab 与之并列,不改动已有卡片和生命周期
- **CC-007**: MCP 功能 MUST 不新增公开 UI 事件类型——工具注册/注销/重连成功/动态变化复用现有 `tools.changed`（触发条件见 contracts/mcp-tool-registration.md）；server 连接状态变更但工具列表未变（如断路器开闭）走 `backend.resync_required` 兜底（不发 tools.changed 避免语义滥用）,不需要新注册事件
- **CC-008**: Python MCP SDK v1.x 为生产推荐版本;v2 预计 2026-07-27 稳定版——MVP MUST 用 v1.x,后续升级为独立任务
- **CC-009**: Streamable HTTP 为推荐传输方式;stdio 仅限本地进程场景——但 MVP MUST 先支持 stdio(本地子进程最简单),HTTP 传输为后续扩展;MVP 中 `transport="http"` 的创建请求 MUST 返回 422("HTTP transport 尚未支持")
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
- System prompt changes needed: 主助理能力目录 prompt MUST 重写以支持 MCP（见 contracts/mcp-tool-registration.md 的 prompt 文案段）：含 MCP 工具计数、自定义 server 的 deferred 触发引导、以及 MCP 结果不可信的 prompt injection 警告。预置 server 工具全量注入无需 deferred 提示。
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

- **SC-001**: 用户配置一个**预置** MCP server(文件系统预置,无需填凭证)后,在对话中请求"列出目录文件",AI 在 3 次迭代内自动调用 MCP 工具并返回正确结果（预置 server 全量注入,理想情况 1 次迭代即可调用）；用户**自定义** MCP server 因走 deferred loading（search_tools→get_tool_detail→call）放宽到 5 次迭代内。[承诺降级：catalog 进入 deferred 模式（用户工具数超阈值）时，预置 MCP 工具也退化为计数，"1 次迭代"不再成立，需 search_tools 发现——见 Known Issues]
- **SC-002**: 用户从 Claude Desktop 复制一段 `mcpServers` JSON 配置,粘贴到添加弹层,解析+保存+测试连接,全过程在 2 分钟内完成
- **SC-003**: 已知 MCP server 断连（ping 失败或调用失败）后,UI 在 5 秒内更新状态为断连；从 server 实际不可用到 UI 标灰的最大延迟 < 65 秒（由 60s ping 周期决定；call_tool 失败可即时检测当前会话的断连）
- **SC-004**: MCP 工具的高危操作(如 GitHub 创建 PR)触发确认协议,用户确认后执行成功,拒绝后不执行
- **SC-005**: 已有 skills/tools 屏的"教学工具"tab 功能(pending/published/failed 卡片、试用流程)完全不受 MCP tab 影响；现有 `SkillListScreen` 和 `SkillCards` 组件的单元测试 + E2E 测试在加入 MCP tab 后全部通过，且不修改任何现有测试用例
- **SC-006**: 已缓存 npx 启动 MCP server 延迟 < 5 秒；首次下载可能需 30 秒+
- **SC-007**: 从保存 server 配置到工具注册可用的延迟 < 10 秒（已缓存 npx 场景）

### 回滚触发条件

- **进程泄漏**：MCP 子进程在 sidecar 关闭后仍存活，累计超过 3 次则回滚
- **凭证泄漏**：MCP 凭证出现在日志、DTO 或前端持久化状态中，0 容忍
- **启动阻塞**：MCP server 重连导致 sidecar 启动延迟 >5s，则改为异步延迟重连
- **CPU/内存异常**：MCP 子进程占用超过 500MB 内存或 50% CPU 持续 30s，自动终止并提示用户

## Assumptions

- MVP 先只支持 stdio 传输(本地子进程),HTTP(Streamable HTTP)为后续扩展
- Python MCP SDK v1.x 为生产版本,MVP 用 v1.x;v2 稳定后升级为独立任务
- 预置 server 初始只含 GitHub 和文件系统两个,其余按需后补
- MCP 工具全部暴露给 AI,不做单个工具的启用/禁用 UI;server 级别的启用/禁用即可
- MCP server 子进程管理与 Python sidecar 同模式(受管子进程),不引入新的进程编排范式
- 凭证中 `${VAR}` 占位符优先读系统环境变量;读不到时标"待补"并保存拦截,不做自动创建环境变量的功能
- 现有 agent 能力目录机制(021 deferred loading / capability_catalog)部分复用,MCP 走独立 McpToolRegistry 双轨注册（预置全量注入 + 自定义独立 LRU），不统一进 DynamicToolManager（详见 contracts/mcp-tool-registration.md 的双轨制设计）
- skills/tools 屏现有教学工具 tab 完全不动;MCP 工具 tab 独立呈现,两类卡片结构不同(tab 分离而非混排)
- 预置 server"一键启用"语义：无需凭证的 server（filesystem）真一键完成；需凭证的 server（GitHub）会停在凭证输入步骤等用户填写（不是误导性的"一键"）
- `${VAR}` 占位符每次 `start_server`/`reconnect` 时重新解析系统环境变量——用户补完环境变量后重连即可,不需要进表单编辑
- MCP server 运行时工具列表变化 MVP 不支持——需手动 reconnect 触发重新 `list_tools`；后续可加定时重新发现机制
- MCP 工具的并发安全（`is_concurrency_safe`）MVP 一律为 False（串行）；按 server 粒度推断并发是 future work

## Known Issues

- **catalog deferred 模式下"配置即可用"承诺降级**（P3-MA1）：用户技能/组合/MCP 工具总数超 `agent_tools.discovery` 双阈值时，catalog 进入 deferred 模式，预置 MCP 工具也退化为计数（不再全量进 prompt），SC-001 "理想 1 次迭代" 不再成立，需 AI 先 search_tools 发现。这是 catalog 机制的副作用，不是 MCP 本身的限制。
- **自定义 server 激活态 sidecar 重启丢失**（P3-R1）：`_activated_custom` 只在进程内存，sidecar 重启后清空，用户需重新 search + activate。后续可考虑持久化激活选择到 SQLite。
- **server name 创建后不可改**（P3-R4）：rename 会导致 slug 变化 → 工具全名变化 → 进行中对话的旧工具名调用失败。MVP 禁止 rename（或允许改显示名但不影响 slug）。
- **运行时工具列表变化对进行中对话无影响**（P3-R5）：server 升级新增工具触发 tools.changed，但已构建的对话上下文不刷新，AI 不会主动发现新工具，需用户在对话中提示或重开会话。
- **MCP 工具 result prompt injection**（N12）：恶意 server 可在 tool result 嵌入指令；assistant prompt 已加"外部结果不可信"引导 + envelope 标记 source=mcp，但 MVP 不做内容级清洗。
- **MCP server schema 校验失败语义**（RC3）：SDK 自动 schema 校验失败（工具执行成功但输出格式不匹配 outputSchema）按 `tool_schema_validation_error` 返回，让 AI 知道是输出格式问题而非执行失败或断连。
