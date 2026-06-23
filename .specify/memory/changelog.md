# Merged Features Log

**Last Updated:** 2026-06-24
**Revision:** 2026-06-24 — Archived 023 unified task collaboration (统一任务模型 + 多范式协作)

## 统一任务模型 + 多范式协作 — 2026-06-24

**Branch:** `023-unified-task-collaboration`
**Spec:** `specs/023-unified-task-collaboration`

**What was added:**
- US-078 (P1): 复杂多步请求收口为持久 Task 图(节点+依赖),跨执行者真并行、实时可观测进度、崩溃围栏恢复 + 迟到结果幂等拒绝,不留永久 running 僵任务
- US-079 (P2): 执行者干完/卡住都交回派活方裁定(认可/打回/放弃),失败沿链冒泡到根 → `abandon_request_graph` 桥接 run 级失败卡;停止作用于整个请求图(留工可续),取消是终态不返工不复活
- US-080 (P3): 协调者临场切换委派/看板认领/受监督二方会议三种范式;看板原子认领 + 租约 + 兜底临时执行者;会议仅传消息不扩权
- US-081 (P4): 执行者私人 Todo 清单(不进任务图/裁定/大脑),持久化、状态词独立、防遗忘

**New Components:**
- `src/business/task_collaboration/`(service / dispatcher / recovery / adjudication / board / meetings / todos / questions / cutover / failure_bridge / health / models / unit_of_work / events / reentry_briefing / parent_reentry_sink / background_worker / run_control)
- 8 个 Repository(task / attempt / operation / question / adjudication / board / meeting / todo)+ v15/v16 SQLite migration + active-attempt partial unique index
- `src/desktop_api/`:routers/assistant_tasks、schemas(派生 displayPhase DTO)、ui_events(5 个 task 事件 Registry)、ui_event_projector、权威快照端点
- `frontend/`:api/assistantTasks、state/assistantTaskStore、TaskGraphPanel / TaskBoardPanel / MeetingChannelDrawer / TodoChecklistPanel、AppShell transport-resync 接线
- 工具:decide_task_adjudication、abandon_request_graph、ask_parent、open_meeting_channel、meeting_send_message、todo_update

**Modified Components:**
- orchestrator(异步 dispatch 接线 + 专员/子代理 spawn 深度封顶 + capability subset)、assistant_tools、assistant_failure_service(record_task_root_failure)、assistant_runtime(reentry 续跑 + 不再用 build_subagent_list 作 task 真相)
- events.py(task blinker 事件)、unified_config(assistant_tasks.* 13 键)、pending_task_repository(legacy 兼容)
- docs/ARCHITECTURE.md、docs/PROJECT_CONSTRAINTS.md、AI 入口 mirror(023 同步)

**Key Decisions:**
- Task 图是新业务事实源;`workflow_transitions` 降级为 debug/audit breadcrumb(不双写,clean-start cutover)
- Task / TaskAttempt 分离;六态状态机 + 父侧裁定(非 Task 状态);容量=1 DB-backed(条件 UPDATE + partial unique index,非进程锁)
- 副作用前写 Operation(operation_key)+ completion marker;非幂等崩溃后交裁定不自动重放
- run 级失败桥接:主助理显式 `abandon_request_graph` → root FAILED → failure_bridge → AssistantRunFailure 卡(补 FR-008 "冒到顶→桥接 run 卡" 缺口)
- Todo `replace_for_executor` 物理删除为例外(不进 brain,no-physical-delete 规则限 brain-eligible 数据)

**Known Infrastructure Note:**
- task collaboration 测试套件多文件同 process 跑时,`in_memory_db` fixture teardown 可能撞 `Cannot operate on a closed database`(多线程/dispatch 残留 session)——单文件/分批跑稳定,非被测代码 bug。

**Tasks Completed:** 119/119 tasks

## 子进程事件推送 — 2026-06-15

**Branch:** `022-process-event-push`
**Spec:** `specs/022-process-event-push`

**What was added:**
- US-075 (P1): subagent / specialist 用新工具 `wait_for_process_event` 阻塞等到 state_changed (running→completed/failed/terminated) 即返回,毫秒级拿到 status + exitCode,超时返回空事件 + 当前状态(非错误)
- US-076 (P2): 累计输出过阈值 emit log_chunked(totalChars / deltaChars,无原文),subagent 用 `process_logs` 拉真实日志
- US-077 (P3): wait 入口懒判定 stalled(idleMs),同一静默周期不刷屏,纯静默(从未输出)场景也按 `last_output_at = started_at` 触发

**New Components:**
- `ProcessEvent` frozen dataclass + `ProcessRecord` 7 个事件字段
- `ProcessManager.wait_for_event` 公共方法 + `_emit_event_locked` / `_refresh_locked_with_emit` / `_maybe_emit_stalled_locked` / `_compute_cursor` / `_build_wait_result` 私有方法
- `wait_for_process_event_handler` + `WAIT_FOR_PROCESS_EVENT_SCHEMA` + ToolDefinition(非 concurrency_safe)
- 三个新配置键 `agent_tools.process.event_buffer_size / stalled_threshold_ms / chunk_threshold_chars` + `AgentToolsProcessConfig` 字段 + 三 getter

**Modified Components:**
- `src/execution/process_manager.py` — 事件机制核心
- `src/business/agents/tools/command_tools.py` — handler
- `src/business/agents/tools/builtin_general_tools.py` — schema + registration
- `src/data/config_models.py` / `src/data/unified_config.py` — 三配置键

**New Tests:**
- `tests/execution/test_process_manager_events.py` — 16 个单测(emit / cursor / wait / state_changed / log_chunked / stalled,含 SC-162 200 ms 唤醒延迟显式断言)
- `tests/business/agents/test_process_event_tool.py` — 6 个工具层单测
- `tests/integration/test_process_event_flow.py` — 3 个集成行为契约

**Key Decisions:**
- 仅 per-process deque + Condition,不抽通用 event bus(YAGNI,设计文档 R-001)
- 事件不进 UI Event Registry / 不持久化 / 主助理不订阅 / 100% 调度纯净
- cursorTooOld 也返回 cursor,subagent 单调推进无须切换兜底(clarify Q1)
- 纯静默场景 `last_output_at = started_at`,与"有过输出再静默"同口径(clarify Q2)

**Tasks Completed:** 28/28 tasks(Setup 1 + Foundational 6 + US1 7 + US2 3 + US3 3 + Polish 8)

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

## UI Stack Redesign — 2026-05-13

**Branch:** `008-ui-stack-redesign`
**Spec:** `specs/008-ui-stack-redesign`

**What was added:**
- US-021 (P1): Tauri + React 应用壳，五个主屏同窗导航，自定义红/黄/绿窗口控件执行真实窗口动作。
- US-022 (P1): Redesigned AI Assistant，支持会话管理、连续时间线、安全 Markdown、执行摘要和非模态高危确认。
- US-023 (P1): Redesigned Skill Teaching，覆盖三种录制模式、准备状态、录制、意图、学习和 trial 阶段。
- US-024 (P1): Redesigned Skill List 和 Skill Composition，支持分类动作、range/ordered 组合创建、试用、发布和需复核状态。
- US-025 (P1): Redesigned Settings，配置和 secret 统一走 `UnifiedConfigManager`，secret 仅遮罩展示，设计可见 actions 接入真实业务路径或真实错误。

**New Components:**
- `frontend/` — React 18 + TypeScript + Vite/Tailwind/Zustand 主 UI、unit tests 和 Playwright e2e。
- `src-tauri/` — Tauri 2 shell、custom window commands、sidecar lifecycle、capabilities 和打包配置。
- `src/desktop_api/` — FastAPI sidecar adapter、Pydantic DTOs、token auth、event-stream adapter 和 routers。
- `src/business/services/desktop_bootstrap_service.py` / `desktop_health_service.py` / `teaching_service.py` / `settings_service.py` / `settings_actions_service.py` / `recording_readiness_service.py` — UI bridge-facing business services。
- `tests/desktop_api/` / `tests/guardrails/` / `frontend/tests/` — API contract、sidecar/security、legacy PyQt removal、frontend unit/e2e 和 visible-control coverage。

**Modified Components:**
- `src/main.py` / `mexamplar_gui.py` / `start.bat` — legacy PyQt normal entrypoints retired to transition/failure guidance.
- `src/ui/` and legacy `tests/ui` / `tests/e2e` PyQt paths — primary PyQt UI removed or replaced by frontend/API/guard coverage.
- `pyproject.toml`, `frontend/package.json`, `build_tauri.bat`, `build_executable.py`, `installer.iss`, `BUILD_README.txt`, `README.md`, `INSTALL.md` — dependency, packaging, build and install docs updated for Tauri/Python sidecar.
- `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` / `AGENTS.md` / `CLAUDE.md` — active docs updated for the new UI stack and sidecar boundaries.

**Tasks Completed:** 119/120 tasks (TD001 cleanup follow-up remains open)

## Frontend Event Layer — 2026-05-16

**Branch:** `009-frontend-event-layer`
**Spec:** `specs/009-frontend-event-layer`

**What was added:**
- US-001 (P1): 公开 UI 事件契约由后端 UI Event Registry 拥有；前端只消费注册过的 typed event type，不再用内部 blinker 事件名或 `sourceEvent` 决定展示。
- US-002 (P2): per-subscriber event stream；同会话内带 last-seen sequence 的重连按 buffer 回放，缺口/会话不匹配走 `backend.resync_required` 拉权威快照。
- US-003 (P3): 试用预览交互式确认走广播 + first-decision-wins，每条请求带后端生成的 `expires_at`，超时/断连/关闭 fail-closed 当拒绝。
- US-004 (P4): 契约一致性 + guard 测试覆盖未注册事件、旧事件来源字段、裸事件发布和敏感字段泄露。

**New Components:**
- `src/desktop_api/ui_events.py` — UI Event Registry、typed envelope、per-subscriber queue、payload safety validation。
- `frontend/src/api/events.ts` + `frontend/src/state/eventStore.ts` — typed event stream consumption、sessionId/sequence 跟踪、resync 触发。
- Trial preview confirmation 浮层组件（独立于普通 Toast 和高危确认）。

**Modified Components:**
- `src/utils/events.py` — 新增 UI 投影所需的标准化字段；保留 blinker 作为后端跨模块通知。
- `src/desktop_api/events.py` — adapter 改走 UI Event Registry + envelope；去掉默认转发未知事件。
- frontend stores（assistant、teaching、skills、compositions、settings）— 改成只消费 typed event type。
- `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` — 同步事件层契约。

**Tasks Completed:** 全量完成（详见 `specs/009-frontend-event-layer/tasks.md`）

## Assistant Brain Redesign — 2026-05-24

**Branch:** `010-assistant-brain-redesign`
**Spec:** `specs/010-assistant-brain-redesign`

**What was added:**
- US-001 (P1): 跨对话延续的工作记忆——Segment 沉淀写入 hot/persistent zone，新对话自动注入前段脉络；冷启动走 icebreaker（1-2 个核心问题，不展开成问卷）。
- US-002 (P2): 永久身份 + 可回溯历史档案——assistant 画像迁入 persistent zone、archive zone 按时间/主题轴聚合，显式 `retrieve_archive` 工具下钻。
- US-003 (P3): 100% 调度 + 可复用 specialist——任务派给临时 subagent 或固定专员，主助理不直接执行；PM/Programmer/Trial 不在 assistant 调度池。
- US-004 (P4): 避坑（failure zone）+ 人格感知（subconscious zone）+ 自我校准（prediction zone 后台 worker 自动验证 hit/miss/partial/expired）。
- US-005 (P5): 自动招募 specialist + 大脑管理模块（`/brain`、`/brain/specialists`）覆盖 6 zone 增删改 + skill pool 管理。

**New Components:**
- `src/business/brain/` — 11 个子模块：`models`、`segment_service`、`distillation_service`、`context_builder`、`decay_router`、`archive_service`、`retrieval_service`、`specialist_service`、`prediction_service`、`management_service`、`background_worker`。
- `src/data/repos/brain_repository.py` + `src/data/repos/specialist_repository.py` — Memory Entry/Segment CRUD、compare-and-swap 状态转换、事务原子写入、invalidation/soft-delete、feedback signal 持久化；专员 CRUD + 版本历史。
- v11 SQLite migration — 一次性建全 `brain_segments`、`brain_memory_entries`、`brain_specialists`、`brain_specialist_versions`、`brain_recruitment_signals`、`feedback_signals`（6 zone 共表，按 `zone` 字段区分）。
- assistant 新工具：`delegate_to_subagent`、`delegate_to_specialist`、`create_specialist`、`retrieve_archive`、`retrieve_failure_zone`、`invalidate_memory_entry`。
- `frontend/src/screens/BrainScreen/` + `frontend/src/screens/SpecialistScreen/` 两个新主屏。
- `frontend/src/state/brainStore.ts` + `frontend/src/state/specialistStore.ts`。
- 自动招募 specialist 的非模态 toast 组件（含 specialist 名 + reason 链接）。

**Modified Components:**
- `src/business/agents/` — assistant prompt 重构为多 zone 注入（hot/persistent/subconscious 被动注入 + specialist 列表 + capability 列表）+ "100% dispatch" 工作风格段；assistant 不再直接执行任务。
- `src/desktop_api/` — 新增 brain/specialist router；assistant worker 在每轮跑前用 `BrainContextBuilder` 重建 prompt。
- `src/utils/events.py` — 新增 `brain_zone_changed`、`brain_specialist_changed`、`segment_boundary_triggered`、`segment_idle_trigger`、`brain_specialist_recruited`、`brain_context_ready` 事件。
- `src/data/migrations/` — v11 一次性建表迁移。
- `docs/ARCHITECTURE.md` 第十节 Brain Service 架构 + `docs/PROJECT_CONSTRAINTS.md` Brain Architecture Constraints。

**Tasks Completed:** 全量完成（详见 `specs/010-assistant-brain-redesign/tasks.md`）

## 子代理可唤回机制 — 2026-06-03

**Branch:** `013-subagent-resumable`
**Spec:** `specs/013-subagent-resumable`

**What was added:**
- US-035 (P1): 临时子代理撞迭代上限不丢工作，转可唤回暂停；主代理凭 `subagent_id` 唤回从断点续跑直至完成，可重复唤回。
- US-036 (P1): 账单/网络类 LLM 调用最终失败时子代理原地冻结保活、暂停原因可区分（可恢复 vs 不可恢复失败）；外部恢复后（含进程重启）凭 `subagent_id` 唤回续跑。
- US-037 (P2): 主代理在不消耗额外模型调用的前提下查看子代理工作概览（轮数/工具调用次数/最后产出/状态），据此决定续跑还是新开。
- US-038 (P3): 对已正常完成的子代理带追加指令唤回，在原有上下文基础上补齐返工，不从零重派。

**New Components:**
- `src/business/agents/config.py` — `ResultType.PAUSED` + `AgentConfig.resumable_on_failure`
- `src/business/agents/agent_loop.py` — 两路 PAUSED 终止语义 + `_is_recoverable_llm_failure` 失败分类
- `src/business/agents/tools/assistant_tools.py` — `continue_subagent` / `inspect_subagent` schema & handler 工厂
- `src/business/orchestration/agent/orchestrator.py` — 委派回传 `subagent_id`、PAUSED 句柄、归属校验、续跑/概览编排
- `src/business/agents/prompts/assistant_prompt.py` — "子代理暂停（可唤回）时的处理"引导段
- `tests/business/agents/test_subagent_resumable.py` — 15 例行为契约测试

**Tasks Completed:** 31/31 tasks

## 主助理对话透明与可控 — 2026-06-05

**Branch:** `014-assistant-chat-transparency`
**Spec:** `specs/014-assistant-chat-transparency`

**What was added:**
- US-039 (P1): AI Assistant 运行时输入门控与停止，停止以协作式深度取消穿透同步派出的子任务，并保留已产内容。
- US-040 (P2): 每会话单条可原地编辑的排队消息，成功或等待用户回答时自动派发，失败或停止时退回草稿。
- US-041 (P2): 主助理活动时间线实时展示，默认折叠、限高内滚，历史回看可重建或显示规整概要。
- US-042 (P2): 子任务卡片、状态动效和详情抽屉，重连或重开会话后通过权威端点恢复。
- US-043 (P3): 暂停子任务的继续任务入口，经主助理调度既有 `continue_subagent` 续跑，可带补充消息。

**New Components:**
- `src/business/agents/run_context.py` — ContextVar 运行上下文、session→Event 注册表、代际 token、待停止集合。
- `src/business/agents/observability.py` — 只读重建子任务权威列表和活动 transcript。
- `frontend/src/screens/assistant/ActivityTimeline.tsx`、`ActivityStepRow.tsx`、`StepIcon.tsx` — 助理过程时间线。
- `frontend/src/screens/assistant/SubagentCard.tsx`、`SubagentDetailDrawer.tsx` — 子任务卡片与详情。
- `frontend/src/state/assistantTypes.ts`、`assistantHelpers.ts` — assistant 透明交互类型与辅助逻辑。

**Modified Components:**
- `src/business/agents/agent_loop.py` / `config.py` — 协作式取消检查、`ResultType.CANCELLED`、活动步骤事件。
- `src/business/orchestration/agent/orchestrator.py` — `CANCELLED` 非错误处理、子任务生命周期事件、继续任务兜底。
- `src/desktop_api/assistant_runtime.py` / `routers/assistant.py` / `confirmations.py` — stop、cancelled progress、pending 高危确认 fail-closed。
- `src/desktop_api/ui_events.py` / `ui_event_projector.py` / `src/utils/events.py` — `assistant.activity`、`assistant.subagent` 和子任务生命周期投影。
- `frontend/src/screens/assistant/AssistantScreen.tsx` / `MessageComposer.tsx` / `frontend/src/state/assistantStore.ts` / `frontend/src/api/assistant.ts` — 输入门控、停止、排队、活动和子任务接线。
- `docs/ARCHITECTURE.md`、`frontend/AGENTS.md`、`src/AGENTS.md` — 活文档与模块入口同步。

**Tasks Completed:** 71/71 tasks

## Agent Built-in Tools Upgrade — 2026-06-09

**Branch:** `015-agent-builtin-tools-upgrade`
**Spec:** `specs/015-agent-builtin-tools-upgrade`

**What was added:**
- US-044 (P1): Agent 内置文件读取升级为有界窗口、continuation metadata、binary/media refusal 和 secret-like redaction。
- US-045 (P1): 既有文件写入、编辑、删除和 patch update/delete 必须使用 raw-byte baseline，stale mutation 在落盘前拒绝。
- US-046 (P2): 新增结构化 `search_files` / `search_content` / `apply_patch` contract，统一 workspace policy、分页、验证和稳定错误码。
- US-047 (P2): 新增 `exec` 与当前 sidecar 会话内的 background process lifecycle 工具，支持 poll/logs/wait/stop/send-input/close 和重复启动防护。
- US-048 (P3): 大输出进入 Agent 会话前压缩，完整 raw output/media 通过持久 `ToolOutputReference` + `load_tool_output` 授权恢复，并受 retention cleanup 管控。

**New Components:**
- `src/business/agents/tools/builtin_contracts.py`、`builtin_permissions.py`、`file_tools.py`、`search_tools.py`、`command_tools.py`、`output_governance.py` — 内置工具 envelope、权限、文件、搜索、命令/process 和输出治理实现。
- `src/execution/command_runner.py` / `src/execution/process_manager.py` — 同步命令执行边界和当前 sidecar 会话内 background process registry。
- `src/data/repos/tool_output_repository.py` + SQLite metadata model/migration — raw-output reference Repository 边界。
- `src/utils/agent_tool_health.py` — log-safe runtime health diagnostics。
- `tests/business/agents/test_builtin_*`、`tests/data/test_tool_output_repository.py`、`tests/guardrails/test_agent_builtin_tool_boundaries.py`、`tests/integration/test_agent_builtin_*` — 工具 contract、Repository、guardrail 和 process lifecycle 覆盖。

**Modified Components:**
- `src/business/agents/agent_loop.py` / `hook_models.py` / `tools/builtin_general_tools.py` — 保持 facade，升级 built-in contract、权限和 exactly-one-result 保存治理。
- `src/data/config_models.py` / `unified_config.py` / `migrations.py` / `models_sqlite.py` / `repositories.py` — 新增 agent tool caps、retention、process limits 和 output reference metadata。
- `config.example.json`、`docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`、`AGENTS.md`、`src/AGENTS.md` — 活文档、配置示例和 AI 入口同步。

**Tasks Completed:** 86/86 tasks

## Tool Output Semantic Summary — 2026-06-11

**Branch:** `016-tool-output-semantic-summary`
**Spec:** `specs/016-tool-output-semantic-summary`
**Revision note:** Archived the completed feature into project memory with deterministic facts remaining authoritative and semantic summaries explicitly advisory.
**Credential note (2026-06-12):** Removed the external credential-store path. `agent_tools.output.semantic_summary.api_key` and all other provider credentials now use `UnifiedConfigManager`, with local `config.json` defaults and `app_settings` runtime overrides.

**What was added:**
- US-049 (P1): 所有大或截断文本工具结果进入统一 compact 治理，保留确定性 facts/preview、原始大小、payload keys 和可授权恢复的 raw reference。
- US-050 (P1): 独立低成本模型可生成固定 JSON 结构的单块或 Map-Reduce advisory 摘要；非法输出、provider 失败和超时确定性省略摘要。
- US-051 (P2): `extractionGoal`、`web_fetch.prompt` 和 custom tool 常见 goal/query/prompt/pattern 参数可引导摘要重点，但不改变执行或权限语义。
- US-052 (P2): Settings 新增“工具输出”分区，支持 provider/model/endpoint/temperature、高级预算、独立密钥和脱敏连接测试；部署配置可通过专用字段提供本地默认值。

**New Components:**
- `src/business/agents/tools/semantic_summary.py` — 工具感知文本提取、15/35/35/15 选择预算、goal 推断、单块/Map-Reduce 调用、deadline、JSON validation 和脱敏。
- `tests/business/agents/test_tool_output_semantic_summary.py` — 选择、摘要、失败、超时、注入、脱敏和 goal 覆盖。
- Settings “Tool Output” section — 高级预算折叠、masked secret 和 connection action。

**Modified Components:**
- `src/business/agents/agent_loop.py` / `tools/output_governance.py` — 原始工具参数传入保存边界；所有文本结果统一治理、reference-first、确定性 facts/preview 和 exactly-one fallback。
- `src/business/agents/tools/builtin_general_tools.py` / `command_tools.py` — `extractionGoal` schema 与 centralized raw-reference ownership。
- `src/data/config_models.py` / `unified_config.py` — `agent_tools.output.semantic_summary.*` 配置、统一 secret getter/setter、遮罩状态和日志脱敏；Real Grand Tour 复用普通只读 getter。
- `src/business/services/settings_service.py` / `settings_actions_service.py` / `src/desktop_api/schemas.py` — 设置 descriptor、状态、secret 操作和只返回 provider/model metadata 的连接测试。
- `frontend/src/api/settings.ts` / `frontend/src/screens/settings/SettingControls.tsx` — typed advanced descriptor 和工具输出设置 UI。
- `src/utils/agent_tool_health.py` / Debug provider inventory / Real Grand Tour coverage — 摘要运行计数、trace、credential 和 budget 门卫。
- `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` / `config.example.json` / AI entry mirrors — 当前架构、约束、配置和协作知识同步。

**Tasks Completed:** 23/23 tasks

## 大脑记忆质量提示词升级 — 2026-06-15

**Branch:** `020-brain-memory-quality`
**Spec:** `specs/020-brain-memory-quality`
**Revision note:** Migrated an implementation that was completed on `prepare-github` without the normal
Spec Kit workflow, then archived its recovered specification and known verification gaps.

**What was added:**
- US-053 (P1): Segment 沉淀使用未来价值、自包含、一条一事和宁缺毋滥标准，明确排除聊天过程摘要、通用知识和宽泛印象。
- US-054 (P2): 潜意识沉淀只归纳有跨对话重复证据的具体行为模式，并要求说明证据来源。
- US-055 (P3): Prediction 生成要求具体、可证伪、有验证时机且由多条记忆支撑；验证明确四状态语义。

**Modified Components:**
- `src/business/brain/distillation_service.py` — Segment 分区规则、低质量反例、空结果许可、feedback signal 边界和潜意识模式判断 prompt。
- `src/business/brain/prediction_service.py` — Prediction 生成质量标准和 `hit / partial / miss / expired` 验证说明。
- `.specify/memory/spec.md` / `.specify/memory/plan.md` / AI entry mirrors — 当前行为、兼容边界和软约束说明。

**Verification:**
- 聚焦 brain tests：41 passed；7 个既有 Python 3.12 SQLite datetime adapter 弃用警告。
- 未完成：3 项 prompt regression tests，继续记录在 `specs/020-brain-memory-quality/tasks.md` T018-T020。

**Tasks Completed:** 18/21 tasks

## Desktop UX、Debug Inspector 与真实 Grand Tour — 2026-05-28

**Branch:** `011-desktop-ux-debug-regression`
**Spec:** `specs/011-desktop-ux-debug-regression`
**Revision note:** Backfilled on 2026-06-15; historical keyring details were reconciled to the current UnifiedConfigManager-only credential architecture.

**What was added:**
- Shared long-paste collapse for Assistant and Teaching composers.
- Authenticated hidden Debug Inspector with bounded ephemeral traces, Agent Flow, reference expansion and failure-isolated observation.
- Opt-in real Grand Tour with isolated data, public-state synchronization, paid-call/time budgets, cleanup and sanitized reports.

**New Components:**
- `src/business/debug/`, `/api/debug`, hidden `/debug` frontend route.
- `useLongPasteCollapse`, trace/flow/reference panels.
- Real Grand Tour runtime, event watcher, audit, fixture and report helpers.

**Tasks Completed:** 104/104 tasks

## Skill Methodology 方法论资产层 — 2026-06-01

**Branch:** `012-skill-methodology-layer`
**Spec:** `.specify/archive/012-skill-methodology-layer`
**Revision note:** The feature spec had been physically moved to `.specify/archive/`, but was backfilled into main memory only on 2026-06-15.

**What was added:**
- Tool/Skill terminology split and `/tools/*` routes with `tools.changed`.
- Versioned Skill Methodology assets, source provenance, stateful equipment and no-physical-delete protection.
- Assistant/specialist lightweight methodology lists plus on-demand `load_skill_methodology`.
- SkillMethodologyScreen, equipment management, statistics, audit and bootstrap protection.

**New Components:**
- v12 `brain_skills`, `brain_skill_source_segments`, `brain_skill_equipment`.
- Brain skill services/repositories/tools/seed and methodology frontend/API/event layer.

**Tasks Completed:** 79/79 tasks

## AgentLoop 并行工具执行 — 2026-06-14

**Branch:** `017-parallel-tool-execution`
**Spec:** `specs/017-parallel-tool-execution`

**What was added:**
- Explicit `ToolDefinition.is_concurrency_safe` opt-in.
- Contiguous safe partitions executed with at most four workers.
- Caller-thread ordered persistence and failure isolation for parallel reads.

**Modified Components:**
- AgentLoop execution/governance split and reviewed read-tool classification.

**Tasks Completed:** 12/12 tasks

## Assistant 失败消息重试与恢复 — 2026-06-15

**Branch:** `018-assistant-failed-message-retry`
**Spec:** `specs/018-assistant-failed-message-retry`

**What was added:**
- v14 persistent Assistant failure state and safe classification.
- Inline recovery card with original retry, edited new-turn retry and Debug Inspector navigation.
- Atomic retry claim, startup recovery and authoritative resync behavior.

**New Components:**
- `AssistantRunFailureRepository`, `AssistantFailureService`, `AssistantFailureClassifier`, `AssistantFailureCard`.

**Tasks Completed:** 31/31 tasks

## 结构化多选澄清 — 2026-06-15

**Branch:** `019-structured-user-clarification`
**Spec:** `specs/019-structured-user-clarification`

**What was added:**
- Main-Assistant-only `ask_user_question` with 1–4 structured single/multi-choice questions and “other” input.
- Exclusive-call AgentLoop contract, in-memory first-decision-wins lifecycle and same-loop continuation.
- Pending/decision APIs, typed UI events and non-modal ClarificationCard.

**New Components:**
- `clarification_manager.py`, `clarifications.py`, ClarificationCard and session-scoped frontend state.

**Outstanding:** T048 manual quickstart smoke checklist remains open.

**Tasks Completed:** 47/48 tasks

## 工具目录渐进式延迟加载 — 2026-06-15

**Branch:** `021-tool-catalog-deferred-loading`
**Spec:** `specs/021-tool-catalog-deferred-loading`
**Revision note:** Archived after merge into `prepare-github`; no unresolved conflicts or constitution exceptions.

**What was added:**
- 主助理、临时子代理和固定专员统一使用授权后的完整/deferred 能力目录策略。
- 默认超过 20 项或 6000 字符时隐藏目录内容，只保留统计和按需发现说明。
- `search_tools` 支持空查询浏览、类型过滤、稳定排序、offset/limit 分页和无歧义 selector。
- 搜索、详情和激活刷新在调用时重新校验发布状态、组合状态、成员授权和 Agent 白名单。
- `agent_tools.discovery.*` 统一运行时配置和不含目录内容的模式选择日志。

**New Components:**
- `src/business/agents/tools/capability_catalog.py` — 共享目录模型、策略、Prompt 渲染、搜索排序和分页。
- `tests/business/agents/test_capability_catalog.py` — 100 项目录、阈值、排序、分页和错误边界覆盖。

**Modified Components:**
- `DynamicToolManager`、`AssistantPromptBuilder`、`AgentOrchestrator`、统一配置模型/管理器和相关活文档。

**Tasks Completed:** 18/18 tasks
