# Main Implementation Plan Memory

**Purpose**: Consolidated technical state from all merged features. Reflects the *implemented* state of the system.
**Last Updated**: 2026-06-15
**Revision**: 2026-06-15 — Archived feature 022 process event push (子进程事件推送)

---

## Technical Context

**Language/Version**: Python 3.11+ (runtime 3.12), Rust stable/Tauri 2, TypeScript 5.x, React 18
**Primary Dependencies**: Tauri 2, React 18, Vite, Tailwind CSS, Zustand, FastAPI, Uvicorn, Pydantic, PyInstaller, SQLite (SQLAlchemy/Alembic), DuckDB, Playwright/Vitest, blinker, sqlglot, LangChain, mitmproxy, AgentLoop (自研), pynput, mss, opencv-python, Pillow, comtypes, pywinauto, pywin32
**Storage**: SQLite (业务数据和 `app_settings` 配置覆盖, via Repository/UnifiedConfigManager); DuckDB (录制分析数据, via FilteredDuckDBConnection/sql_rewriter; desktop_recordings/desktop_actions); local `config.json` defaults; filesystem (`data/recordings/<recording_id>/`, `data/trials/<trial_id>/`, packaged sidecar artifacts)
**Testing**: pytest (`tests/`), Vitest + React Testing Library (`frontend/tests/unit`), Playwright/Tauri smoke (`frontend/tests/e2e`), guardrail tests (`tests/guardrails`)
**Target Platform**: Windows desktop first via Tauri/WebView2; desktop recording remains Windows-only
**Project Type**: Tauri desktop application with React frontend and packaged Python FastAPI sidecar

---

## Current Project Structure

```
frontend/
├── package.json                    # Vite/Tauri scripts: dev/build/lint/test/e2e/tauri
├── src/
│   ├── app/                        # App shell, route registry, custom titlebar, backend status
│   ├── api/                        # typed frontend clients for Python sidecar contracts
│   ├── components/                 # shared primitives and shell UI controls
│   ├── screens/                    # assistant, teaching, skills, compositions, settings, BrainScreen, SpecialistScreen, SkillMethodologyScreen, debug
│   ├── state/                      # Zustand local UI/session stores
│   ├── styles/                     # Tailwind/theme tokens and reduced-motion/contrast baseline
│   └── test/                       # frontend mocks and component helpers
└── tests/
    ├── unit/                       # React component/workflow tests
    └── e2e/                        # Playwright/Tauri smoke and acceptance checks

src-tauri/
├── Cargo.toml
├── tauri.conf.json                 # custom window + externalBin sidecar config
├── capabilities/default.json       # scoped shell/http/window permissions
├── binaries/                       # PyInstaller sidecar output by target triple
└── src/
    ├── lib.rs                      # plugin/window/sidecar command registration
    ├── sidecar.rs                  # Python sidecar lifecycle, random port/token handoff
    └── window.rs                   # minimize/maximize/close/drag commands

src/
├── desktop_api/
│   ├── app.py                      # FastAPI factory, token auth, loopback CORS, router registration
│   ├── __main__.py                 # sidecar process entrypoint
│   ├── schemas.py                  # Pydantic DTOs for shell, assistant, teaching, skills, settings
│   ├── events.py                   # blinker -> frontend event-stream adapter
│   ├── assistant_runtime.py        # assistant worker dispatch adapter
│   ├── confirmations.py            # high-risk confirmation DTO mapping
│   ├── orchestrator_runtime.py     # desktop agent runtime; TD001 tracks business-owned factory extraction
│   └── routers/
│       ├── health.py
│       ├── assistant.py
│       ├── teaching.py
│       ├── skills.py
│       ├── compositions.py
│       └── settings.py
├── business/
│   ├── orchestration/agent/        # AgentOrchestrator remains source of truth
│   ├── services/
│   │   ├── desktop_bootstrap_service.py
│   │   ├── desktop_health_service.py
│   │   ├── recording_readiness_service.py
│   │   ├── settings_service.py
│   │   ├── settings_actions_service.py
│   │   ├── skills_service.py
│   │   └── teaching_service.py
│   ├── agents/                     # AgentLoop, tools, prompts, assistant memory
│   └── brain/                      # 大脑业务层：segment, distillation, context, decay, archive, retrieval, specialist, prediction, management, skill
├── data/                           # repositories, config models, migrations, unified config
├── execution/                      # tool execution and desktop trial runner
├── recording/                      # browser/extension/desktop recording and DuckDB filtering
├── utils/                          # blinker events and shared helpers
└── main.py / mexemplar_gui.py       # legacy entrypoints: failure/transition guidance, not maintained PyQt UI

tests/
├── desktop_api/                    # FastAPI contracts, token auth, event-stream, sidecar/runtime tests
├── guardrails/                     # UI stack boundary and legacy PyQt removal/launch guards
├── business/                       # service and memory behavior tests
├── data/                           # repository/config/migration tests
├── integration/                    # Agent, recording, settings, local data safety, sidecar integration
├── recording/                      # recording/filtering regression tests
└── test_hook_protocol.py           # hook protocol and migrated gate regression suite
```

[Sources: specs/001-recording-field-layering, specs/002-tool-hook-system, specs/003-fix-agentloop-tool-calls, specs/004-auth-toast, specs/005-fix-compression-tool-pairing, specs/006-chat-ui-polish, specs/007-desktop-recording, specs/008-ui-stack-redesign]

### Desktop Recording Runtime After UI Redesign [Sources: specs/007-desktop-recording, specs/008-ui-stack-redesign]

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

frontend/src/screens/teaching/
├── TeachingScreen.tsx                  # redesigned teaching shell
├── RecordingModePicker.tsx             # browser/extension/desktop readiness and setup actions
├── RecordingStage.tsx                  # active recording, stop, desktop sanity choices
├── IntentStage.tsx                     # intent clarification/confirmation
├── LearningStage.tsx                   # learning progress, retry, blocked/failure states
└── TrialStage.tsx                      # trial validation progress and publish threshold

frontend/src/screens/settings/
└── SettingsScreen.tsx / SettingControls.tsx / SettingsActions.tsx
                                        # recording.desktop config and product actions

tests/
├── business/test_high_risk_api_detector.py
├── data/test_recording_desktop_config.py
├── data/test_recording_repository_desktop.py
├── integration/test_desktop_*                 # tools, prompts, syntax gate, trial runner, mode dispatch
├── recording/test_desktop_*                   # hook/UIA/clipboard/ring/sink/action semantics
├── desktop_api/test_teaching_api.py           # readiness/run/recording/health decision bridge
├── desktop_api/test_settings_api.py           # settings schema/values/secrets/actions bridge
└── frontend/tests/*                           # React unit + Playwright teaching/settings smoke
```

PyQt desktop recording widgets were retired with the primary PyQt UI. The desktop recording backend, tools, prompts, syntax gate, and trial runner remain the semantic source of truth; the React teaching/settings screens access them only through `src/desktop_api` and business services.

[Sources: specs/007-desktop-recording, specs/008-ui-stack-redesign]

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

provider routing 和 API key 复用 `analyze_image` 当前统一配置 entry；不新增 `recording.desktop.vision_provider`。

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

---

## UI Stack Redesign [Source: specs/008-ui-stack-redesign]

### 架构概览

维护中的桌面入口是 Tauri + React。`frontend/` 渲染五个主屏和自定义窗口 chrome；`src-tauri/` 负责窗口命令、Python sidecar lifecycle、随机端口/token handoff 和打包配置；`src/desktop_api/` 是 FastAPI sidecar adapter，通过 typed DTO 调用现有业务服务、AgentOrchestrator、录制/设置/技能/组合服务和 blinker event adapter。

旧 PyQt 正常 UI 已退休：`src/main.py` / `mexamplar_gui.py` / batch entrypoint 只保留 legacy 失败或迁移提示，不再作为可维护 fallback。Guard tests 覆盖正常启动路径不得打开 PyQt 窗口、旧主 UI 模块不得重新成为入口。

### Frontend Structure

- `frontend/src/app`: 应用壳、路由、导航、红/黄/绿标题栏、backend 状态。
- `frontend/src/api`: typed clients，负责 token header、错误归一化和 event stream。
- `frontend/src/state`: Zustand stores，保存 route、draft、selected IDs、transient panel state、optimistic flags 和 sidecar connection；server data 以 Python API 为权威。
- `frontend/src/screens/assistant`: 会话列表、timeline、composer、SafeMarkdown、ExecutionSummary、ConfirmationToast。
- `frontend/src/screens/teaching`: 录制模式、准备状态、录制/健康决策、意图、学习、trial 阶段。
- `frontend/src/screens/skills` 与 `frontend/src/screens/compositions`: 技能分类、技能卡、组合列表、组合编辑器、成员选择、range/ordered 验证。
- `frontend/src/screens/settings`: AI、Recording、Data、About 设置、masked secrets、settings actions。

### Desktop API Contracts

`src/desktop_api/app.py` 注册以下 router：

- `health.py`: `/api/health`、`/api/bootstrap`
- `assistant.py`: sessions/messages/confirmation decisions
- `teaching.py`: readiness/runs/recording stop/desktop health/intent/trial
- `skills.py`: pending/published/failed skills, trial, update, delete, retry, dismiss
- `compositions.py`: list/create/update/generate applicability/recommend order/trial/publish
- `settings.py`: schema/values/non-secret updates/secret write/delete/actions

所有非显式例外 endpoint 均要求 `X-Mexemplar-Session` runtime token。Event stream 由 `src/desktop_api/events.py` 适配 `src/utils/events.py` 的后端事件；后端下层不得 import Tauri 或 frontend。

### Configuration And Secrets

Settings API 通过 `UnifiedConfigManager` 读写所有配置和 secrets；`config.json` 提供本地默认值，`app_settings` 可覆盖。secret values 不以明文进入 response DTO、frontend store、普通日志或配置示例。设计中可见的 test connection、backup、export、clear memory、update check、docs、changelog、certificate install 等 action 要么调用真实业务路径，要么返回真实不可用/验证错误。

### Packaging And Commands

- Frontend: `npm --prefix frontend run lint`, `npm --prefix frontend run test`, `npm --prefix frontend run test:e2e`
- Tauri dev/build: `npm --prefix frontend run tauri:dev`, `npm --prefix frontend run tauri:build`
- Python checks: `uv run pytest tests/desktop_api tests/guardrails tests/integration tests/business tests/data`
- Sidecar packaging: `scripts/build_desktop_sidecar.ps1`, `build_tauri.bat`, `build_executable.py`, `installer.iss`, `BUILD_README.txt`

### Testing Strategy

- **API/sidecar**: FastAPI app contract, token auth, event stream, assistant/teaching/skills/compositions/settings routers, sidecar token non-persistence/no-log.
- **Frontend unit**: app shell, assistant screen, teaching screen, skills/compositions screen, settings screen.
- **E2E/smoke**: five-route navigation, assistant happy path, teaching fixture, skills/compositions creation, settings actions, no-sample-data audit, visible-control wiring, performance/health.
- **Guardrails**: UI stack boundary imports, legacy PyQt launch/removal, no direct frontend/API storage access.
- **Safety**: legacy local data non-mutation, secret masking, backend degraded/failed/shutdown states.

### Known Follow-Up

Cleanup task `TD001` remains open: extract desktop orchestrator construction from `src/desktop_api/orchestrator_runtime.py` into a business-owned factory/service so the FastAPI adapter depends only on business entry points and does not assemble config, LLM client, and `AgentOrchestrator` directly. This is tracked as technical debt, not as a blocking archive conflict.

---

## Frontend Event Layer [Source: specs/009-frontend-event-layer]

### 架构概览

公开 UI 事件契约由后端的 **UI Event Registry**（`src/desktop_api/ui_events.py`）独家拥有。所有面向前端的事件必须先在 Registry 注册 type、scope 和 payload allowlist，再以 typed envelope 发出；裸 blinker 事件名、`payload.sourceEvent` 和默认未知事件转发被 guard tests 禁止。

### Event Envelope

每条公开 UI 事件统一 envelope：

| 字段 | 说明 |
|------|------|
| `eventId` | 全局唯一 UUID |
| `sequence` | 当前桌面事件会话内单调递增整数 |
| `sessionId` | 桌面事件会话标识，进程级 |
| `causationId` | 关联多事件同源关系的因果链 ID |
| `type` | 注册过的公开事件 type |
| `scope` | `global` / `session` / `screen-specific` |
| `payload` | safety 校验后的 allowlisted 字段 |
| `createdAt` | 后端 ISO timestamp |

### Per-Subscriber Stream 与 Replay

`event_queue` 为每个订阅者维护独立 FIFO 队列 + 有界 replay buffer。前端重连时携带 `sessionId` + last-seen sequence；buffer 能覆盖缺口 → 按序回放；不能覆盖或 sessionId 不匹配 → 发 `backend.resync_required`，前端刷新权威快照恢复状态。慢订阅者积压超阈值时单独被踢，不阻塞其他订阅者和发布者。

### Interactive Trial Preview Confirmation

桌面 Trial 事前预览确认走广播 + first-decision-wins 协议：

- 每条请求带后端生成的 `expires_at`；前端到期前 disable 操作。
- 同 scope 多订阅者都收到请求，只接受 `expires_at` 前第一个有效决策。
- 用户拒绝、超时、断连、订阅者溢出、应用关闭 → 后台流程一律得到 deny 结果。
- Trial preview 浮层独立于普通 Toast 和 assistant 高危确认的生命周期。

### Payload Safety

公开 UI event payload 必须只含 allowlist 字段。下列内容禁止进入公开 UI 事件，校验失败直接拒发：runtime token、secret、完整代码、完整命令体、未脱敏 stack trace、本地数据库路径、raw query 结果、未过滤录制数据。需要前端恢复状态时只能发另一个已注册的 allowlist resync/summary 事件。

### Frontend Consumption

`frontend/src/api/events.ts` 和 `frontend/src/state/eventStore.ts` 实现 typed event subscription、sessionId/sequence 跟踪和 resync 触发。所有 frontend screen store（assistant、teaching、skills、compositions、settings、brain、specialist）按 typed event type 消费；未注册的内部事件不会到达前端。

### Testing

- **Contract**: 后端 UI Event Registry 与前端 event type/example payload 一致性自动化校验。
- **Safety**: payload allowlist enforcement、敏感字段 leak guard。
- **Replay/resync**: 同 sessionId 重连按 last-seen sequence 回放；缺口或 sessionId mismatch 触发 `backend.resync_required`。
- **Multi-subscriber**: 至少 20 trial 验证两订阅者都收到事件且不互相抢占；慢订阅者单独 resync 不影响 healthy 订阅者。
- **Trial preview**: approve / deny / timeout / disconnect / overflow / shutdown 6 种结果在自动化测试中确定性发生，非 approve 一律按拒绝处理。
- **Guard**: 禁止直接 SSE 发布、禁止裸 blinker 事件名进入前端 store。

---

## Assistant Brain Service [Source: specs/010-assistant-brain-redesign]

### 架构概览

办公助理重构为"大脑 + 100% 调度"架构。新增 `src/business/brain/` 业务层（11 个子模块）、`src/data/repos/brain_repository.py` + `specialist_repository.py`、v11 SQLite migration 一次性建全所有 brain 表，以及前端 `BrainScreen` + `SpecialistScreen` 两个新主屏。PM / Programmer / Trial 录制流水线保持不变，不在 assistant 调度池。

### Business Modules

| 模块 | 职责 |
|------|------|
| `src/business/brain/models.py` | dataclass、enum：zone、entry status、entry type、specialist origin |
| `src/business/brain/segment_service.py` | Segment 生命周期、`pending → distilling → completed/failed` 状态机、CAS、崩溃恢复 |
| `src/business/brain/distillation_service.py` | 单次结构化 LLM 调用沉淀，phase-aware schema，原子事务写入 entries + 状态转换 |
| `src/business/brain/context_builder.py` | persistent zone 全量注入 + hot/subconscious top-N（复合评分） |
| `src/business/brain/decay_router.py` | 沉淀触发 + worker 周期；event → archive，insight → persistent 或退役 |
| `src/business/brain/archive_service.py` | unit summary、theme/time 聚合、年月日层级 |
| `src/business/brain/retrieval_service.py` | `retrieve_archive` / `retrieve_failure_zone`、invalidation fallback、相关性排序 |
| `src/business/brain/specialist_service.py` | 专员 CRUD、白名单子集校验、自动招募扫描 |
| `src/business/brain/prediction_service.py` | prediction 生成 + worker 自动验证（hit/miss/partial/expired）|
| `src/business/brain/management_service.py` | 大脑管理模块业务 facade：zone entry 增删改、skill pool 管理 |
| `src/business/brain/background_worker.py` | pending Segment 沉淀、distillation 崩溃重置、衰减扫描、archive 分层、prediction 周期、招募扫描、事件唤醒 |

### Data Tables (v11 migration)

一次性建全：

| 表 | 说明 |
|----|------|
| `brain_segments` | Segment 记录；`open` 态不持久化，行只在封存（转 `pending`）时创建 |
| `brain_memory_entries` | 6 zone 共表，按 `zone` 字段区分；entry status: `active` / `fading` / `invalidated` / `soft-deleted`；entry type: `event` / `insight`；含 `loaded_count`、`referenced_count`、`superseded_by`；prediction 条目额外有 `verification_checkpoint`、`verification_status`、`verification_rationale` |
| `brain_specialists` | 专员定义（name、description、role、tool whitelist、origin、reason、`is_active`） |
| `brain_specialist_versions` | 专员版本历史（软删除后必须保留） |
| `brain_recruitment_signals` | 招募信号 |
| `feedback_signals` | 用户对自动产物的 edit / delete 信号；keyed by zone + operation + entry/specialist id；后续沉淀和招募 LLM 调用从此读取作为反向提示 |

### Assistant Tools

`delegate_to_subagent`、`delegate_to_specialist`、`create_specialist`、`retrieve_archive`、`retrieve_failure_zone`、`invalidate_memory_entry`（仅允许 invalidate 当前上下文中已注入或本会话已检索过的 entry）。`invalidate_memory_entry` 主动失效必须在同轮回复中向用户披露原因。

### 100% Dispatch

任务（需要 tool use、外部操作或多步执行的请求）一律派给临时 subagent 或固定 specialist；纯对话（问候、记忆查询、简短澄清）由 assistant 直接回复。PM / Programmer / Trial 不在 assistant 调度池。

### Prompt 重构

assistant prompt 由 `BrainContextBuilder` 在每轮跑前在 assistant worker 内重建：

- persistent zone 全量注入所有 active entry
- hot zone top-N，主排序 `relevance_score`（新近度兜底）
- subconscious zone top-N，主排序新近度
- effectiveness ratio (`referenced_count / loaded_count`) 作为附加加权项叠加，不作单一主键；`loaded_count` 低的新 entry 有探索配额
- specialist 列表 + capability 列表
- "100% dispatch" 工作风格段

`referenced_count` 测量：assistant 回复必须含 `memory_entries_referenced` 结构化字段，后端读取后批量更新；字段缺失或格式错误静默跳过本轮。

### Events

新增（定义在 `src/utils/events.py`）：`brain_zone_changed`、`brain_specialist_changed`、`segment_boundary_triggered`、`segment_idle_trigger`、`brain_specialist_recruited`、`brain_context_ready`。`segment_idle_trigger` 是前端 idle timer emit，不轮询；其余由 brain 业务服务发出，经 `src/desktop_api/ui_events.py` 投影为前端 UI event stream。

### Frontend

新增路由 + Zustand store：

- `/brain` → `BrainScreen`（6 zone 浏览/过滤/编辑/删除、evolution chain、skill pool 管理）
- `/brain/specialists` → `SpecialistScreen`（专员 CRUD、软删除停用、白名单编辑）

`brainStore`（zone/entry/segment/skill pool 状态）、`specialistStore`（专员列表/编辑草稿/白名单）。自动招募 specialist 走非模态 toast（含 specialist 名 + reason，点击跳 `/brain/specialists`）。

### Background Worker

`BrainBackgroundWorker` 在 desktop API 启动时创建，随 sidecar 生命周期停止：

1. pending Segment 蒸馏处理
2. 蒸馏中崩溃的 Segment 重置（`distilling → pending`）
3. hot-zone 衰减清扫
4. archive 分层聚合
5. prediction 生成 + 验证周期
6. 自动招募信号扫描
7. 事件唤醒（`threading.Event`）

worker 周期由 `brain.*` 配置占位符控制（CC-008，待实测调整）。

### Testing

- **Brain service**: zone 注入策略、复合评分、衰减路由、archive 分层、prediction 生成/验证。
- **Segment**: CAS 状态转换、原子事务（entries + 状态在同一 commit）、崩溃恢复 `distilling → pending`、all-empty 一次重试、`failed` 终态。
- **Specialists**: 自动招募、白名单子集约束、软删除版本保留、技能池移除时阻断 + 强制裁剪。
- **Repository**: invalidation 降权而非过滤、`superseded_by` 链生成与遍历、`feedback_signals` 读写。
- **Frontend**: BrainScreen 6 zone 操作、SpecialistScreen CRUD、自动招募 toast、`segment_idle_trigger` emit。
- **Guard**: 禁止物理 DELETE `brain_*` 表行；prediction zone 不进 `context_builder` 注入；specialist 白名单子集校验。

---

## 子代理可唤回机制 [Source: specs/013-subagent-resumable]

### 架构概览

临时子代理在被迫中断时不再丢弃已完成工作：撞迭代上限或 LLM 调用经重试仍最终失败时，会话转入 `suspended` 并完整保留工作历史。委派结果以"暂停（可唤回）+ 子代理标识符 + 可区分暂停原因"返回给主代理。纯 business 层增量，无新表/迁移/配置/依赖。

### Source Code Structure

```text
src/business/agents/
├── config.py                     # +ResultType.PAUSED, +AgentConfig.resumable_on_failure
├── agent_loop.py                 # 迭代上限/LLM 调用失败两路 → suspended + PAUSED（仅 resumable_on_failure）
│                                 # +_is_recoverable_llm_failure 失败分类
├── prompts/
│   └── assistant_prompt.py       # +「子代理暂停（可唤回）时的处理」引导段
└── tools/
    └── assistant_tools.py        # +continue_subagent / +inspect_subagent schema & handler 工厂

src/business/orchestration/agent/
└── orchestrator.py               # 委派回传 subagent_id；PAUSED 句柄 + transition；
                                  # _resolve_subagent_session 归属校验；
                                  # _continue_subagent 续跑（持久化恢复/重复唤回）；
                                  # _inspect_subagent 零模型调用概览；
                                  # 注册两个新工具；ephemeral_config max_iterations=50 + resumable_on_failure

tests/business/agents/
└── test_subagent_resumable.py    # 行为契约测试（15 例）
```

### Agent Tools

| 工具 | 类型 | 说明 |
|------|------|------|
| `delegate_to_subagent` | 修改 | 始终返回 `subagent_id`；暂停时附 `paused`/`reason`/`result_type` |
| `inspect_subagent` | 新增 | 只读、零模型调用；返回 `{success, subagent_id, status, assistant_turns, tool_call_counts, last_output}` |
| `continue_subagent` | 新增 | 唤回续跑，可选 `instruction` + `extra_iterations`（默认 20）；完成返回结果，再暂停返回句柄 |

### Testing Strategy

- **契约测试**：`tests/business/agents/test_subagent_resumable.py`（15 例）覆盖两路 PAUSED 终止语义、默认 Agent 不回归、委派回传 `subagent_id`、PAUSED 句柄、续跑完成/再暂停/归属拒绝/未知 id、inspect 概览零模型调用、非可恢复失败仍 ERROR、已完成无 instruction 提示、prompt 引导段存在。
- **回归**：`test_agent_loop_retry` / `test_agent_loop_multi_tool_calls` / `test_agent_orchestrator_architecture` / `test_assistant_dispatch` 保证 FR-156 / SC-084。
- **语法/格式**：`py_compile` + `flake8`。

---

## 主助理对话透明与可控 [Source: specs/014-assistant-chat-transparency]

### 架构概览

AI Assistant 主屏新增运行态输入门控、停止/深度取消、单条排队、活动时间线、子任务卡片/详情和暂停子任务继续入口。技术核心是业务层 `run_context` ContextVar：assistant worker 入口登记 `{root_session_id, cancel_event}`，同步委派的子 loop 共享同一取消事件；`AgentLoop` 在迭代边界和工具批次前协作式检查取消，并以 `ResultType.CANCELLED` 表示用户主动停止。过程和子任务状态经 `src/utils/events.py` blinker 事件投影为 UI Event Registry typed envelope。

### Source Code Structure

```text
frontend/src/
├── screens/assistant/
│   ├── MessageComposer.tsx        # running 门控、停止、单条排队三态
│   ├── ActivityTimeline.tsx       # 默认折叠、限高内滚的活动过程
│   ├── ActivityStepRow.tsx        # 活动步骤行
│   ├── StepIcon.tsx               # 活动步骤图标
│   ├── SubagentCard.tsx           # 子任务卡片、状态、继续任务入口
│   ├── SubagentDetailDrawer.tsx   # 子任务过程详情
│   └── AssistantScreen.tsx        # 时间线/卡片/停止/继续接线
├── state/
│   ├── assistantStore.ts          # progress、queuedMessageBySession、activity/subagents
│   ├── assistantTypes.ts          # AssistantProgress cancelled、ActivityStep、Subagent
│   └── assistantHelpers.ts        # 过程/排队/子任务辅助逻辑
└── api/
    ├── assistant.ts               # stopAssistantRun/listSubagents/getSubagentTranscript/continue
    └── uiEvents.ts                # assistant.activity / assistant.subagent 类型

src/
├── business/
│   ├── agents/
│   │   ├── run_context.py         # ContextVar + session→Event + 代际 token + 待停止集合
│   │   ├── observability.py       # 只读 transcript / 子任务权威列表重建
│   │   ├── agent_loop.py          # CANCELLED 检查 + assistant_agent_step emit
│   │   └── config.py              # ResultType.CANCELLED
│   └── orchestration/agent/
│       └── orchestrator.py        # CANCELLED 非错误、子任务生命周期、继续任务兜底
├── desktop_api/
│   ├── assistant_runtime.py       # begin/end run_context、cancel_session、cancelled progress
│   ├── confirmations.py           # stop 时 pending confirmation fail-closed
│   ├── routers/assistant.py       # stop / subagents / transcript / continue 入口
│   ├── ui_events.py               # assistant.activity / assistant.subagent 注册
│   └── ui_event_projector.py      # blinker → typed UI event 投影
└── utils/events.py                # assistant_agent_step / assistant_subagent_* 信号

tests/
├── business/agents/               # loop 取消、深度取消、observability、续跑
├── desktop_api/                   # runtime cancel、端点、projector、确认停止
└── guardrails/                    # 同线程不变量、非助理零 emit/零行为变化

frontend/tests/
├── unit/                          # composer、排队、停止、时间线、卡片/详情
└── e2e/                           # assistant 发→停→续、排队自动派发
```

### Runtime And Cancellation

- `src/business/agents/run_context.py` 是取消原语唯一入口；desktop API 只能调用业务层 API，不把取消状态落到配置、SQLite 或 DuckDB。
- 每次运行登记代际 token，`end()` 清理 session→Event 表；停止早于 worker `begin()` 的竞态通过待停止集合兜底。
- 深度取消依赖"父助理与子代理/专员同线程同步委派"这一承重不变量；门卫测试必须在委派改走线程或异步时失败。
- `ResultType.CANCELLED` 表示用户主动停止后的可恢复暂停，不走错误路径；子任务暂停线索先落库，再由主助理下一轮可见并可 `continue_subagent` 续跑。

### UI Events And Endpoints

- 新 blinker 信号：`assistant_agent_step`、`assistant_subagent_started`、`assistant_subagent_finished`、`assistant_subagent_paused`。
- 新 UI event type：`assistant.activity`、`assistant.subagent`；`assistant.progress.status` 新增 `cancelled` 取值。
- 新/扩展 assistant API：`POST /api/assistant/sessions/{sessionId}/stop`、子任务权威列表、子任务 transcript、暂停子任务继续入口。
- 事件 payload 走 009 payload safety allowlist 和截断；前端只消费注册过的 typed event type，缺口走 `backend.resync_required` 拉权威快照。

### Frontend Interaction Model

- `progress.status === "running"` 是输入门控唯一判据；`waiting_for_user` 不算忙。
- running 时发送按钮切为停止；点击后约 200ms 内进入"停止中"，重复点击幂等。
- 每会话一条 `queuedMessageBySession`，状态为 `editing` / `queued`；成功或等待回答自动派发，失败或停止退回普通草稿。
- 活动时间线默认折叠、限高内滚；最终回复正常显示且不重复进过程区域。
- 子任务卡片显示运行/完成/暂停/失败状态，双击和键盘入口打开详情；继续暂停子任务通过主助理消息派发，不直连子代理。

### Data And Configuration

- 无新增 SQLite 表、迁移或 DuckDB 结构；历史过程与子任务列表由 `MessageRepository`、`WorkflowTransitionRepository`、`SessionRepository` 只读重建。
- 无新增密钥；取消检查阈值等若未来需要可调，必须走 `get_unified_config()`，Settings UI 暂不暴露。

### Testing Strategy

- 后端行为契约：`AgentLoop` 迭代边界/工具批次前取消、父子深度取消、`CANCELLED` 非错误、代际 token、早停竞态、pending 确认 fail-closed。
- 事件与 API：UI Event Registry 注册、projector 映射、payload safety、stop/subagents/transcript/continue 端点。
- 前端：composer 门控与停止、排队三态、自动派发边界、ActivityTimeline 折叠/限高、SubagentCard/DetailDrawer、缺口 resync。
- Guardrails：非助理 Agent 零 emit/零行为变化；同线程同步委派承重不变量。

## Agent Built-in Tools Upgrade [Source: specs/015-agent-builtin-tools-upgrade]

**Revision note (2026-06-09)**: Archived merged feature 015 into main implementation memory; documents the implemented built-in tool subsystem, configuration contract, storage boundary, and verification strategy.

### Technical Context

- **Runtime**: Python 3.11+ source with Python 3.12 sidecar runtime; no frontend or Rust change is required for the core tool subsystem.
- **Dependencies**: existing `AgentLoop` / `ToolDefinition` hook protocol, `pathlib`, `subprocess`, `threading`, SQLAlchemy SQLite repositories, `get_unified_config()` / `UnifiedConfigManager`, and pytest.
- **Storage**: persistent raw-output reference metadata lives in SQLite via Repository; raw blobs live under the application data directory in a private `tool_outputs/` subtree. Background process records are in-memory and valid only for the current sidecar process session.
- **Boundaries**: business-facing schemas and summaries live in `src/business/agents/tools/`; live command/process execution belongs to `src/execution/`; durable metadata belongs to `src/data/repos/`.

### Configuration

The following runtime knobs are owned by unified configuration and must not be read from `config.json` directly:

```text
agent_tools.file.default_max_lines
agent_tools.file.max_window_chars
agent_tools.file.max_decode_bytes
agent_tools.output.visible_char_cap
agent_tools.output.raw_reference_threshold_chars
agent_tools.output.max_artifact_bytes
agent_tools.output.retention_days
agent_tools.search.default_page_size
agent_tools.search.max_files_scanned
agent_tools.search.max_bytes_per_file
agent_tools.search.max_elapsed_ms
agent_tools.process.default_timeout_ms
agent_tools.process.max_timeout_ms
agent_tools.process.log_tail_chars
agent_tools.process.max_background_processes
```

Fixed policy constants:

- Authorized workspace is resolved from Agent runtime context, not from a user-editable config key.
- Outside-workspace reads are always exceptional high-risk inspection.
- Outside-workspace mutation, deletion, patching, and execution are always denied.

### Source Code Structure

```text
src/
├── business/
│   └── agents/
│       ├── agent_loop.py                 # exactly-one-result persistence/governance boundary
│       └── tools/
│           ├── builtin_general_tools.py  # stable public registry facade
│           ├── builtin_contracts.py      # envelope, errors, limits, reference DTOs
│           ├── builtin_permissions.py    # workspace/risk classification and summaries
│           ├── file_tools.py             # read/write/edit/patch handlers
│           ├── search_tools.py           # filename/content search
│           ├── command_tools.py          # exec + process lifecycle tool handlers
│           └── output_governance.py      # redaction, compaction, raw-reference creation
├── execution/
│   ├── command_runner.py                 # synchronous command execution boundary
│   └── process_manager.py                # session-scoped background process registry
└── data/
    ├── models_sqlite.py                  # tool output reference metadata model
    ├── migrations.py                     # SQLite schema migration
    ├── unified_config.py                 # typed agent_tools getters
    └── repos/
        └── tool_output_repository.py     # metadata Repository for raw-output references

tests/
├── business/agents/test_builtin_*        # file/search/command/output/facade contracts
├── data/test_tool_output_repository.py
├── guardrails/test_agent_builtin_tool_boundaries.py
└── integration/test_agent_builtin_*      # tool contract + process lifecycle
```

### Tool Result Envelope

All upgraded foundational built-ins return a shared JSON envelope with `schemaVersion`, `tool`, `outcome`, bounded `payload`, optional `error`, `permission`, `limits`, `references`, `warnings`, `verification`, and `createdAt`. Stable outcomes include `success`, `error`, `rejected`, `unsupported`, `timeout`, `background_started`, `not_executed`, and `confirmation_required`.

Stable error codes include path errors, permission/confirmation failures, `unsupported_binary`, decode failures, `baseline_required`, `baseline_stale`, edit/patch/search failures, command/process errors, output-reference errors, `compaction_failed_fallback`, and `internal_error`.

### Workspace And File Mutation Policy

- All file, search, patch, delete, and command requests resolve canonical paths before side effects.
- Workspace writes, deletes, patch updates/deletes, and command execution are allowed only after policy classification and any required confirmation.
- Outside-workspace reads require high-risk confirmation with a safe summary; outside-workspace writes/deletes/patches/execution are rejected.
- Existing-file mutation uses raw-byte `FileBaseline`; missing/stale baselines reject before disk changes.
- Edits preserve detectable text style where possible and report concise changed regions plus verification metadata.

### Search And Patch

`search_files` and `search_content` use structured traversal with deterministic sorting, default generated/dependency ignores, page-size caps, elapsed/file caps, line-numbered content matches, and opaque continuation tokens. An optimized `rg --json` adapter may sit behind the same contract if large-repo fixtures exceed native traversal limits.

`apply_patch` validates every operation before mutation. Add/update/delete summaries expose affected files, operation type, verification, and stable rejection codes, but never full replacement payloads in confirmation or ordinary visible summaries.

### Command And Process Lifecycle

- Sync command execution is isolated in `src/execution/command_runner.py` and returns status, exit code, timeout classification, bounded output, and raw-reference availability.
- Background process management is in `src/execution/process_manager.py`; records are sidecar-session scoped and not restored as live handles after restart.
- Process logs are bounded ring buffers using `agent_tools.process.log_tail_chars`; duplicate starts use normalized command/cwd/session keys and point to the existing `processId`.
- Stop first attempts graceful termination, then force-stops the process tree on Windows or child process group on POSIX where supported.

### Raw Output Artifact Security

- Ordinary envelopes expose only opaque `referenceId`, kind, size, content type, digest, and expiry metadata.
- Blob paths and `storageKey` stay internal to data-layer helpers and Repository metadata; they must not enter Agent-visible text, public UI events, ordinary logs, confirmation summaries, or error responses.
- Reference creation writes a temp blob, computes sha256, atomically finalizes the blob, then commits active metadata. Failures remove temp/final blobs best effort and return a compact safe fallback with `compaction_failed_fallback`.
- Retention uses `expiresAt = createdAt + agent_tools.output.retention_days`; cleanup marks metadata expired/deleted and removes orphaned blobs/metadata with log-safe diagnostics.
- `load_tool_output` authorizes by owner session/workspace context before reading a blob.

### AgentLoop Result Governance

Result governance is a single save-time boundary, not a post-hook pipeline. All built-in tool save paths route through the governance wrapper before persistence so redaction, compaction, raw-reference creation, fallback warnings, and exactly-one-result pairing happen together. Governance failure returns one safe fallback envelope and must never create a second tool result for the same `tool_call_id`.

Feature 016 extends this same save-time boundary to every text tool result, including legacy and custom tools, while preserving the original format for small results. This extension does not change custom handler arguments, permission decisions, or business semantics. [Source: specs/016-tool-output-semantic-summary]

### Runtime Health Metadata

Implementation emits log-safe diagnostics/counters for compacted outputs, fallback count, raw-reference create/load failures, stale or missing baseline rejections, outside-workspace read confirmations and fail-closed outcomes, background process starts/reuse/timeouts/stops/shutdown cleanup, and retention cleanup of expired metadata, missing blobs, and orphaned blobs.

Diagnostics must omit raw command bodies, local blob paths, file contents, credentials, runtime tokens, raw stack traces, and secret-like values.

### Testing Strategy

- Unit tests cover path resolution, workspace escapes, symlinks, binary detection, redaction, pagination, baseline hashing, style preservation, patch validation, search caps, and output compaction.
- Integration tests cover AgentLoop multi-tool batches and prove accepted, rejected, compacted, failed, skipped, and fallback built-ins each create exactly one tool result.
- Data tests cover tool-output metadata persistence, retention cleanup, expired/deleted lookup, and post-restart reference behavior.
- Process tests cover background start, poll, logs, wait, stop, input, close, duplicate prevention, timeout, and unavailable-after-restart.
- Guardrails keep UI/desktop API out of built-in execution state, prevent direct SQL in business code, preserve fail-closed confirmation semantics, and assert no legacy contract dependency remains.

---

## Tool Output Semantic Summary [Source: specs/016-tool-output-semantic-summary]

**Revision note (2026-06-11)**: Archived merged feature 016 into main implementation memory; records the implemented deterministic compaction, optional advisory summarization, dedicated settings/credential path, and verification coverage.

**Credential revision (2026-06-12)**: Removed the external credential-store path. All provider credentials, including the dedicated tool-output summary key, now use `UnifiedConfigManager`; `config.json` supplies local defaults and `app_settings` supplies runtime overrides.

### Technical Context

- **Runtime**: Python 3.11+ source with Python 3.12 sidecar runtime; React 18 + TypeScript/Vite Settings UI.
- **Dependencies**: no new external package. The implementation reuses `AgentLoop`, `ToolOutputRepository`, `LangChainLLMClient`, `TraceContext`, unified config, pytest, Vitest, and the existing typed settings API.
- **Storage**: semantic summaries remain inside persisted tool-result message content. Raw output continues to use existing SQLite reference metadata and private blobs through `ToolOutputRepository`; no migration is introduced.
- **Performance**: the default total summary deadline is 12 seconds, with at most 6 map calls and concurrency 3. Visible results remain bounded by `agent_tools.output.visible_char_cap`.
- **Safety**: exactly-one result pairing, deterministic fail-open fallback, UnifiedConfigManager-only secret access, masked DTO/UI state, redacted ordinary logs, and no raw prompt/model output in UI events or connection-test responses.

### Configuration

All values are owned by `get_unified_config()` / `UnifiedConfigManager`:

```text
agent_tools.output.semantic_summary.enabled              # true
agent_tools.output.semantic_summary.provider             # anthropic
agent_tools.output.semantic_summary.model                # ""
agent_tools.output.semantic_summary.base_url             # ""
agent_tools.output.semantic_summary.api_key              # "" (dedicated secret)
agent_tools.output.semantic_summary.temperature          # 0.2
agent_tools.output.semantic_summary.trigger_chars        # 20000
agent_tools.output.semantic_summary.max_input_chars      # 120000
agent_tools.output.semantic_summary.chunk_chars          # 20000
agent_tools.output.semantic_summary.max_map_chunks       # 6
agent_tools.output.semantic_summary.map_concurrency      # 3
agent_tools.output.semantic_summary.total_timeout_seconds # 12
agent_tools.output.semantic_summary.map_max_tokens       # 500
agent_tools.output.semantic_summary.reduce_max_tokens    # 900
agent_tools.output.semantic_summary.summary_max_chars    # 4000
```

The dedicated runtime secret is `agent_tools.output.semantic_summary.api_key`. It follows the same unified-config precedence as other credentials: `config.json` provides the local default and `app_settings` may override it. Settings save/delete operations call `UnifiedConfigManager`; Real Grand Tour uses the same read-only getter and does not introduce a separate credential path.

### Source Code Structure

```text
src/
├── business/
│   ├── agents/
│   │   ├── agent_loop.py                    # passes original tool args into save-time governance
│   │   └── tools/
│   │       ├── output_governance.py         # all-text trigger, facts/preview, reference-first compact
│   │       ├── semantic_summary.py           # selection, goals, single/Map-Reduce, validation/deadline
│   │       ├── builtin_general_tools.py      # optional extractionGoal schemas
│   │       └── command_tools.py              # centralized governance owns command raw references
│   └── services/
│       ├── settings_service.py               # Tool Output descriptors/status/secret operations
│       └── settings_actions_service.py       # sanitized connection test
├── data/
│   ├── config_models.py                      # semantic-summary config dataclass
│   └── unified_config.py                     # validated getters + unified secret helpers
├── desktop_api/
│   └── schemas.py                            # settings descriptor `advanced` metadata
└── utils/
    └── agent_tool_health.py                  # log-safe semantic summary counters

frontend/
├── src/api/settings.ts                       # typed advanced descriptor contract
└── src/screens/settings/SettingControls.tsx  # Tool Output section + advanced disclosure
```

### Governance Flow

1. Parse upgraded envelopes when possible and inspect all text results at the single AgentLoop save boundary.
2. Keep small legacy/custom results unchanged. Trigger compact for size, truncation/clipping metadata, or an existing raw reference.
3. Redact the visible object and derive deterministic `facts`, `preview`, `rawChars`, and `originalPayloadKeys`.
4. Reuse an authorized existing reference; otherwise persist the original handler result before summary work when artifact limits allow.
5. Resolve an extraction goal from explicit `extractionGoal`, `web_fetch.prompt`, or conservative custom goal/query/prompt/pattern arguments.
6. Attempt semantic summarization over redacted, bounded selected text.
7. Validate, redact, and bound the semantic JSON. Any failure omits `semanticSummary` while preserving deterministic fields and reference.
8. Fit the compact envelope to the existing visible cap and persist exactly one result.

### Semantic Summarizer

- Tool-aware extraction prefers stdout/stderr, file content, search matches, web body, and loaded reference content; unknown tools use bounded structured JSON text.
- Inputs above `max_input_chars` use 15% head, 35% error/warning context, 35% uniform samples, and 15% tail.
- One chunk uses `mode=single`; multiple chunks use a bounded thread pool for map calls and one reduce call.
- Partial map success may reduce. Total map failure, invalid output, reduce failure, provider failure, or deadline exhaustion returns no semantic summary.
- Every provider request receives only the remaining deadline, uses no business-layer retry, and runs under `TraceContext(source="tool_output_summary")`.
- Prompt instructions treat tool output as untrusted data and require a fixed JSON-only advisory schema.

### Settings And Provider Integration

- The generic settings descriptor supports `advanced`; the Tool Output section keeps budget controls collapsed by default.
- Provider options include Anthropic, OpenAI, DeepSeek, Qwen, Zhipu, Moonshot, and custom OpenAI-compatible endpoints.
- The UI exposes only masked secret presence. Save/delete operations use the existing settings secret API.
- Connection validation performs one minimal bounded provider call and returns status plus provider/model metadata, never the model response.
- Empty model, missing secret, disabled summary, or invalid compatible endpoint degrades without a provider call.
- Debug provider inventory and Real Grand Tour coverage register summary client construction, credential reads, trace source, and paid-call budget.

### Testing Strategy

- Unit tests cover deterministic selection budgets, diagnostics at different positions, redaction, prompt injection text, extraction goals, single call, Map-Reduce, partial maps, invalid JSON, provider failure, and timeout.
- Governance tests cover legacy/custom/upgraded result shapes, all trigger rules, existing-reference reuse, artifact-limit fallback, visible caps, and second-stage `load_tool_output` governance.
- Integration tests prove AgentLoop argument propagation and exactly-one result pairing across summary success/failure and multi-tool batches.
- Settings/data/API tests cover defaults, validation, config persistence and precedence, secret masking/log redaction, read-only Real Grand Tour credential resolution, connection action, provider metadata, and advanced descriptor shape.
- Frontend tests cover Tool Output navigation, advanced disclosure, value save, secret write/delete, connection status, and actionable error display.
- Guardrails cover provider inventory, Real Grand Tour credential/budget registration, secret/log/UI-event leakage, active documentation, and AI entry mirrors.

---

## 大脑记忆质量提示词升级 [Source: specs/020-brain-memory-quality]

**Revision note (2026-06-15)**: Archived the migrated business-only prompt update and its explicit
verification gaps without changing brain schemas, services, contracts, or runtime wiring.

### Technical Scope

- Runtime: Python 3.11+（当前 3.12），沿用现有 LLM client、`BrainRepository` 和 `BrainBackgroundWorker`。
- Source files:
  - `src/business/brain/distillation_service.py` — Segment 多分区沉淀与周期性潜意识沉淀 prompt。
  - `src/business/brain/prediction_service.py` — Prediction 生成与验证 prompt。
- Storage、config、secret、API、event、frontend、Tauri：均无变化。
- 性能影响：不增加 LLM 调用次数，只增加少量 prompt 输入 token。

### Implemented Prompt Strategy

1. Segment 沉淀使用“未来不看这条信息会造成什么影响”作为价值筛选问题。
2. 记忆条目必须自包含、一条一事；聊天过程、通用知识、宽泛印象和单次事件误判被列为反例。
3. P1/P2/P4 继续按 phase 拼接已激活 zone 的判断问题、适用内容和示例。
4. 没有合格内容时允许所有分区为空；feedback signal 只作参考，不逐条复制。
5. 潜意识沉淀聚焦跨对话重复行为模式，排除单次事件、明确偏好和泛化人格判断。
6. Prediction 生成要求具体、可证伪、带 checkpoint 且至少有两条记忆支撑；验证 prompt 明确四种状态语义。

### Compatibility

- 保持 `distillation_output`、`subconscious_distillation_output`、
  `prediction_generation_output` 名称和 schema 不变。
- 保持 phase-aware validation、事务写入、all-empty retry、prediction retry/expired fallback
  和 startswith verification parser 不变。
- “至少两条证据”当前仅由 prompt 指导，未增加 schema 或业务代码硬校验。

### Testing

- 迁移时运行：
  `uv run pytest tests/business/brain/test_distillation_service.py tests/business/brain/test_prediction_worker.py -q`
  — 41 passed，7 个既有 Python 3.12 SQLite datetime adapter 弃用警告。
- 现有覆盖验证 schema、结构化解析、事务/all-empty 行为、prediction 生成/验证和 worker 调度。
- 待补 gap：关键 prompt 语义与 P1/P2/P4 zone 边界的低脆弱性回归测试；不使用整段字符串快照。

---

## Desktop UX、Debug Inspector 与真实 Grand Tour [Source: specs/011-desktop-ux-debug-regression]

**Revision note (2026-06-15)**: Backfilled 011 and reconciled its historical credential design with
the current UnifiedConfigManager-only constitution.

### Implemented Structure

- `frontend/src/hooks/useLongPasteCollapse.ts` + `LongPastePreview.tsx` 为 Assistant/Teaching composer 提供共享长粘贴交互。
- `src/business/debug/` 拥有 control、epoch-scoped buffer、observation、redaction、flow projection 和 reference facade。
- `src/desktop_api/routers/debug.py` 只做鉴权 DTO adapter；`/debug` 是隐藏 route，不进入普通导航。
- `LangChainLLMClient`、vision helper、AgentLoop、review、compression 和 brain worker 通过 context/source inventory 进入统一 observation 边界。
- Real Grand Tour 使用独立 Playwright config/runtime、public event watcher、预算审计、安全 fixture 和 summary reporter。

### Runtime Boundaries

- `debug.trace.enabled` 仅 runtime-only，默认 false；初始上限为 200 records、1 MiB/record、16 MiB total。
- Raw trace 和 debug-only handoff detail 不持久化；disable/clear/restart 使用 epoch invalidation。
- Trace API 使用 no-store，前端 raw state 只驻留内存；媒体只保留安全 metadata。
- Real Grand Tour 通过 UnifiedConfigManager 只读使用现有 credential，secret mutation 被拒绝；历史 keyring resolver 已删除。
- Real suite 最多 30 次付费请求、20 分钟，并与默认 mock E2E 完全分离。

### Testing

- Composer paste/selection/keyboard、debug control/buffer/redaction/reference/API、flow correlation、provider inventory 和 raw leakage guard。
- Real-tour runtime、event watcher、budget、cleanup、safe report 和 controlled failure tests。
- Feature tasks: 104/104 completed。

---

## Skill Methodology 方法论资产层 [Source: .specify/archive/012-skill-methodology-layer]

**Revision note (2026-06-15)**: Backfilled 012 from the physical archive folder.

### Data And Services

- v12 SQLite: `brain_skills`、`brain_skill_source_segments`、`brain_skill_equipment`，含 closed enums、partial unique indexes 和 no-DELETE triggers。
- `SkillRepository`、`SkillService`、`SkillEquipmentService`、`SkillBootstrapService` 和 `SkillReferenceCounter`。
- Seed: `src/business/brain/seed/how_to_create_skill_methodology.md`，读取失败使用内置 fallback。
- Config: `brain.skill.token_budget.warn_threshold`、`danger_threshold`、`seed_file_path`，统一由 UnifiedConfigManager 管理。

### Runtime Model

- Tool Teaching/List/Composition 使用 `/tools/*` 和 `tools.changed`；Skill Methodology 使用 `/skills/methodology` 和独立 `skill.*` events。
- Assistant/specialist system prompt 只注入有序轻量 equipment list，正文经 `load_skill_methodology` 工具进入 messages。
- 派活时冻结 equipment snapshot，in-flight 执行不受后续装备变化影响。
- Supersede、编辑、soft-delete 和 equipment transfer 使用单事务；方法论和 equipment history 均不物理删除。
- `create_skill_methodology` 由 Assistant 调度并按 specialist whitelist 授权；`system_bootstrap` 链根有默认装备和编辑/删除保护。

### Frontend And Events

- `SkillMethodologyScreen`：active list、排序/筛选、详情/编辑、版本链、equipment audit、bootstrap status。
- `SpecialistScreen`：Assistant 固定装备卡和 specialist equipment panels，含 token meter、tool warning、排序。
- Blinker: `brain_skill_changed`、`brain_skill_equipment_changed`、`brain_skill_supersede_completed`、fallback signal。
- UI events: `skill.changed`、`skill.equipment.changed`；Tool 域唯一事件为 `tools.changed`。

### Testing

- 26 项 success criteria 映射到 Repository/business/integration/guardrail/frontend tests。
- 重点覆盖 no physical delete、origin enum、supersede atomicity、frozen snapshot、body 不进 prompt、load/reference count、terminology/event rename。
- Feature tasks: 79/79 completed。

---

## AgentLoop 并行工具执行 [Source: specs/017-parallel-tool-execution]

**Revision note (2026-06-15)**: Backfilled 017.

- `ToolDefinition.is_concurrency_safe` 保守默认 false。
- AgentLoop 将连续 safe calls 分组到最多 4-worker 的 `ThreadPoolExecutor`，并复制 `contextvars`。
- Handler/hook/output governance 在 worker 执行；message persistence 和 activity emission 在 caller thread 按模型顺序完成。
- 并发读取失败不触发 sibling cancellation 或串行 cascade；side-effect tools 保持原有 `not_executed` 级联。
- 只有审查后的 immutable/read-only tools opt-in；`get_tool_detail`、`load_skill_methodology`、process、用户工具、写入/执行/委派保持串行。
- Verification: `tests/integration/test_agent_loop_parallel_tools.py` 及既有 AgentLoop/hook/cancellation/output suites。
- Feature tasks: 12/12 completed。

---

## Assistant 失败消息重试与恢复 [Source: specs/018-assistant-failed-message-retry]

**Revision note (2026-06-15)**: Backfilled 018.

### Data And Business

- v14 `assistant_run_failures` + `AssistantRunFailureRepository`。
- `AssistantFailureClassifier` 只输出 allowlisted category/message/suggestion。
- `AssistantFailureService` 管理 `failed -> retrying -> resolved|failed`、atomic retry claim 和 startup recovery。
- Message repository 提供按 session/sequence 读取原 user text 和 failure projection。

### Runtime And API

- Terminal failure 先持久化/发布 display messages，再发布 failed progress。
- `POST /api/assistant/sessions/{sessionId}/retry` 支持原样或编辑后新回合重试。
- 普通新消息会 supersede 旧 failure；成功重试通过权威 messages 移除卡片。
- Debug action 按 session 打开隐藏 inspector；未预先 arm trace 时显示历史 raw detail unavailable。

### Frontend And Testing

- `AssistantFailureCard` 内联显示 retry/edit/debug；提交期间锁定，API 失败后恢复。
- Store 不从 `lastError`/progress 猜失败，resync 后重拉 messages。
- Repository/migration/classifier/runtime/API/event、React unit 和 Playwright E2E 覆盖。
- Feature tasks: 31/31 completed。

---

## 结构化多选澄清 [Source: specs/019-structured-user-clarification]

**Revision note (2026-06-15)**: Backfilled 019; automated implementation is complete, while the
manual quickstart smoke checklist remains open.

### Runtime Design

- `clarification_manager.py` 使用 `request_id + threading.Event + lock + first-decision-wins` 管理 per-session pending。
- `ask_user_question` 是主助理专属、非中断、需独占调用的阻塞工具；solo 返回后继续同一 AgentLoop。
- 混批时 AgentLoop 对全批零执行并写 `invalid_model_output`。
- 默认 5 分钟超时；cancel/stop/shutdown/unavailable 均返回明确终态，不提供猜测答案。

### API, Events, Frontend

- GET pending snapshot + POST decision，沿用 sidecar auth 并校验 session ownership。
- UI Registry: `assistant.clarification_requested` / `assistant.clarification_resolved`，resolved 不含答案。
- `ClarificationCard` 使用 fieldset/radio/checkbox/other text，按 session 保存内存 draft/submitting。
- SSE disconnect 不结算请求；replay 或 pending snapshot 恢复卡片。
- 与 confirmation manager/Toast 完全独立，无数据库、migration 或配置。

### Testing

- Manager、exclusive batch、API、integration flow、tool scope、UI card、E2E 和 confirmation regression。
- Feature tasks: 47/48 completed；T048 手工 quickstart smoke 未勾选。

---

## 工具目录渐进式延迟加载 [Source: specs/021-tool-catalog-deferred-loading]

**Revision note (2026-06-15)**: Archived the merged 021 implementation.

### Runtime Design

- `src/business/agents/tools/capability_catalog.py` 提供共享的 `CapabilityCatalogItem`、`CapabilityDiscoveryPolicy`、完整/deferred Prompt 渲染、确定性相关度排序和 offset 分页。
- `AssistantPromptBuilder.format_capability_catalog()` 从 Repository/Service 读取发布能力，在 Agent 授权过滤后决定 `empty|full|deferred` 模式；主助理、临时子代理和固定专员统一使用该路径。
- 小目录注入名称和描述；超过 20 项或完整候选超过 6000 字符时只注入技能/组合统计和 `search_tools` / `get_tool_detail` 说明。
- `DynamicToolManager.search_tools()` 每次调用重新读取当前发布目录并校验工具、组合、成员和 Agent 白名单；返回 JSON 分页和 `技能:<name>` / `技能组合:<name>` selector。
- `get_tool_detail` 继续负责按需激活 FC schema 和现有 LRU；搜索使用局部锁保护共享 Repository/Service 会话，并保持 `is_concurrency_safe=True`。

### Configuration

`agent_tools.discovery.*` 由 `UnifiedConfigManager` 管理，不进入 Settings UI：

| Key | Default | Bound / Effect |
|-----|---------|----------------|
| `full_catalog_max_items` | 20 | 1..1000；完整目录条目上限 |
| `full_catalog_max_chars` | 6000 | 500..100000；完整候选字符上限 |
| `search_default_limit` | 10 | 1..`search_max_limit` |
| `search_max_limit` | 25 | 1..100 |
| `result_description_max_chars` | 500 | 50..5000 |

配置在每次 Prompt 构建和搜索时读取，因此运行时覆盖无需重启即可生效。无新增 secret、schema、migration、UI/API 或事件。

### Testing

- `tests/business/agents/test_capability_catalog.py`：双阈值、100 项隐藏/有界 Prompt、空目录、排序、selector、分页、描述截断和非法参数。
- `tests/test_skill_composition_regressions.py`：浏览/旧 query 兼容、组合授权、状态失效、非法参数不改变激活状态和详情激活。
- `tests/integration/test_agent_orchestrator_architecture.py`：三类 Agent 接线、授权隔离、运行时阈值和日志不泄漏。
- `tests/data/test_unified_config.py`：默认值、边界、非法值和嵌套配置。
- `tests/integration/test_agent_loop_parallel_tools.py`：`search_tools` 并发安全、`get_tool_detail` 串行声明。
- Clarify 因无 `NEEDS CLARIFICATION` 或范围未决项而跳过；归档前补跑 Analyze/Verify，14/14 FR、18/18 tasks 和宪法检查无发现。
- 最终全量验证为 1474 passed、3 skipped、5 个已在未修改基线复现的既有失败；功能相关测试、Black、Flake8 和 diff check 通过。
- Feature tasks: 18/18 completed。

---

## 子进程事件推送 [Source: specs/022-process-event-push]

**Revision note (2026-06-15)**: 022 process-event-push 落地;为 subagent / specialist 提供低延迟"等事件、有进展叫我"能力,替代循环 poll。事件机制完全内嵌于 ProcessManager,不抽通用 event bus、不进 UI Event Registry、不持久化。

### Modified Components

- `src/execution/process_manager.py`(+约 140 行,核心扩展):
  - 新增 `ProcessEvent` frozen dataclass(sequence / type / payload)。
  - `ProcessRecord` 加 7 个字段:`events`(有界 deque)、`event_sequence`、`event_condition`(共享 `_lock` 的 `threading.Condition`)、`last_output_at`、`last_chunk_announce`、`total_output_chars`、`last_stalled_announce_output_at`,以及 closure 用的 `_chunk_threshold_chars`。
  - `ProcessManager.start()` 内显式初始化 condition、events deque(从配置取 maxlen)、`last_output_at = started_at`。
  - 新增 `_emit_event_locked`、`wait_for_event`、`_refresh_locked_with_emit`、`_maybe_emit_stalled_locked`、`_compute_cursor`、`_build_wait_result`、`_load_event_config`(便于测试 monkeypatch)。
  - `_start_reader.reader` 内累加字符 + emit log_chunked(顺序:先存 delta、再推基线、再 emit)。
  - `stop()` 的 terminated 分支显式 emit state_changed。`close()` 路径不触发事件。
- `src/business/agents/tools/command_tools.py`(+约 35 行):新增 `wait_for_process_event_handler`,复用 `_process_for_current_session` 归属校验 + `get_config_int` 钳位 timeoutMs + 内部异常映射到 `internal_error`(沿用 ERROR_CODES 注册表)。
- `src/business/agents/tools/builtin_general_tools.py`(+约 20 行):新增 `WAIT_FOR_PROCESS_EVENT_SCHEMA` + `ToolDefinition`(**未**标记 `is_concurrency_safe`,沿用 process_* 系列约束)。
- `src/data/config_models.py`:`AgentToolsProcessConfig` 加三字段 `event_buffer_size=64`、`stalled_threshold_ms=10000`、`chunk_threshold_chars=4096`。
- `src/data/unified_config.py`:加三个 getter `get_agent_tools_process_event_buffer_size`(上限 512)、`get_agent_tools_process_stalled_threshold_ms`(上限 600000)、`get_agent_tools_process_chunk_threshold_chars`(上限 65536),沿用 `_get_bounded_positive_int` 模式。

### Configuration

| Key | Default | Bound |
|-----|---------|-------|
| `agent_tools.process.event_buffer_size` | 64 | 1..512 |
| `agent_tools.process.stalled_threshold_ms` | 10000 | 1..600000 |
| `agent_tools.process.chunk_threshold_chars` | 4096 | 1..65536 |

均通过 `UnifiedConfigManager` 读取,默认值随代码下发,SQLite `app_settings` 可覆盖,Settings UI 暂不暴露。无新增 secret / schema / migration / UI 事件。

### Testing

- `tests/execution/test_process_manager_events.py`(新建,16 个测试):覆盖 `_emit_event_locked` 单调 + 环形覆盖、cursorTooOld 续 cursor、空队列 cursor=event_sequence、state_changed completed/failed、wait 立即返回/超时/200 ms 唤醒断言(SC-162)、log_chunked 阈值/复位/无原文 payload、stalled 懒判定/不刷屏/纯静默/仅 running。
- `tests/business/agents/test_process_event_tool.py`(新建,6 个测试):覆盖归属 permission_denied、process_missing、timeoutMs 钳位、default_timeout 接线、cursorTooOld 时 cursor 字段保留、内部异常 → `internal_error`。
- `tests/integration/test_process_event_flow.py`(新建,3 个测试):走工具入口起真子进程,验证 state_changed end-to-end、log_chunked + process_logs 链路、典型 7 步交互(log_chunked → process_logs → 终态)。
- 既有 `tests/integration/test_agent_builtin_process_lifecycle.py`(process_poll / logs / wait / stop / send_input)零回归;`tests/business/agents/test_builtin_command_tools.py` / `test_builtin_general_tools.py` 零回归;guardrails 103 全过。
- 22 步 speckit 流程含 clarify 两条契约边界澄清(cursor 续约 / 纯静默 stalled)和 analyze 两条 medium 修订(SC-001 200 ms 显式断言、log_chunked delta 计算顺序)。
- Feature tasks: 28/28 completed。
