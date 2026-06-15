# Implementation Plan: 子进程事件推送(Process Event Push)

**Branch**: `022-process-event-push` | **Date**: 2026-06-15 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/022-process-event-push/spec.md`

## Summary

为 subagent / specialist 起的后台进程提供"等事件、有进展叫我"的低延迟订阅能力,取代循环 poll。技术方向已由 `docs/superpowers/specs/2026-06-15-process-event-push-design.md` 锁定:在 `ProcessManager` 内嵌一个 per-process 的有界事件 deque + 单调 sequence + `threading.Condition`,通过既有 `_refresh_locked`(状态变化)与 `_start_reader`(累积输出)直接 append + notify;新增的 `ProcessManager.wait_for_event` 阻塞等到有事件或超时;业务层在 `command_tools.py` 新增 `wait_for_process_event` 工具,复用现有 `_process_for_current_session` 归属校验。三个配置键 `agent_tools.process.event_buffer_size / stalled_threshold_ms / chunk_threshold_chars` 走 `UnifiedConfigManager`,在 `AgentToolsProcessConfig` 上补字段,Settings UI 不暴露。事件不进 UI Event Registry、不持久化、不抽通用 bus。

## Technical Context

**Language/Version**: Python 3.12(运行时)/ 3.11+(源码兼容)
**Primary Dependencies**: 标准库 `threading`(Condition / deque) + 既有 `ProcessManager`、`get_unified_config()`、`get_process_manager()`、`builtin_contracts`(success_json / error_json)
**Storage**: N/A(事件仅活在 sidecar 进程内存,与 `ProcessRecord` 同生命周期)
**Testing**: pytest;新增 `tests/execution/test_process_manager_events.py`、`tests/business/agents/tools/test_process_event_tool.py`、`tests/integration/test_process_event_flow.py`(行为契约)
**Target Platform**: 本机 sidecar(Windows / macOS / Linux)
**Project Type**: 已有桌面 + sidecar Python 后端
**Performance Goals**: 单次状态切换 → subagent 唤醒延迟 ≤ 200 ms(本机 idle);事件 deque 操作 O(1);wait_for_event 阻塞期间不占 CPU
**Constraints**: 既有 `process_poll` / `process_logs` / `process_wait` 签名 + 行为零变化;事件不进 UI Event Registry;不引入新表 / 迁移 / 持久化层;无 stdout/stderr 原文进入事件 payload
**Scale/Scope**: 同一会话最多 16 个 background process(既有上限);每进程事件 deque 默认 64 条上限 512;事件平均 payload < 100 字节

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. Layered Boundaries & Event Coordination | 设计是否保持 UI → business → execution → data/driver 单向依赖?跨模块通知是否走 `src/utils/events.py`? | 触及 business(`command_tools.py`) + execution(`process_manager.py`) + data(config 字段);事件仅在 `ProcessManager` 内部 condition 上唤醒同会话工具,不跨模块、不走 blinker、不进 UI Event Registry——这是设计明确的 YAGNI 决策(spec FR-011/CC-006)。无反向依赖、无外发事件,不构成原则违反。|
| II. Data Boundary & Persistence Discipline | SQLite / DuckDB / Repository / network_requests 边界是否清晰? | 不触 SQLite、不触 DuckDB、不触 network_requests、不新建 Repository、不写迁移。N/A。|
| III. Unified Config & Secret Handling | 配置/密钥是否全走 `UnifiedConfigManager`?DTO/UI/日志脱敏到位? | 三个新配置键 `agent_tools.process.event_buffer_size / stalled_threshold_ms / chunk_threshold_chars` 通过在 `AgentToolsProcessConfig` 补字段 + 在 `UnifiedConfigManager` 加 getter 暴露;默认值随代码下发;Settings UI 不暴露;无 secret、无明文 DTO、无 UI event。合规。|
| IV. Verifiable Delivery | 自动化覆盖 + 静默失败路径补测试?架构接线变更是否补冒烟/门卫? | 新增 ProcessManager 事件单元测(游标推进、三类事件触发条件、stalled 懒计算与不刷屏、环形 buffer 覆盖、超时返回);工具层单元测(归属校验、process_missing、timeoutMs 钳位、cursorTooOld 续 cursor);集成层行为契约测一条(真起 subprocess,跑通 log_chunked → process_logs → state_changed 整链路);既有 process_poll / process_logs / process_wait 测试不动也必须全绿。无架构接线替换,不需要新增门卫测试。|
| V. Living Docs & Spec-Driven Delivery | 受影响的活文档列出来了吗?临时记录是否在 `docs/local/`? | spec.md / plan.md / tasks.md / research.md / data-model.md / quickstart.md 都在 `specs/022-process-event-push/`;`docs/superpowers/specs/2026-06-15-process-event-push-design.md` 是脑暴定稿源,设计阶段结束后留作历史(本 feature 不动它);`docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` 不受影响(事件仅在 execution 内部);`src/CLAUDE.md` 的 "Agent 与工具约束" 已涵盖 process 系列非 concurrency_safe 约束,本 feature 沿用,不需修改。无 `docs/local/` 临时材料。|

无 Gate 失败,不需要 Complexity Tracking 例外。

## Project Structure

### Documentation (this feature)

```text
specs/022-process-event-push/
├── plan.md              # 本文件
├── research.md          # Phase 0:决策依据(本 plan 直接引用脑暴定稿)
├── data-model.md        # Phase 1:ProcessEvent / ProcessEventCursor / ProcessRecord 扩展字段
├── contracts/
│   └── wait_for_process_event.md  # Phase 1:工具入参 / 出参 / 错误码契约
├── quickstart.md        # Phase 1:开发者本地起子进程并跑通事件流的手把手脚本
├── checklists/
│   └── requirements.md  # speckit-specify 阶段产出
└── tasks.md             # Phase 2:由 /speckit-tasks 生成
```

### Source Code (repository root)

本 feature 只触及后端的 business + execution + data 三个文件:

```text
src/
├── business/
│   └── agents/
│       └── tools/
│           └── command_tools.py        # + wait_for_process_event_handler、注册到既有 process 工具集
├── execution/
│   └── process_manager.py              # + ProcessRecord 事件字段、_emit_event / wait_for_event、
│                                       #   在 _refresh_locked / _start_reader 内注入 append+notify
└── data/
    ├── config_models.py                # + AgentToolsProcessConfig 三个字段
    └── unified_config.py               # + 三个 getter(沿用 _get_bounded_positive_int 上下限钳位)

tests/
├── execution/
│   └── test_process_manager_events.py  # 单元测:游标 / 三类事件 / stalled 懒计算 / 环形 buffer / 超时唤醒
├── business/
│   └── agents/
│       └── tools/
│           └── test_process_event_tool.py  # 单元测:归属校验 / process_missing / timeoutMs 钳位 / 配置接线
└── integration/
    └── test_process_event_flow.py      # 行为契约:真起 subprocess,log_chunked → process_logs → state_changed
```

未触及:`frontend/`、`src-tauri/`、`src/desktop_api/`、`src/recording/`、`src/utils/events.py`、SQLite migrations、DuckDB filter pipeline。

**Structure Decision**: 沿用现有后端目录(execution + business/agents/tools + data),不新建子包;新增工具走 `command_tools.py` 既有进程工具组的同模块同前缀。测试按既有 `tests/execution`、`tests/business/agents/tools`、`tests/integration` 分布,与同类历史 feature(015 builtin tools、017 parallel tool)的目录约定一致。

## Complexity Tracking

> 无 Constitution Check 违反,无需例外记录。
