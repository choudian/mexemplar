---

description: "Tasks for 022-process-event-push"
---

# Tasks: 子进程事件推送(Process Event Push)

**Input**: Design documents from `/specs/022-process-event-push/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/wait_for_process_event.md ✅, quickstart.md ✅

**Tests**: 强制写。理由:本 feature 改了 `ProcessManager` 状态机和工具入口,属于宪法 IV 明确要求"静默失败路径"配自动化测试的范畴;同时遵循用户全局 `~/.claude/rules/testing.md` 的 TDD 工作流。

**Organization**: 按 spec.md 的三条 user story 分阶段;P1 是 MVP,P2/P3 增量交付。每个 story 内部 Tests → Impl 顺序。

## Constitution-Driven Minimums(本 feature 适用项)

- [x] 无 SQLite/业务数据变更 → 不需要 Repository / migration 任务
- [x] 无 DuckDB / 录制数据变更 → 不需要 filtered DuckDB 任务
- [x] 新增三个配置键 → 必须含 `AgentToolsProcessConfig` + `UnifiedConfigManager` getter 任务(T002 / T003)
- [x] 无 secret 处理 → 不需要 masking/redaction 任务
- [x] 改了 `ProcessManager` 状态机 + 新工具入口 → 必须含三层测试(T006 / T009 / T012 / T013 / T015 / T017)
- [x] 无架构接线替换 → 不需要新增 guardrail 门卫测试;既有 guardrails 必须保持全绿(T020)
- [x] 文档:本 feature 文档全在 `specs/022-process-event-push/`,无需改 `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` / 根 AI 入口;`src/CLAUDE.md` 已涵盖 process 系列约束。Polish 阶段对照检查(T019)。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行(改不同文件、不依赖未完成任务)
- **[Story]**: US1 / US2 / US3 对应 spec.md 中的 P1 / P2 / P3 story
- 文件路径相对于 worktree 根(`.worktrees/022-process-event-push/`),实际编辑时直接对应 `src/...`、`tests/...`

## Project Paths

- 业务源:`src/business/agents/tools/command_tools.py`
- 执行源:`src/execution/process_manager.py`
- 数据源:`src/data/config_models.py`、`src/data/unified_config.py`
- 单测:`tests/execution/test_process_manager_events.py`、`tests/business/agents/tools/test_process_event_tool.py`
- 集成测:`tests/integration/test_process_event_flow.py`
- 测试命令:`uv run python -m pytest tests/execution/test_process_manager_events.py tests/business/agents/tools/test_process_event_tool.py tests/integration/test_process_event_flow.py -q`
- Linter:`uv run python -m black src/ tests/` + `uv run python -m flake8 src/ tests/`

---

## Phase 1: Setup

**Purpose**:确认 worktree + 依赖就绪;无 scaffolding 改动。

- [X] T001 验证 `uv sync` 在 worktree 内可跑通,且 `uv run python -c "from src.execution.process_manager import get_process_manager; print(get_process_manager())"` 不报错(确认现有 ProcessManager 引用链未坏)

---

## Phase 2: Foundational(阻塞所有 User Story)

**Purpose**:配置项、ProcessRecord 字段扩展、_emit_event_locked 助手、wait_for_event 框架——所有 story 共用底座。

**⚠️ CRITICAL**: 完成前不允许进入任何 user story 阶段。

- [X] T002 [P] 在 `src/data/config_models.py` 的 `AgentToolsProcessConfig` 上加三个字段:`event_buffer_size: int = 64`、`stalled_threshold_ms: int = 10000`、`chunk_threshold_chars: int = 4096`(保持默认值与 data-model 一致;新字段 strictly 排在既有字段后面,避免改变 dataclass 位置参数)
- [X] T003 [P] 在 `src/data/unified_config.py` 加三个 getter:`get_agent_tools_process_event_buffer_size` → 默认 64 上限 512;`get_agent_tools_process_stalled_threshold_ms` → 默认 10000 上限 600000;`get_agent_tools_process_chunk_threshold_chars` → 默认 4096 上限 65536;沿用同文件 `_get_bounded_positive_int` 模式,与既有 `get_agent_tools_process_default_timeout_ms` 同节
- [X] T004 在 `src/execution/process_manager.py` 的 `ProcessRecord` dataclass 上加 7 个新字段(参见 `specs/022-process-event-push/data-model.md` 实体 3 表):`events: deque[ProcessEvent]`、`event_sequence: int = 0`、`event_condition: threading.Condition | None = None`、`last_output_at: float = field(default_factory=time.time)`、`last_chunk_announce: int = 0`、`total_output_chars: int = 0`、`last_stalled_announce_output_at: float | None = None`;以及在文件顶部 import 一个 `@dataclass(frozen=True) class ProcessEvent: sequence: int; type: str; payload: dict[str, Any]`(本文件内私有,不导出)
- [X] T005 在 `src/execution/process_manager.py` 的 `ProcessManager.start()` 内,record 构造完成后立刻读取配置 `event_buffer_size`、用 `deque(maxlen=...)` 替换默认 events、绑定 `record.event_condition = threading.Condition(self._lock)`、`record.last_output_at = record.started_at`;同时新增私有方法 `_emit_event_locked(record, event_type, payload)` —— 调用方必须已持 `_lock`,该方法将 `record.event_sequence += 1` 然后构造 `ProcessEvent(sequence=record.event_sequence, type=event_type, payload=payload)` append 到 `record.events`,再调 `record.event_condition.notify_all()`
- [X] T006 [P] 在 `tests/execution/test_process_manager_events.py` 新建:针对 `_emit_event_locked` 的纯单测——多次 emit 后 `event_sequence` 单调、`events` 长度 ≤ `event_buffer_size`、超出时旧事件被环形覆盖且 sequence 不复用(spec FR-015)
- [X] T007 在 `src/execution/process_manager.py` 新增 `wait_for_event(self, process_id: str, *, since_cursor: int | None, timeout_ms: int) -> dict` 公共方法:接收 since_cursor=None 等价 0;在 `_lock` 持有期间执行 `_refresh_locked` 先收敛状态;计算 deque 中 > since_cursor 的事件;若有立即返回;若无则在 `record.event_condition.wait(timeout=...)` 上阻塞(`wait_for` 配合 deadline);超时返回空 events + 当前 status/exitCode + 返回时**始终**包含 cursor 字段(实现 R-003:cursor = deque 中最新事件 sequence,空队列时 = `record.event_sequence`);since_cursor 早于 deque 最旧 sequence 时返回 `cursorTooOld=true` 并仍然给 cursor

**Checkpoint**: Foundation 就位;state_changed / log_chunked / stalled 三类 emit 还没接入(留给各 user story 阶段),但 wait 框架已能跑通——可以开始 user story。

---

## Phase 3: User Story 1 - subagent 阻塞等到状态边界即返回 (P1) 🎯 MVP

**Goal**:进程从 running 切到 completed / failed / terminated 时,subagent 在毫秒级被唤醒拿到 status + exitCode。

**Independent Test**:真起一个 5 秒后退出码 1 的子进程,subagent 调一次 `wait_for_process_event(processId, timeoutMs=10000)`;断言返回 events 中含 `state_changed: failed, exitCode=1`,唤醒时刻接近进程退出时刻而非 timeout 上限。

### Tests for User Story 1 ⚠️(先写,RED → 验证 fail → 再 GREEN)

- [X] T008 [P] [US1] 在 `tests/execution/test_process_manager_events.py` 加用例:`test_state_changed_emitted_on_running_to_completed` 与 `test_state_changed_emitted_on_running_to_failed`,起真子进程(`python -c "import sys; sys.exit(0)"` / `sys.exit(1)`),`wait_for_event(timeout_ms=5000)` 返回事件含 `state_changed`,status/exitCode 与实际一致
- [X] T009 [P] [US1] 在 `tests/execution/test_process_manager_events.py` 加用例:`test_wait_returns_immediately_when_event_already_in_deque`(进程已退出,wait 不阻塞)、`test_wait_blocks_until_timeout_when_no_event`(长 sleep 进程,wait 接近 timeoutMs 后返回空)、`test_wait_wakes_up_on_new_event`(wait 阻塞中、另一线程触发状态切换,wait 立即返回,并断言 t1-t0 < 200 ms;直接覆盖 spec SC-001 唤醒延迟上限)
- [X] T010 [P] [US1] 在 `tests/business/agents/tools/test_process_event_tool.py` 新建文件,加用例:`test_permission_denied_for_other_session`(伪造 session_id 不同时返回 permission_denied)、`test_process_missing`(不存在 processId 返回 process_missing)、`test_timeout_ms_clamped_to_max`(传 timeoutMs=10_000_000 被钳位到 `get_agent_tools_process_max_timeout_ms`)、`test_default_timeout_used_when_missing`(不传 timeoutMs 用 `default_timeout_ms`)
- [X] T011 [P] [US1] 在 `tests/integration/test_process_event_flow.py` 新建:`test_state_changed_end_to_end` —— 通过 `wait_for_process_event_handler` 入口(而非直接 `ProcessManager.wait_for_event`)起一个会失败的真进程,断言从 `success_json` payload 中解出 events 含 `state_changed: failed, exitCode=1`

### Implementation for User Story 1

- [X] T012 [US1] 在 `src/execution/process_manager.py` 的 `_refresh_locked` 内,把 status 从 `running` 切到 `completed` / `failed` 那一行后,调用 `self._emit_event_locked(record, "state_changed", {"status": record.status, "exitCode": record.exit_code})`;对 `terminate()` 中显式把 status 设为 `terminated` 的路径,同样在持锁段内调 `_emit_event_locked`(传入 status=terminated、exitCode=record.exit_code,可能是 None);`close()` 路径**不**触发事件(closed 不是状态边界,见 R-002)
- [X] T013 [US1] 在 `src/business/agents/tools/command_tools.py` 新增 `wait_for_process_event_handler(processId: str, sinceCursor: int | None = None, timeoutMs: int | None = None) -> str`:复用 `_process_for_current_session("wait_for_process_event", processId)` 做归属校验;读 `get_agent_tools_process_default_timeout_ms` / `get_agent_tools_process_max_timeout_ms` 钳位 timeoutMs;调 `get_process_manager().wait_for_event(processId, since_cursor=sinceCursor, timeout_ms=timeout)`;包装成 `success_json("wait_for_process_event", payload | {"processId": processId})`;内部异常走 logger.warning + `error_json("wait_for_process_event", "tool_internal_error", ...)` 沿用 `process_stop_handler` 模式
- [X] T014 [US1] 在 `command_tools.py` 同文件的 ToolDefinition 注册段,把 `wait_for_process_event` 加进进程工具组(与 process_poll / process_logs / process_wait 同前缀同入口);**不**标记 `is_concurrency_safe`;tool description 简短说明"等子进程事件信号 + 超时返回;事件不带原文,原文用 process_logs 取";name=`wait_for_process_event`、parameters schema 与 `specs/022-process-event-push/contracts/wait_for_process_event.md` 的 Input 节一致

**Checkpoint**: T008..T014 全绿后,US1 MVP 已交付——subagent 可阻塞等状态边界;`process_poll` / `process_logs` / `process_wait` 既有测试同步必须仍全绿(执行 `uv run python -m pytest tests/execution tests/business/agents/tools tests/integration -q` 验证)。

---

## Phase 4: User Story 2 - log_chunked 累积通告 (P2)

**Goal**:进程累计输出过阈值后,subagent 收到 log_chunked 信号(不带原文)并能用 `process_logs` 去读。

**Independent Test**:起一个写 8192+ 字符且持续运行的子进程,subagent 调 `wait_for_process_event(timeoutMs=10000)`;返回 events 至少包含一条 `log_chunked`,字段 `totalChars` / `deltaChars` 与实际累积字符大致吻合;事件不含 stdout 原文。

### Tests for User Story 2 ⚠️

- [X] T015 [P] [US2] 在 `tests/execution/test_process_manager_events.py` 加用例:`test_log_chunked_emitted_when_threshold_exceeded`(起 `python -c "import sys; sys.stdout.write('x'*8192); sys.stdout.flush(); import time; time.sleep(2)"`,wait 返回 events 含 log_chunked,deltaChars 约等于 chunk_threshold_chars,totalChars ≥ 8192)、`test_log_chunked_baseline_resets_after_emit`(同一进程继续写 8192 字符,下次 wait 仍能再拿到一条 log_chunked,deltaChars 在阈值附近)、`test_log_chunked_does_not_carry_payload`(断言事件 payload 字段集 ⊆ {sequence, type, totalChars, deltaChars},不出现 'log'/'text'/'stdout' 等键)
- [X] T016 [P] [US2] 在 `tests/integration/test_process_event_flow.py` 加用例:`test_log_chunked_end_to_end` —— 工具入口起真进程,验证 wait → log_chunked → process_logs(取到非空日志) → wait(空 events / 状态仍 running) 整链路;事件 deltaChars > 0 且非 None

### Implementation for User Story 2

- [X] T017 [US2] 在 `src/execution/process_manager.py` 的 `_start_reader.reader` 函数内,既有 `chunks.append(line)` 之后(仍在持 `_lock` 段)加:`record.total_output_chars += len(line)`;`record.last_output_at = time.time()`;若 `record.total_output_chars - record.last_chunk_announce >= chunk_threshold`,按以下顺序执行:(1) `delta = record.total_output_chars - record.last_chunk_announce`(先保存增量);(2) `record.last_chunk_announce = record.total_output_chars`(再推进基线);(3) `self._emit_event_locked(record, "log_chunked", {"totalChars": record.total_output_chars, "deltaChars": delta})`。其中 chunk_threshold 在 reader 启动前从配置 snapshot 进 closure,避免每条 line 都 hit 配置层(可在 record 上挂 `_chunk_threshold_chars: int`,start 内一次写入)

**Checkpoint**: US2 完成后,wait 既能等状态边界又能等累积输出信号;US1 测试与所有既有 process_* 测试持续全绿。

---

## Phase 5: User Story 3 - stalled 静默通告 (P3)

**Goal**:running 状态下静默时长过阈值后,subagent 收到一条 stalled 信号,且同一静默周期不刷屏;纯静默(从未输出)场景同样触发。

**Independent Test**:起一个 sleep 60 秒、整个过程不写一个字节的子进程(`python -c "import time; time.sleep(60)"`),subagent 调 `wait_for_process_event(timeoutMs=15000)`,stalled 阈值默认 10s;返回 events 含一条 `stalled`,idleMs ≥ 10000;立即再次调同样 wait,events 为空(不刷屏)。

### Tests for User Story 3 ⚠️

- [X] T018 [P] [US3] 在 `tests/execution/test_process_manager_events.py` 加用例:`test_stalled_emitted_when_idle_exceeds_threshold`(monkeypatch `time.time` 推进或 sleep 略大于阈值的真子进程;wait 返回 events 含 stalled)、`test_stalled_not_repeated_within_same_silence_window`(连续两次 wait,只第一次收到 stalled)、`test_stalled_emitted_after_new_output_then_silence_again`(中间用 monkeypatch 模拟 reader 写一条 line 推进 last_output_at,然后再次 sleep 过阈值,wait 再收到 stalled)、`test_stalled_emitted_for_process_that_never_outputs`(起 `python -c "import time; time.sleep(2)"`,stalled 阈值改为 500ms,wait 也能收到 stalled,idleMs ≥ 500)
- [X] T019 [P] [US3] 在 `tests/execution/test_process_manager_events.py` 加用例:`test_stalled_only_when_running`(进程已 completed / failed / terminated 时不再产生 stalled)

### Implementation for User Story 3

- [X] T020 [US3] 在 `src/execution/process_manager.py` 的 `wait_for_event` 入口(已在 T007 框架内),在 `_refresh_locked` 之后、计算 deque 事件之前,加懒判定块:`if record.status == "running": idle_ms = int((time.time() - record.last_output_at) * 1000); if idle_ms >= stalled_threshold and record.last_stalled_announce_output_at != record.last_output_at: self._emit_event_locked(record, "stalled", {"idleMs": idle_ms}); record.last_stalled_announce_output_at = record.last_output_at` —— stalled_threshold 在 wait 入口一次性从配置读取

**Checkpoint**: US3 完成后,三类事件全部接入;同 stalled 静默周期内多次 wait 不刷屏;纯静默进程也能被通告。

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**:cursor 续约边界、配置接线、文档对齐、回归全绿。

- [X] T021 [P] 在 `tests/execution/test_process_manager_events.py` 加用例:`test_cursor_too_old_returns_new_cursor_for_continued_wait`(快速产生大量 chunks 使环形 buffer 覆盖;旧 sinceCursor 调 wait 得 `cursorTooOld=true` 且 `cursor != since_cursor` 且 `cursor` 单调递增;再用该 cursor wait,不再 cursorTooOld)、`test_empty_deque_cursor_equals_event_sequence`(队列已被全部消费时,wait 返回 cursor == record.event_sequence)
- [X] T022 [P] 在 `tests/business/agents/tools/test_process_event_tool.py` 加用例:`test_handler_returns_cursor_field_even_on_cursor_too_old`(走工具入口,断言 `success_json` payload 含 cursorTooOld=true 且 cursor 字段非空)
- [X] T023 [P] 在 `tests/integration/test_process_event_flow.py` 加用例:`test_full_lifecycle_log_then_state_change` —— 一次性走完 wait(等 log_chunked)→ process_logs(读原文)→ wait(等 state_changed)→ 终态返回,覆盖 spec 数据流章节的"典型一次交互"7 步
- [X] T024 跑 `uv run python -m pytest tests/execution tests/business/agents/tools tests/integration tests/guardrails -q`(本 feature 全套 + guardrail 全绿);若任一 process_* 既有测试回归,回到对应 impl 任务修复,**不**修改既有测试
- [X] T025 [P] 跑 `uv run python -m black src/data/config_models.py src/data/unified_config.py src/execution/process_manager.py src/business/agents/tools/command_tools.py tests/execution/test_process_manager_events.py tests/business/agents/tools/test_process_event_tool.py tests/integration/test_process_event_flow.py` 与 `uv run python -m flake8 ` 同上文件集;有 warning 修齐
- [X] T026 走一遍 `specs/022-process-event-push/quickstart.md` 的"集成行为契约"与"手动跑通(可选)"两节,确认本机端到端通过;若失败,把现象登记到 quickstart 的"常见故障排查"表
- [X] T027 对照 `src/CLAUDE.md` 的"Agent 与工具约束" + "Brain Service / 录制与执行约束",确认本 feature 的新工具描述、并发安全声明、Repository 边界都与之一致;无需变更则在 PR 描述里显式标注"无 AI 入口文档变更";若需要新增"process 系列又多一个 wait_for_process_event,非并发安全"提示,**只**改 `src/AGENTS.md`,然后镜像到 `src/CLAUDE.md` / `src/GEMINI.md`(同内容)
- [X] T028 验证 `docs/superpowers/specs/2026-06-15-process-event-push-design.md` 仍是历史脑暴稿(本 feature 不动它);本次实现产物全部活在 `specs/022-process-event-push/`,不污染主仓 `docs/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**:无依赖,T001 必先跑(确认环境)
- **Phase 2 (Foundational)**:依赖 Phase 1;T002 / T003 [P] 同跑;T004 → T005 顺序;T006 在 T005 后,T007 在 T005 后
- **Phase 3 (US1)**:依赖 Phase 2 完成;T008 / T009 / T010 / T011 [P] 全部先于 T012 / T013 / T014;T012 与 T013/T014 可并行(改不同文件);T014 依赖 T013(同文件,先 handler 再 register)
- **Phase 4 (US2)**:依赖 Phase 2;独立于 US1(实测推荐先完成 US1 至少 T012/T013/T014 以保证 wait 框架已串通);T015 / T016 [P] 先于 T017
- **Phase 5 (US3)**:依赖 Phase 2;独立于 US1 / US2;T018 / T019 [P] 先于 T020
- **Phase 6 (Polish)**:依赖前述所有 phase 至少一遍 GREEN;T021 / T022 / T023 [P] 同跑;T024 必在 T021/T022/T023 后;T025 必在 impl 全部完成后;T026 / T027 / T028 顺序无要求,T028 是最后一道审查

### User Story Dependencies

- **US1 (P1, state_changed)**:Foundational → US1 独立可交付为 MVP
- **US2 (P2, log_chunked)**:Foundational → US2,不强依赖 US1,但建议接在 US1 之后(共用 ProcessManager 调试)
- **US3 (P3, stalled)**:Foundational → US3;独立交付

### Within Each User Story

- 测试先写、必须 RED,再写 impl 让其 GREEN
- Foundational 改 ProcessRecord / wait_for_event 框架,**不**改入口语义,因此可独立完成
- 跨 story 的回归靠 `tests/execution/test_process_manager_events.py` 总和 + integration 三条端到端

### Parallel Opportunities

- T002 与 T003:两个不同文件,并行
- T006(emit + ring buffer 单测)与 T007(wait 框架)写完 T005 后并行
- T008 / T009 / T010 / T011:都是测试文件 / 不同测试用例,并行
- T015 / T016:不同测试文件,并行
- T018 / T019:同一测试文件不同用例,可串行也可并行(注意冲突已被 Test ID 隔离)
- T021 / T022 / T023:不同测试文件,并行
- 但:T012(_refresh_locked emit)、T017(reader emit)、T020(wait stalled 懒判定)都改 `process_manager.py` 同文件,**必须串行**

---

## Parallel Example: User Story 1

```bash
# 同时跑(不同文件):
Task: "T008 ProcessManager state_changed 单测 in tests/execution/test_process_manager_events.py"
Task: "T009 wait_for_event 阻塞/唤醒/超时单测 in tests/execution/test_process_manager_events.py"
Task: "T010 工具层归属/钳位单测 in tests/business/agents/tools/test_process_event_tool.py"
Task: "T011 集成 state_changed 端到端 in tests/integration/test_process_event_flow.py"
# 全 RED 后:
Task: "T012 _refresh_locked emit state_changed in src/execution/process_manager.py"
Task: "T013 + T014 wait_for_process_event handler + register in src/business/agents/tools/command_tools.py"
```

---

## Implementation Strategy

### MVP First(US1)

1. Phase 1 → T001(几秒)
2. Phase 2:T002 / T003 并行 → T004 → T005 → T006 / T007 并行 →(全绿)
3. Phase 3:T008..T011 全部并行写完 → 验证 RED → T012 → T013 → T014 → 跑测全绿 → MVP 可交付

### Incremental Delivery

- MVP(US1)交付后,再做 US2(log_chunked),不影响 US1 绿
- US2 完成后做 US3(stalled),仍不影响前两者
- Polish 阶段在三 story 全绿后跑一遍

### Parallel Team Strategy

单人开发场景,直接按 MVP First 顺序走;团队场景在 Foundational 完成后,US1 / US2 / US3 可分给三人,但 `process_manager.py` 文件级 merge conflict 风险高,建议串行 emit 改动。

---

## Notes

- [P] = 不同文件、无依赖,可并行
- 所有 impl 任务都改 `src/...`、所有测试任务都改 `tests/...`;改 spec / plan / design doc 任何一个 → 暂停 implement 阶段,先回到 `/speckit-clarify` 或 `/speckit-plan`
- 测试用真子进程而不是 mock subprocess(参见 plan.md R-008 决策);Windows / macOS / Linux 上均用 `python -c "..."` 保持跨平台
- 既有 `process_poll` / `process_logs` / `process_wait` 行为 + 签名 + 测试 MUST 全程不动(spec FR-010 / CC-001)
- 不引入 blinker 事件、不进 UI Event Registry、不持久化、不抽通用 bus(spec FR-011 / FR-012 / CC-006);任一发现违反 → 暂停回 plan
- 完成所有任务后,worktree 状态应是:8 个 spec/plan 产物 + 4 个 src 文件 mod + 3 个 tests 文件 new + 1 个可选 src/AGENTS.md mod
