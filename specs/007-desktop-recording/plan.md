# Implementation Plan: 桌面录制 Phase 1

**Branch**: `007-desktop-recording` | **Date**: 2026-05-02 | **Spec**: [./spec.md](./spec.md)
**Input**: Feature specification from `/specs/007-desktop-recording/spec.md`

## Summary

把当前主仓库 `RecordingMixin._on_recording_started` 桌面分支的"暂不支持"路径替换为完整可用闭环：① 录制层基于 pynput 全局 hook + UIA + WM_CLIPBOARDUPDATE + 30 帧 ring buffer + 双 sink（PNG / mp4 clip）落 `desktop_recordings` / `desktop_actions` 两张 DuckDB 表；② Agent 工具层让 5 个通用工具按 `recording_mode` 内部切表（mode dispatch），新增 3 桌面专属工具 `list_desktop_actions` / `analyze_desktop_action` / `read_action_clip`，桌面 mode 用 3 工具替换 `analyze_image`；③ Agent 编排层 `build_pm_prompt(mode)` / `build_programmer_prompt(mode)` 双轨 prompt（浏览器 legacy 字节级保留）+ Programmer 输出代码 `ast.parse` syntax gate + 自动反馈重试（≤ 2 次）；④ execution 层 `src/execution/desktop_trial_runner.py` 负责子进程执行沙箱：`python -u -c <wrapper>` + `data/trials/<trial_id>/` 隔离 cwd + env 白名单继承 + 120s `taskkill /F /T` 整树兜底，business 层只负责编排 runner 调用与 blinker 事件，UI 走"事前提示对话框 → 跑期间无遮挡 → 跑完普通 Toast 通知"三步骤；⑤ UI 层新增录制态浮窗（hook 在主窗 minimize 完成事件回调后启动）+ Ctrl+Alt+S 全局热键 + sanity check modal child 对话框（经 `DesktopRecordingService` 读取 health_stats JSON）；⑥ Phase 1 仅支持 Windows、不引入录制数据 retention/cleanup/quota，崩溃孤儿用户手动清理；`data/trials/<trial_id>/` 调试目录保留 7 天后由启动恢复清理。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）
**Primary Dependencies**: PyQt6（UI + 全局事件循环）、pynput（全局键鼠 hook）、`mss`（多屏截屏 + frame ring buffer 取帧）、`comtypes` / `pywinauto`、`pywin32`（UIA `ElementFromPoint`、WM_CLIPBOARDUPDATE 订阅、Per-Monitor V2 DPI awareness、`RegisterHotKey`、`taskkill` 接线）、`opencv-python`（mp4 clip 编码，自带 ffmpeg）、`Pillow`（PNG 落盘 + vision 上传前缩放）、DuckDB（`desktop_recordings` / `desktop_actions` 表）、blinker（事件总线，复用 `src/utils/events.py`）、sqlglot（SQL 列血缘 / mode 隔离 allowlist）、自研 AgentLoop、LangChain LLM 客户端（vision provider 沿用 `analyze_image` factory）
**Storage**: DuckDB（录制分析层，新建 `desktop_recordings` / `desktop_actions` 两张表 + 复用 `actions` 表的 large_field 占位机制）+ SQLite（业务数据无变更）+ 文件系统（`data/recordings/<recording_id>/{frames/<action_id>/, clips/, clipboard/}` + `data/trials/<trial_id>/`）
**Testing**: pytest（单元 / 集成）、`tests/integration/test_agent_loop_multi_tool_calls.py`（已有 14 场景集成测试，新增桌面工具 mode dispatch 链路冒烟与门卫测试沿用此风格）、行为级守卫测试（PM/Programmer 浏览器 prompt 字节级 + 关键短语断言）、5 标准场景 manual e2e
**Target Platform**: Windows 10/11（CC-001 显式 Phase 1 仅 Windows，UIA 限制 + Per-Monitor V2 DPI awareness + `taskkill /F /T` 整树 kill 均为 Windows 专属 API）
**Project Type**: desktop-app（PyQt6 单进程 + pynput 全局 hook + 子进程隔离 Trial）
**Performance Goals**: CC-007 软目标——CPU 单核 < 15% / 鼠标延迟 < 50ms / 内存峰值 < 500MB / 磁盘 IO 突发 < 50MB/s；不卡退出标准、不写自动化测试，仅靠 SC-007 用户主观判断
**Constraints**:
- UIA `ElementFromPoint` 50ms 同步超时，超时排进异步队列稍后 UPDATE `uia_summary`；UIA COM 初始化失败 → 降级启动（uia_summary 全空）
- pynput hook 注册失败 → **阻塞**录制启动并弹错对话框（hook 是录制根基，无降级）
- WM_CLIPBOARDUPDATE 订阅失败 → 降级启动（剪贴板事件全空）
- Ctrl+Alt+S 注册失败 → 降级启动 + UI toast 提示用浮窗按钮
- Trial 子进程仅靠 120s `Popen.terminate()` + `taskkill /F /T <pid>` 整树兜底，不监控 RSS/CPU/句柄（不引入 Windows Job Object）
- env 白名单：仅传 `{PATH, SYSTEMROOT, SYSTEMDRIVE, WINDIR, TEMP, TMP, PYTHONPATH, PYTHONHOME, LANG, LC_ALL, USERPROFILE, APPDATA, LOCALAPPDATA, PROGRAMFILES, "PROGRAMFILES(X86)"}`，含 `API_KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `KEYRING` 子串（大小写不敏感）的变量必过滤
- ring buffer 固定 30 帧 ≈ 2 秒；前 1s + 后 2s 约 45 帧；buffer 不足时取所有可用帧不补帧
- vision LLM 上传前 PNG 长边 1280px **仅缩小不放大**（语义对齐 `PIL.Image.thumbnail`）
- mode 隔离 allowlist 严格：浏览器 mode 屏蔽桌面 2 张表，桌面 mode 屏蔽浏览器 5 张表，跨 mode 触及 sqlglot security gate 拒绝
**Scale/Scope**:
- 单次录制无硬上限（CC-008），5 标准场景为分钟级（30 秒 ~ 5 分钟）；典型动作量 5-50 条
- vision LLM 单次调用 ≤ 2 个 action × ≤ 45 帧/action，缩放后单帧 ~150KB（1280×720 PNG），单次上传 ~13MB 上限
- Phase 1 用户 = 开发/内测，单机现场可观察手动停止
- 受影响 Agent: PM / Programmer / Trial（Assistant 不受影响）
- 受影响层: UI / Business / Execution / Data / Recording

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. 分层边界与事件协调 | UI → business → execution → data/driver 方向是否保留？跨模块通知是否走 `src/utils/events.py` 的 blinker？ | **触达层**：UI（`src/ui/widgets/recording_widget.py` + `src/ui/mixins/recording_mixin.py` + 新浮窗 + sanity check dialog + 试用事前/通知 Toast）/ Business（Orchestrator dispatch + `build_pm_prompt(mode)` + `create_desktop_specific_tools` 工厂 + 5 通用工具 mode dispatch + Trial 编排；不直接启动 subprocess、不创建 `data/trials/`）/ Execution（`src/execution/desktop_trial_runner.py` + `desktop_trial_models.py`，负责 Trial 子进程执行沙箱、cwd/env 白名单、120s kill 兜底、stdout/stderr 落盘）/ Data（`desktop_recordings` / `desktop_actions` 两表 + `RecordingRepository.save_recording_session` default 修正 + `get_recording_mode(recording_id)` mode 查询入口 + `config_models.default_recording_mode` 修正）/ Recording（新增 `src/recording/desktop_recorder.py` + `src/recording/desktop/` 子模块）。**跨模块事件**：Recorder / Orchestrator / TrialRunner 对 UI 的通知统一走 `src/utils/events.py` blinker 事件；复用 `recording_started` / `recording_stopped`，新增 `desktop_action_count_changed` / `desktop_recorder_start_failed` / `desktop_recording_degraded` / `desktop_syntax_gate_retry_failed` / `desktop_trial_preview_ready` / `desktop_trial_finished`。UI 层只在本地 Qt bridge 中把 blinker 事件切回 UI 线程后更新 widget / toast。**同模块 UI 内部信号**：浮窗按钮、主窗 minimize 监听等 UI 内部交互可继续用 Qt signal / eventFilter，不作为跨模块通知。**反向依赖**：无；UI 通过 Service / Bridge 调用业务层，不直接触达 Repository（FR-024 sanity check 通过 Service 读 `desktop_recordings.health_stats`）。**例外**：无。 |
| II. 数据边界与持久化纪律 | SQLite / DuckDB 职责显式？Repository 边界保留？`network_requests` 过滤契约保留？ | **DuckDB**：新增 `desktop_recordings` / `desktop_actions` 两张表 schema；5 通用工具 mode dispatch 改造，浏览器路径 byte-equal（CC-002 + SC-005 门卫不变量 1-7 不退化）；桌面 mode allowlist 严格 = `{desktop_recordings, desktop_actions}`，浏览器 mode allowlist 严格 = 现有 5 张表，跨 mode 在 sqlglot security gate 拒绝（FR-012a）。**SQLite**：业务库零变更（无新增 Repository、无新增表）。**Repository 边界**：UI 通过 Service 间接读 `desktop_recordings.health_stats`（非直访 Repository）；桌面 Recorder 通过 `RecordingRepository` 的 `insert_desktop_recording` / `update_desktop_recording_*` 等 desktop 专用方法写 `desktop_recordings`，不镜像写 `recording_sessions`；`save_recording_session()` 仅修正浏览器默认值/历史隐患。**`network_requests` 过滤**：本次 spec 不触及 `network_requests` / `sql_rewriter` / `FilteredDuckDBConnection`；现有过滤契约 100% 保留（CC-002 门卫不变量 #2）。**例外**：无。 |
| III. 统一配置与密钥安全 | 新配置走 `UnifiedConfigManager`？密钥 keyring？默认/模板/UI/文档同步？ | **新配置项**：① `recording.desktop.enable_clip`（bool，默认 `True`，开关 mp4 clip 编码）；② `recording.desktop.vision_model`（str，无默认，独立指定 vision-capable model；未配置时 `analyze_desktop_action` 不注入桌面 PM/Programmer/Trial 工具集自然降级）。**Config model**：`src/data/config_models.py` 新增 `RecordingDesktopConfig(enable_clip=True, vision_model=None)` 并挂到现有 recording config；`src/data/unified_config.py` 暴露读写入口。**Keyring**：vision provider API key 沿用 `analyze_image` 同套 keyring entry（不分裂密钥）；provider 维度也沿用 `analyze_image` 当前 provider 配置（不新增 `vision_provider` 字段）。**默认/模板/UI/文档同步**：① `config.example.json` + `config.example.comments.md` 加两条新字段及说明；② 设置面板新增"桌面录制"配置区暴露 `vision_model`（FR-026a）；③ `docs/PROJECT_CONSTRAINTS.md` / `docs/ARCHITECTURE.md` 同步说明 mode dispatch + 双轨 prompt + 桌面工具集对称规则。**修正既有代码默认值**：`config_models.py:176` `default_recording_mode = "desktop"` → `"browser"`；`recording_widget.py:459` `fallback=BROWSER`；`RecordingRepository.save_recording_session()` 参数默认值 `"desktop"` → `"browser"` 或必填（FR-009 / FR-010）；不改 SQLite schema default。**例外**：无。 |
| IV. 可验证交付 | 静默失败风险高的编排/事件/数据/恢复是否有自动化覆盖？接线替换是否有链路冒烟 + 门卫双测？ | **单元测试**：① `ast.parse` syntax gate（fixture：合法代码通过 / 一次语法错二次通过 / 连续 3 次语法错触发终态失败 / 反馈消息模板渲染断言，FR-017a）；② `query_data` mode dispatch + sqlglot security gate 跨 mode 表访问拒绝（FR-012a）；③ `read_recording` 桌面 mode 聚合摘要 schema 断言；④ `analyze_desktop_action` 多模态消息组装顺序断言（typing 文本前缀 → 剪贴板图前缀 → 帧序列 → question；缩放仅缩小语义；失败段 `[error: <reason_code>]` 拼接）；⑤ Trial wrapper 异常包装为 `{"ok": False, "summary": "<ExcType>: <msg>", "details": {"traceback": ...}}`；⑥ env 白名单过滤断言（含 `API_KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `KEYRING` 子串变量必过滤）。**链路冒烟**：① 桌面 mode 下 `RecordingMixin._on_recording_started` → `DesktopRecordingService.start_after_minimize()` → `DesktopRecorder.start()` 路径调通；② `create_desktop_specific_tools` 工厂注入 PM/Programmer/Trial 工具集；③ `build_pm_prompt("desktop")` 返回三段拼接、`build_programmer_prompt("desktop")` 同；④ `dataclasses.replace(PM_CONFIG/PROGRAMMER_CONFIG, system_prompt=...)` 临时拷贝路径生效。**门卫**：① 浏览器 mode 5 通用工具 canonical JSON baseline 字节级 byte-equal（SC-005 门卫不变量 1-7）；② 浏览器 PM/Programmer prompt 行为级守卫测试关键短语断言不退化（SC-006）；③ `recording_data_tools.py` 不直接 import sqlglot（CC-002 #5）；④ 桌面 mode 不注入 `analyze_image`（FR-014）；⑤ 浏览器 mode 不注入 3 桌面专属工具（FR-015 反向）。**Manual e2e**：5 标准场景按 SC-001 / SC-002 / SC-003 / SC-004 / SC-007 漏斗判定（quickstart.md 固化执行步骤）。**例外**：CC-007 性能软目标不写自动化测试，靠 SC-007 用户主观判断 + 进程日志 INFO 行事后审计；CC-008 单次录制无硬上限不写测试。 |
| V. 活文档与规格驱动交付 | 活文档识别完整？临时材料隔离 `docs/local/`？ | **活文档更新**：① `docs/ARCHITECTURE.md` 加"桌面录制 + Trial 子进程隔离 + 5 工具 mode dispatch + 双轨 prompt"小节；② `docs/PROJECT_CONSTRAINTS.md` 加"DuckDB 桌面 2 表 allowlist 隔离 + 跨 mode 表访问 sqlglot 拒绝 + Trial env 白名单 + Trial cwd `data/trials/<trial_id>/`"约束；③ `AGENTS.md`（`.specify/init-options.json` 指定的 Codex context file）与 `CLAUDE.md` 在"当前代码现实"区追加桌面录制相关条目，并把 SPECKIT marker 指向 `specs/007-desktop-recording/plan.md`（mode dispatch / 双轨 prompt / 浮窗 hook 启动时机 / sanity check 通过 Service 读 health_stats / 三按钮状态机）。**docs/local/**：保留 `docs/local/_archive/design-drafts/2026-04-29-desktop-recording-brainstorm.md` 作为决策溯源；本次 plan 阶段不新增临时材料。**例外**：无。 |

无 Constitution 违规。Complexity Tracking 表保持空。

### Post-Design Re-evaluation (after Phase 1)

Phase 1 artifacts（`research.md` / `data-model.md` / `contracts/*` / `quickstart.md`）完成后对上表的逐条复审：

| Principle | Re-check 结论 | Phase 1 artifact 证据 |
|---|---|---|
| I. 分层边界 | ✅ 保留 | `contracts/ui_signals_and_states.md` §6 显式声明跨模块通知走 `src/utils/events.py` blinker，UI 只用本地 Qt bridge 切回 UI 线程；`research.md` R7 将 minimize 监听限定为 UI 内部 eventFilter / Qt signal，不承担业务 → UI 跨模块通知；UI 通过 `DesktopRecordingService.get_health_stats()` 间接读 `desktop_recordings.health_stats` 不直访 Repository |
| II. 数据边界 | ✅ 保留 | `data-model.md` §1 表 schema + §5 mode 对称表 + `contracts/recording_data_tools_mode_dispatch.md` 门卫不变量 #3 (`recording_data_tools.py` 不直接 import sqlglot) #4-#7 (mode allowlist 双向严格隔离 + 跨 mode 标准化错误) 均正式契约化 |
| III. 配置与密钥 | ✅ 保留 | `research.md` R8 (vision provider 沿用 `analyze_image` keyring entry，不分裂密钥) + `contracts/desktop_specific_tools.md` provider routing 段 + `data-model.md` §6 新增 2 配置项缺失时默认值生效 + `quickstart.md` 前置条件列 vision_model 配置路径 |
| IV. 可验证交付 | ✅ 保留 | 每条 contract 末尾"测试切面"段已列出具体单元/集成测试 fixture + `quickstart.md` 漏斗判定 + `contracts/pm_programmer_prompt_dual_track.md` §5 浏览器路径门卫（SC-005 / SC-006）+ `contracts/recording_data_tools_mode_dispatch.md` 7 条门卫不变量 + `contracts/trial_subprocess_protocol.md` 11 条测试切面 |
| V. 活文档 | ✅ 保留 | plan.md "Constitution Check" 行已列 `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` / `AGENTS.md` / `CLAUDE.md` 四处活文档更新点；`AGENTS.md` / `CLAUDE.md` SPECKIT marker 均应指向 `specs/007-desktop-recording/plan.md`；过程性材料保留在 `docs/local/_archive/design-drafts/2026-04-29-desktop-recording-brainstorm.md` 不进活文档 |

无新违规、无新例外、Complexity Tracking 表仍保持空。Phase 1 设计与 Phase 0 研究一致，可进入 `/speckit.tasks`。

## Project Structure

### Documentation (this feature)

```text
specs/007-desktop-recording/
├── spec.md              # 已存在，含 8 轮 ≈ 40 条 Q&A
├── plan.md              # 本文件
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出
├── contracts/           # Phase 1 输出
│   ├── recording_data_tools_mode_dispatch.md
│   ├── desktop_specific_tools.md
│   ├── pm_programmer_prompt_dual_track.md
│   ├── trial_subprocess_protocol.md
│   └── ui_signals_and_states.md
├── checklists/          # 已存在
└── tasks.md             # Phase 2 输出（/speckit.tasks 命令生成，不在 plan 阶段）
```

### Source Code (repository root)

```text
src/
├── business/
│   ├── agents/
│   │   ├── prompts/
│   │   │   ├── pm_prompt.py                    # 既有：浏览器 PM_SYSTEM_PROMPT_LEGACY 字节级保留
│   │   │   ├── programmer_prompt.py            # 既有：浏览器 Programmer prompt 字节级保留
│   │   │   └── desktop_prompts.py              # 新增：_PM_COMMON_HEADER / _PM_DESKTOP_GUIDANCE / _PM_COMMON_FOOTER + Programmer 桌面段 + build_pm_prompt(mode) / build_programmer_prompt(mode)
│   │   └── tools/
│   │       ├── programmer_tools.py             # 改造：execution_strategy enum 增 'desktop'（FR-018）
│   │       ├── recording_data_tools.py         # 改造：5 通用工具按 recording_mode 内部切表（mode dispatch）；create_recording_tools 工厂调用 RecordingRepository.get_recording_mode(recording_id) 一次并闭包传给 5 handler + query_data_pre_hook（FR-012）
│   │       └── desktop_tools.py                # 新增：create_desktop_specific_tools(recording_id) + 3 工具 handler（list_desktop_actions / analyze_desktop_action / read_action_clip）
│   ├── orchestration/
│   │   └── agent/
│   │       ├── orchestrator.py                 # 改造：启动 PM/Programmer 前分别用 dataclasses.replace(PM_CONFIG/PROGRAMMER_CONFIG, system_prompt=...) 构造临时 AgentConfig；接入 desktop execution_strategy 分发；ast.parse syntax gate + 自动反馈重试 ≤ 2 次（FR-017 / FR-017a）
│   │       └── desktop_syntax_gate.py          # 新增：ast.parse syntax gate + 反馈消息模板 + 重试计数器
│   └── tool_trial/
│       └── trial_models.py                     # 改造：execution_strategy 允许值/注释增加 desktop（不承载 desktop subprocess runner）
├── data/
│   ├── config_models.py                        # 改造：default_recording_mode 'desktop' → 'browser'（FR-010）；新增 RecordingDesktopConfig（enable_clip / vision_model）
│   ├── recording_repository.py                 # 改造：save_recording_session() recording_mode default 修正（FR-009）；新增 desktop_recordings / desktop_actions 表的 ensure / insert / query 方法 + get_recording_mode(recording_id) 唯一 mode 查询入口
│   └── unified_config.py                       # 改造：暴露 recording.desktop.enable_clip / recording.desktop.vision_model 字段访问
├── execution/
│   ├── desktop_trial_models.py                 # 新增：TrialResult dataclass（ok / summary / details / exit_code / timed_out / stdout_path / stderr_path / trial_id）
│   └── desktop_trial_runner.py                 # 新增：subprocess.Popen + python -u -c <wrapper> + cwd data/trials/<trial_id>/ + env 白名单 + 120s taskkill 整树兜底 + stdout 末行 JSON 解析；不依赖 UI / business
├── recording/
│   ├── desktop_recorder.py                     # 新增：DesktopRecorder 顶层（启动/停止/状态机/health_stats 汇总）
│   ├── desktop/
│   │   ├── __init__.py
│   │   ├── pynput_hook.py                      # 新增：pynput keyboard/mouse hook 全局抓取 + typing/hotkey 归类规则
│   │   ├── uia_querier.py                      # 新增：UIA ElementFromPoint(50ms) 同步 + 异步队列 + window_title owning window 溯源
│   │   ├── clipboard_watcher.py                # 新增：WM_CLIPBOARDUPDATE 订阅 + 500ms 兜底 + Ctrl+V 立即读 + _ClipboardLatest 引用 + clipboard/<recording_id>_<event_seq>.png 命名
│   │   ├── frame_ring_buffer.py                # 新增：15 fps 30 帧 FIFO + 前 1s 后 2s 取帧 + 不足时取所有可用
│   │   ├── png_sink.py                         # 新增：原生分辨率 PNG compress_level=6 落 frames/<action_id>/
│   │   ├── clip_sink.py                        # 新增：opencv-python mp4 编码 → clips/<action_id>.mp4，受 enable_clip 开关控制；失败 → has_clip=FALSE / clip_total++ / clip_success 不变
│   │   ├── dpi_awareness.py                    # 新增：进程启动期 SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
│   │   └── hotkey_register.py                  # 新增：Ctrl+Alt+S RegisterHotKey + 失败 fallback toast
│   └── filtering/
│       ├── decision.py                         # 改造：mode 隔离 allowlist——桌面 mode = {desktop_recordings, desktop_actions}，浏览器 mode = 现有 5 张表
│       └── sql_rewriter.py                     # 改造：跨 mode 表访问 → security gate 拒绝并返回 {"error": "table_not_in_mode", "table": "<name>", "mode": "<current_mode>"}（FR-012a）
└── ui/
    ├── mixins/
    │   └── recording_mixin.py                  # 改造：_on_recording_started 桌面分支 → DesktopRecordingService / business bridge → DesktopRecorder.start()（去除"暂不支持"，FR-001）
    └── widgets/
        ├── recording_widget.py                 # 改造：fallback=BROWSER（FR-010）；点"开始"后启动 minimize 监听 → minimize 完成回调启动 hook（FR-022）；停止时 restore 主窗 + 弹 sanity check dialog（FR-024）
        ├── recording_floating_widget.py        # 新增：100×40 px 浮窗 + 实时 N 个动作计数 + [停止] 按钮 + Ctrl+Alt+S 兜底
        ├── desktop_sanity_check_dialog.py      # 新增：modal child + 通过 DesktopRecordingService 读取 health_stats JSON + 颜色判定（红/黄/绿）+ 三按钮（继续分析 / 放弃录制 / 重新录制）
        ├── desktop_trial_dialogs.py            # 新增：事前提示对话框（代码前 20 行预览 + 高危 API 标签 + 开始/取消按钮）+ 跑完普通 Toast（试用成功/失败/超时）
        └── settings/
            └── desktop_recording_settings.py   # 新增：设置面板"桌面录制"配置区，暴露 vision_model 字段 + 说明文本

tests/
├── data/
│   └── test_recording_repository_desktop.py    # 新增：desktop_recordings / desktop_actions 表 ensure / insert / query 单元测试 + recording_mode default 修正断言
├── recording/
│   └── test_desktop_recorder_components.py     # 新增：pynput hook / UIA / 剪贴板 / ring buffer / sink 组件单元测试
├── integration/
│   ├── test_desktop_tools_mode_dispatch.py     # 新增：5 通用工具浏览器/桌面 mode 链路冒烟 + 跨 mode 表访问 sqlglot 拒绝
│   ├── test_desktop_specific_tools.py          # 新增：3 桌面专属工具集成测试（含 analyze_desktop_action 多模态组装顺序 mock 断言）
│   ├── test_desktop_orchestration.py           # 新增：build_pm_prompt(mode) / build_programmer_prompt(mode) 双轨 + dataclasses.replace(system_prompt=...) 临时拷贝 + ast.parse syntax gate + 重试 ≤ 2 次
│   ├── test_desktop_trial_subprocess.py        # 新增：cwd / env 白名单 / 120s taskkill / wrapper 异常包装 / 末行 JSON 解析兜底
│   └── test_desktop_browser_path_byte_equal.py # 新增：浏览器 5 通用工具 canonical JSON baseline 字节级门卫 + recording_data_tools.py 不直接 import sqlglot 门卫（SC-005 / CC-002）
└── ui/
    ├── test_desktop_floating_widget.py         # 新增：浮窗实时计数 + 停止按钮 + 拖拽
    ├── test_desktop_sanity_check_dialog.py     # 新增：颜色判定（红/黄/绿）+ 三按钮状态转移 + UI 跳转
    └── test_desktop_trial_dialogs.py           # 新增：事前提示 + 高危 API 标签 + Toast 通知（含末行 JSON 缺失兜底）
```

**Structure Decision**: 既有 `src/` 七层结构（UI / Business / Execution / Data / Recording / Utils）保留不变；本次 feature 新代码遵循同一分层方向：`recording/desktop/` 子模块挂在 `src/recording/` 下与 `recording/browser/` 对称；`agents/prompts/desktop_prompts.py` 与 `agents/prompts/pm_prompt.py` / `programmer_prompt.py` 同层；`agents/tools/desktop_tools.py` 与 `recording_data_tools.py` 同层。UI 层全部走 Service / Bridge 间接访问业务层，不直接触达 Repository，不直接创建或写入 `data/trials/`。Trial 子进程作为 `subprocess.Popen` 启动的独立进程，是 execution 层代码执行沙箱能力：`src/execution/desktop_trial_runner.py` 负责创建 `data/trials/<trial_id>/`、设置 cwd/env、120s kill、落 stdout/stderr；business/orchestrator 只负责编排调用、状态转换和 blinker 事件，不直接执行 subprocess。

## Complexity Tracking

> 无 Constitution 违规，本表保持空。
