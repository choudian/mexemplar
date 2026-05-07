---

description: "Tasks for 桌面录制 Phase 1"
---

# Tasks: 桌面录制 Phase 1

**Input**: Design documents from `/specs/007-desktop-recording/`
**Prerequisites**: plan.md (✅), spec.md (✅, 8 轮 ≈ 40 条 Q&A), research.md (✅), data-model.md (✅), contracts/ (✅, 5 文件), quickstart.md (✅)

**Tests**: Constitution Principle IV（可验证交付）+ plan.md Constitution Check 已显式列出每条 FR 对应的单元/集成/门卫测试，本任务列表 INCLUDE 测试任务（不是可选）。

**Organization**: 按 spec.md 4 个 user story 分相分组（US1 + US2 = P1 / US3 = P2 / US4 = P3）。

## Constitution-Driven Minimums

- ✅ Repository / data tasks：`src/data/recording_repository.py` 桌面 DuckDB 表 schema + 代码默认值修正（不改 SQLite schema default）；
- ✅ Filtered DuckDB boundary：`src/recording/filtering/sql_rewriter.py` + `decision.py` mode allowlist；
- ✅ Configuration / keyring：`src/data/config_models.py` + `src/data/unified_config.py` + `config.example.json` + `config.example.comments.md`；
- ✅ Wiring smoke + guard tests：`tests/integration/test_desktop_browser_path_byte_equal.py`（SC-005 门卫）+ `tests/integration/test_desktop_tools_mode_dispatch.py`（链路冒烟）+ `tests/integration/test_browser_prompts_guard.py`（SC-006 行为级）；
- ✅ Active doc updates：`docs/ARCHITECTURE.md` + `docs/PROJECT_CONSTRAINTS.md` + `AGENTS.md` + `CLAUDE.md`。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel（不同文件、无未完成任务依赖）
- **[Story]**: 所属 user story（US1 / US2 / US3 / US4）
- 文件路径全部是 repo-relative

## Project Paths

- **Source**: `src/`（business / data / recording / execution / ui / utils）
- **Tests**: `tests/`（mirrors src/）
- **Test runner**: `uv run pytest tests/`
- **Formatter**: `uv run black src/ tests/`
- **Linter**: `uv run flake8 src/ tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 项目级配置与依赖

- [X] T001 创建 `src/recording/desktop/dpi_awareness.py`，封装 `apply()` 调用 `ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)` 启用 Per-Monitor V2 DPI awareness；函数需在非 Windows 或 API 不可用时返回降级结果而非导入期崩溃（FR-006）
- [X] T002 [P] 在 `pyproject.toml` 添加或验证桌面录制依赖：`pynput`、`mss`、`opencv-python`、`Pillow`、`comtypes`、`pywinauto`、`pywin32`
- [X] T003 [P] 在 `config.example.json` + `config.example.comments.md` 添加 `recording.desktop.enable_clip`（默认 `true`）+ `recording.desktop.vision_model`（无默认）两条配置项及说明文本

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 阻塞所有 user story 的核心基建——DuckDB schema + Repository default 修正 + Service 薄封装。

**⚠️ CRITICAL**: 完成本阶段后才能进入任一 user story。

- [X] T004 修正 `src/data/config_models.py:176` 把 `default_recording_mode = "desktop"` 改为 `"browser"`；并在 `src/data/config_models.py` 新增/接线 `RecordingDesktopConfig(enable_clip=True, vision_model=None)` 到现有 recording config 模型（FR-010 / FR-026 / FR-026a）
- [X] T005 [P] 修正 `src/ui/widgets/recording_widget.py:459` 把 `fallback=BROWSER`（FR-010 UI 侧）
- [X] T006 修正 `src/data/recording_repository.py` 的 `save_recording_session()` 代码参数 default `"desktop"` → `"browser"` 或改为必填；不修改 SQLite schema default（FR-009）
- [X] T007 在 `src/data/recording_repository.py` 添加 `ensure_desktop_tables()` 方法创建 `desktop_recordings` 与 `desktop_actions` 两张 DuckDB 表（schema 见 `data-model.md` §1.1 / §1.2，含 `monitor_index INTEGER NOT NULL` 列与 `(recording_id, timestamp)` / `(recording_id, type)` 复合索引）
- [X] T008 在 `src/data/recording_repository.py` 添加桌面表的 insert / get / list 方法：`insert_desktop_recording` / `update_desktop_recording_status` / `update_desktop_recording_health_stats` / `get_desktop_recording_meta` / `insert_desktop_action` / `list_desktop_actions`；并新增唯一 mode 查询入口 `get_recording_mode(recording_id)`（先查 `recording_sessions.recording_mode`，未命中再查 `desktop_recordings.recording_mode`，两表均未命中返回标准化 `recording_not_found` 错误）（FR-007 / FR-008 / FR-012，按 data-model.md §1.2 / §5 字段集）
- [X] T009 [P] 创建 `src/business/services/desktop_recording_service.py` 提供 UI 层访问点 `start_after_minimize(recording_id)` / `get_health_stats(recording_id) -> HealthStats` / `stop(recording_id)` / `mark_abandoned(recording_id)` / `mark_stopped(recording_id)`（UI 通过 Service / business bridge 间接启动 Recorder、读取 Repository，Constitution Principle I）
- [X] T010 [P] 在 `src/data/unified_config.py` 暴露 `recording.desktop.enable_clip` / `recording.desktop.vision_model` 两个字段读写（接入 `UnifiedConfigManager`）
- [X] T010a [P] `tests/data/test_recording_desktop_config.py` 配置模型/统一配置单测：缺失 `recording.desktop` 时默认 `enable_clip=True` / `vision_model=None`；配置文件含字段时 round-trip 读写正确；示例配置字段与 `config_models.py` 模型字段保持一致（Constitution Principle III）
- [X] T011 在 `src/data/recording_repository.py` 的 `ensure_startup_recovery()` 中追加扫描 `data/trials/` 子目录、mtime > 7 天 `shutil.rmtree` 的 cleanup 逻辑（FR-021a + spec round 6 第 2 题）
- [X] T011a [P] 创建 `src/business/utils/high_risk_api_detector.py` 提供共享函数 `detect_high_risk_apis(code: str) -> list[str]`，用 `ast` 静态扫描识别 6 项命中规则（subprocess 模块导入或 attr 调用 / `os.startfile` / `webbrowser` 模块 / Win32 协议 URL 字符串字面量含 URL-like `<scheme>:` 模式但排除 Windows 盘符路径如 `C:\foo` / `pywin32` 高级 API import 或调用，限定 `win32api`、`win32gui`、`win32com`、`win32process`、`win32service`、`win32clipboard`、`pythoncom` 等模块 / `pywinauto` 控件级 API 如 `pywinauto.Application`）；返回命中标签字符串列表（如 `["subprocess", "pywinauto"]`），空列表表示无命中；**FR-021 事前对话框（T073）+ SC-004 捷径判定（T088）+ 单测（T066）三处共用此 detector，不允许独立实现避免规则漂移**
- [X] T011b [P] `tests/business/test_high_risk_api_detector.py` 单测覆盖 6 项命中规则各自 fixture（含命中 / 不命中 / 边界 case），含"纯 pyautogui 坐标点击循环不算捷径"、Windows 盘符路径 `C:\foo\bar.txt` 不算 Win32 协议 URL、`wechat:` / `mailto:` 算 Win32 协议 URL三类反例/正例 fixture
- [X] T011c [P] 在 `src/utils/events.py` 新增桌面录制跨模块 blinker 事件并导出：`desktop_action_count_changed` / `desktop_recorder_start_failed` / `desktop_recording_degraded` / `desktop_syntax_gate_retry_failed` / `desktop_trial_preview_ready` / `desktop_trial_finished`；复用既有 `recording_started` / `recording_stopped` 表达录制生命周期；UI 侧后续通过本地 Qt bridge 切回 UI 线程，业务 / recording / Trial 层不得直接 import UI widget 或发跨模块 Qt signal（Constitution Principle I）

**Checkpoint**: Foundation 就绪——4 个 user story 现可并行启动。

---

## Phase 3: User Story 1 - 录制桌面操作并产出可分析数据 (Priority: P1) 🎯 MVP

**Goal**: 用户在录制页选"桌面"模式 → hook 在主窗 minimize 完成回调后启动 → 实时落 `desktop_actions` 行 + 帧/clip/剪贴板图 → 用户停止 → restore 主窗 → 弹基础 sanity check 对话框 → 点"继续分析"进入 intent 页。颜色判定、"放弃录制"、"重新录制"增强行为由 US4 补齐。

**Independent Test**: 跑通"开始录制 → 在记事本完成 5 个动作 → 停止 → 健康对话框显示动作总数 ≥ 5 → 点'继续分析'进入 intent 页"。US1 不校验颜色、不校验 Agent 多模态回答。

### Tests for User Story 1

- [X] T012 [P] [US1] `desktop_recordings` / `desktop_actions` schema + insert / query 单测，含 `monitor_index` 列、`status` 三态 CHECK、`(recording_id, timestamp)` / `(recording_id, type)` 复合索引存在断言；补充 `desktop_actions.clipboard_text` / `text_content` 超 `recording.large_field.threshold_chars` 时走既有 large_field 占位、短文本原样返回的断言（`tests/data/test_recording_repository_desktop.py`）
- [X] T013 [P] [US1] pynput hook 抓取 + typing/hotkey 归类规则（含 Ctrl/Alt/Win → hotkey、Shift+letter / IME 候选 → typing、功能键 / 方向键 → hotkey）单测（`tests/recording/test_desktop_pynput_hook.py`）
- [X] T014 [P] [US1] UIA `ElementFromPoint` 50ms 同步 + 超时排进异步队列、UIA COM 初始化失败降级、`window_title` 从 owning window 溯源（不调 `GetForegroundWindow`）单测（`tests/recording/test_desktop_uia_querier.py`）
- [X] T015 [P] [US1] `WM_CLIPBOARDUPDATE` 订阅 + 500ms 兜底 + Ctrl+V 立即读、CF_UNICODETEXT 文本快照、`clipboard/<recording_id>_<event_seq>.png` 命名 event_seq 自增、`_ClipboardLatest` 引用快照（含最新文本 + 最新图片路径）、订阅失败降级单测（`tests/recording/test_desktop_clipboard_watcher.py`）
- [X] T016 [P] [US1] `_FrameRingBuffer` 30 帧 FIFO + 前 1s 后 2s 取 45 帧、首动作 buffer 不足时取所有可用帧不补帧单测（`tests/recording/test_desktop_frame_ring_buffer.py`）
- [X] T017 [P] [US1] PNG sink 原生分辨率 + compress_level=6 落盘、clip sink opencv-python mp4v 编码失败 `has_clip=FALSE` / `clip_total++` / `clip_success` 不变、`enable_clip=false` 不编码单测（`tests/recording/test_desktop_sinks.py`）
- [X] T018 [P] [US1] DesktopRecorder lifecycle 集成测试：`uia_total/uia_hit` 仅累加鼠标类、typing/hotkey 不计入；停止时 `health_stats` 一次性 UPDATE 写入 `desktop_recordings.health_stats`；`recording → stopped` / `recording → abandoned` 状态转移（`tests/integration/test_desktop_recorder_lifecycle.py`）
- [X] T019 [P] [US1] minimize 后启动时机集成测试：点开始 → `showMinimized()` → `changeEvent` minimize 跃迁回调后才启动 `DesktopRecorder.start()` 及其 hook / ring buffer / UIA 异步队列 / 剪贴板订阅关键子系统；回调前任一子系统 MUST NOT 启动，且"点开始"按钮 click MUST NOT 落到 `desktop_actions`（`tests/ui/test_desktop_hook_start_after_minimize.py`）
- [X] T019a [P] [US1] 基础 sanity check "继续分析"路径 UI 测试：停止录制后 dialog 通过 `DesktopRecordingService.get_health_stats()` 展示动作总数，点"继续分析"调用 `mark_stopped(recording_id)` 并进入 intent 页；不测试颜色与放弃/重录按钮（`tests/ui/test_desktop_basic_continue_analysis.py`）
- [X] T020 [P] [US1] drag 类型 `coord_x/coord_y/timestamp` 取 mouse_up 终点 + UIA 查询 up 点 + `monitor_index` 取 up 终点屏单测（`tests/recording/test_desktop_drag_semantics.py`）
- [X] T021 [P] [US1] typing 序列切片规则（停字 1s / 切非字符键 / 切窗口 / 鼠标动作任一先到结束）单测（`tests/recording/test_desktop_typing_segmentation.py`）

### Implementation for User Story 1

- [X] T022 [US1] 在 `src/main.py` 进程启动期（`get_unified_config()` 之前、`QGuiApplication` 创建之前）调用 T001 的 `src.recording.desktop.dpi_awareness.apply()`；记录降级日志但不阻塞非 Windows 启动（FR-006）
- [X] T023 [P] [US1] pynput hook 抓取 + typing/hotkey 归类（`src/recording/desktop/pynput_hook.py`），抓鼠标左/右/中/滚轮/拖拽 + 键盘 typing/hotkey；hook 注册失败抛 `RecorderStartFailed("hook_register_failed")`；不抓鼠标移动
- [X] T024 [P] [US1] UIA querier `ElementFromPoint(50ms)` 同步 + 异步队列 UPDATE + `window_title` owning window 溯源（`src/recording/desktop/uia_querier.py`）
- [X] T025 [P] [US1] clipboard_watcher `AddClipboardFormatListener` 订阅 + 500ms QTimer 兜底 + Ctrl+V hook 内立即读 + CF_UNICODETEXT 文本快照 + `clipboard/<recording_id>_<event_seq>.png` 命名 + `_ClipboardLatest` 引用（同时保存最新文本与最新图片路径，供 DesktopRecorder 写入 `desktop_actions.clipboard_text` / `clipboard_image_path`）（`src/recording/desktop/clipboard_watcher.py`）
- [X] T026 [P] [US1] `_FrameRingBuffer` 15 fps + 30 帧固定容量 + FIFO + 前 1s 后 2s 取 45 帧 + 不足时取所有可用（`src/recording/desktop/frame_ring_buffer.py`）
- [X] T027 [P] [US1] PNG sink Pillow `Image.save(path, "PNG", compress_level=6)` 原生分辨率落 `data/recordings/<recording_id>/frames/<action_id>/`（`src/recording/desktop/png_sink.py`）
- [X] T028 [P] [US1] clip sink opencv-python `cv2.VideoWriter` mp4v 落 `data/recordings/<recording_id>/clips/<action_id>.mp4`，受 `recording.desktop.enable_clip` 开关控制；编码失败 `has_clip=FALSE` / `clip_total++` / `clip_success` 不变（`src/recording/desktop/clip_sink.py`）
- [X] T029 [P] [US1] hotkey_register Ctrl+Alt+S 全局热键 + 注册失败返回标准化降级结果（如 `HotkeyRegistrationResult(ok=False, reason="hotkey_register_failed")`）给 `DesktopRecorder`；由 T030 统一通过 `desktop_recording_degraded` blinker 事件通知 UI，禁止新增跨模块 Qt signal（`src/recording/desktop/hotkey_register.py`）
- [X] T030 [US1] DesktopRecorder 顶层（`src/recording/desktop_recorder.py`）：聚合 T023-T029 子组件，暴露 `start()` / `stop()` / `get_action_count()`，维护 in-memory health_stats counter（`uia_hit` / `uia_total` / `clip_success` / `clip_total` / `clipboard_event_count` / `action_type_counts`）；插入 action 前按既有 large_field 规则处理 `clipboard_text` / `text_content` / `uia_summary` 长字段，停止时一次性序列化 JSON 调 `update_desktop_recording_health_stats`；跨模块通知通过 `src/utils/events.py` 发 blinker 事件：动作计数变更发 `desktop_action_count_changed`，停止发既有 `recording_stopped`，pynput hook 阻塞失败发 `desktop_recorder_start_failed`，UIA / 剪贴板 / Ctrl+Alt+S 降级发 `desktop_recording_degraded`（依赖 T007-T011c, T023-T029）
- [X] T031 [US1] 修正 `src/ui/mixins/recording_mixin.py:_on_recording_started` 桌面分支：去除"暂不支持"，通过 `DesktopRecordingService` / business bridge 路由到 `DesktopRecorder.start()`；UI 层不直接实例化 Recorder（FR-001）
- [ ] T032 [US1] `src/ui/widgets/recording_widget.py` 改造：点"开始"后保存主窗 geometry/state → `showMinimized()` → 安装 `eventFilter` 监听 `WindowStateChange` minimize 跃迁 → 跃迁后调用 `DesktopRecordingService.start_after_minimize(recording_id)` 启动业务侧 DesktopRecorder + 显示浮窗（FR-022 + spec round 7 第 3 题）
- [X] T033 [P] [US1] 录制态浮窗 `RecordingFloatingWidget`（`src/ui/widgets/recording_floating_widget.py`）：100×40 px、右下角默认、`Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint`、可拖、显示"🔴 录制中 N 个动作 [停止]"、停止按钮 emit `stopRequested` signal
- [ ] T034 [US1] `src/ui/widgets/recording_widget.py` 续：UI 本地事件 bridge 订阅 `recording_stopped` blinker 事件并切回 UI 线程，录制停止后执行 `showNormal()` + `restoreGeometry()` + `setWindowState()` 还原主窗几何与状态，并弹出基础 `DesktopSanityCheckDialog`；dialog 通过 `DesktopRecordingService.get_health_stats(recording_id)` 读 `health_stats`，展示动作总数等基础指标，"继续分析"调用 `mark_stopped(recording_id)` 并跳 intent 页（FR-022 + FR-024 P1 子集）
- [ ] T035 [P] [US1] 录制启动失败的弹错对话框 / 降级 toast 路径：pynput hook 注册失败弹错对话框阻塞启动；UIA COM / 剪贴板订阅 / Ctrl+Alt+S 失败 → 一次性 toast 不阻塞（FR-002 / FR-003 / FR-004 / FR-023）
- [X] T036 [US1] `src/recording/desktop_recorder.py` 接入互斥判定：基于 in-memory active recorder state（不查 DB），三模式两两互斥（FR-025 业务层）
- [ ] T036a [US1] `src/ui/widgets/recording_widget.py` UI 侧防呆：在浏览器/扩展触发录制中时，桌面卡片 `setEnabled(False)` + tooltip 提示"已有其他模式录制中"；与 T036 业务层拒绝构成 FR-025 + Acceptance Scenario 4 "UI 禁用 + 程序拒绝双保险"
- [ ] T036b [P] [US1] `tests/ui/test_desktop_card_disabled_when_other_recording_active.py` UI 侧防呆单测：mock 浏览器 recorder 处于 active 状态 → 桌面卡片 `isEnabled()` 为 False；mock 全部 idle → 桌面卡片 `isEnabled()` 为 True

**Checkpoint**: US1 独立可用——录制 + 数据落盘 + 主窗 minimize/restore + 浮窗 + 三模式互斥（业务 + UI 双保险）全链路通；sanity check 基础展示 + "继续分析"进入 intent 页可用。颜色判定、"放弃录制"、"重新录制"由 US4 完成。

---

## Phase 4: User Story 2 - Agent 用多模态分析桌面录制 (Priority: P1)

**Goal**: 5 通用工具按 `recording_mode` 内部切表 + 3 桌面专属工具（`list_desktop_actions` / `analyze_desktop_action` / `read_action_clip`）通过独立工厂注入桌面 PM/Programmer/Trial 工具集；PM/Programmer 双轨 prompt + ast.parse syntax gate + 自动反馈重试；浏览器路径 byte-equal。

**Independent Test**: 用 US1 产出的桌面 fixture（5 个动作以上、含 1 个剪贴板复制）跑 PM Agent，验证：① `list_desktop_actions` 列出动作；② `analyze_desktop_action` 拿到画面文本结论；③ Agent 生成可执行 intent；④ 浏览器 fixture 上 5 通用工具 canonical JSON byte-equal（SC-005 门卫不变量）。

### Tests for User Story 2

- [X] T037 [P] [US2] 浏览器 mode 5 通用工具 canonical JSON baseline 字节级 byte-equal 门卫（SC-005 不变量 1-7），并追加 `recording_data_tools.py` 不直接 import `sqlglot` 的 AST/import 门卫（CC-002 #5）（`tests/integration/test_desktop_browser_path_byte_equal.py`）
- [X] T038 [P] [US2] 5 通用工具 mode dispatch 链路冒烟：浏览器 mode 走现有 5 张表、桌面 mode 走 `desktop_recordings` / `desktop_actions`；跨 mode 表访问 sqlglot security gate 拒绝并返回 `{"error": "table_not_in_mode", "table": "<name>", "mode": "<current_mode>"}`；`read_field_chunk("desktop_actions.<column>.<action_id>")` 在桌面 mode 可读取 `text_content` / `clipboard_text` / `uia_summary` 长字段 chunk，浏览器 mode 拒绝该 stable locator（FR-011 + FR-012a）（`tests/integration/test_desktop_tools_mode_dispatch.py`）
- [X] T039 [P] [US2] sql_rewriter mode allowlist 双向严格隔离单测：浏览器 mode allowlist 屏蔽桌面 2 张表、桌面 mode allowlist 屏蔽浏览器 5 张表、mode 内两表 JOIN 允许（`tests/recording/filtering/test_mode_allowlist.py`）
- [X] T040 [P] [US2] `read_recording` 桌面 mode 聚合摘要 schema 断言：返回 `desktop_recordings` 行（含 `health_stats`）+ 动作总数 + type 分组计数 + window_title 前 5 + 时间范围 + 首尾节点（前 5 + 后 5 共 ≤10 行）；MUST NOT 返回中段动作（`tests/integration/test_desktop_read_recording.py`）
- [X] T041 [P] [US2] `list_desktop_actions` 输入参数校验：`action_types` 元素不在 7 枚举集 → `{"error": "invalid_action_type", "value": "<x>"}`；`limit > 500` → 错误；翻页正确（`tests/integration/test_list_desktop_actions.py`）
- [ ] T042 [P] [US2] `analyze_desktop_action` 多模态消息组装顺序 mock 断言：mock vision LLM 拦截 payload；断言 typing 文本前缀（`Action <id> 用户输入文本: <text>`）→ 剪贴板图前缀（`Action <id> 剪贴板图...`）→ 帧序列（`Action <id> 帧 N/M (T={t}ms ...)`）→ question 末尾；多 action 间用 `--- Action <prev_id> 帧序列结束 / Action <next_id> 开始 ---` 分隔；缩放仅缩小语义（< 1280 不放大）；失败段拼接 `[error: <reason_code>]`；`action_ids` ≤ 2 上限（`tests/integration/test_analyze_desktop_action.py`）
- [X] T043 [P] [US2] `read_action_clip` `has_clip=FALSE` 时返回 `{"error": "clip_unavailable", "action_id": "<id>"}`；正常时 mp4 路径与元数据（`tests/integration/test_read_action_clip.py`）
- [X] T044 [P] [US2] `build_pm_prompt(mode)` / `build_programmer_prompt(mode)` 双轨：浏览器 mode 返回 LEGACY identity；桌面 mode 三段拼接分别含 `_PM_DESKTOP_GUIDANCE` 关键短语（"按 window_title 聚焦"等）与 `_PROGRAMMER_DESKTOP_GUIDANCE` 契约短语（`async def execute() -> dict` 等）（`tests/integration/test_desktop_prompts.py`）
- [X] T045 [P] [US2] 浏览器 PM/Programmer prompt 行为级守卫测试关键短语断言不退化（SC-006）（`tests/integration/test_browser_prompts_guard.py`）
- [X] T046 [P] [US2] ast.parse syntax gate + 自动反馈重试单测：合法代码一次通过；一次语法错二次通过；连续 3 次语法错触发终态失败 + UI Toast；反馈消息模板渲染断言（含 `lineno` / `msg` / 上下 2 行片段、不暴露 `offset` / `filename`）（`tests/integration/test_desktop_syntax_gate.py`）
- [X] T047 [P] [US2] `vision_model` 未配置 → `analyze_desktop_action` 不注入桌面 PM/Programmer/Trial 工具集（其余两工具仍可用）（`tests/integration/test_vision_model_gating.py`）
- [ ] T047a [P] [US2] 工具集 composition 门卫测试：桌面 PM/Programmer/Trial 工具集 = 5 通用工具 mode dispatch + 3 桌面专属工具、且 MUST NOT 注入 `analyze_image`；浏览器 PM/Programmer/Trial 保留浏览器现行工具集与 `analyze_image`，且 MUST NOT 注入 3 桌面专属工具；**追加断言**：`analyze_desktop_action` handler 构造的 LLM client 路径与 `analyze_image` handler 共用同一 factory 函数（provider routing 复用验证，FR-026a）（`tests/integration/test_desktop_toolset_composition.py`）
- [ ] T047b [P] [US2] PM Agent 桌面 fixture 半集成测试：用 5 个以上动作且含剪贴板事件的桌面录制 fixture 跑 PM Agent 到 intent 输出，断言其可调用 `list_desktop_actions`、按需调用 `analyze_desktop_action` mock，并最终进入 `talk_to_user` 终态生成可执行 intent（`tests/integration/test_desktop_pm_agent_intent.py`）

### Implementation for User Story 2

- [X] T048 [US2] 改造 `src/business/agents/tools/recording_data_tools.py` `create_recording_tools(recording_id)` 工厂：启动时通过 `RecordingRepository.get_recording_mode(recording_id)` 一次查 mode（浏览器查 `recording_sessions`，桌面查 `desktop_recordings`，均未命中返回 `recording_not_found`）→ 闭包传给 5 个 handler 与 `query_data_pre_hook`；5 个 handler 内部按 mode 切表（FR-011 + FR-012）
- [X] T049 [US2] 改造 `src/recording/filtering/sql_rewriter.py` 新增 `validate_table_against_mode_allowlist(sql, mode)` 接口（依赖 sqlglot 列血缘分析）+ `src/recording/filtering/decision.py` 新增 mode 隔离 allowlist 表，跨 mode 触及返回 `table_not_in_mode` 标准化错误（FR-012a）
- [X] T050 [US2] 创建 `src/business/agents/tools/desktop_tools.py` 工厂 `create_desktop_specific_tools(recording_id)` + `list_desktop_actions` handler（含枚举校验 + `limit` 上限 500）
- [ ] T051 [US2] `analyze_desktop_action` handler（`src/business/agents/tools/desktop_tools.py`）：多模态消息组装（按 contracts/desktop_specific_tools.md §2 顺序）+ PNG 缩放 `Image.thumbnail((1280,1280), LANCZOS)` 仅缩小不放大 + provider routing 复用 `analyze_image` factory + `vision_model` 缺失则不注入（自然降级）+ INFO 日志（recording_id / action_ids / frames_uploaded / session 累计）+ 失败段 `[error: <reason_code>]` 拼接（`vision_timeout` / `vision_unauthorized` / `vision_failed`）
- [X] T052 [US2] `read_action_clip` handler（`src/business/agents/tools/desktop_tools.py`）：返回 mp4 路径 + duration_ms + fps + resolution；`has_clip=FALSE` 时返回 `{"error": "clip_unavailable", "action_id": "<id>"}`
- [X] T052a [US2] 改造 Orchestrator / 工具集组装入口，按以下 6 条路径逐一接线并各加断言：(1) 桌面 PM 工具集 = 5 通用工具（recording_mode 闭包切表）+ 3 桌面专属工具、MUST NOT 含 `analyze_image`；(2) 桌面 Programmer 工具集 = 同 (1)；(3) 桌面 Trial 工具集 = 同 (1)；(4) 浏览器 PM 工具集 = 现行工具集 + `analyze_image`、MUST NOT 含 3 桌面专属工具；(5) 浏览器 Programmer 工具集 = 同 (4)；(6) 浏览器 Trial 工具集 = 同 (4)（FR-014 / FR-015）
- [X] T053 [US2] 创建 `src/business/agents/prompts/desktop_prompts.py` 含 `_PM_COMMON_HEADER` / `_PM_DESKTOP_GUIDANCE`（导航策略：先看头尾 → 按 window_title 聚焦 → 跳过冗余类型 → 关键节点用 analyze_desktop_action）/ `_PM_COMMON_FOOTER` + `build_pm_prompt(mode)`；浏览器 mode 通过 `from .pm_prompt import PM_SYSTEM_PROMPT as PM_SYSTEM_PROMPT_LEGACY` 别名重导出主仓现有常量并 identity return（FR-016 + CC-003 字节级保留；不修改主仓 `pm_prompt.PM_SYSTEM_PROMPT` 常量名，别名仅在 desktop_prompts.py 内部）
- [X] T054 [US2] 在 `src/business/agents/prompts/desktop_prompts.py` 续 `_PROGRAMMER_COMMON_HEADER` / `_PROGRAMMER_DESKTOP_GUIDANCE`（含 1-2 个"找捷径"元思维例子 + `async def execute() -> dict` 强约束 + 返回 `{"ok", "summary", "details"}` 契约）/ `_PROGRAMMER_COMMON_FOOTER` + `build_programmer_prompt(mode)`（FR-020）
- [X] T055 [US2] 改造 `src/business/orchestration/agent/orchestrator.py` 启动 PM/Programmer 前分别用 `dataclasses.replace(PM_CONFIG, system_prompt=build_pm_prompt(workflow.recording_mode))` 与 `dataclasses.replace(PROGRAMMER_CONFIG, system_prompt=build_programmer_prompt(workflow.recording_mode))` 构造临时 AgentConfig 拷贝（`agent_loop.format_system_prompt()` 不改造，FR-017）
- [X] T056 [US2] 在 `src/business/agents/tools/programmer_tools.py` 的 `execution_strategy` tool schema enum 增 `desktop` 取值，并同步 `src/business/tool_trial/trial_models.py` 的 `execution_strategy` 语义注释 / 允许值（FR-018）
- [X] T057 [US2] 创建 `src/business/orchestration/agent/desktop_syntax_gate.py`：`ast.parse` syntax gate + 反馈消息模板（lineno + msg + 出错行 ± 2 行片段）+ 重试上限 2 次 + 终态失败 UI Toast 标题"Programmer 输出代码持续语法错误" + 进程日志落 3 次代码 + 反馈消息 + 原始 SyntaxError；浏览器 mode 不走 syntax gate（FR-017a）
- [X] T058 [US2] 在 `src/business/orchestration/agent/orchestrator.py` 接入 syntax gate：Programmer 输出代码后、交给 Trial 子进程前调 desktop_syntax_gate，3 次失败终态发 `desktop_syntax_gate_retry_failed` blinker 事件（UI bridge 转 toast），不发跨模块 Qt signal
- [X] T059 [US2] 改造 `src/business/agents/tools/recording_data_tools.py` 的 `read_field_chunk` handler：桌面 mode stable locator 形式扩展为 `desktop_actions.<column>.<action_id>`（与浏览器 `actions.<column>.<action_id>` 同形），并保持 `desktop_tools.py` 只承载 3 个桌面专属工具
- [ ] T059a [US2] **STOP and VALIDATE MVP**：完成 US1 + US2 后、进入 US3/US4 前，按 `quickstart.md` 5 标准场景执行 P1 漏斗验证：5/5 录制成功（`health_stats.action_type_counts` 之和 > 0，不看 sanity check 颜色）+ 5/5 进入 intent 页并给出可执行方案（PM `talk_to_user` 终态 + Programmer 代码 `ast.parse` 通过）；记录结果，未达标则先修 P1，不继续推进试用层（SC-001 / SC-002）

**Checkpoint**: US2 独立可用——5 通用工具 mode dispatch + 3 桌面工具 + 双轨 prompt + syntax gate 全链路通；浏览器路径 byte-equal 门卫不退化。

---

## Phase 5: User Story 3 - 试用 Agent 在桌面真实执行 (Priority: P2)

**Goal**: Trial 子进程隔离执行 Programmer 代码：subprocess + python -u -c wrapper + cwd `data/trials/<trial_id>/` + env 白名单 + 120s `taskkill /F /T` 整树兜底；UI 走"事前提示对话框 → 跑期间无遮挡 → 跑完普通 Toast 通知"。

**Independent Test**: 用一段记事本"打开 → 输入 'hello' → 保存"录制走完 PM → Programmer，得到一段执行代码；启动试用，观察"事前提示 → 跑期间无遮挡 → 跑完通知"流程；故意写一段死循环代码验证 120 秒 kill 兜底。

### Tests for User Story 3

- [X] T060 [P] [US3] subprocess 启动正常路径单测：简单 `execute()` 返回 `{"ok": True}` → 子进程退出码 0 + `TrialResult.exit_code == 0` + 末行 JSON 正常 + Toast "试用成功"（`tests/integration/test_desktop_trial_subprocess.py`）
- [X] T061 [P] [US3] wrapper 异常包装单测：`execute()` 抛 `ValueError("boom")` → wrapper 包成 `{"ok": False, "summary": "ValueError: boom", "details": {"traceback": ...}}` 写 stdout 末行（`tests/integration/test_desktop_trial_wrapper.py`）
- [X] T062 [P] [US3] 120s 超时 + taskkill 整树 kill 单测：`execute()` 含 `await asyncio.sleep(150)` → `Popen.terminate()` + `taskkill /F /T` → `timed_out=True` + Toast "试用超时"；含 `subprocess.Popen(["timeout", "200"])` 的孙子进程也整树 kill（`tests/integration/test_desktop_trial_timeout.py`）
- [X] T063 [P] [US3] env 白名单单测：父 env 含 `OPENAI_API_KEY=sk-xxx` → 子 env 不含；父 env 含 `MY_TOKEN_X` → 子 env 不含（大小写不敏感）；父 env 含 `PATH` → 子 env 含同值（`tests/integration/test_desktop_trial_env_whitelist.py`）
- [X] T064 [P] [US3] cwd 隔离单测：wrapper 内 `Path.cwd()` 返回 `data/trials/<trial_id>/`（`tests/integration/test_desktop_trial_cwd.py`）
- [X] T065 [P] [US3] stdout 末行无 JSON 兜底单测：wrapper 自身崩溃 → stdout 无有效 JSON → UI Toast "试用失败" + 正文 = stderr 末 5 行（截断到 ≤ 200 字符）（`tests/integration/test_desktop_trial_stdout_fallback.py`）
- [X] T066 [P] [US3] 高危 API 检测单测：代码含 `subprocess.run([...])` → 事前对话框 UI 路径调用共享 `high_risk_api_detector.detect_high_risk_apis()`（T011a）并显示 "subprocess" 标签；纯 `pyautogui` 坐标点击循环不算；本测试 MUST 通过 mock detector 验证调用而非重复实现规则（避免与 T011b 重叠）（`tests/integration/test_desktop_trial_high_risk_api.py`）
- [X] T066a [P] [US3] Trial UI 三步骤测试：事前提示对话框展示代码预览与高危 API 标签，"取消"不启动 runner，"开始"触发 business/blinker 路径；正常 `TrialResult(ok=True, exit_code=0)` 显示普通 Toast "试用成功"，失败/超时分别显示 "试用失败" / "试用超时"（`tests/ui/test_desktop_trial_dialogs.py`）
- [X] T067 [P] [US3] 7 天 cleanup 单测：mtime > 7 天的 trial 目录在 `ensure_startup_recovery()` 调用后被删除（`tests/integration/test_desktop_trial_cleanup.py`）
- [X] T067a [P] [US3] startup recovery 门卫测试：构造孤儿 `desktop_recordings` 行与 `data/recordings/<recording_id>/` 目录，调用 `ensure_startup_recovery()` 后断言 desktop 表行与录制目录均保留，证明 T011 只清理过期 `data/trials/`，不扫描 desktop 表、不清理录制孤儿（FR-027 / Edge Case "录制中崩溃"）（`tests/integration/test_desktop_startup_recovery_non_cleanup.py`）
- [X] T068 [P] [US3] stdout/stderr 落盘单测：试用结束后 `data/trials/<trial_id>/stdout.log` 与 `stderr.log` 落盘（`tests/integration/test_desktop_trial_logs.py`）

### Implementation for User Story 3

- [X] T069 [US3] 创建 `src/execution/desktop_trial_runner.py`：`run_desktop_trial(code, trial_id) -> TrialResult` 主入口、wrapper 模板字符串注入、`subprocess.Popen` 启动参数（`python -u -c wrapper` + `creationflags=CREATE_NEW_PROCESS_GROUP` + `cwd=data/trials/<trial_id>/` + `env=whitelisted_env`）+ 120s `proc.communicate(timeout=120)` + 捕获 `proc.returncode` 写入 `TrialResult.exit_code` + `Popen.terminate()` + `subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)])` 整树兜底；execution runner 负责创建 `data/trials/<trial_id>/` 并落 stdout/stderr，不 import UI 或 business
- [X] T070 [US3] 在 `src/execution/desktop_trial_runner.py` 续 `build_whitelisted_env()` 函数：仅传 `WHITELISTED_ENV_VARS` 集合 + 含 `SENSITIVE_PATTERNS`（`API_KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `KEYRING`）子串变量过滤（大小写不敏感）
- [X] T071 [US3] 在 `src/execution/desktop_trial_runner.py` 续 `parse_trial_stdout(stdout_bytes, stderr_bytes, exit_code: int) -> dict`：末行 JSON 解析 + 字典 shape 校验（`ok` / `summary` 字段必存）+ 兜底返回 `{"ok": False, "summary": stderr 末 5 行≤200 字符, "details": {"_fallback": "stdout_no_json"}}`；SC-003 的试用通过 helper MUST 同时要求 `exit_code == 0` + JSON 解析成功 + `ok=True`
- [X] T072 [P] [US3] 创建 `src/execution/desktop_trial_models.py` 添加 `TrialResult` dataclass（ok / summary / details / exit_code / timed_out / stdout_path / stderr_path / trial_id 字段）；`src/business/tool_trial/trial_models.py` 仅保留/更新既有 pending tool 与 `execution_strategy` 语义，不承载 subprocess result 模型
- [X] T073 [US3] 创建 `src/ui/widgets/desktop_trial_dialogs.py` 事前提示对话框：文案"试用代码即将在桌面真实执行（最长 120s）" + 代码前 20 行预览 (`QPlainTextEdit` 可滚动) + 高危 API 标签列表 + "开始 / 取消"双按钮；高危 API 检测**调用共享** `src.business.utils.high_risk_api_detector.detect_high_risk_apis()`（T011a 提供）获得命中标签，**不在本文件复制 ast 扫描规则**避免与 T088 SC-004 判定漂移
- [X] T074 [US3] 在 `src/ui/widgets/desktop_trial_dialogs.py` 续完成 Toast 路由：复用现有普通 Toast；标题 = "试用成功" / "试用失败" / "试用超时"；正文按 `parse_trial_stdout` 返回字段或 stderr 末 5 行
- [X] T075 [US3] 在 `src/business/orchestration/agent/orchestrator.py` 接入 `src.execution.desktop_trial_runner.run_desktop_trial`：试用按钮点击后构造 `trial_id`（与 `recording_id` / `action_id` 同套 UUID 生成函数）→ 通过 blinker 事件 `desktop_trial_preview_ready` 请求 UI 显示事前提示对话框 → 用户点开始后业务层调用 execution runner → runner 创建 `data/trials/<trial_id>/`、设置 cwd、落 stdout.log / stderr.log → 业务层收到 `TrialResult` 后发 `desktop_trial_finished` blinker 事件，UI bridge 转普通 Toast；UI 不直接创建或写入 `data/trials/`

**Checkpoint**: US3 独立可用——Trial 子进程 + UI 三步骤通；121s 死循环代码触发超时 kill；`data/trials/<trial_id>/` 隔离与 7 天 cleanup 工作。

---

## Phase 6: User Story 4 - 录制健康反馈与早期止损 (Priority: P3)

**Goal**: 在 US1 基础 sanity check 对话框之上补齐颜色判定（红 / 黄 / 绿）+ "放弃录制" / "重新录制"状态机；保留 US1 已实现的"继续分析"路径；补充 vision_model 缺失一次性 toast 与设置面板"桌面录制"配置区。

**Independent Test**: 故意让一段录制无任何动作（不点不输入，30 秒后停），验证 sanity check 标红且"动作总数 = 0"高亮，"放弃录制"按钮把 status UPDATE 为 abandoned；再做正常录制验证"继续分析"路径与绿色态。

### Tests for User Story 4

- [X] T076 [P] [US4] 颜色判定单测：红（`action_type_counts` 之和 = 0）/ 黄 UIA（`uia_total > 0` 且命中率 < 50%）/ 黄 clip（`enable_clip=true` 且失败率 > 20%）/ 绿（条件均不触发）/ UIA 跳过（`uia_total = 0` 时不参与判定）/ clip 跳过（`enable_clip = false` 时不参与判定）（`tests/ui/test_desktop_sanity_check_color.py`）
- [ ] T077 [P] [US4] 三按钮状态机单测：继续分析 → status=stopped + UI 跳 intent 页；放弃录制 → status=abandoned + UI 回录制页**不预选 mode**；重新录制 → status=abandoned + UI 回录制页**默认预选桌面 mode** 不立即启动 hook（`tests/ui/test_desktop_sanity_check_buttons.py`）
- [ ] T078 [P] [US4] vision_model 缺失 toast 一次性单测：同一 `recording_id` 多次进 intent 页只显示一次 toast；不同 `recording_id` 各显示一次；toast 自动消失约 8 秒；非模态不阻塞 PM 启动（`tests/ui/test_vision_model_missing_toast.py`）

### Implementation for User Story 4

- [X] T079 [US4] 扩展 `src/ui/widgets/desktop_sanity_check_dialog.py` `DesktopSanityCheckDialog`：在 US1 基础展示之上补齐各类型分布 / 帧总数 / clip 数 / 剪贴板事件 / UIA 命中率 / 录制时长与颜色 badge；继续通过 `DesktopRecordingService.get_health_stats(recording_id)` 间接读 `desktop_recordings.health_stats` JSON 列（不扫 `desktop_actions` 表）
- [X] T080 [US4] 在 `src/ui/widgets/desktop_sanity_check_dialog.py` 续 `determine_health_color(stats, enable_clip) -> "red" | "yellow" | "green"` 函数（按 contracts/ui_signals_and_states.md §3 颜色判定规则）
- [ ] T081 [US4] 三按钮 slot 增强：
  - "继续分析" → 沿用 US1 的 `DesktopRecordingService.mark_stopped(recording_id)` + UI 跳 intent 页（PM Agent 启动）；
  - "放弃录制" → `DesktopRecordingService.mark_abandoned(recording_id)` + UI 回录制页**不预选 mode**；
  - "重新录制" → `DesktopRecordingService.mark_abandoned(recording_id)` + UI 回录制页**默认预选桌面 mode** 不立即启动 hook
- [ ] T082 [P] [US4] 在 `src/ui/widgets/recording_widget.py` 实现 vision_model 缺失一次性 toast：`_vision_model_warning_shown_for_recordings: set[str]` 内存集合记录已显示的 recording_id；首次进 intent 页时若 `recording.desktop.vision_model` 缺失则显示 toast 8 秒（比普通 5s toast 长）；非模态不阻塞 PM 启动
- [X] T083 [P] [US4] 创建 `src/ui/widgets/settings/desktop_recording_settings.py` 设置面板"桌面录制"配置区：`vision_model` 输入框 + 说明文本"留空 → ..."、`enable_clip` 复选框；改动通过 `UnifiedConfigManager` 写回

**Checkpoint**: US4 独立可用——sanity check 颜色判定 + 三按钮 + vision_model 提示 + 设置面板全部就绪；4 个 user story 全部独立可用。

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 跨 user story 的活文档、quickstart 验证、合规签字。

- [X] T084 [P] 更新 `docs/ARCHITECTURE.md` 加"桌面录制 + Trial 子进程隔离 + 5 工具 mode dispatch + 双轨 prompt"小节（参考 plan.md Constitution Check V 列）
- [X] T085 [P] 更新 `docs/PROJECT_CONSTRAINTS.md` 加约束：① DuckDB 桌面 2 表 allowlist 隔离 + 跨 mode 表访问 sqlglot 拒绝；② Trial env 白名单（含敏感子串过滤）；③ Trial cwd `data/trials/<trial_id>/`；④ vision provider 沿用 analyze_image
- [X] T086 [P] 更新 `AGENTS.md`（`.specify/init-options.json` 指定的 Codex context file）与 `CLAUDE.md` 的"当前代码现实"段，并把两者 SPECKIT marker 指向 `specs/007-desktop-recording/plan.md`；追加：① 5 通用工具 mode dispatch + sqlglot 跨 mode 错误码；② `build_pm_prompt(mode)` / `build_programmer_prompt(mode)` 双轨；③ 浮窗 hook 在主窗 minimize 完成回调后启动；④ sanity check 通过 `DesktopRecordingService.get_health_stats()` 读取 `desktop_recordings.health_stats`；⑤ sanity check 三按钮状态机（继续分析 / 放弃录制 / 重新录制）；⑥ Trial 子进程 cwd / env 白名单 / 120s taskkill，且 `data/trials/<trial_id>/` 由 `src/execution/desktop_trial_runner.py` 创建，business 只编排调用与事件；⑦ ast.parse syntax gate + 自动反馈重试 ≤ 2 次；⑧ DPI Per-Monitor V2；⑨ `monitor_index` per action；⑩ 桌面录制跨模块通知走 `src/utils/events.py` blinker，UI 仅做本地 Qt bridge
- [X] T087 [P] 验证 `config.example.json` + `config.example.comments.md` 已通过 T003 包含 `recording.desktop.enable_clip` / `recording.desktop.vision_model` 字段与说明；不得把本 worktree 任务写成直接修改主仓库工作树
- [ ] T088 按 `quickstart.md` 5 标准场景手工跑 manual e2e 漏斗验证（SC-001 / SC-002 / SC-003 / SC-004 / SC-007）：5/5 录制成功 + 5/5 出方案 + ≥3/5 试用通过（按 `TrialResult.exit_code == 0` + stdout 末行 JSON 解析成功 + `ok=True` 判定）+ ≥3/5 走捷径 + 用户主观判断不卡；记录是否观察到 CC-007 软目标（CPU 单核 < 15% / 鼠标延迟 < 50ms / 内存 < 500MB / 磁盘 IO 突发 < 50MB/s）明显偏离；**SC-004 走捷径机械判定 MUST 调用共享** `src.business.utils.high_risk_api_detector.detect_high_risk_apis(code)`（T011a 提供）对 5 场景生成代码逐一判定，命中即算捷径；人工 spot check 仅做规则误伤复核（不重写规则）
- [ ] T089 在 PR 描述里记录 SC-008 合规签字流程：installer 公开发版前由产品/安全侧对"全局录制 + 无隐私机制 + vision 按需上传"的隐私风险范围签字（CC-004 + CC-005）
- [ ] T090 [P] 在 `tests/integration/test_agent_loop_multi_tool_calls.py` 增加桌面 mode 工具 14 场景集成测试（按现有浏览器 mode 测试套路对称）
- [ ] T091 [P] 全量跑 `uv run pytest tests/` + `uv run black src/ tests/` + `uv run flake8 src/ tests/`，commit 前确认零失败

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始
- **Foundational (Phase 2)**: 依赖 Phase 1，**阻塞**所有 user story
- **User Stories (Phase 3-6)**: 依赖 Foundational
  - 各 user story 独立可测，可并行（如有人手）
  - 优先级顺序 P1 (US1, US2) → P2 (US3) → P3 (US4)
- **Polish (Phase 7)**: 依赖所有 user story 完成

### User Story Dependencies

- **US1 (P1)**: 无外部依赖；T022 依赖 T001 并负责 `src/main.py` 启动期接线；T030 DesktopRecorder 顶层依赖 T023-T029 子组件、T007-T010 Foundational；T034 基础 sanity check "继续分析"路径依赖 T009 Service
- **US2 (P1)**: 无外部依赖；T048 mode dispatch 改造 + T049 sql_rewriter 是 mode 隔离前置；T050-T052 是 3 桌面专属工具 handler，T052a 是 PM/Programmer/Trial 工具集 composition 接线；T053-T054 双轨 prompt 与 T055 Orchestrator dispatch 链；T057-T058 syntax gate 链；可与 US1 并行（实施时 US2 用 fixture 数据，不必等 US1 完成）；T059a 是 P1 MVP 人工验证关口，依赖 US1 + US2 均完成，未通过不得进入 US3/US4
- **US3 (P2)**: 依赖 US2 的 syntax gate（T057）+ Programmer 出码闭环；T069-T071 `src/execution/desktop_trial_runner.py` 三段是同文件三函数顺序、T072 `desktop_trial_models.py` 独立、T073-T074 dialog 同文件
- **US4 (P3)**: 依赖 US1（health_stats 写入 + 基础 sanity check "继续分析"路径）+ Foundational T009 Service 薄封装；T079-T081 同文件串行，T082 widget 改动、T083 settings 文件可并行

### Within Each User Story

- 测试 SHOULD 先于实现写（TDD）；本 feature 测试在每个 user story 内已显式列出
- Models / 子组件 → Service / 顶层（如 T023-T029 → T030）
- 业务 / recording / Trial 层 → UI 层跨模块通知走 blinker（如 T030 DesktopRecorder → T034 UI bridge），UI 内部交互才用 Qt signal / eventFilter
- 单个 story 内任务完成（含 Checkpoint）后，该 story 才算可交付；不要求等待其他 story 串行完成

### Parallel Opportunities

- T002 / T003 在 Setup 内可并行；
- T005 / T009 / T010 / T010a / T011a / T011b 在 Foundational 内可并行（不同文件）；T006-T008 / T011 均改 `recording_repository.py`，按顺序串行；
- US1 内 T012-T021 测试任务（含 T019a）全部 [P]；T022 是 `src/main.py` 接线任务，依赖 T001；T023-T029 子组件实现全部 [P]；
- US2 内 T037-T047b 测试任务全部 [P]；T050-T052 同文件串行，T053-T054 同文件串行，其中 T052a 需在 T050-T052 后串行接线；T059a 不并行，作为 US1 + US2 完成后的 STOP and VALIDATE 关口；
- US3 内 T060-T068 测试任务全部 [P]；T069-T071 同文件串行，T073-T074 同文件串行；
- US4 内 T076-T078 测试任务全部 [P]；T079-T081 同文件串行，T082 / T083 可与 dialog 增强并行；
- Polish 内 T084-T087 文档/配置验证任务全部 [P]、T090-T091 全量测试可并行 lint/format。

---

## Parallel Example: User Story 1

```bash
# 启动 US1 全部测试任务并行（11 文件）：
Task: "T012 desktop_recordings/desktop_actions schema + large_field 占位单测 in tests/data/test_recording_repository_desktop.py"
Task: "T013 pynput hook + typing/hotkey 归类单测 in tests/recording/test_desktop_pynput_hook.py"
Task: "T014 UIA querier 50ms 超时降级单测 in tests/recording/test_desktop_uia_querier.py"
Task: "T015 clipboard_watcher 文本/图片 latest 快照 + event_seq 自增单测 in tests/recording/test_desktop_clipboard_watcher.py"
Task: "T016 frame_ring_buffer 30 帧 FIFO 单测 in tests/recording/test_desktop_frame_ring_buffer.py"
Task: "T017 PNG sink + clip sink 失败 has_clip=FALSE 单测 in tests/recording/test_desktop_sinks.py"
Task: "T018 DesktopRecorder lifecycle 集成测试 in tests/integration/test_desktop_recorder_lifecycle.py"
Task: "T019 minimize 后启动全子系统集成测试 in tests/ui/test_desktop_hook_start_after_minimize.py"
Task: "T019a 基础 sanity check 继续分析路径 UI 测试 in tests/ui/test_desktop_basic_continue_analysis.py"
Task: "T020 drag 类型语义单测 in tests/recording/test_desktop_drag_semantics.py"
Task: "T021 typing 序列切片规则单测 in tests/recording/test_desktop_typing_segmentation.py"

# 启动 US1 全部子组件实现并行（8 文件）：
Task: "T022 wire DPI awareness apply() call in src/main.py"
Task: "T023 pynput hook in src/recording/desktop/pynput_hook.py"
Task: "T024 UIA querier in src/recording/desktop/uia_querier.py"
Task: "T025 clipboard_watcher 文本/图片 latest 快照 in src/recording/desktop/clipboard_watcher.py"
Task: "T026 frame_ring_buffer in src/recording/desktop/frame_ring_buffer.py"
Task: "T027 PNG sink in src/recording/desktop/png_sink.py"
Task: "T028 clip sink in src/recording/desktop/clip_sink.py"
Task: "T029 hotkey_register in src/recording/desktop/hotkey_register.py"
```

---

## Implementation Strategy

### MVP First (US1 + US2 = P1)

桌面录制 Phase 1 的"最小可用"是 P1 双 story（录制数据 + Agent 多模态分析），US3 / US4 是后置增量：

1. 完成 Phase 1 (Setup) + Phase 2 (Foundational)；
2. 并行完成 Phase 3 (US1) + Phase 4 (US2)；
3. **STOP and VALIDATE**: 5 标准场景跑 SC-001 录制成功（`health_stats.action_type_counts` 之和 > 0；不看 sanity check 颜色）+ SC-002 出方案漏斗；
4. 此时 MVP 可演示——用户能录、Agent 能分析。

### Incremental Delivery

1. **MVP**: Setup + Foundational + US1 + US2 → 5 场景 SC-001 / SC-002 通过；
2. **+US3**: 加试用层 → 5 场景 SC-003 通过（≥ 3/5 试用通过）+ SC-004 通过（≥ 3/5 走捷径）；
3. **+US4**: 加 sanity check + 设置面板 → UX 完整闭环；
4. **Polish**: 活文档同步 + quickstart manual e2e 验证 + SC-008 合规签字。

### Parallel Team Strategy

如果有 3 人团队：

1. 全员先合力完成 Setup + Foundational（高频改 schema / config / Repository，串行更稳）；
2. Foundational 完成后：
   - 开发者 A：US1（录制层 + UI 录制流，单进程内复杂度最高）；
   - 开发者 B：US2（Agent 工具 + dispatch + prompt 双轨，可独立用 fixture 测试）；
   - 开发者 C：先 US4（sanity check + 设置面板，UI 改动独立），再 US3（Trial，依赖 US2 的 syntax gate，等 B 出 T057）；
3. Polish 阶段全员合力做活文档同步与 quickstart 验证。

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖；同文件内多任务必须串行
- [Story] 标签用于追溯到 spec.md user story；Setup / Foundational / Polish 阶段无 [Story] 标签
- 每个 user story 独立可完成、独立可测——US1 完成后即使 US2/US3/US4 未做，录制 + 数据落盘也能 demo
- 测试先写、断言失败、再写实现（TDD 推荐但非强制）
- 每完成 1 个任务或一组逻辑任务后 commit；checkpoint 可发 PR 评审
- 避免：模糊任务 / 同文件冲突 / 跨 story 依赖破坏 story 独立性
- 文件路径全部 repo-relative，运行命令在 `D:\develop\code\Exemplar\.worktrees\007-desktop-recording\` 下执行
