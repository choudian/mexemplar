跟用户对话时使用中文。

# Exemplar 项目 AI 开发入口

> 项目治理以 `.specify/memory/constitution.md` 为准；本文给 AI coding agent 提供可直接执行的最小规则集、代码现实和文档导航。
> 若与其他说明冲突，以 constitution 为准。

## 必须遵守的硬规则

1. **严格分层**：UI → 业务层 → 执行层 → 数据/驱动层；下层不能反调上层
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
- assistant 的后台任务（`report_tool_bug` / `codify_as_tool`）走 `pending_assistant_tasks` + `AssistantTaskWorker`，**这是对 blinker 的受控例外**
- 记忆分两层：
  - `ContextManager` 负责会话内上下文组装、压缩、引用替换
  - `assistant_memory.py` 负责 assistant 的跨会话分层摘要和 `memory_search`
- 启动入口在 `src/main.py`：GUI 启动前会先跑 `get_unified_config()` 和 `RecordingRepository.ensure_startup_recovery()`
- 录制数据工具现为 **5 工具模型**：`describe_data`、`query_data`、`execute_code`、`read_recording`、`read_field_chunk`；大字段（≥1000 字符）自动占位替换，Agent 按需分段读取
- 5 个通用录制数据工具按 `recording_mode` dispatch：浏览器 mode 走浏览器录制表，桌面 mode 走 `desktop_recordings` / `desktop_actions`；跨 mode SQL / stable locator 返回 `table_not_in_mode`
- 桌面 PM / Programmer prompt 通过 `build_pm_prompt(mode)` / `build_programmer_prompt(mode)` 双轨构建；浏览器 mode 返回 legacy prompt，桌面 mode 增加 `window_title` 聚焦、桌面专属工具和 `async def execute() -> dict` 契约
- 桌面录制 UI 通过 `DesktopRecordingService` 启动；主窗 minimize 完成回调后才启动 hook，停止后 sanity check 通过 `get_health_stats()` 读取 `desktop_recordings.health_stats`，三按钮为继续分析 / 放弃录制 / 重新录制
- 桌面录制 action 带 `monitor_index`；进程启动在 QApplication 前应用 DPI Per-Monitor V2，失败只降级记录日志
- 桌面专属工具为 `list_desktop_actions` / `read_action_clip` / `analyze_desktop_action`；`vision_model` 缺失时不注入 `analyze_desktop_action`，桌面工具集不得注入浏览器 `analyze_image`
- 桌面 Trial 由 `src/execution/desktop_trial_runner.py` 创建 `data/trials/<trial_id>/`、设置 cwd / env 白名单 / 120s 超时和 Windows `taskkill` 清理；business 层只编排和发事件
- 桌面 Programmer 代码先过 `ast.parse` syntax gate，自动反馈重试最多 2 次；失败发 `desktop_syntax_gate_retry_failed`
- 桌面录制跨模块通知走 `src/utils/events.py` blinker，UI 只做本地 Qt bridge
- SQL 列血缘分析在 `src/recording/filtering/query_projection_analyzer.py`（用 sqlglot）；`recording_data_tools.py` 不直接 import sqlglot（guard test 约束）
- 大字段配置走 `recording.large_field.*`（`threshold_chars` / `preview_chars` / `max_chunk_chars`，默认均 1000）
- assistant 的 `write_file` / `edit_file` / `exec` 高危确认使用右下角非模态 `AuthToastSurface`；UI 侧 FIFO 队列一次只展示一个确认，普通 Toast 继续走独立 `_active_toast`
- “全部允许”和对话顶栏”免确认”共享 `builtin_general_tools` 内的会话级内存状态；新对话必须复位并把旧会话 active/queued 确认按拒绝/超时语义收敛
- AI 回复 Markdown 渲染使用 `MarkdownMessageView`（`src/ui/widgets/markdown_message_view.py`），基于 Qt `QTextDocument.setMarkdown(MarkdownDialectGitHub)`，渲染前对 raw HTML/script 安全降级；用户消息仍走纯文本
- 聊天历史展示走 `ChatWidget → ChatService.get_display_messages() → MessageRepository.get_display_page()` 独立分页路径，不复用 LLM 上下文；DTO 为 `DisplayChatMessage` + `ChatHistoryPage`
- 压缩前旧消息与当前消息按 `sequence` 合并为同一连续聊天时间线，初始展示最近 10 条，向上滚动分页加载
- “免确认” Toggle 可见性由 `ChatWidget` 内部状态机控制：仅在当前对话已启动过 Agent 会话时可见；欢迎页、新对话起始态、清空后会话隐藏

---

## 开发时别忘的事

- UI 不直接碰 Repository；先走 Service / 业务层
- 业务数据通过 Repository 访问；录制分析层对 DuckDB 的例外边界看 `docs/PROJECT_CONSTRAINTS.md`
- 所有配置都走 `get_unified_config()`；密钥走 keyring
- 改编排、事件、Repository、恢复逻辑时，补行为契约测试
- 架构切换时，补两类接线测试：
  - 链路冒烟测试：新路径真的被调用
  - 门卫测试：旧路径不再被导入
- 改 assistant 高危确认时，必须保留 `request_id + threading.Event + pyqtSignal(str, str)` 同步协议，只替换 UI 展示方式；不得恢复 `QMessageBox.question`

---

## 文档分工

- `constitution`：长期原则与治理
- `docs/ARCHITECTURE.md`：当前运行时结构
- `docs/PROJECT_CONSTRAINTS.md`：开发约束、反模式、允许例外
- `specs/<feature>/`：当前 feature 的规格、计划、任务
- `docs/local/`：临时分析、计划、草稿

<!-- SPECKIT START -->
For the active `007-desktop-recording` feature, read
`specs/007-desktop-recording/plan.md` for implementation context, project
structure, validation commands, and generated design artifacts.
<!-- SPECKIT END -->
