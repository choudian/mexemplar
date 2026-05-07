跟用户对话时使用中文。
# Exemplar 项目 AI 开发入口

> 项目治理以 `.specify/memory/constitution.md` 为准；本文给 AI coding agent 提供可直接执行的最小规则集、代码现实和文档导航。
> 若与其他说明冲突，以 constitution 为准。

## 必须遵守的硬规则

1. **严格分层**：UI → 业务层 → 接口层/驱动层 → 数据层；下层不能反调上层
2. **业务数据走 Repository**：不要在业务代码里直接写 SQL；DuckDB 录制分析层的例外边界看 `docs/PROJECT_CONSTRAINTS.md`
3. **配置统一入口**：配置走 `get_unified_config()`；密钥走 keyring；不要直接读 `config.json` 或硬编码
4. **跨模块通知默认用 blinker**：但 assistant 的 `report_tool_bug` / `codify_as_tool` 是受控例外，必须走 DB 队列 + Worker，不能直接 emit 后同步嵌套 Agent
5. **UI 不直接碰数据层**：UI 通过 Service / Bridge 调业务层，不直接调用 Repository
6. **改静默失败路径必须补测试**：尤其是编排、事件、Repository、恢复逻辑；架构切换时补链路冒烟测试和门卫测试
7. **改文档时只改活文档**：原则/流程改 constitution，运行结构改 `docs/ARCHITECTURE.md`，开发约束改 `docs/PROJECT_CONSTRAINTS.md`

## 先看哪里

1. **长期原则**：`.specify/memory/constitution.md`
2. **当前系统怎么组织**：`docs/ARCHITECTURE.md`
3. **开发约束与允许例外**：`docs/PROJECT_CONSTRAINTS.md`
4. **当前 feature 要做什么**：对应 `specs/<feature>/` 下的 `spec.md`、`plan.md`、`tasks.md`

---

## 当前代码现实

- Orchestrator 实现在 `src/business/orchestration/agent/`，由多个子组件协作：`AgentSessionStore`、`AssistantPromptBuilder`、`AssistantTaskWorker`、`TeachingFailureTracker`、`WorkflowRetryCoordinator`
- `AgentLoop.run()` 支持两种工具注入方式：
  - 直接传 `list[ToolDefinition]`（PM / 程序员 / 试用）
  - 传 `callable` 每轮重建工具列表（assistant 的动态工具懒加载依赖这个）
- 工具执行 Hook 系统：`ToolDefinition` 支持 `pre_hook` / `post_hook`；`AgentConfig` 支持 `global_pre_hooks` / `global_post_hooks`；hook 模型定义在 `src/business/agents/hook_models.py`
- pre_hook 只做放行/拒绝/观测，不支持改参；`ToolCallContext.args` 是递归只读隔离视图；post_hook 不做流水线，每个 hook 都看到 handler 原始字符串结果
- `write_file` / `edit_file` / `exec` 等确认类 pre_hook 必须 fail-closed：确认请求异常时返回拒绝，不能让 AgentLoop 通用 pre_hook 异常策略放行 handler
- AgentLoop 注入的 `talk_to_user` / `load_reference` 不进入 hook 管线；callable 动态工具路径每轮刷新 handler、hook 和 `is_interrupting` 元数据
- assistant 的后台任务（`report_tool_bug` / `codify_as_tool`）走 `pending_assistant_tasks` + `AssistantTaskWorker`，**这是对 blinker 的受控例外**
- 记忆分两层：
  - `ContextManager` 负责会话内上下文组装、压缩、引用替换
  - `assistant_memory.py` 负责 assistant 的跨会话分层摘要和 `memory_search`
- 启动入口在 `src/main.py`：GUI 启动前会先跑 `get_unified_config()` 和 `RecordingRepository.ensure_startup_recovery()`
- 录制数据工具现为 5 工具模型：`describe_data`、`query_data`、`execute_code`、`read_recording`、`read_field_chunk`；桌面 mode 通过 mode dispatch 走 `desktop_recordings` / `desktop_actions`
- 桌面录制 UI 通过 `DesktopRecordingService` 启动；主窗 minimize 完成回调后才启动 hook，停止后 sanity check 通过 `get_health_stats()` 读取 `desktop_recordings.health_stats`
- 桌面专属工具为 `list_desktop_actions` / `read_action_clip` / `analyze_desktop_action`；`vision_model` 缺失时不注入 `analyze_desktop_action`，桌面工具集不得注入浏览器 `analyze_image`
- 桌面 Trial 由 `src/execution/desktop_trial_runner.py` 创建 `data/trials/<trial_id>/`、设置 cwd / env 白名单 / 120s 超时和 Windows `taskkill` 清理；business 层只编排和发事件
- 桌面 Programmer 代码先过 `ast.parse` syntax gate，自动反馈重试最多 2 次；失败发 `desktop_syntax_gate_retry_failed`
- 桌面录制跨模块通知走 `src/utils/events.py` blinker，UI 只做本地 Qt bridge

---

## 开发时别忘的事

- UI 不直接碰 Repository；先走 Service / 业务层
- 业务数据通过 Repository 访问；录制分析层对 DuckDB 的例外边界看 `docs/PROJECT_CONSTRAINTS.md`
- 所有配置都走 `get_unified_config()`；密钥走 keyring
- 改编排、事件、Repository、恢复逻辑时，补行为契约测试
- 改 AgentLoop 工具执行、hook、确认 gate 或中断型工具时，补 `tests/test_hook_protocol.py` / 多工具批处理回归，确保失败级联和 `ToolSignal` 语义不漂移
- 架构切换时，补两类接线测试：
  - 链路冒烟测试：新路径真的被调用
  - 门卫测试：旧路径不再被导入

---

## 文档分工

- `constitution`：长期原则与治理
- `docs/ARCHITECTURE.md`：当前运行时结构
- `docs/PROJECT_CONSTRAINTS.md`：开发约束、反模式、允许例外
- `specs/<feature>/`：当前 feature 的规格、计划、任务
- `docs/local/`：临时分析、计划、草稿

## Recent Changes

- 007-desktop-recording: 新增 Windows 桌面录制 Phase 1、桌面数据工具、双轨 prompt、syntax gate、Trial 子进程和 sanity check UI。
- 002-tool-hook-system: 新增 Agent 工具执行 pre/post hook 协议、AgentConfig global hooks，并把门卫式工具 gate 迁移到 pre_hook。
- 003-fix-agentloop-tool-calls: AgentLoop 支持同轮多工具调用完整配对、声明式中断型分类和恢复补齐。
- 001-recording-field-layering: 录制数据工具改为 5 工具模型，大字段按需占位与 `read_field_chunk` 分段读取。

## Known Issues & Gotchas

### Hook 不做参数或结果流水线
**Issue:** pre_hook 不是改参系统，post_hook 的改写也不会传给后续 post_hook。
**Root Cause:** hook 只承担 gate/观测/结果替换职责；流水线语义会把 hook 顺序变成业务逻辑。
**Prevention Rule:** 不要引入 `PreHookResult.args`、`ToolCallContext.result` 或 post_hook 串联改写依赖；需要改参时应显式改 handler 或工具定义。

### 确认类 pre_hook 必须 fail-closed
**Issue:** `_ask_user_confirm()` 如果抛异常，AgentLoop 的通用 pre_hook 异常策略会继续执行 handler。
**Root Cause:** 通用 hook 契约为了不污染工具结果而在 pre_hook 异常后运行 handler；确认 gate 属于安全边界，必须在 hook 内捕获异常并返回拒绝。
**Prevention Rule:** `write_file`、`edit_file`、非安全 `exec` 等确认 gate 必须用本地包装捕获确认异常，返回 `PreHookResult(error=...)`。

### 桌面录制 hook 启动不能早于主窗最小化完成
**Issue:** 如果点"开始"后立即启动 hook，开始按钮 click 会污染为首个桌面动作。
**Root Cause:** 用户点击仍发生在 Exemplar 窗口内，目标应用尚未获得焦点。
**Prevention Rule:** desktop hook / ring buffer / UIA / clipboard 订阅必须在 Qt minimize 完成回调后启动，UI 只通过 `DesktopRecordingService.start_after_minimize()` 进入业务层。

### 桌面 vision 只独立 model，不独立 provider
**Issue:** 为桌面录制新增独立 vision provider 会分裂密钥和 routing 语义。
**Root Cause:** Phase 1 约定 provider 维度复用 `analyze_image`，仅 `recording.desktop.vision_model` 独立。
**Prevention Rule:** `analyze_desktop_action` 复用 `analyze_image` 的 provider/keyring entry；`vision_model` 缺失时不注入该工具，并用设置页说明和一次性 toast 告知用户。

### Desktop Trial 子进程只能由 execution runner 创建
**Issue:** UI 或 business 直接创建 `data/trials/`、启动 subprocess 或继承全量 env 会破坏分层和安全边界。
**Root Cause:** Trial 执行需要 cwd 隔离、env 白名单、stdout/stderr 落盘和 120s `taskkill` 兜底。
**Prevention Rule:** 只通过 `src/execution/desktop_trial_runner.py` 启动桌面 Trial；business/orchestrator 只编排 runner 调用和 blinker 事件，UI 只展示对话框和 Toast。
