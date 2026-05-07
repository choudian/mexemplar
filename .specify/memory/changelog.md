# Merged Features Log

## 录制数据大字段按需读取 — 2026-04-25

**Branch:** `001-recording-field-layering`
**Spec:** `specs/001-recording-field-layering`

**What was added:**
- US-001 (P1): query_data 对任意达到阈值的文本字段返回结构化占位对象，取代旧 12KB 截断
- US-002 (P1): 新增 `read_field_chunk` 工具，Agent 按 locator + field + offset 分段读取原文
- US-003 (P2): 多次续读闭环、EOF 空成功、Unicode 码点切片、9 种错误码全覆盖
- US-004 (P2): describe_data 增补机器可读大字段提示；prompt/文档更新为 5 工具工作流

**New Components:**
- `src/recording/filtering/query_projection_analyzer.py` — SQL 列血缘分析 (sqlglot)
- `tests/recording/test_recording_data_large_fields.py` — 占位+续读+错误+性能+配置测试
- `tests/recording/filtering/test_query_projection_analyzer.py` — 分析器单元测试
- `tests/recording/filtering/test_recording_tools_no_sqlglot.py` — import guard test

**Modified Components:**
- `src/business/agents/tools/recording_data_tools.py` — 占位 builder + read_field_chunk + 5 工具注册
- `src/data/config_models.py` — LargeFieldConfig dataclass
- `src/data/unified_config.py` — get_recording_large_field_config()
- `config.example.json` / `config.example.comments.md` — recording.large_field.* 配置
- `src/business/agents/prompts/pm_prompt.py` / `programmer_prompt.py` — 5 工具工作流
- `docs/ARCHITECTURE.md` / `docs/design/*.md` — 文档同步

**Tasks Completed:** 44/44 tasks

## AgentLoop 多工具调用结果配对修复 — 2026-04-26

**Branch:** `003-fix-agentloop-tool-calls`
**Spec:** `specs/003-fix-agentloop-tool-calls`

**What was added:**
- US-005 (P1): 多工具调用完整配对 — 同轮多个普通工具按顺序执行并逐一保存结果
- US-006 (P1): 中断型工具行为可预期 — 混合批次拒绝、solo 中断保留既有语义、handler 契约校验
- US-007 (P2): 会话恢复按原始顺序补齐缺失结果，不重复已完成调用

**New Components:**
- `ToolDefinition.is_interrupting` — 声明式中断型分类字段
- `classify_tool_calls()` — 批次分类 helper
- `make_error_result()` / `ERROR_CODES` — 标准化错误结构生成
- `tests/integration/test_agent_loop_multi_tool_calls.py` — 14 场景集成测试

**Modified Components:**
- `src/business/agents/agent_loop.py` — 多工具批次处理、失败级联、中断校验、契约校验、恢复
- `src/business/agents/config.py` — ToolDefinition 新增 `is_interrupting` 字段
- `src/business/agents/tools/*.py` — 中断型工具注册添加 `is_interrupting=True`
- `src/business/memory/context_manager.py` — `get_pending_tool_calls()` 多工具恢复

**Tasks Completed:** 34/34 tasks

## 工具执行 Pre/Post Hook 系统 — 2026-04-27

**Branch:** `002-tool-hook-system`
**Spec:** `specs/002-tool-hook-system`

**What was added:**
- US-008 (P1): `ToolDefinition` 支持工具级 pre/post hook，未声明 hook 的工具保持透明行为
- US-009 (P2): `builtin_general_tools`、`recording_data_tools`、`trial_tools` 的门卫式 gate 迁移到 pre_hook
- US-010 (P3): `AgentConfig` 支持实例级 global pre/post hooks，按固定顺序作用于 `ToolDefinition` 工具

**New Components:**
- `src/business/agents/hook_models.py` — hook 协议 dataclass/type alias 与递归 args freezing helper
- `tests/test_hook_protocol.py` — hook 协议、迁移 gate、global hook、动态工具和性能烟测覆盖

**Modified Components:**
- `src/business/agents/agent_loop.py` — hook-aware per-call execution、hook 异常处理、post_hook rewrite、可靠失败状态
- `src/business/agents/config.py` — `ToolDefinition.pre_hook/post_hook` 与 `AgentConfig.global_pre_hooks/global_post_hooks`
- `src/business/agents/tools/builtin_general_tools.py` — read/write/edit/list/exec pre_hooks；确认请求失败 fail-closed
- `src/business/agents/tools/recording_data_tools.py` — query_data/analyze_image gate pre_hooks
- `src/business/agents/tools/trial_tools.py` — run_command per-run pre_hook 限流
- `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` — hook 运行结构与边界文档

**Tasks Completed:** 34/37 tasks

## 上下文压缩 tool_call/tool_result 配对修复 — 2026-04-27

**Branch:** `005-fix-compression-tool-pairing`
**Spec:** `specs/005-fix-compression-tool-pairing`

**What was added:**
- US-011 (P1): 压缩切分时检测跨越边界的 tool 组并整体移入保留区，修复 400 错误
- US-012 (P2): 多次压缩后边界 tool 组不累积——已完全在压缩区内部的被正常压缩
- US-013 (P3): assemble_context 兜底校验检测并剔除孤立 tool result，恢复路径自愈

**New Components:**
- `src/business/memory/compression_handler._adjust_boundary_for_tool_pairs` — 边界 tool 组检测与移入
- `src/business/memory/context_manager._cleanup_orphan_tool_results` — 孤立 tool result 兜底校验
- `tests/business/memory/test_compression_tool_pairing.py` — 边界调整 7 场景
- `tests/business/memory/test_context_orphan_cleanup.py` — 孤立校验与兼容性 6 场景
- `tests/business/memory/conftest.py` — mock Message 工厂与 mock MessageRepository

**Modified Components:**
- `src/business/memory/compression_handler.py` — `_split_messages` 接入边界调整；`compress` 处理空压缩区
- `src/business/memory/context_manager.py` — `assemble_context` 接入孤立校验
- `docs/ARCHITECTURE.md` — 压缩流程边界调整描述
- `CLAUDE.md` — 当前代码现实补充

**Tasks Completed:** 15/15 tasks
## 高危操作确认 Toast 化 — 2026-04-27

**Branch:** `004-auth-toast`
**Spec:** `specs/004-auth-toast`

**What was added:**
- US-011 (P1): Assistant 高危工具确认从 QMessageBox 模态弹窗改为非阻塞右下角浮层
- US-012 (P2): 浮层"全部允许"按钮开启会话级自动放行，新对话自动复位
- US-013 (P3): 顶栏"免确认"Toggle 与浮层双向同步

**New Components:**
- `src/ui/widgets/auth_toast.py` — AuthToastSurface 非模态确认浮层
- `tests/test_auth_toast_confirmation.py` — 确认状态/脱敏/自动放行业务测试
- `tests/ui/test_auth_toast_surface.py` — 浮层 UI 测试
- `tests/ui/test_chat_widget_auth_toggle.py` — Toggle 状态同步测试

**Modified Components:**
- `src/business/agents/tools/builtin_general_tools.py` — PendingConfirmation、自动放行状态、脱敏摘要/日志、确认 helper 重构
- `src/ui/mixins/agent_handler_mixin.py` — 非阻塞确认队列替代 QMessageBox
- `src/ui/main_window.py` — auth toast 状态/队列/resize 重定位
- `src/ui/widgets/chat_widget.py` — 顶栏 Toggle + new_chat_started 信号
- `src/ui/resources/styles.qss` — auth toast + Toggle 样式

**Tasks Completed:** 37/38 tasks (T038 black/flake8 待完成)

## 聊天界面体验完善 — 2026-04-29

**Branch:** `006-chat-ui-polish`
**Spec:** `specs/006-chat-ui-polish`

**What was added:**
- US-014 (P1): AI 回复 Markdown 渲染为富文本（标题、列表、代码块、表格、远程图片等），用户消息保持纯文本
- US-015 (P2): 压缩后旧聊天记录按原时间线分页回看，初始 10 条，向上滚动加载更早历史
- US-016 (P3): "免确认" Toggle 仅在已启动 Agent 的对话中可见，欢迎页/新对话起始态隐藏

**New Components:**
- `src/ui/widgets/markdown_message_view.py` — Markdown 安全渲染 widget（Qt 内建）
- `src/business/services/chat_service.py` — DisplayChatMessage/ChatHistoryPage DTO + get_display_messages()
- `tests/ui/test_chat_widget_markdown.py` — Markdown 渲染/安全降级测试
- `tests/ui/test_chat_widget_history.py` — 历史分页/性能/归档透明性测试
- `tests/ui/test_chat_widget_layering.py` — UI 分层门卫测试
- `tests/business/test_chat_service_history.py` — Service 契约测试
- `tests/data/chat_history_test_helpers.py` + `tests/ui/chat_widget_test_helpers.py` — 测试辅助

**Modified Components:**
- `src/ui/widgets/chat_widget.py` — Markdown 集成 + 历史分页 + Toggle 可见性状态机
- `src/data/repos/message_repository.py` — get_display_page() 展示历史分页查询
- `src/ui/resources/styles.qss` — Markdown 内容样式
- `docs/ARCHITECTURE.md` — 展示历史分页路径文档

**Tasks Completed:** 36/36 tasks

## 桌面录制 Phase 1 — 2026-05-07

**Branch:** `007-desktop-recording`
**Spec:** `specs/007-desktop-recording`

**What was added:**
- US-017 (P1): 桌面录制从"暂不支持"变为 Windows-only 录制闭环，包含 minimize 后启动 hook、浮窗停止、health_stats sanity check。
- US-018 (P1): 5 个通用录制数据工具按 browser/desktop mode dispatch，新增 3 个桌面专属工具并保持浏览器路径不退化。
- US-019 (P2): 桌面 Programmer 代码先过 `ast.parse` syntax gate，再由 execution 层 Trial 子进程用隔离 cwd/env 和 120s `taskkill` 兜底试用。
- US-020 (P3): sanity check 三按钮状态机、`vision_model` 缺失提示、桌面录制设置区和 early-loss feedback。

**New Components:**
- `src/recording/desktop_recorder.py` + `src/recording/desktop/` — pynput hook、UIA、剪贴板、ring buffer、PNG/clip sink、热键和 DPI awareness。
- `src/business/agents/tools/desktop_tools.py` — `list_desktop_actions` / `analyze_desktop_action` / `read_action_clip`。
- `src/business/agents/prompts/desktop_prompts.py` — PM / Programmer 双轨 prompt 构建。
- `src/business/orchestration/agent/desktop_syntax_gate.py` — Programmer 代码语法 gate 与自动反馈模板。
- `src/execution/desktop_trial_runner.py` / `desktop_trial_models.py` — Trial 子进程执行协议。
- `src/ui/widgets/recording_floating_widget.py` / `desktop_sanity_check_dialog.py` / `desktop_trial_dialogs.py` / `settings/desktop_recording_settings.py`。

**Modified Components:**
- `src/business/agents/tools/recording_data_tools.py` — 5 通用工具 mode dispatch + desktop stable locator 支持。
- `src/data/recording_repository.py` — `desktop_recordings` / `desktop_actions` 表、mode 查询入口、Trial 调试目录 startup cleanup。
- `src/data/config_models.py` / `src/data/unified_config.py` — `recording.desktop.enable_clip` / `vision_model` 配置。
- `src/recording/filtering/decision.py` / `sql_rewriter.py` — desktop/browser mode allowlist 和 `table_not_in_mode`。
- `src/ui/widgets/recording_widget.py` / `src/ui/mixins/recording_mixin.py` — desktop 启停、minimize/restore、互斥与 sanity flow。
- `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` / `AGENTS.md` / `CLAUDE.md` — 桌面录制运行结构与边界同步。

**Tasks Completed:** 86/104 tasks
