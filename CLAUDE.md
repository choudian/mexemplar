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
- 压缩边界调整：`CompressionHandler._adjust_boundary_for_tool_pairs` 检测跨越压缩/保留边界的 tool 组（assistant(tool_calls) + tool result），整体移入保留区，避免配对断裂；边界调整后压缩区为空时跳过 LLM 调用和持久化
- `assemble_context` 在压缩后、引用替换前执行 `_cleanup_orphan_tool_results` 兜底校验，剔除孤立 tool result
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
- `AgentLoop.run()` 支持**多工具批次处理**：同一轮 LLM 响应的多个 tool_calls 按顺序执行并逐一保存结果；普通工具失败时停止后续真实执行并写入 `not_executed` 级联
- 中断型工具通过 `ToolDefinition.is_interrupting: bool` 声明式分类；与任何其他工具同轮出现时判定为 `invalid_model_output`，不执行任何 handler
- `is_interrupting` 与 handler 返回类型必须强一致（`True` → `ToolSignal`，`False` → `str`）；运行时不一致写入 `handler_contract_violation`
- 工具执行 Hook 系统：`ToolDefinition` 支持 `pre_hook`/`post_hook`；`AgentConfig` 支持 `global_pre_hooks`/`global_post_hooks`；hook 模型定义在 `hook_models.py`；`load_reference`/`talk_to_user` 不进入 hook 管线
- pre_hook 只做放行/拒绝/观测；post_hook 不形成流水线，每个 hook 看到同一个原始 handler 结果；详见 `docs/PROJECT_CONSTRAINTS.md` 和 `docs/ARCHITECTURE.md`
- 会话恢复走 `get_pending_tool_calls()`，只补齐最近 assistant 消息中未配对的调用，按原始顺序
- AgentLoop 发出的配对错误统一为标准化 JSON 结构：`{"error": "<code>", "message": "...", ...}`，错误码：`unknown_tool` / `handler_exception` / `handler_contract_violation` / `not_executed` / `invalid_model_output` / `pre_hook_rejected`
- Assistant 高危工具确认已从 `QMessageBox.question` 模态弹窗改为非阻塞 `AuthToastSurface` 浮层（右下角）；UI 端由 `AgentHandlerMixin` 的 FIFO 队列管理，一次显示一个浮层
- 确认状态模型：`PendingConfirmation` dataclass（request_id / tool_name / summary / decision / source）+ 模块级 `_auto_approve_enabled` 自动放行开关；均受 `_confirm_lock` 保护
- 脱敏摘要：`_truncate_summary` + `_sanitize_fragment` 生成工具参数摘要，自动截断长参数并替换敏感模式（sk-* / password= / token= / secret=）
- 结构化决策日志：每次终态决策写入 `logger.info`，含 request_id / tool_name / decision / source / elapsed_ms / summary
- 会话级自动放行："全部允许"按钮或顶栏"免确认" Toggle 开启后，同会话后续高危请求自动放行；新对话时 `reset_auto_approve` 复位
- 顶栏 Toggle 与浮层"全部允许"双向同步：任一入口变化，另一处同帧/下一帧内同步状态
- 新对话时 `settle_pending_confirmations` 按 monotonic 截止时间收敛旧会话未决请求
- `AuthToastSurface` 无普通关闭按钮，不响应外部点击关闭，只通过三按钮或 QTimer 超时结束
- 普通 Toast 与确认浮层独立生命周期管理，互不覆盖；`MainWindow.resizeEvent` 分别重定位
- PM / Trial Agent 的 `IntentConfirmationUI` 和手动参数 `ToolExecutionDialog` 不受确认 Toast 化影响
- AI 回复 Markdown 渲染使用 `MarkdownMessageView`（`src/ui/widgets/markdown_message_view.py`），基于 Qt `QTextDocument.setMarkdown(MarkdownDialectGitHub)`，渲染前对 raw HTML/script 安全降级；用户消息仍走纯文本 `QLabel`
- 聊天历史展示走 `ChatWidget → ChatService.get_display_messages() → MessageRepository.get_display_page()` 独立分页路径，不复用 LLM 上下文的 `ContextManager`；DTO 为 `DisplayChatMessage` + `ChatHistoryPage`，不暴露 `is_archived`/`message_type` 给 UI
- 压缩前旧消息（含 archived）与当前消息按 `sequence` 合并为同一条连续聊天时间线，初始展示最近 10 条，向上滚动分页加载
- "免确认" Toggle 可见性由 `ChatWidget` 内部状态机控制：仅在当前对话已启动过 Agent 会话时可见；欢迎页、新对话起始态、清空后会话隐藏

---

## 开发时别忘的事

- UI 不直接碰 Repository；先走 Service / 业务层
- 业务数据通过 Repository 访问；录制分析层对 DuckDB 的例外边界看 `docs/PROJECT_CONSTRAINTS.md`
- 所有配置都走 `get_unified_config()`；密钥走 keyring
- 改编排、事件、Repository、恢复逻辑时，补行为契约测试
- 改 AgentLoop 工具处理或中断型工具时，确保多工具批次配对完整（14 场景集成测试在 `tests/integration/test_agent_loop_multi_tool_calls.py`）
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

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/007-desktop-recording/plan.md`
<!-- SPECKIT END -->
