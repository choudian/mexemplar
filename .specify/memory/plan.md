# Main Implementation Plan Memory

**Purpose**: Consolidated technical state from all merged features. Reflects the *implemented* state of the system.
**Last Updated**: 2026-05-07
**Revision**: 2026-05-07 — Merged `specs/007-desktop-recording`

---

## Technical Context

**Language/Version**: Python 3.11+ (runtime 3.12)
**Primary Dependencies**: PyQt6, SQLite (SQLAlchemy/Alembic), DuckDB, Playwright, blinker, sqlglot, LangChain, mitmproxy, AgentLoop (自研), pynput, mss, opencv-python, Pillow, comtypes, pywinauto, pywin32
**Storage**: SQLite (业务数据, via Repository); DuckDB (录制分析数据, via FilteredDuckDBConnection/sql_rewriter; desktop_recordings/desktop_actions); filesystem (`data/recordings/<recording_id>/`, `data/trials/<trial_id>/`)
**Testing**: pytest (`tests/`)
**Target Platform**: Windows + Linux desktop; desktop recording Phase 1 is Windows-only
**Project Type**: Desktop application (single repo)

---

## Current Project Structure

```
src/
├── business/
│   └── agents/
│       ├── config.py                       # ToolDefinition (含 is_interrupting/pre_hook/post_hook) 与 AgentConfig global hooks
│       ├── agent_loop.py                   # 多工具批次处理、hook 执行、失败级联、中断校验、契约校验
│       ├── hook_models.py                  # ToolCallContext / PreHookResult / PostHookResult / args freezing
│       ├── tools/
│       │   ├── recording_data_tools.py     # 5 工具: describe_data, query_data, execute_code, read_recording, read_field_chunk
│       │   ├── pm_output_tools.py          # PM 中断型工具 (talk_to_user 等)
│       │   ├── programmer_tools.py         # 程序员工具
│       │   ├── trial_tools.py              # 试用工具；run_command per-run pre_hook 限流
│       │   └── builtin_general_tools.py    # read/write/edit/list/exec pre_hooks + 确认状态/自动放行/脱敏日志
│       └── prompts/
│           ├── pm_prompt.py                # 5 工具工作流
│           └── programmer_prompt.py        # 5 工具工作流
│   ├── services/
│   │   └── chat_service.py                  # DisplayChatMessage/ChatHistoryPage DTO + get_display_messages() 展示分页
│   ├── ai/
│       ├── compression_handler.py         # _adjust_boundary_for_tool_pairs (压缩边界 tool 组调整)
│       └── context_manager.py             # get_pending_tool_calls (多工具恢复), _cleanup_orphan_tool_results (孤立校验)
│       └── context_manager.py             # get_pending_tool_calls (多工具恢复)
├── ui/
│   ├── main_window.py                       # auth toast 状态/队列/resize 重定位
│   ├── mixins/
│   │   ├── agent_bridge_mixin.py            # register_confirm_mechanism wiring
│   │   └── agent_handler_mixin.py           # 非阻塞确认队列 + toast 决策处理
│   ├── resources/
│   │   └── styles.qss                       # auth toast + 顶栏 Toggle 样式
│   └── widgets/
│       ├── chat_widget.py                   # 顶栏 "免确认" Toggle + new_chat_started + 历史分页 + Markdown 集成
│       ├── markdown_message_view.py         # AI 回复 Markdown 安全渲染 widget
│       └── auth_toast.py                    # AuthToastSurface 非模态确认浮层
├── recording/
│   └── filtering/
│       ├── query_projection_analyzer.py    # SQL 列血缘分析 (sqlglot), StableLocatorRule, ProjectionBinding
│       ├── sql_rewriter.py                 # network_requests SQL rewrite + filter
│       └── filtered_conn.py               # FilteredDuckDBConnection
└── data/
    ├── config_models.py                    # LargeFieldConfig dataclass (threshold/preview/chunk)
    ├── unified_config.py                   # get_recording_large_field_config()
    └── repos/
        └── message_repository.py           # get_display_page() 展示历史分页查询

tests/
├── test_hook_protocol.py                    # hook 协议、迁移 gate、global hook、动态工具、性能烟测
├── business/
│   └── memory/
│       ├── conftest.py                      # mock Message 工厂与 mock MessageRepository fixture
│       ├── test_compression_tool_pairing.py # 压缩边界调整单元测试 (7 场景)
│       └── test_context_orphan_cleanup.py   # 孤立校验与上下文兼容性测试 (6 场景)
├── test_auth_toast_confirmation.py          # 确认状态/日志/自动放行业务测试
├── integration/
│   └── test_agent_loop_multi_tool_calls.py  # 多工具批次、中断型、恢复、契约校验 14 场景
├── recording/
│   ├── test_recording_data_large_fields.py         # 占位+续读+错误码+EOF+性能+配置变更测试
│   ├── test_query_data_sanitization.py             # 大字段替换后的 query_data 验证
│   ├── test_recording_data_tools_noise_filtering.py # filter 边界 + chunk read filter 测试
│   ├── test_architecture_wiring.py                 # 5 工具注册 wiring smoke
│   └── filtering/
│       ├── test_query_projection_analyzer.py       # 投影分析器 unit tests
│       └── test_recording_tools_no_sqlglot.py      # guard test: recording_data_tools 不 import sqlglot
└── ui/
    ├── test_auth_toast_surface.py           # AuthToastSurface 按钮/超时/关闭限制
    ├── test_chat_widget_auth_toggle.py      # Toggle 状态同步/可见性/新对话复位
    ├── test_chat_widget_markdown.py         # Markdown 渲染/安全降级/纯文本回归
    ├── test_chat_widget_history.py          # 历史分页/性能/归档透明性
    ├── test_chat_widget_layering.py         # UI 分层门卫测试
    └── test_agent_handler_mixin.py          # 队列 FIFO/QMessageBox guard/会话切换
```

[Sources: specs/001-recording-field-layering, specs/002-tool-hook-system, specs/003-fix-agentloop-tool-calls, specs/005-fix-compression-tool-pairing]
[Sources: specs/001-recording-field-layering, specs/002-tool-hook-system, specs/003-fix-agentloop-tool-calls, specs/004-auth-toast, specs/006-chat-ui-polish]

### Desktop Recording Additions [Source: specs/007-desktop-recording]

```text
src/
├── business/
│   ├── agents/
│   │   ├── prompts/
│   │   │   └── desktop_prompts.py              # build_pm_prompt(mode) / build_programmer_prompt(mode)
│   │   └── tools/
│   │       └── desktop_tools.py                # list_desktop_actions / analyze_desktop_action / read_action_clip
│   ├── orchestration/agent/
│   │   └── desktop_syntax_gate.py              # ast.parse gate + retry feedback
│   ├── services/
│   │   └── desktop_recording_service.py        # UI -> business bridge for start/stop/health/status
│   └── utils/
│       └── high_risk_api_detector.py           # Trial warning + shortcut detector
├── execution/
│   ├── desktop_trial_models.py                 # TrialResult DTO
│   └── desktop_trial_runner.py                 # subprocess cwd/env/timeout/stdout/stderr
├── recording/
│   ├── desktop_recorder.py                     # DesktopRecorder lifecycle + health_stats
│   └── desktop/
│       ├── dpi_awareness.py                    # Per-Monitor V2 startup call
│       ├── pynput_hook.py                      # keyboard/mouse hook + typing/hotkey segmentation
│       ├── uia_querier.py                      # UIA ElementFromPoint + async backfill
│       ├── clipboard_watcher.py                # WM_CLIPBOARDUPDATE + Ctrl+V latest snapshot
│       ├── frame_ring_buffer.py                # 15fps / 30-frame FIFO
│       ├── png_sink.py                         # native-resolution frames
│       ├── clip_sink.py                        # mp4v clips controlled by enable_clip
│       └── hotkey_register.py                  # Ctrl+Alt+S global stop hotkey
└── ui/widgets/
    ├── recording_floating_widget.py            # always-on-top desktop recording stop/count widget
    ├── desktop_sanity_check_dialog.py          # health stats + color + three-button state machine
    ├── desktop_trial_dialogs.py                # trial preflight dialog + toast result helpers
    └── settings/desktop_recording_settings.py  # recording.desktop config controls

tests/
├── business/test_high_risk_api_detector.py
├── data/test_recording_desktop_config.py
├── data/test_recording_repository_desktop.py
├── integration/test_desktop_*                 # tools, prompts, syntax gate, trial runner, mode dispatch
├── recording/test_desktop_*                   # hook/UIA/clipboard/ring/sink/action semantics
└── ui/test_desktop_*                          # minimize start, sanity dialog, trial dialog, vision toast
```

[Source: specs/007-desktop-recording]

---

## Configuration

### recording.large_field.* (via UnifiedConfigManager)

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `recording.large_field.threshold_chars` | int | 1000 | 文本字段值 ≥ 此值触发占位替换 |
| `recording.large_field.preview_chars` | int | 1000 | 占位对象 preview 前缀最大字符数 |
| `recording.large_field.max_chunk_chars` | int | 1000 | read_field_chunk 单次 content 最大字符数 |

配置变更仅影响后续阈值/预览/chunk 大小，不使既有 locator 失效。

[Source: specs/001-recording-field-layering]

### recording.desktop.* (via UnifiedConfigManager)

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `recording.desktop.enable_clip` | bool | `true` | 控制桌面录制是否生成 mp4 clip；关闭后仍保留多帧 PNG |
| `recording.desktop.vision_model` | string/null | `null` | 独立指定桌面多模态分析 model；缺失时不注入 `analyze_desktop_action` |

provider routing 和 API key 复用 `analyze_image` 当前 provider/keyring entry；不新增 `recording.desktop.vision_provider`。

[Source: specs/007-desktop-recording]

---

## Tool Architecture

### Recording Data Tools (5 tools, registered via `create_recording_tools()`)

1. **describe_data** — 表结构 + 大字段提示 (`large_field` / `read_via` / `locator_fields`)
2. **query_data** — SQL 查询 + 大字段自动占位替换
3. **execute_code** — 代码执行
4. **read_recording** — 录制元数据
5. **read_field_chunk** — 大字段分段读取 (新增)

Desktop recording extends these 5 tools through mode dispatch: `create_recording_tools(recording_id)` queries `RecordingRepository.get_recording_mode(recording_id)` once and closes over browser/desktop mode for handlers and the query pre_hook. Browser mode continues to use the existing 5 browser tables; desktop mode uses `desktop_recordings` / `desktop_actions`. Cross-mode table access returns `table_not_in_mode`.

### Desktop-Specific Recording Tools [Source: specs/007-desktop-recording]

1. **list_desktop_actions** — pages and filters `desktop_actions` by action type/time.
2. **analyze_desktop_action** — sends up to 2 actions' typing text, clipboard image, and frame sequence to the configured vision model; returns per-action text segments with `[error: <reason_code>]` on partial failure.
3. **read_action_clip** — returns mp4 clip path/metadata, or `clip_unavailable` when no clip exists.

Desktop PM / Programmer / Trial toolsets replace browser `analyze_image` with these 3 tools. If `recording.desktop.vision_model` is missing, `analyze_desktop_action` is not injected and the other two desktop tools remain available.

### SQL 列血缘分析

`query_projection_analyzer.py` 使用 sqlglot 分析 SQL AST，为每个结果列生成 `ProjectionBinding`（直接列 vs 计算列），结合 `StableLocatorRule` 判定是否支持续读。

### Filter Boundary

- `network_requests`: 占位 + 续读必须走 `sql_rewriter` / `FilteredDuckDBConnection`
- 其他 StableLocatorRule 覆盖表：参数化单行直读
- `recording_data_tools.py` 不直接 import `sqlglot`（guard test 约束）

[Source: specs/001-recording-field-layering]

---

## StableLocatorRule Coverage (v1)

| Table | Stable ID Field | describe_locator_fields |
|-------|----------------|------------------------|
| `network_requests` | `request_id` | `["request_id"]` |
| `actions` | `action_id` | `["action_id"]` |
| `sibling_snapshots` | `snapshot_id` | `["snapshot_id"]` |

[Source: specs/001-recording-field-layering]

---

## Testing Strategy

- **Unit**: 投影分析器、占位 builder、chunk reader、错误码枚举
- **Integration**: describe_data → query_data → read_field_chunk 全链路
- **Wiring smoke**: `create_recording_tools()` 返回 5 个 ToolDefinition
- **Guard**: `recording_data_tools.py` 不导入 `sqlglot`
- **Performance**: SC-003 占位构造 ≤ 200ms (in-process benchmark)
- **Regression**: CC-002 reference_handler 正交性、SC-004 小字段零回归

[Source: specs/001-recording-field-layering]

### Desktop Recording Testing [Source: specs/007-desktop-recording]

- **Recording components**: pynput hook classification, UIA 50ms timeout/backfill, clipboard watcher latest snapshot, 30-frame ring buffer, PNG/clip sink behavior, drag/typing segmentation.
- **Data/config**: `desktop_recordings` / `desktop_actions` schema and status transitions; `recording.desktop.*` defaults and round trip; `recording_mode` defaults corrected to browser.
- **Tooling and guard tests**: browser 5-tool canonical JSON byte-equal, desktop mode allowlist, `read_recording` desktop summary, desktop tool validation, `recording_data_tools.py` no direct sqlglot import.
- **Agent orchestration**: PM/Programmer dual prompt, browser prompt guard, desktop toolset composition, `ast.parse` syntax gate and retry feedback.
- **Trial**: subprocess cwd isolation, env whitelist, timeout/taskkill, stdout last-line JSON parsing, stderr fallback, high-risk API detector.
- **UI**: minimize-complete startup, floating widget, sanity color and three-button state machine, `vision_model` missing toast, desktop card mutual exclusion.
- **Manual e2e**: 5 scenarios in quickstart; gates are 5/5 recording success, 5/5 intent generation, at least 3/5 trial success, at least 3/5 shortcut detection, and subjective no-jank check.

---

## Agent System Architecture

### AgentLoop 多工具批次处理 [Source: specs/003-fix-agentloop-tool-calls]

AgentLoop 在收到 LLM 响应后，按以下流程处理 tool_calls：

1. **批次分类**：调用 `classify_tool_calls()` 按 `ToolDefinition.is_interrupting` 将每个 tool call 分为 `ordinary`/`interrupting`/`unknown`
2. **三种批次路径**：
   - **Ordinary batch**（全部 ordinary/unknown）：按顺序执行，失败时级联 `not_executed`
   - **Solo interrupting**（恰好 1 个 interrupting）：执行 handler，成功则触发暂停/完成语义，异常则继续 loop
   - **Invalid-output batch**（>1 且含 interrupting）：保存原响应，不执行任何 handler，为每个 call 写入 `invalid_model_output`
3. **契约校验**：运行时检查 `is_interrupting` 与 handler 返回类型一致，不一致写入 `handler_contract_violation`
4. **恢复**：`get_pending_tool_calls()` 返回最近 assistant 消息中所有未配对调用，按原始顺序补齐

### 标准化错误结构

AgentLoop 发出的配对错误统一为顶层 JSON：`{"error": "<code>", "message": "...", ...}`
错误码枚举：`unknown_tool`、`handler_exception`、`handler_contract_violation`、`not_executed`、`invalid_model_output`、`pre_hook_rejected`

### Agent 工具执行 Hook 管线 [Source: specs/002-tool-hook-system]

Hook 执行发生在 AgentLoop 批处理分类之后、实际 handler 执行之前/之后。参与对象仅限调用方传入或动态构建的 `ToolDefinition`；AgentLoop 注入的 `talk_to_user` / `load_reference` 不进入 hook 管线。

顺序：

1. 工具级 `pre_hook`
2. 当前 `AgentConfig.global_pre_hooks`（列表顺序）
3. handler
4. 工具级 `post_hook`
5. 当前 `AgentConfig.global_post_hooks`（列表顺序）

关键运行规则：

- `ToolCallContext.args` 使用递归只读隔离视图；pre_hook 不能改写 handler 入参。
- pre_hook 返回 `PreHookResult(error=...)` 时写入 `pre_hook_rejected` 并跳过 handler/post_hook。
- pre_hook 抛异常时记录 WARNING、停止剩余 pre_hook、执行 handler、跳过全部 post_hook。
- post_hook 不做结果流水线；所有 post_hook 接收 handler 原始字符串结果，最后一个非空 rewrite 生效。
- post_hook 抛异常时返回 handler 原始结果，丢弃前序 post_hook 的部分改写。
- handler 抛异常时转换为标准化 error 字符串；若未被 pre_hook 异常短路，post_hook 仍可观察/改写该错误文本，但批处理级联依据原始失败状态。
- 合法 `ToolSignal` 跳过 post_hook；声明式 `is_interrupting` 与 handler 返回类型不一致时写入 `handler_contract_violation`。

### Migrated Gate Ownership [Source: specs/002-tool-hook-system]

- `builtin_general_tools`: `read_file` / `write_file` / `edit_file` / `list_dir` / `exec` 的路径、系统目录、命令安全和确认 gate 在 pre_hook；确认请求异常必须 fail-closed。
- `recording_data_tools`: `query_data` 复用 `rewrite(sql)` / 过滤策略做 pre_hook 拒绝判断；`analyze_image` 的 6-action 拒绝在 pre_hook。
- `trial_tools`: `run_command` 5 次上限由 `create_trial_tools()` 内的 per-run 闭包 pre_hook 维护。
- 非迁移边界：`programmer_tools.syntax_check`、`recording_data_tools.execute_code` 沙箱、`tool_executor` venv 隔离/命令白名单、`dynamic_tool_manager` 工具发现/激活。

### 结构化日志

4 类日志事件（`logger.info`）：`batch.start`、`batch.call_result`、`batch.complete`、`recovery.start`/`recovery.call_result`

---

## Testing Strategy — Agent System

- **Integration**: 14 场景覆盖普通多工具、失败级联、纯文本非失败、未知工具级联、混合中断、多中断、solo 异常、契约违反双向、恢复部分/全部/缺 handler/损坏记录、单工具回归
- **Regression**: 现有 `test_v2_full_flow.py`、`test_assistant_new_session.py` 无可见回归
- **Guard**: 下一轮 LLM messages 无未配对 tool calls

[Source: specs/003-fix-agentloop-tool-calls]

### Hook Protocol and Migration Tests [Source: specs/002-tool-hook-system]

- `tests/test_hook_protocol.py`: no-hook 透明性、pre_hook 拒绝、递归只读 args、pre/post hook 异常、post_hook rewrite、handler 异常、ToolSignal 契约、动态 callable 刷新、global hook 顺序/作用域、SC-002/SC-005 性能/挂载成本烟测。
- Migrated gate coverage: builtin general 工具拒绝路径、`query_data` parser/filter 拒绝与 harmless 路径、`analyze_image` action 上限、`run_command` 第 6 次拒绝。
- Static guards: 旧 gate 判断不残留在 handler，非迁移边界保持原位。
- Final gates: hook 协议套件、recording guard/regression、AgentLoop multi-tool smoke、syntax validation、black/flake8/full pytest 或明确例外说明。

### Compression Boundary Tests [Source: specs/005-fix-compression-tool-pairing]

- `tests/business/memory/test_compression_tool_pairing.py`: 7 场景覆盖无 tool 组不调整、tool 组完全在压缩区不调整、边界跨越整组移入、assistant 在压缩区全部 result 在保留区、多组仅最后跨越、空压缩区跳过、二次压缩吸收上一轮边界组
- `tests/business/memory/test_context_orphan_cleanup.py`: 6 场景覆盖无孤立不变、孤立剔除、混合有效/孤立、warning 日志、reference_handler 替换后仍可续读、pending_tool_calls 检测不受影响
- 使用 mock Message 和 mock MessageRepository，不依赖真实 DB
---

## 高危操作确认 Toast 化 [Source: specs/004-auth-toast]

### 确认浮层架构

Assistant 高危工具确认从 `QMessageBox.question` 模态弹窗改为非阻塞 `AuthToastSurface` 浮层。保留现有 `builtin_general_tools` 的 request_id + `threading.Event` 等待模型和 `pyqtSignal` 跨线程通道。UI 端新增独立于普通 Toast 的确认浮层队列管理。

核心运行机制：
1. Worker 线程触发 `_ask_user_confirm` → 创建 `PendingConfirmation` → `pyqtSignal` emit request_id + message
2. UI 线程 `AgentHandlerMixin._on_confirm_action_requested` 入队 → 显示一个 `AuthToastSurface`
3. 用户决策（三按钮或超时）→ `set_confirm_result` 回写 → Worker `event.set()` 唤醒
4. 自动放行开启时（"全部允许"或顶栏 Toggle）：pre_hook 直接返回 None，不 emit signal

### 会话级自动放行状态

`_auto_approve_enabled` 为模块级变量，受 `_confirm_lock` 保护。开启时覆盖 Assistant 全部高危工具（write_file/edit_file/exec）。新对话时 `reset_auto_approve` 复位。不持久化。

### 脱敏结构化日志

每次终态决策写入 `logger.info`，字段：request_id、tool_name、decision、source、elapsed_ms、summary。summary 由 `_truncate_summary` + `_sanitize_fragment` 生成，自动截断长参数并替换敏感模式（sk-*、password=、token= 等）。

### 测试覆盖

- **Business tests**: `tests/test_auth_toast_confirmation.py` — 确认状态、脱敏摘要、自动放行开关、超时映射、settle 截止时间
- **UI surface tests**: `tests/ui/test_auth_toast_surface.py` — 三按钮信号、超时触发、重复决策忽略、手动关闭拒绝
- **UI integration tests**: `tests/ui/test_agent_handler_mixin.py` — 5-Worker FIFO、Toast 共存、响应性 ≤100ms、超时收敛 ≤1s、allow-all 排队放行、Toggle 双向同步、新对话收敛、QMessageBox guard
- **ChatWidget tests**: `tests/ui/test_chat_widget_auth_toggle.py` — Toggle 默认关闭、状态同步、新对话复位

---

## 聊天界面体验完善 [Source: specs/006-chat-ui-polish]

### 架构概览

三类聊天界面体验修复：AI 回复 Markdown 富文本渲染、压缩前旧聊天记录分页回看、欢迎页/新对话隐藏"免确认" Toggle。改动集中在 `ChatWidget → ChatService → MessageRepository` 分层路径内。

### Markdown 渲染

使用 Qt 内建 `QTextDocument.setMarkdown(MarkdownDialectGitHub)` 渲染 AI 回复，不引入新依赖。`MarkdownMessageView` 作为聊天气泡内部 widget，渲染前统一安全降级 raw HTML/script。用户消息仍用 `QLabel` 纯文本。

### 展示历史分页

`ChatService.get_display_messages()` 调用 `MessageRepository.get_display_page()`，按 `sequence` keyset 分页读取 user/assistant 消息（排除 tool/summary/compressed/空内容），返回 `DisplayChatMessage` + `ChatHistoryPage` DTO。UI 初始展示最近 10 条，向上滚动 prepend 更早页。不复用 `ContextManager.get_context()` 避免污染 LLM 上下文。

### Toggle 可见性状态机

`ChatWidget` 维护内部视图状态：`session_list`/`new_chat_empty`/`conversation_started`/`conversation_cleared`。仅 `conversation_started` 时显示 Toggle。不改变 004-auth-toast 的确认协议。

### 测试覆盖

- **UI**: `tests/ui/test_chat_widget_markdown.py`（渲染+安全+纯文本回归）、`tests/ui/test_chat_widget_history.py`（分页+性能+归档透明性）、`tests/ui/test_chat_widget_layering.py`（分层门卫）
- **Business**: `tests/business/test_chat_service_history.py`（DTO+Service 契约）
- **Data**: `tests/data/test_message_repository.py`（分页查询+过滤+排序）
- **Integration**: `tests/integration/test_assistant_new_session.py`（扩展冒烟测试）

---

## 桌面录制 Phase 1 [Source: specs/007-desktop-recording]

### 架构概览

桌面录制把原有录制页的 desktop "暂不支持"路径替换为 Windows-only 录制闭环。UI 只通过 `DesktopRecordingService` / bridge 调业务层；业务层编排 Recorder、Agent 工具和 Trial；execution 层独立负责桌面 Trial 子进程；DuckDB 录制分析数据通过 Repository/过滤层访问；跨模块通知走 `src/utils/events.py` blinker，UI 只在本地 Qt bridge 切回 UI 线程。

### 录制管线

进程启动期在 `QGuiApplication` 前应用 Per-Monitor V2 DPI awareness。用户开始桌面录制后主窗先最小化，minimize 完成回调后启动 hook / ring buffer / UIA / 剪贴板订阅，避免开始按钮 click 被记录为首动作。`DesktopRecorder` 聚合 pynput、UIA、clipboard、frame buffer、PNG sink、clip sink 和 Ctrl+Alt+S hotkey，写 `desktop_recordings` / `desktop_actions` 并在停止时一次性写 `health_stats`。

### Agent 与工具

5 个通用录制数据工具按 `recording_mode` dispatch，browser mode 保持现有 5 表与 prompt 不退化，desktop mode 只允许 `desktop_recordings` / `desktop_actions`。桌面专属工具由 `create_desktop_specific_tools(recording_id)` 提供；`recording.desktop.vision_model` 缺失时不注入 `analyze_desktop_action`。PM / Programmer prompt 由 `build_pm_prompt(mode)` / `build_programmer_prompt(mode)` 双轨构建，Orchestrator 使用临时 `AgentConfig` 拷贝接线。

### Trial 子进程

桌面 Programmer 输出代码进入 Trial 前先过 `ast.parse` syntax gate，最多自动反馈重试 2 次。Trial 由 `src/execution/desktop_trial_runner.py` 创建 `data/trials/<trial_id>/`、设置 cwd/env 白名单、启动 `python -u -c <wrapper>`、解析 stdout 末行 JSON、落 stdout/stderr、120s 超时后 `taskkill /F /T` 清理子进程树。business/orchestrator 只编排 runner 调用和 blinker 事件，不直接执行 subprocess。

### UI 状态与健康反馈

桌面录制 UI 使用 `RecordingFloatingWidget` 显示录制状态和停止入口。停止后主窗恢复并弹 `DesktopSanityCheckDialog` modal child；dialog 通过 `DesktopRecordingService.get_health_stats(recording_id)` 间接读取 `desktop_recordings.health_stats`，提供继续分析 / 放弃录制 / 重新录制三按钮。录制模式互斥同时由 UI 禁用和业务层 active recorder state 拒绝保证。

### Phase 1 边界

Phase 1 不引入录制数据 retention、cleanup、compress、disk quota、运行期隐私确认、vision quota/rate limit、Trial 资源配额或桌面 UI 播放器。录制数据崩溃孤儿保留并由用户手动清理；Trial 调试目录单独保留 7 天并在 startup recovery 清理。
