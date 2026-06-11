跟用户对话时使用中文。

# Exemplar 项目 AI 开发总入口

> 项目治理以 `.specify/memory/constitution.md` 为准；本文只放跨模块通用规则、运行时总览和模块导航。
> 若与其他说明冲突，以 constitution 为准；进入具体模块工作时，还必须读取该模块目录下的 AI 入口文档。
>
> AI 入口同步规则：当前项目 `.specify/init-options.json` 的 `context_file` 是 `AGENTS.md`；`CLAUDE.md` 和 `GEMINI.md` 是同内容兼容镜像。根目录和各模块目录内的 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` 必须保持同内容。

## 模块入口

- `frontend/`：React + TypeScript 前端。进入该目录工作时先读 `frontend/AGENTS.md`。
- `src/`：Python 后端、desktop API、业务层、执行层、数据层和录制层。进入该目录工作时先读 `src/AGENTS.md`。
- `src-tauri/`：Tauri 2 / Rust 桌面壳、窗口命令、sidecar 生命周期和打包配置。进入该目录工作时先读 `src-tauri/AGENTS.md`。
- 跨模块改动必须同时遵守相关模块入口；如果约束变化只影响某个模块，优先更新该模块 AI 文档；如果影响模块边界或全局协作，再更新根目录 AI 文档。

## 必须遵守的全局硬规则

1. **严格分层**：UI → 业务层 → 执行层 → 数据/驱动层；下层不能反调上层。
2. **业务数据走 Repository**：不要在业务代码里直接写 SQL；DuckDB 录制分析层的例外边界看 `docs/PROJECT_CONSTRAINTS.md`。
3. **配置统一入口**：配置走 `get_unified_config()`；密钥走 keyring；不要直接读 `config.json` 或硬编码。
4. **跨模块通知默认用 blinker**：assistant 的 `report_tool_bug` / `codify_as_tool` 是受控例外，必须走 DB 队列 + Worker，不能直接 emit 后同步嵌套 Agent。
5. **UI 不直接碰数据层**：UI 通过 typed API / Service / Bridge 调业务层，不直接调用 Repository。
6. **改静默失败路径必须补测试**：尤其是编排、事件、Repository、恢复逻辑；架构切换时补链路冒烟测试和门卫测试。
7. **改文档时只改活文档**：原则/流程改 constitution，运行结构改 `docs/ARCHITECTURE.md`，开发约束改 `docs/PROJECT_CONSTRAINTS.md`，模块约束改对应模块 AI 文档。
8. **AI 入口保持同内容镜像**：同一目录内的 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` 必须同步，不允许只更新某个工具专属入口。

## 当前运行时总览

- 当前桌面应用是前后端分离结构：`frontend/` 渲染 UI，`src-tauri/` 启动桌面窗口和 Python sidecar，`src/desktop_api/` 提供本地 FastAPI bridge，最终调用 `src/business`、`src/execution`、`src/recording`、`src/data`。
- `src/desktop_api/` 是 UI adapter，不是数据访问层；它只处理 DTO、auth、错误映射、事件流和业务入口调用。
- 前端 React 主界面共 **七个主屏**：AI Assistant、Skill Teaching、Skill List、Skill Composition、Settings、**Brain Management**（`/brain`）、**Specialist Management**（`/brain/specialists`）。
- `src/business/brain/` 是办公助理的"大脑"业务层：6 个认知分区（hot / persistent / archive / subconscious / failure / prediction）、Segment 沉淀、专员系统、后台 worker、显式 archive 检索；存储走 SQLite 的 `brain_*` 表（v11 migration），跨模块通知用 `brain_*` blinker 事件。
- 公开 UI 事件契约以 `src/desktop_api/ui_events.py` 的 **UI Event Registry** 为权威：每条 envelope 含 `eventId / sequence / sessionId / causationId / type / scope / payload / createdAt`，前端按 sessionId + last-seen sequence 重连回放，缺口或会话不匹配走 `backend.resync_required` 拉权威快照。
- sidecar API 绑定随机 localhost 端口，并使用每次启动生成的 runtime token；token 不持久化、不写普通日志、不进入 OpenAPI 或错误响应。
- `src/main.py`、`mexemplar_gui.py`、`start.bat`、`mexemplar_gui.bat` 是显式失败的 legacy 兼容入口；正常开发和打包路径走 Tauri shell。
- `src/ui/`、`tests/ui/` 和旧 Python GUI E2E 不再是维护面；新增 UI 行为覆盖放在 `frontend/tests/unit/` 或 `frontend/tests/e2e/`。
- 后端桥接和跨层行为覆盖放在 `tests/desktop_api/`、`tests/integration/` 或 `tests/guardrails/`。

## 先看哪里

1. 长期原则：`.specify/memory/constitution.md`
2. 当前系统怎么组织：`docs/ARCHITECTURE.md`
3. 开发约束与允许例外：`docs/PROJECT_CONSTRAINTS.md`
4. 当前 feature 要做什么：对应 `specs/<feature>/` 下的 `spec.md`、`plan.md`、`tasks.md`
5. 当前模块怎么改：最近目录下的 `AGENTS.md`

## 跨模块协作要点

- 前端只能通过 typed API client、Tauri window command 或本地 UI state 访问产品能力。
- Tauri/Rust 层只负责桌面壳、窗口命令、sidecar 生命周期、端口/token handoff 和打包；不要塞 Python 业务规则。
- Python 后端是业务语义来源；业务层不 import 前端或 Tauri，数据层不反调业务/UI。
- 后端内部跨模块通知用 `src/utils/events.py` 的 blinker 事件；面向前端的事件必须经 UI Event Registry 注册并以 typed envelope 发出，不允许裸事件名或未注册 payload 直接走 SSE。
- 高危确认必须保留 `request_id + threading.Event + emit(request_id, message)` 同步协议；可以换 UI 展示，不得恢复模态阻塞确认。
- 试用预览交互式确认走广播 + first-decision-wins 协议，每条请求带后端生成的 `expires_at`；超时、断连、关闭一律 fail-closed 当拒绝。
- “全部允许/免确认”只允许是当前进程会话级内存状态，不得写入配置、keyring、SQLite 或 DuckDB。
- 办公助理（assistant）走 **100% 调度**：任务派给临时 subagent 或固定专员，主助理不直接执行；PM / Programmer / Trial 不在调度池内。

## Recent Changes

- 016-tool-output-semantic-summary: 所有文本工具结果统一进入大输出治理；compact envelope 保留确定性 facts/preview 和 raw reference，并可用独立低成本模型在 12 秒预算内生成 goal-aware 单块或 Map-Reduce advisory 摘要。摘要模型配置和独立 keyring 密钥在 Settings“工具输出”分区管理。
- 015-agent-builtin-tools-upgrade: Agent 内置基础工具升级为统一 envelope + workspace 权限契约，文件读取/写入/编辑/patch/search/exec/process/output recovery 均走 baseline、分页/截断、fail-closed 确认和 output governance；大输出通过 `ToolOutputRepository` 私有 artifact + `load_tool_output` 授权恢复。
- 014-assistant-chat-transparency: AI Assistant 主屏新增运行态输入门控、协作式深度取消停止、单条原地排队、实时折叠活动时间线、子任务卡片/详情，以及暂停子任务经主助理续跑；过程/子任务事件走 UI Event Registry，历史过程由既有 Repository 只读重建。
- 013-subagent-resumable: 临时子代理可唤回机制——撞迭代上限或 LLM 调用最终失败时转 `suspended` 保活，主代理可 `inspect_subagent`（零模型调用概览）和 `continue_subagent`（断点续跑/返工），归属校验拒绝非己出会话，`_is_recoverable_llm_failure` 区分可恢复（配额/网络）与不可恢复失败，跨进程重启仍可唤回。
- 010-assistant-brain-redesign: 办公助理重构为"大脑 + 100% 调度"架构，新增 `src/business/brain/` 6 分区认知层（hot/persistent/archive/subconscious/failure/prediction）、Segment 沉淀、自动招募专员、显式 archive/failure 检索工具、`brain_*` SQLite 表（v11 migration）、`BrainScreen` 和 `SpecialistScreen` 两个新主屏。
- 009-frontend-event-layer: 前端事件层重写，新增后端 **UI Event Registry**（公开契约权威来源）、typed envelope（`eventId / sequence / sessionId / causationId / type / scope / payload`）、per-subscriber event stream、same-session replay + `backend.resync_required` 兜底、试用预览广播 + first-decision-wins + `expires_at` 闭环、payload safety allowlist。
- 008-ui-stack-redesign: 主桌面 UI 切到 Tauri 2 + React + TypeScript，新增 Python FastAPI sidecar bridge、frontend 状态/API 层、Tauri custom chrome、五个主屏和 legacy PyQt removal guards。
- 007-desktop-recording: 新增 Windows 桌面录制 Phase 1、桌面数据工具、双轨 prompt、syntax gate、Trial 子进程和 sanity check UI。
- 006-chat-ui-polish: 聊天历史展示改为独立分页时间线，前端隐藏 archive/compression 术语，Markdown 回复走 `SafeMarkdown`。
- 005-fix-compression-tool-pairing: 压缩边界保护 assistant tool_calls 与 tool results 配对，避免孤立 tool result 进入上下文。
- 004-auth-toast: assistant 高危确认改为前端非模态确认浮层，并保留同步确认协议和会话级免确认语义。
- 003-fix-agentloop-tool-calls: AgentLoop 支持同轮多工具调用完整配对、声明式中断型分类和恢复补齐。
- 002-tool-hook-system: 新增 Agent 工具执行 pre/post hook 协议、AgentConfig global hooks，并把门卫式工具 gate 迁移到 pre_hook。
- 001-recording-field-layering: 录制数据工具改为 5 工具模型，大字段按需占位与 `read_field_chunk` 分段读取。

## Known Issues & Gotchas

### 模块边界不能被临时绕开

**Issue:** 前端、Tauri shell、desktop API 或业务层为了补功能直接读写下层资源，会把分层重新混在一起。
**Root Cause:** UI 重构后接口很多，缺口容易被就地补在最方便的目录。
**Prevention Rule:** 缺业务能力时先补业务 Service / facade / repository，再由模块边界调用；不要跨层直连。

### Sidecar runtime token 不能泄漏

**Issue:** localhost API 即使只绑定本机，也可能被其它本机进程调用。
**Root Cause:** loopback 不是鉴权边界，打包 sidecar 端口还是网络端口。
**Prevention Rule:** 每次启动生成随机 token，所有 API/event-stream 请求带 `X-Mexemplar-Session`，token 不持久化、不进普通日志、不作为 UI 文本展示。

### Legacy PyQt 只能是失败提示路径

**Issue:** 恢复 `src/main.py` 或 `mexemplar_gui.py` 的正常 PyQt UI 会重新引入双 UI 栈。
**Root Cause:** 008 接受态要求单一 Tauri/React 主界面，PyQt 主 UI 已被移除或替换。
**Prevention Rule:** 正常启动、开发和打包路径都走 Tauri shell；任何 PyQt 入口只能显示 legacy/迁移失败提示，并由 guard tests 约束。

### 大脑数据不能物理删除或泄漏分区

**Issue:** 直接 DELETE `brain_memory_entries` 行、把 prediction zone 注入 assistant 上下文、或让 specialists 物理删除会破坏可追溯性和"100% 调度"约束。
**Root Cause:** brain 设计要求"distilled data 永不物理删除"——invalidation 是降权、user delete 是 soft-delete、edit 是新建条目 + `superseded_by` 链；prediction zone 仅做系统自校准，不暴露给 assistant；specialists 走 `is_active=0` 软删但保留版本历史。
**Prevention Rule:** 走 `BrainRepository` / `SpecialistRepository` 的 soft delete / invalidation / supersede 路径；不写直接物理 DELETE；prediction 条目只在 BrainScreen 管理界面展示，不进 context_builder 注入。

### 前端不得用内部事件名做展示决策

**Issue:** React store 用 `payload.sourceEvent` 或内部 blinker 事件名（如 `workflow_completed`）判断要不要刷新某个屏，是 009 之前的反模式。
**Root Cause:** 009 把公开 UI 事件契约收敛到后端 UI Event Registry；前端只能消费注册过的 typed event type。
**Prevention Rule:** 新增展示行为先在 `src/desktop_api/ui_events.py` 注册公开事件 type + payload allowlist，再在前端 store 按 type 消费；缺失上下文走 `backend.resync_required` 拉权威快照。

### 子代理暂停不等于失败，但不可恢复错误仍是错误

**Issue:** 将所有 LLM 调用失败一概转为可唤回暂停、或把暂停与失败混为一谈，会导致主代理对不可恢复错误（400/认证/序列化 bug）无效等待"等恢复后再续"。
**Root Cause:** `_call_llm_with_retry` 对任何异常重试耗尽后返回 `None`，本身无法区分可恢复与不可恢复失败；需要 `_is_recoverable_llm_failure` 按异常类型/消息做二次分类。
**Prevention Rule:** `_is_recoverable_llm_failure` 必须按异常链严格匹配——仅 429/配额/billing/网络/超时/5xx 转可唤回 PAUSED，其余仍走 `ERROR` 置会话 `failed`；不可恢复错误的测试 (`test_llm_failure_nonrecoverable_still_error_when_resumable`) 必须持续通过。

### Agent 内置工具不能绕过统一安全契约

**Issue:** 新增或修改 `read_file` / `write_file` / `edit_file` / `apply_patch` / `search_*` / `exec` / process / `load_tool_output` 时，如果直接返回旧纯文本、绕过 baseline、workspace policy 或 output governance，会破坏 function-calling 配对、安全确认和 raw artifact 隔离。
**Root Cause:** 通用内置工具现在由 `builtin_general_tools.py` facade 分发到 focused 模块，安全语义分散在 shared envelope、permission helper、AgentLoop 保存边界和 Repository blob 管理中，临时就地补逻辑容易漏掉其中一层。
**Prevention Rule:** 已升级内置工具必须返回统一 envelope；既有文件 mutation 必须带当前 raw-byte baseline；workspace 外写/删/patch/exec fail-closed；大输出只能经 `ToolOutputRepository` 私有 artifact + `load_tool_output` 授权读取；配置只走 `get_unified_config().get_agent_tools_*`。

### 语义摘要不能替代确定性事实

**Issue:** 让模型摘要覆盖 exit code、错误码或状态，或摘要失败后丢掉 raw reference，会把辅助信息误当成执行真相。
**Root Cause:** 工具输出很大时，模型摘要更易读，但它仍可能遗漏、误判或超时。
**Prevention Rule:** `facts` / `preview` 始终由确定性逻辑生成；`semanticSummary` 固定 `advisory=true`，失败时直接省略；摘要前后都脱敏，原文 reference 在摘要调用前完成复用或创建。

<!-- SPECKIT START -->
The `016-tool-output-semantic-summary` feature was archived to `.specify/memory/` on 2026-06-11.
For historical context, see `specs/016-tool-output-semantic-summary/`.

The `015-agent-builtin-tools-upgrade` feature has been archived to `.specify/memory/`.
For historical context, see `specs/015-agent-builtin-tools-upgrade/`.

The `014-assistant-chat-transparency` feature has been archived to `.specify/memory/`.
For historical context, see `specs/014-assistant-chat-transparency/`.

The `013-subagent-resumable` feature has been archived to `.specify/memory/`.
For historical context, see `specs/013-subagent-resumable/`.
<!-- SPECKIT END -->
