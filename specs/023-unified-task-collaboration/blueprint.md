# Blueprint: 统一任务模型 + 多范式协作

**Branch**: `023-unified-task-collaboration` | **Date**: 2026-06-17
**Mode**: `doc-only`
**Total Tasks**: 119 | **Files**: 51 new, 31 modified, 0 deleted

## Scope

本蓝图覆盖 `specs/023-unified-task-collaboration/tasks.md` 的全部任务。`doc-only` 模式只生成本文档，不创建实现文件。实现时必须保持项目分层：前端通过 typed API 和事件投影访问能力，desktop API 只做 DTO、鉴权、错误映射和业务入口适配，业务语义由 `src/business/task_collaboration` 提供，持久化只能走 Repository。

## Key Decisions

- 新增 Assistant Task 图作为任务、委派、子任务、看板、会议和 Todo 的业务事实源；`workflow_transitions` 保留为 Debug Inspector 和审计线索，不作为 UI/API 的任务真相。→ T011, T037, T046
- Task 与 TaskAttempt 分离：Task 保存持久工作项，Attempt 保存运行实例、lease、checkpoint 和 fence token。→ T013, T016, T039
- 父侧裁定进入 `assistant_task_adjudications`，不是 Task 状态；Task 只保留 `pending_dispatch`, `running`, `suspended`, `completed`, `failed`, `cancelled` 六态。→ T009, T019, T023, T059
- 委派工具返回 `accepted`, `taskId`, `graphId`, `assignment`，父 agent 进入 parking 和重入流程，不同步等待子任务完成。→ T038, T044, T045
- 并发执行以 DB-backed claim、attempt lease 和 per-worker Repository session 控制；每个 executor 同时最多一个 active attempt。→ T020, T038, T079
- 副作用前必须写 Operation 记录，成功后写 completion marker；未知幂等性或 `unsafe_to_retry` 进入父侧裁定。→ T017, T054, T055, T060, T061
- Stop 只作用当前用户请求 graph，Cancel 才做终态级联；迟到结果必须按 graph version、task version 和 fence token 幂等拒绝。→ T056, T062
- 用户 pending clarification 和原始答案仍只在进程内；agent-to-agent question route 可持久化，但公开投影只暴露安全摘要。→ T018, T078
- 会议通道仅允许两名执行者交换消息，不代理工具、不扩授权；超预算或互等关闭并创建父侧裁定。→ T080, T081, T082
- Todo 是 executor 私有 checklist，不生成 Task 节点，不参与依赖、裁定或 brain distillation。→ T092, T097, T105
- 公共 UI 事件只走 `src/desktop_api/ui_events.py` 注册 allowlist，前端 validators 必须与后端 payload 契约同步。→ T012, T042, T048, T083, T099, T107
- v15/v16 MVP 默认 clean-start cutover，不双写 legacy transition 和新 Task 图；v15 建表、v16 加 active-attempt 约束，回退关闭 unified dispatch 但不删除审计数据。→ T014, T026, T033
- Root graph terminal failure 才桥接到 `assistant_run_failures`；局部子任务失败保留在 graph/adjudication 内。→ T057, T063, T064, T071

## Implementation Order

```text
Phase 1 setup
  T001, T002, T003, T004, T005, T006
Phase 2 foundation
  T007, T008, T009, T010, T011, T012
  T013, T014
  T015, T016, T017, T018, T019, T020, T021, T022
  T023, T024, T025, T026, T027, T028
User Story 1 gate
  T029, T030, T031, T032, T033, T034, T035, T036
  T037, T038, T039, T040, T041, T042, T043, T044, T045, T046, T047, T048, T049, T050, T051, T052
User Story 2 gate
  T053, T054, T055, T056, T057, T058
  T059, T060, T061, T062, T063, T064, T065, T066, T067, T068, T069, T070, T071
User Story 3 gate
  T072, T073, T074, T075, T076, T077
  T078, T079, T080, T081, T082, T083, T084, T085, T086, T087, T088, T089, T090, T091
User Story 4 gate
  T092, T093, T094, T095, T096
  T097, T098, T099, T100, T101, T102, T103, T104, T105, T106
Polish and verification
  T107, T108, T109, T110, T111, T112, T113, T114, T115, T116, T117, T118, T119
```

## Reference Patterns Read

- `src/data/repos/base_repository.py`: Repository session and transaction conventions.
- `src/data/models_sqlite.py`: SQLAlchemy declarative model style and indexed column conventions.
- `src/data/migrations.py`: SQLite migration registration and idempotent DDL style.
- `src/desktop_api/routers/assistant.py`: FastAPI router adapter pattern.
- `src/desktop_api/schemas.py`: Pydantic DTO naming and redaction projection style.
- `src/desktop_api/ui_events.py`: UI Event Registry authority and allowlist shape.
- `src/desktop_api/ui_event_projector.py`: internal blinker event to public draft projection pattern.
- `src/business/agents/tools/assistant_tools.py`: Agent tool handler registration and output contracts.
- `frontend/src/api/uiEvents.ts`: frontend event validator pattern.
- `frontend/src/state/assistantStore.ts`: Zustand-style frontend store and resync handling.

## Phase 1: Setup

### T001: Create task collaboration package scaffolding

**File**: `src/business/task_collaboration/__init__.py` (new)

**Requirements**: package bootstrap.
**Dependencies**: none.
**Implementation contract**: create a side-effect-free package initializer with an explanatory module docstring and, after T023 lands, stable exports for public business-layer DTOs and services only. It must not import repositories at module import time.
**Verification**: `uv run python -m compileall src/business/task_collaboration` succeeds and importing `src.business.task_collaboration` performs no database work.

### T002: Create task collaboration router module

**File**: `src/desktop_api/routers/assistant_tasks.py` (new)

**Requirements**: REST adapter bootstrap.
**Dependencies**: none.
**Implementation contract**: create an `APIRouter` module with sidecar-token compatible dependency wiring following `src/desktop_api/routers/assistant.py`. Route handlers are added in T041, T065, T084 and T100; the module must not access repositories directly.
**Verification**: importing the module exposes `router` and does not change app routes until T028 registers it.

### T003: Create frontend task API client module

**File**: `frontend/src/api/assistantTasks.ts` (new)

**Requirements**: typed client bootstrap.
**Dependencies**: none.
**Implementation contract**: create a typed module that centralizes task collaboration DTO types, request helpers and runtime-token aware calls. Endpoint functions are filled by T047, T068, T086 and T102, using existing frontend API conventions.
**Verification**: TypeScript compilation accepts imports from this module before UI wiring begins.

### T004: Create frontend task store module

**File**: `frontend/src/state/assistantTaskStore.ts` (new)

**Requirements**: frontend state bootstrap.
**Dependencies**: none.
**Implementation contract**: define the store boundary for graph, board, meeting and Todo slices with actions added in later user stories. Store code must only consume `assistantTasks.ts` and public UI event validators.
**Verification**: unit tests can import store factory without requiring a live backend.

### T005: Create task graph panel module

**File**: `frontend/src/screens/assistant/TaskGraphPanel.tsx` (new)

**Requirements**: React component bootstrap.
**Dependencies**: T004.
**Implementation contract**: create the component entry point and prop surface used by AssistantScreen. Final interactive graph behavior lands in T050 and T070.
**Verification**: component renders without throwing in a minimal unit render.

### T006: Create backend task collaboration test package marker

**File**: `tests/business/task_collaboration/__init__.py` (new)

**Requirements**: test package bootstrap.
**Dependencies**: none.
**Implementation contract**: create an empty package marker for business task collaboration tests.
**Verification**: pytest collection under `tests/business/task_collaboration` does not fail because of package resolution.

## Phase 2: Foundation

### T007: Add migration coverage for task collaboration tables and indexes

**File**: `tests/data/test_assistant_task_migration.py` (new)

**Requirements**: data model, v15/v16 schema, index requirements.
**Dependencies**: T013, T014.
**Implementation contract**: assert every v15 table from `data-model.md` exists, all enumerated indexes including v16 active-attempt partial unique indexes exist, migrations are idempotent, clean-start guard metadata is present, and legacy `pending_assistant_tasks` compatibility remains available.
**Verification**: `uv run python -m pytest tests/data/test_assistant_task_migration.py -q`.

### T008: Add repository CRUD and transaction tests

**File**: `tests/data/test_assistant_task_repositories.py` (new)

**Requirements**: repository contracts for Task, Attempt, Operation, Question, Adjudication, Claim, Meeting and Todo.
**Dependencies**: T015, T016, T017, T018, T019, T020, T021, T022.
**Implementation contract**: cover create, update, snapshot, transaction rollback, optimistic version checks, redacted projection data, lease expiry scans and unique non-failed operation key behavior.
**Verification**: `uv run python -m pytest tests/data/test_assistant_task_repositories.py -q`.

### T009: Add state-machine tests

**File**: `tests/business/agents/test_task_state_machine.py` (new)

**Requirements**: Task, Attempt, Operation, Claim, Adjudication, Stop, Cancel and Recovery transitions.
**Dependencies**: T023.
**Implementation contract**: table-drive allowed and rejected transitions. Terminal Task states must not revive, suspended tasks require a suspend reason, returned adjudication reopens to `pending_dispatch`, and fenced attempts reject late mutation.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_state_machine.py -q`.

### T010: Add layering and 100% dispatch guard tests

**File**: `tests/guardrails/test_assistant_task_boundaries.py` (new)

**Requirements**: architecture guardrails, no direct UI/data coupling, main Assistant not executor.
**Dependencies**: T023, T037.
**Implementation contract**: assert desktop API imports business services rather than repositories, frontend imports typed API rather than backend internals, TaskAttempt executor type excludes main Assistant, and task collaboration code does not bypass `UnifiedConfigManager`.
**Verification**: `uv run python -m pytest tests/guardrails/test_assistant_task_boundaries.py -q`.

### T011: Add transition-source guard test

**File**: `tests/guardrails/test_assistant_task_transition_source.py` (new)

**Requirements**: new task truth source, no `workflow_transitions` derived UI/API task state.
**Dependencies**: T037, T046.
**Implementation contract**: inspect backend runtime and API paths to prove task graph snapshots are built from task repositories and not from `build_subagent_list` or transition log reconstruction.
**Verification**: `uv run python -m pytest tests/guardrails/test_assistant_task_transition_source.py -q`.

### T012: Add backend/frontend event contract sync test

**File**: `tests/desktop_api/test_assistant_task_event_contract_sync.py` (new)

**Requirements**: public UI event registry and frontend validators.
**Dependencies**: T042, T048, T083, T087, T099, T103.
**Implementation contract**: load backend task event allowlists and frontend event contract examples, then assert event types, required keys and allowed keys match for graph, board, meeting and Todo events.
**Verification**: `uv run python -m pytest tests/desktop_api/test_assistant_task_event_contract_sync.py -q`.

### T013: Define SQLAlchemy ORM models

**File**: `src/data/models_sqlite.py` (modify)

**Requirements**: all entities in `data-model.md`.
**Dependencies**: none.
**Implementation contract**: add ORM classes for tasks, edges, questions, attempts, operations, adjudications, claims, meeting channels, meeting messages and Todo items. Use existing timestamp, JSON text and index style; keep public projection-only fields such as `display_phase` out of DB models.
**Verification**: model metadata contains all new tables and import of `src.data.models_sqlite` succeeds.

### T014: Implement SQLite v15/v16 migrations

**File**: `src/data/migrations.py` (modify)

**Requirements**: v15 schema, v16 active-attempt indexes, clean-start cutover guard, rollback strategy.
**Dependencies**: T013.
**Implementation contract**: add idempotent migrations that create all v15 tables/indexes, add v16 active-attempt partial unique indexes, record clean-start metadata, preserve legacy queue compatibility, and do not backfill `workflow_transitions` unless an explicit implementation switch is added before schema work.
**Verification**: T007 passes and an existing DB with legacy rows migrates without data loss.

### T015: Implement Task and Edge repository

**File**: `src/data/repos/assistant_task_repository.py` (new)

**Requirements**: Task graph CRUD, version fencing, cycle checks.
**Dependencies**: T013, T014.
**Implementation contract**: provide repository methods for creating root and child tasks, adding typed edges, querying graph snapshots, updating task status with optimistic `task_version`, checking dependency cycles and enforcing terminal-state immutability.
**Verification**: T008 graph repository cases pass.

### T016: Implement TaskAttempt repository

**File**: `src/data/repos/assistant_task_attempt_repository.py` (new)

**Requirements**: leases, heartbeats, fence scans and stale result rejection.
**Dependencies**: T013, T014.
**Implementation contract**: expose methods to start attempts, heartbeat, finish, pause, fail, cancel, fence expired active attempts, increment fence tokens and reject result writes with stale tokens.
**Verification**: T008 and T030 pass.

### T017: Implement TaskOperation repository

**File**: `src/data/repos/assistant_task_operation_repository.py` (new)

**Requirements**: idempotency and side-effect markers.
**Dependencies**: T013, T014.
**Implementation contract**: record planned, in-progress, completed, failed and unsafe-to-retry operations; enforce one non-failed `(task_id, operation_key)` record; expose recovery queries by attempt and task.
**Verification**: T008, T054 and T055 pass.

### T018: Implement TaskQuestion repository

**File**: `src/data/repos/assistant_task_question_repository.py` (new)

**Requirements**: persisted agent-to-agent question route, expiry, safe summaries.
**Dependencies**: T013, T014.
**Implementation contract**: create, escalate, answer, cancel and expire questions; persist capability deltas only when they are bounded by parent scope; never persist raw user answers.
**Verification**: T008 and T072 pass.

### T019: Implement TaskAdjudication repository

**File**: `src/data/repos/assistant_task_adjudication_repository.py` (new)

**Requirements**: parent-side accept, return and abandon decisions.
**Dependencies**: T013, T014.
**Implementation contract**: create at most one pending adjudication per task, decide once, store safe summaries and private raw result refs, and support parent-session scoped pending queries.
**Verification**: T008 and T053 pass.

### T020: Implement TaskClaim repository

**File**: `src/data/repos/assistant_task_board_repository.py` (new)

**Requirements**: open board claim, release, rejection history and lease expiry.
**Dependencies**: T013, T014.
**Implementation contract**: atomically claim unassigned tasks by matching `task_version`, record rejected claimers, expire stale claims, and release or complete claims when attempts finish.
**Verification**: T008 and T073 pass.

### T021: Implement Meeting repository

**File**: `src/data/repos/assistant_meeting_repository.py` (new)

**Requirements**: channel lifecycle and paged messages.
**Dependencies**: T013, T014.
**Implementation contract**: open supervised two-party channels, append participant-only messages with monotonic sequence, page transcript by `afterSequence` and `limit`, conclude or timeout channels with safe conclusion data.
**Verification**: T008 and T074 pass.

### T022: Implement Todo repository

**File**: `src/data/repos/assistant_todo_repository.py` (new)

**Requirements**: private per-task executor checklist.
**Dependencies**: T013, T014.
**Implementation contract**: create, replace, reorder, update and list Todo items by task and executor, with stable sort order and completed timestamp management.
**Verification**: T008 and T092 pass.

### T023: Define task collaboration business models

**File**: `src/business/task_collaboration/models.py` (new)

**Requirements**: enums, DTO dataclasses, projection helpers and state validators.
**Dependencies**: T013.
**Implementation contract**: define closed enums matching `data-model.md`, DTOs for business inputs and safe snapshots, transition validators, suspend-reason checks, display-phase derivation and redaction helpers that hide attempt, fence, lease, raw output and local path details.
**Verification**: T009 passes and DTOs serialize through T040 schemas without lossy enum conversion.

### T024: Add config defaults and getters

**File**: `src/data/unified_config.py` (modify)

**Requirements**: `assistant_tasks.*` settings through unified config.
**Dependencies**: none.
**Implementation contract**: add defaults and getters for dispatcher worker count, attempt lease seconds, meeting turn budget, meeting time budget, API page limit, recovery scan interval and unified dispatch cutover flags. Do not read config files or tables directly from task services.
**Verification**: guard test T010 proves task services use `UnifiedConfigManager`.

### T025: Add internal blinker events

**File**: `src/utils/events.py` (modify)

**Requirements**: internal task collaboration events.
**Dependencies**: T023.
**Implementation contract**: register internal events for graph change, board change, meeting change, Todo change, adjudication creation/decision and root graph terminal failure. Payloads remain internal and are projected through T043 and T067 before reaching UI.
**Verification**: event projector tests can subscribe without importing frontend or desktop API from business code.

### T026: Implement clean-start cutover guard

**File**: `src/business/task_collaboration/cutover.py` (new)

**Requirements**: v15/v16 clean-start default and rollback disable path.
**Dependencies**: T024.
**Implementation contract**: centralize feature enablement, clean-start validation, legacy state detection and rollback-disable behavior. Guard must prevent simultaneous task truth from legacy transitions and new repositories.
**Verification**: T033 passes and disabling unified dispatch does not delete legacy audit rows.

### T027: Preserve pending task compatibility

**File**: `src/data/repos/pending_task_repository.py` (modify)

**Requirements**: legacy codify and bug queue compatibility.
**Dependencies**: T014.
**Implementation contract**: keep existing `pending_assistant_tasks` behavior for `report_tool_bug` and `codify_as_tool` queues while making any table rename or migration compatibility explicit. Do not route these legacy queues through Assistant Task graph.
**Verification**: existing pending task repository tests continue passing and T007 verifies compatibility after v15/v16.

### T028: Register assistant task router

**File**: `src/desktop_api/app.py` (modify)

**Requirements**: sidecar route registration.
**Dependencies**: T002.
**Implementation contract**: include `assistant_tasks.router` under the same runtime-token protected API conventions as existing assistant routers. Keep app startup side effects unchanged.
**Verification**: route list includes task endpoints after T041 and existing assistant routes remain available.

## User Story 1: Sub-agent work is visible, durable and parallel

### T029: Add async dispatch tests with fake executors

**File**: `tests/business/agents/test_task_dispatch_async.py` (new)

**Requirements**: parallel observable graph, accepted async dispatch.
**Dependencies**: T037, T038.
**Implementation contract**: use fake executors and fake delays to assert independent tasks overlap, parent tool call returns accepted task IDs, parking does not block child completion and graph snapshots update before final answer.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_dispatch_async.py -q`.

### T030: Add crash recovery and fence tests

**File**: `tests/business/agents/test_task_recovery.py` (new)

**Requirements**: expired lease recovery, fence token, late-result rejection.
**Dependencies**: T016, T039.
**Implementation contract**: create expired active attempts, run startup recovery, assert old attempts become fenced, tasks suspend with `waiting_system`, missing checkpoint creates adjudication and stale result writes are idempotent no-ops.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_recovery.py -q`.

### T031: Add task graph snapshot API tests

**File**: `tests/desktop_api/test_assistant_task_api.py` (new)

**Requirements**: graph snapshot REST contract and safe DTOs.
**Dependencies**: T040, T041.
**Implementation contract**: assert current graph and specific graph endpoints return session-scoped snapshots, 404 or null behavior hides archived/deleted sessions, and projections redact internal execution fields.
**Verification**: `uv run python -m pytest tests/desktop_api/test_assistant_task_api.py -q`.

### T032: Add task graph UI event tests

**File**: `tests/desktop_api/test_assistant_task_events.py` (new)

**Requirements**: graph event registry and projector.
**Dependencies**: T042, T043.
**Implementation contract**: assert `assistant.task_graph.changed` is registered with required and allowed payload keys, projector emits safe fields and `backend.resync_required` domains include `assistant_tasks`.
**Verification**: `uv run python -m pytest tests/desktop_api/test_assistant_task_events.py -q`.

### T033: Add clean-start cutover smoke test

**File**: `tests/integration/test_assistant_task_cutover.py` (new)

**Requirements**: v15/v16 clean-start and no dual truth.
**Dependencies**: T026, T037.
**Implementation contract**: run migration with legacy rows, enable unified dispatch, assert new UI/API snapshots only read Task graph repositories, and verify rollback disable preserves legacy audit data.
**Verification**: `uv run python -m pytest tests/integration/test_assistant_task_cutover.py -q`.

### T034: Add frontend task graph store tests

**File**: `frontend/tests/unit/assistant-task-store.test.ts` (new)

**Requirements**: graph snapshot, event application and resync.
**Dependencies**: T049.
**Implementation contract**: test initial load, ordered event application, duplicate/old event ignore, resync-required handling, derived display phases and safe failure projection.
**Verification**: `cd frontend; npm run test -- assistant-task-store`.

### T035: Add frontend task graph panel tests

**File**: `frontend/tests/unit/assistant-task-panels.test.tsx` (new)

**Requirements**: accessible compact and expanded task graph UI.
**Dependencies**: T050.
**Implementation contract**: render empty, loading, running, reviewing, paused and done graph states; assert accessible names and keyboard expansion behavior.
**Verification**: `cd frontend; npm run test -- assistant-task-panels`.

### T036: Add task graph E2E smoke

**File**: `frontend/tests/e2e/assistant-task-graph.spec.ts` (new)

**Requirements**: browser-level mock API smoke.
**Dependencies**: T050, T051, T052.
**Implementation contract**: run Assistant screen against mock task endpoints and events, assert graph appears, status changes stream in and resync reloads authoritative snapshot.
**Verification**: `cd frontend; npm run test:e2e -- assistant-task-graph`.

### T037: Implement authoritative task graph facade

**File**: `src/business/task_collaboration/service.py` (new)

**Requirements**: graph creation, snapshot building, version checks and redaction.
**Dependencies**: T015, T016, T019, T023, T025, T026.
**Implementation contract**: expose business operations for root graph creation, child task creation, dependency edges, status transitions, snapshot building, graph version fencing and session visibility filtering. All public DTOs must use safe projections.
**Verification**: T029, T031, T033 and T034 pass.

### T038: Implement bounded async dispatcher

**File**: `src/business/task_collaboration/dispatcher.py` (new)

**Requirements**: durable enqueue, parking, parent re-entry, per-worker Repository session.
**Dependencies**: T015, T016, T017, T020, T023, T024, T037.
**Implementation contract**: accept directed and board tasks, start bounded workers, claim eligible tasks atomically, start attempts with leases, park parent until adjudication or child completion and emit internal graph events. Each worker must create its own Repository/session scope.
**Verification**: T029 passes and no SQLAlchemy Session is shared across worker threads.

### T039: Implement TaskAttempt recovery

**File**: `src/business/task_collaboration/recovery.py` (new)

**Requirements**: lease recovery, fence handling, checkpoint lookup and stale result rejection.
**Dependencies**: T016, T017, T019, T023, T037.
**Implementation contract**: on startup or scheduled scan, fence expired attempts, suspend tasks with `waiting_system`, resume from safe checkpoint when possible, create adjudication when not safe, and reject stale completion attempts without emitting success UI events.
**Verification**: T030 passes.

### T040: Implement graph snapshot DTO schemas

**File**: `src/desktop_api/schemas.py` (modify)

**Requirements**: graph snapshot, task, edge and adjudication DTOs.
**Dependencies**: T023, T037.
**Implementation contract**: add Pydantic schemas matching contract field names such as `graphId`, `taskId`, `descriptionPreview`, `displayPhase`, `requiresReview`, `safeExplanation` and `updatedAt`. Schemas must not include lease, fence, raw result refs, local paths or stack traces.
**Verification**: T031 passes and schema serialization matches frontend DTOs.

### T041: Implement current graph and graph snapshot endpoints

**File**: `src/desktop_api/routers/assistant_tasks.py` (modify)

**Requirements**: GET current graph and GET graph by ID.
**Dependencies**: T037, T040.
**Implementation contract**: implement `/api/assistant/sessions/{sessionId}/task-graphs/current` and `/api/assistant/sessions/{sessionId}/task-graphs/{graphId}` by calling business service methods, enforcing session scope and mapping missing data to null or 404 as specified.
**Verification**: T031 passes.

### T042: Register task graph UI event

**File**: `src/desktop_api/ui_events.py` (modify)

**Requirements**: `assistant.task_graph.changed` and resync domains.
**Dependencies**: T025.
**Implementation contract**: register event type, required keys, allowlist and `backend.resync_required` domains for task graph changes. Allowed fields must mirror contract and omit internal execution terms.
**Verification**: T032 and T012 pass.

### T043: Project task graph events

**File**: `src/desktop_api/ui_event_projector.py` (modify)

**Requirements**: safe projection from internal graph events.
**Dependencies**: T025, T042.
**Implementation contract**: map internal graph change events to public drafts with safe payload fields, monotonically scoped sequence handling and resync fallback when payload cannot be safely projected.
**Verification**: T032 passes.

### T044: Replace synchronous delegation tool return

**File**: `src/business/agents/tools/assistant_tools.py` (modify)

**Requirements**: `delegate_task` accepted async output.
**Dependencies**: T037, T038.
**Implementation contract**: make delegation create durable task records through dispatcher and return `accepted`, `taskId`, `graphId` and `assignment`. The tool remains side-effecting and must not be marked concurrency-safe.
**Verification**: T029 proves parent receives accepted output without blocking on child completion.

### T045: Wire Orchestrator delegation to TaskDispatcher

**File**: `src/business/orchestration/agent/orchestrator.py` (modify)

**Requirements**: parking, parent re-entry and main Assistant coordinator role.
**Dependencies**: T038, T044.
**Implementation contract**: route delegation entry points through `TaskDispatcher`, park parent execution at safe points, resume parent on adjudication or completion events and prevent main Assistant from owning user-work attempts.
**Verification**: T029 and T010 pass.

### T046: Stop using build_subagent_list as task truth

**File**: `src/desktop_api/assistant_runtime.py` (modify)

**Requirements**: no transition-derived task UI/API truth.
**Dependencies**: T037.
**Implementation contract**: keep `build_subagent_list` for legacy progress or debug surfaces only, and route new task graph UI/API paths to `TaskCollaborationService` snapshots.
**Verification**: T011 passes.

### T047: Implement task graph API client functions

**File**: `frontend/src/api/assistantTasks.ts` (modify)

**Requirements**: typed graph snapshot API.
**Dependencies**: T040, T041.
**Implementation contract**: add DTOs and functions for current graph and graph by ID. Use existing runtime-token client conventions and normalize null current graph responses.
**Verification**: T034 passes.

### T048: Mirror task graph event types and validators

**File**: `frontend/src/api/uiEvents.ts` (modify)

**Requirements**: frontend public event contract.
**Dependencies**: T042.
**Implementation contract**: add validators for `assistant.task_graph.changed` and task resync domains using the same required and allowed keys as backend registry.
**Verification**: T012 and T107 pass.

### T049: Implement graph store logic

**File**: `frontend/src/state/assistantTaskStore.ts` (modify)

**Requirements**: snapshot, event application, resync and display phases.
**Dependencies**: T047, T048.
**Implementation contract**: store graph snapshot by session and graph ID, apply ordered events, ignore stale sequence, trigger authoritative reload on resync-required and derive display labels from public projection fields only.
**Verification**: T034 passes.

### T050: Implement task graph UI

**File**: `frontend/src/screens/assistant/TaskGraphPanel.tsx` (modify)

**Requirements**: accessible compact and expandable graph.
**Dependencies**: T049.
**Implementation contract**: render dense task graph status for current request with stable dimensions, keyboard-accessible expand/collapse, safe summaries, reviewing and paused states, and no internal fence/lease wording.
**Verification**: T035 passes.

### T051: Mount graph panel in Assistant screen

**File**: `frontend/src/screens/assistant/AssistantScreen.tsx` (modify)

**Requirements**: current-request progress strip and graph visibility.
**Dependencies**: T049, T050.
**Implementation contract**: mount the task graph panel where Assistant progress belongs, subscribe to store lifecycle with session awareness and avoid showing it when no current graph exists.
**Verification**: T036 passes.

### T052: Add task graph mock API routes

**File**: `frontend/tests/e2e/mock-api.ts` (modify)

**Requirements**: E2E mock graph endpoints and event fixtures.
**Dependencies**: T047, T048.
**Implementation contract**: add current graph, graph by ID and event-stream fixtures for graph created, task updated, reviewing, paused and completed states.
**Verification**: T036 passes.

## User Story 2: Recovery, stop and adjudication are safe

### T053: Add adjudication tests

**File**: `tests/business/agents/test_task_adjudication.py` (new)

**Requirements**: accept, return and abandon semantics.
**Dependencies**: T019, T059.
**Implementation contract**: assert accepted completes delivered task, returned reopens with instruction and increments task version, abandoned fails task and cascades parent wake behavior.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_adjudication.py -q`.

### T054: Add idempotent operation recovery tests

**File**: `tests/business/agents/test_task_idempotency.py` (new)

**Requirements**: completed side effects are not repeated.
**Dependencies**: T017, T060.
**Implementation contract**: simulate pre-effect and completed operation markers, then assert recovery retries only safe cases and never repeats completed external side effects.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_idempotency.py -q`.

### T055: Add negative idempotency tests

**File**: `tests/business/agents/test_task_idempotency_negative.py` (new)

**Requirements**: duplicate operation key, unsafe retry and stale fenced result rejection.
**Dependencies**: T017, T039, T061.
**Implementation contract**: assert duplicate non-failed operation keys fail, `unsafe_to_retry` creates parent adjudication and stale fenced result after later success emits no success event.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_idempotency_negative.py -q`.

### T056: Add stop, continue and cancel race tests

**File**: `tests/business/agents/test_task_recovery.py` (modify)

**Requirements**: graph-scoped stop, continue, cancel and replan ordering.
**Dependencies**: T039, T062.
**Implementation contract**: extend recovery tests with two active graphs in one session, graph-scoped stop, continue from `user_stop`, cascading cancel and late cancelled-success rejection.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_recovery.py -q`.

### T057: Add failure bridge integration tests

**File**: `tests/integration/test_assistant_task_failure_bridge.py` (new)

**Requirements**: only root graph terminal failure bridges to assistant run failures.
**Dependencies**: T063, T064.
**Implementation contract**: fail child task without root terminal failure and assert no failure card row; then fail root graph terminally and assert safe failure projection is persisted.
**Verification**: `uv run python -m pytest tests/integration/test_assistant_task_failure_bridge.py -q`.

### T058: Add frontend stop, continue and adjudication tests

**File**: `frontend/tests/unit/assistant-task-store.test.ts` (modify)

**Requirements**: UI state transitions for recovery controls.
**Dependencies**: T068, T069, T070.
**Implementation contract**: cover optimistic pending command state, authoritative event reconciliation, error rollback and review decision state changes.
**Verification**: `cd frontend; npm run test -- assistant-task-store`.

### T059: Implement adjudication service

**File**: `src/business/task_collaboration/adjudication.py` (new)

**Requirements**: parent-side accept, return and abandon.
**Dependencies**: T019, T023, T037.
**Implementation contract**: create pending adjudications from delivered or stuck tasks, apply decisions exactly once, validate returned instruction, update task status and version inside one transaction, emit internal events and wake parent execution.
**Verification**: T053 passes.

### T060: Enforce side-effect operation records

**File**: `src/business/task_collaboration/dispatcher.py` (modify)

**Requirements**: operation marker before side effects and completion marker after success.
**Dependencies**: T017, T038.
**Implementation contract**: wrap side-effecting tool or external actions with `AssistantTaskOperation` creation before execution, in-progress state while executing and completion marker after success. Unknown idempotency must not auto-retry.
**Verification**: T054 passes.

### T061: Implement unsafe retry and cancel/replan ordering

**File**: `src/business/task_collaboration/recovery.py` (modify)

**Requirements**: unsafe retry to adjudication and cancel/replan race handling.
**Dependencies**: T039, T059, T060.
**Implementation contract**: route `unsafe_to_retry` and unknown operation states to parent adjudication, preserve terminal cancel over later replan, and reject stale late results for cancelled tasks.
**Verification**: T055 and T056 pass.

### T062: Implement graph stop, continue and cancel

**File**: `src/business/task_collaboration/service.py` (modify)

**Requirements**: stop current graph, continue `user_stop`, cascading cancel.
**Dependencies**: T037, T039, T059.
**Implementation contract**: add graph-scoped stop that marks active tasks `suspended/user_stop`, continue that resumes only that graph, cancel that terminally cascades according to edges and graph version checks that reject stale commands.
**Verification**: T056 passes.

### T063: Implement root failure bridge

**File**: `src/business/task_collaboration/failure_bridge.py` (new)

**Requirements**: root graph terminal failure to AssistantRunFailureService only.
**Dependencies**: T037.
**Implementation contract**: convert root graph terminal failure into safe assistant failure input, skip partial child failures, redact diagnostics and preserve graph identifiers for Debug Inspector navigation.
**Verification**: T057 passes.

### T064: Wire failure bridge safely

**File**: `src/business/services/assistant_failure_service.py` (modify)

**Requirements**: integrate task root failure without leaking diagnostics.
**Dependencies**: T063.
**Implementation contract**: expose a narrow method or adapter used by task failure bridge, reusing existing failure state machine and safe projection rules without making ordinary task services depend on desktop API.
**Verification**: T057 passes and existing assistant failure retry tests remain green.

### T065: Add stop, continue and adjudication endpoints

**File**: `src/desktop_api/routers/assistant_tasks.py` (modify)

**Requirements**: command routes for graph recovery and review.
**Dependencies**: T059, T062, T066.
**Implementation contract**: implement POST stop, continue and adjudication decision routes with session scoping, DTO validation, business service calls and safe error mapping.
**Verification**: T031 extended command cases pass.

### T066: Add recovery DTO schemas

**File**: `src/desktop_api/schemas.py` (modify)

**Requirements**: adjudication, stop, cancel and failure bridge DTOs.
**Dependencies**: T059, T062, T063.
**Implementation contract**: add request and response schemas for graph stop, graph continue, adjudication decision and safe failure summaries. Returned decision must require non-empty instruction.
**Verification**: T031 and T057 pass.

### T067: Project adjudication, stop, cancel and failure events

**File**: `src/desktop_api/ui_event_projector.py` (modify)

**Requirements**: safe event projection for recovery and review.
**Dependencies**: T025, T042, T059, T062, T063.
**Implementation contract**: project adjudication created/decided, graph stopped, graph continued, graph cancelled and root failure events through existing allowlists with safe summaries only.
**Verification**: T032 extended cases pass.

### T068: Add command methods to frontend task API

**File**: `frontend/src/api/assistantTasks.ts` (modify)

**Requirements**: stop, continue and adjudication commands.
**Dependencies**: T065, T066.
**Implementation contract**: add typed functions for stop graph, continue graph and adjudication decision with request validation and consistent API error handling.
**Verification**: T058 passes.

### T069: Add recovery transitions to frontend store

**File**: `frontend/src/state/assistantTaskStore.ts` (modify)

**Requirements**: stop, continue and adjudication state.
**Dependencies**: T068.
**Implementation contract**: implement command pending state, optimistic disabled controls, authoritative event reconciliation and resync on command ambiguity.
**Verification**: T058 passes.

### T070: Add user-facing recovery controls

**File**: `frontend/src/screens/assistant/TaskGraphPanel.tsx` (modify)

**Requirements**: stop, continue and review controls.
**Dependencies**: T069.
**Implementation contract**: render controls only when graph state allows them, preserve keyboard focus after action, show safe review text and require instruction for return decisions.
**Verification**: T058 and T108 pass.

### T071: Render safe root failure summaries

**File**: `frontend/src/screens/assistant/AssistantScreen.tsx` (modify)

**Requirements**: root graph failure card without raw diagnostics.
**Dependencies**: T063, T064, T069.
**Implementation contract**: display root graph failure projection through existing failure UI affordance, link to current graph/debug context when available and never show raw provider errors, stack traces or local paths.
**Verification**: T057 and relevant frontend failure tests pass.

## User Story 3: Delegation can route questions, board work and meetings

### T072: Add persisted ask_parent tests

**File**: `tests/business/agents/test_task_questions.py` (new)

**Requirements**: clarification, resource request and capability request routing.
**Dependencies**: T018, T078.
**Implementation contract**: test agent-to-agent persistence, capability subset enforcement, user escalation without raw answer persistence and restart behavior that leaves task suspended with `waiting_user`.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_questions.py -q`.

### T073: Add board claim tests

**File**: `tests/business/agents/test_task_board_claims.py` (new)

**Requirements**: atomic claim, lease expiry, reject history and fallback executor.
**Dependencies**: T020, T079.
**Implementation contract**: race two claimers against one open task, assert exactly one wins, expire lease, exclude rejected claimers and verify fallback executor selection follows capability scope.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_board_claims.py -q`.

### T074: Add meeting tests

**File**: `tests/business/agents/test_task_meetings.py` (new)

**Requirements**: meeting budget, conclusion, timeout and message-only permission.
**Dependencies**: T021, T080.
**Implementation contract**: assert two participants only, transcript sequence ordering, no tool authorization changes, conclusion closes channel and budget exhaustion creates parent adjudication.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_meetings.py -q`.

### T075: Add board and meeting API tests

**File**: `tests/desktop_api/test_assistant_task_api.py` (modify)

**Requirements**: board listing and meeting transcript REST contracts.
**Dependencies**: T084, T085.
**Implementation contract**: extend API tests with task board list, meeting transcript paging, session scoping, archived session hiding and limit capping.
**Verification**: `uv run python -m pytest tests/desktop_api/test_assistant_task_api.py -q`.

### T076: Add board and meeting event tests

**File**: `tests/desktop_api/test_assistant_task_events.py` (modify)

**Requirements**: board and meeting public event contracts.
**Dependencies**: T083.
**Implementation contract**: assert event registration, required keys, allowed keys and projector redaction for board and meeting changes.
**Verification**: `uv run python -m pytest tests/desktop_api/test_assistant_task_events.py -q`.

### T077: Add frontend board and meeting panel tests

**File**: `frontend/tests/unit/assistant-task-panels.test.tsx` (modify)

**Requirements**: board and meeting UI behavior.
**Dependencies**: T089, T090, T091.
**Implementation contract**: render open board, claim pending, rejected, empty board, meeting transcript, loading messages, conclusion and timeout states with accessible controls.
**Verification**: `cd frontend; npm run test -- assistant-task-panels`.

### T078: Implement question service

**File**: `src/business/task_collaboration/questions.py` (new)

**Requirements**: persisted agent-to-agent question and capability request service.
**Dependencies**: T018, T023, T037.
**Implementation contract**: handle `ask_parent`, resource requests and capability requests, persist route state, enforce scope subset grants, escalate to existing in-memory user clarification only when needed and store safe answer summaries for agent hops.
**Verification**: T072 passes.

### T079: Implement board service

**File**: `src/business/task_collaboration/board.py` (new)

**Requirements**: open board listing, atomic claim, release, expiry, reject history and fallback selection.
**Dependencies**: T020, T023, T037, T038.
**Implementation contract**: list eligible open tasks, claim by version, release or reject with safe reason, expire claims, avoid rejected claimers unless parent overrides and trigger dispatcher attempt start after successful claim.
**Verification**: T073 passes.

### T080: Implement meeting service

**File**: `src/business/task_collaboration/meetings.py` (new)

**Requirements**: supervised two-party meeting channel lifecycle and pagination.
**Dependencies**: T021, T023, T024, T037, T059.
**Implementation contract**: open two-party message-only channels, append participant messages, enforce turn and time budgets, require safe conclusion for success and create parent adjudication on timeout or abandoned closure.
**Verification**: T074 passes.

### T081: Add question and meeting tool handlers

**File**: `src/business/agents/tools/assistant_tools.py` (modify)

**Requirements**: `ask_parent`, `open_meeting_channel` and `meeting_send_message`.
**Dependencies**: T078, T080.
**Implementation contract**: register side-effecting handlers with schemas from contracts, route to business services and return safe accepted or message result envelopes. These tools must not be concurrency-safe.
**Verification**: T072 and T074 pass.

### T082: Enforce capability scope and meeting no-tool-proxy rule

**File**: `src/business/orchestration/agent/orchestrator.py` (modify)

**Requirements**: specialist capability subset grants and meeting permission boundary.
**Dependencies**: T078, T080, T081.
**Implementation contract**: constrain resource and capability grants to parent frozen scope, ensure meetings only exchange messages and prevent meeting participants from using the channel to gain tool authorization.
**Verification**: T072 and T074 pass.

### T083: Register board, meeting and question events

**File**: `src/desktop_api/ui_events.py` (modify)

**Requirements**: public board, meeting, question and resource request event types.
**Dependencies**: T025, T078, T079, T080.
**Implementation contract**: register `assistant.task_board.changed`, `assistant.meeting.changed` and any public question/resource resync events with allowlists from contracts.
**Verification**: T076 and T012 pass.

### T084: Add board and meeting endpoints

**File**: `src/desktop_api/routers/assistant_tasks.py` (modify)

**Requirements**: task board list and meeting transcript routes.
**Dependencies**: T079, T080, T085.
**Implementation contract**: implement board list, claim/release commands if supported by service surface, and meeting transcript paging. Enforce session scope and configured limit caps.
**Verification**: T075 passes.

### T085: Add board, meeting and question schemas

**File**: `src/desktop_api/schemas.py` (modify)

**Requirements**: DTO schemas for board, meeting and question projections.
**Dependencies**: T078, T079, T080.
**Implementation contract**: add safe Pydantic schemas for board items, claim state, meeting participants, messages, conclusion, question projections and capability request summaries.
**Verification**: T075 passes.

### T086: Add board and meeting frontend API methods

**File**: `frontend/src/api/assistantTasks.ts` (modify)

**Requirements**: board list and meeting transcript clients.
**Dependencies**: T084, T085.
**Implementation contract**: add typed methods for board list, claim/release actions if exposed, meeting transcript fetch and meeting message send or conclude actions.
**Verification**: T077 passes.

### T087: Add board and meeting event validators

**File**: `frontend/src/api/uiEvents.ts` (modify)

**Requirements**: frontend public event contracts for board and meeting.
**Dependencies**: T083.
**Implementation contract**: mirror backend allowed fields, validate change types and trigger resync domains for board or meeting gaps.
**Verification**: T012 and T107 pass.

### T088: Add board and meeting store slices

**File**: `frontend/src/state/assistantTaskStore.ts` (modify)

**Requirements**: board and meeting state.
**Dependencies**: T086, T087.
**Implementation contract**: maintain board items, active meeting transcript cache, pagination cursor, pending claim/send states and event-driven invalidation.
**Verification**: T077 passes.

### T089: Implement task board panel

**File**: `frontend/src/screens/assistant/TaskBoardPanel.tsx` (new)

**Requirements**: open board claim and release UI.
**Dependencies**: T088.
**Implementation contract**: render open and claimed tasks, claim/release controls, rejection messages and empty state with dense work-focused styling and accessible button labels.
**Verification**: T077 passes.

### T090: Implement meeting drawer

**File**: `frontend/src/screens/assistant/MeetingChannelDrawer.tsx` (new)

**Requirements**: supervised transcript, pagination and conclusion.
**Dependencies**: T088.
**Implementation contract**: render paged transcript, participants, turn budget, conclusion state and message input when channel is open. The UI must not imply tool sharing or hidden authorization.
**Verification**: T077 passes.

### T091: Integrate board and meeting panels

**File**: `frontend/src/screens/assistant/AssistantScreen.tsx` (modify)

**Requirements**: contextual board and active meeting visibility.
**Dependencies**: T089, T090.
**Implementation contract**: show board and active meeting controls only when relevant to current Assistant session and graph, preserving existing chat layout and progress behavior.
**Verification**: T036 and T077 pass.

## User Story 4: Long tasks expose private Todo progress

### T092: Add Todo persistence tests

**File**: `tests/business/agents/test_task_todos.py` (new)

**Requirements**: Todo persistence, ordering and task separation.
**Dependencies**: T022, T097.
**Implementation contract**: test create, update, reorder, complete, skip, reload after restart and prove Todo items do not become Task nodes or adjudication entries.
**Verification**: `uv run python -m pytest tests/business/agents/test_task_todos.py -q`.

### T093: Add Todo API tests

**File**: `tests/desktop_api/test_assistant_task_api.py` (modify)

**Requirements**: Todo REST contract.
**Dependencies**: T100, T101.
**Implementation contract**: cover list and update endpoints, session scoping, task ownership checks and safe projection of Todo text.
**Verification**: `uv run python -m pytest tests/desktop_api/test_assistant_task_api.py -q`.

### T094: Add Todo event contract tests

**File**: `tests/desktop_api/test_assistant_task_events.py` (modify)

**Requirements**: Todo public event type.
**Dependencies**: T099.
**Implementation contract**: assert `assistant.todo.changed` registration, required keys, allowed keys and projector behavior for create, update, delete and reorder changes.
**Verification**: `uv run python -m pytest tests/desktop_api/test_assistant_task_events.py -q`.

### T095: Add Todo panel and accessibility tests

**File**: `frontend/tests/unit/assistant-task-panels.test.tsx` (modify)

**Requirements**: Todo checklist rendering and accessible updates.
**Dependencies**: T105, T106.
**Implementation contract**: render item statuses, reorder stability, optimistic updates, keyboard focus retention and distinction between Todo status labels and Task status.
**Verification**: `cd frontend; npm run test -- assistant-task-panels`.

### T096: Add brain distillation guard test

**File**: `tests/guardrails/test_assistant_task_boundaries.py` (modify)

**Requirements**: Todo text not distilled into brain memory.
**Dependencies**: T097.
**Implementation contract**: assert task Todo repository and service data do not flow into brain context builder or distillation inputs outside ordinary message/reference paths.
**Verification**: `uv run python -m pytest tests/guardrails/test_assistant_task_boundaries.py -q`.

### T097: Implement Todo service

**File**: `src/business/task_collaboration/todos.py` (new)

**Requirements**: private checklist service.
**Dependencies**: T022, T023, T037.
**Implementation contract**: validate executor ownership, create or replace ordered Todo items, update status, emit internal Todo events and keep Todo detached from graph edges, adjudication and brain memory.
**Verification**: T092 and T096 pass.

### T098: Add todo_update tool handler

**File**: `src/business/agents/tools/assistant_tools.py` (modify)

**Requirements**: per-task executor-owned Todo updates.
**Dependencies**: T097.
**Implementation contract**: register `todo_update` handler, validate caller owns the task attempt, apply ordered item list through service and return safe item summaries.
**Verification**: T092 passes.

### T099: Register Todo UI event

**File**: `src/desktop_api/ui_events.py` (modify)

**Requirements**: `assistant.todo.changed`.
**Dependencies**: T025, T097.
**Implementation contract**: register Todo event type with required `taskId`, `todoId`, `changeType` and safe allowed fields.
**Verification**: T094 and T012 pass.

### T100: Add Todo endpoints

**File**: `src/desktop_api/routers/assistant_tasks.py` (modify)

**Requirements**: Todo list and update REST routes.
**Dependencies**: T097, T101.
**Implementation contract**: implement `/api/assistant/sessions/{sessionId}/tasks/{taskId}/todos` list and update route variants through business service, with session and executor ownership checks.
**Verification**: T093 passes.

### T101: Add Todo schemas

**File**: `src/desktop_api/schemas.py` (modify)

**Requirements**: Todo request and response DTOs.
**Dependencies**: T097.
**Implementation contract**: add Pydantic schemas for Todo item, list response and update request with closed statuses `todo`, `doing`, `done`, `skipped`.
**Verification**: T093 passes.

### T102: Add Todo frontend API methods

**File**: `frontend/src/api/assistantTasks.ts` (modify)

**Requirements**: Todo list and update methods.
**Dependencies**: T100, T101.
**Implementation contract**: add typed Todo DTOs, fetch function and update function using existing client error handling.
**Verification**: T095 passes.

### T103: Add Todo event validators

**File**: `frontend/src/api/uiEvents.ts` (modify)

**Requirements**: frontend Todo event contract.
**Dependencies**: T099.
**Implementation contract**: mirror backend Todo required and allowed keys, validate change types and route Todo resync domain to store reload.
**Verification**: T012 and T107 pass.

### T104: Add Todo store state

**File**: `frontend/src/state/assistantTaskStore.ts` (modify)

**Requirements**: Todo state and optimistic update handling.
**Dependencies**: T102, T103.
**Implementation contract**: store Todo items by task ID, support fetch and update, reconcile optimistic changes with authoritative events and separate Todo status from Task status.
**Verification**: T095 passes.

### T105: Implement Todo checklist panel

**File**: `frontend/src/screens/assistant/TodoChecklistPanel.tsx` (new)

**Requirements**: Todo checklist UI.
**Dependencies**: T104.
**Implementation contract**: render ordered checklist, status controls, skipped state and update progress with compact accessible UI. It must never render Todo items as graph nodes.
**Verification**: T095 passes.

### T106: Integrate Todo into task details

**File**: `frontend/src/screens/assistant/AssistantScreen.tsx` (modify)

**Requirements**: Todo visibility in task graph details.
**Dependencies**: T105.
**Implementation contract**: show Todo panel in selected task details when the task has private checklist data, without changing graph topology or Assistant message timeline.
**Verification**: T095 and T108 pass.

## Phase 7: Polish and Cross-Cutting Verification

### T107: Add frontend event contract coverage

**File**: `frontend/tests/unit/ui-events.test.ts` (modify)

**Requirements**: examples for all task collaboration payloads.
**Dependencies**: T048, T087, T103.
**Implementation contract**: add positive and negative validator examples for graph, board, meeting and Todo events, including resync domains and disallowed internal fields.
**Verification**: `cd frontend; npm run test -- uiEvents`.

### T108: Add UI empty, loading, resync and focus scenarios

**File**: `frontend/tests/unit/assistant-task-panels.test.tsx` (modify)

**Requirements**: graph, board, meeting and Todo UI quality.
**Dependencies**: T050, T070, T089, T090, T105.
**Implementation contract**: test empty states, loading states, resync-required recovery, command button focus retention and text containment for compact panels.
**Verification**: `cd frontend; npm run test -- assistant-task-panels`.

### T109: Add 200-node graph snapshot performance coverage

**File**: `tests/integration/test_assistant_task_graph_smoke.py` (new)

**Requirements**: snapshot performance with fake data.
**Dependencies**: T037, T040.
**Implementation contract**: create 200 tasks and representative edges in local SQLite, request snapshot through business or API layer and assert latency stays within spec budget under fake deterministic data.
**Verification**: `uv run python -m pytest tests/integration/test_assistant_task_graph_smoke.py -q`.

### T110: Add E2E fixtures for all task collaboration paths

**File**: `frontend/tests/e2e/mock-api.ts` (modify)

**Requirements**: mock graph, board, meeting and Todo E2E data.
**Dependencies**: T052, T086, T102.
**Implementation contract**: extend mock API with board items, meeting transcripts, Todo lists, command responses and event stream fixtures for browser smoke tests.
**Verification**: `cd frontend; npm run test:e2e -- assistant-task-graph`.

### T111: Update architecture documentation

**File**: `docs/ARCHITECTURE.md` (modify)

**Requirements**: live architecture doc update.
**Dependencies**: implementation complete enough to describe.
**Implementation contract**: document Task graph fact source, dispatcher, recovery, UI event projection, clean-start cutover, failure bridge and frontend panels. Keep it aligned with active code, not planned behavior.
**Verification**: docs mention v15/v16 task collaboration and no longer describe `workflow_transitions` as task UI source.

### T112: Update project constraints

**File**: `docs/PROJECT_CONSTRAINTS.md` (modify)

**Requirements**: recovery, retention and dispatch boundaries.
**Dependencies**: T111.
**Implementation contract**: add constraints for Task repository usage, no physical task artifact deletion from task service, stop versus cancel semantics, operation idempotency and main Assistant coordinator-only rule.
**Verification**: guardrail text matches tests T010, T011 and T096.

### T113: Sync root AI entry mirrors

**File**: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md` (modify)

**Requirements**: root AI entry mirror sync.
**Dependencies**: T111, T112.
**Implementation contract**: add feature summary and known issues to all three root mirror files with identical content.
**Verification**: compare the three files and confirm task collaboration section is identical.

### T114: Sync backend AI entry mirrors

**File**: `src/AGENTS.md`, `src/CLAUDE.md`, `src/GEMINI.md` (modify)

**Requirements**: backend module AI entry mirror sync.
**Dependencies**: T112.
**Implementation contract**: if backend constraints changed, document task collaboration repository, service, dispatcher and event boundaries identically across the three backend entry mirrors.
**Verification**: compare the three files and confirm no mirror drift.

### T115: Sync frontend AI entry mirrors

**File**: `frontend/AGENTS.md`, `frontend/CLAUDE.md`, `frontend/GEMINI.md` (modify)

**Requirements**: frontend module AI entry mirror sync.
**Dependencies**: T050, T089, T090, T105.
**Implementation contract**: if frontend constraints changed, document task UI store, event validator and panel boundaries identically across the three frontend entry mirrors.
**Verification**: compare the three files and confirm no mirror drift.

### T116: Run focused backend verification

**File**: `specs/023-unified-task-collaboration/quickstart.md` (modify)

**Requirements**: focused backend verification evidence.
**Dependencies**: backend implementation tasks.
**Implementation contract**: run the backend quickstart commands that apply to implemented scope and record command results or intentional exceptions with concrete dates and reasons.
**Verification**: quickstart contains the executed backend command list and outcomes.

### T117: Run frontend verification

**File**: `specs/023-unified-task-collaboration/quickstart.md` (modify)

**Requirements**: frontend lint, unit and E2E verification evidence.
**Dependencies**: frontend implementation tasks.
**Implementation contract**: run frontend quickstart commands, record outcomes and document any intentional exception with exact command and reason.
**Verification**: quickstart contains frontend command results.

### T118: Run formatting and lint checks for Python paths

**File**: `src/` (modify as needed)

**Requirements**: Python formatting and lint cleanup.
**Dependencies**: Python implementation tasks.
**Implementation contract**: run project-approved formatting and lint checks for changed Python files, fix issues in touched `src` paths and avoid unrelated refactors.
**Verification**: formatting and lint commands complete or documented exceptions are recorded in final implementation notes.

### T119: Run broad regression and fix task-related issues

**File**: `tests/` (modify as needed)

**Requirements**: backend and guardrail regression.
**Dependencies**: all implementation tasks.
**Implementation contract**: run broad task-related backend and guardrail tests, fix failures caused by this feature and leave unrelated failures documented with evidence.
**Verification**: quickstart broad regression commands pass or have concrete intentional exceptions.

## Checklist

- [ ] T001: create `src/business/task_collaboration/__init__.py`
- [ ] T002: create `src/desktop_api/routers/assistant_tasks.py`
- [ ] T003: create `frontend/src/api/assistantTasks.ts`
- [ ] T004: create `frontend/src/state/assistantTaskStore.ts`
- [ ] T005: create `frontend/src/screens/assistant/TaskGraphPanel.tsx`
- [ ] T006: create `tests/business/task_collaboration/__init__.py`
- [ ] T007: add `tests/data/test_assistant_task_migration.py`
- [ ] T008: add `tests/data/test_assistant_task_repositories.py`
- [ ] T009: add `tests/business/agents/test_task_state_machine.py`
- [ ] T010: add `tests/guardrails/test_assistant_task_boundaries.py`
- [ ] T011: add `tests/guardrails/test_assistant_task_transition_source.py`
- [ ] T012: add `tests/desktop_api/test_assistant_task_event_contract_sync.py`
- [ ] T013: modify `src/data/models_sqlite.py`
- [ ] T014: modify `src/data/migrations.py`
- [ ] T015: add `src/data/repos/assistant_task_repository.py`
- [ ] T016: add `src/data/repos/assistant_task_attempt_repository.py`
- [ ] T017: add `src/data/repos/assistant_task_operation_repository.py`
- [ ] T018: add `src/data/repos/assistant_task_question_repository.py`
- [ ] T019: add `src/data/repos/assistant_task_adjudication_repository.py`
- [ ] T020: add `src/data/repos/assistant_task_board_repository.py`
- [ ] T021: add `src/data/repos/assistant_meeting_repository.py`
- [ ] T022: add `src/data/repos/assistant_todo_repository.py`
- [ ] T023: add `src/business/task_collaboration/models.py`
- [ ] T024: modify `src/data/unified_config.py`
- [ ] T025: modify `src/utils/events.py`
- [ ] T026: add `src/business/task_collaboration/cutover.py`
- [ ] T027: modify `src/data/repos/pending_task_repository.py`
- [ ] T028: modify `src/desktop_api/app.py`
- [ ] T029: add `tests/business/agents/test_task_dispatch_async.py`
- [ ] T030: add `tests/business/agents/test_task_recovery.py`
- [ ] T031: add `tests/desktop_api/test_assistant_task_api.py`
- [ ] T032: add `tests/desktop_api/test_assistant_task_events.py`
- [ ] T033: add `tests/integration/test_assistant_task_cutover.py`
- [ ] T034: add `frontend/tests/unit/assistant-task-store.test.ts`
- [ ] T035: add `frontend/tests/unit/assistant-task-panels.test.tsx`
- [ ] T036: add `frontend/tests/e2e/assistant-task-graph.spec.ts`
- [ ] T037: add `src/business/task_collaboration/service.py`
- [ ] T038: add `src/business/task_collaboration/dispatcher.py`
- [ ] T039: add `src/business/task_collaboration/recovery.py`
- [ ] T040: modify `src/desktop_api/schemas.py`
- [ ] T041: modify `src/desktop_api/routers/assistant_tasks.py`
- [ ] T042: modify `src/desktop_api/ui_events.py`
- [ ] T043: modify `src/desktop_api/ui_event_projector.py`
- [ ] T044: modify `src/business/agents/tools/assistant_tools.py`
- [ ] T045: modify `src/business/orchestration/agent/orchestrator.py`
- [ ] T046: modify `src/desktop_api/assistant_runtime.py`
- [ ] T047: modify `frontend/src/api/assistantTasks.ts`
- [ ] T048: modify `frontend/src/api/uiEvents.ts`
- [ ] T049: modify `frontend/src/state/assistantTaskStore.ts`
- [ ] T050: modify `frontend/src/screens/assistant/TaskGraphPanel.tsx`
- [ ] T051: modify `frontend/src/screens/assistant/AssistantScreen.tsx`
- [ ] T052: modify `frontend/tests/e2e/mock-api.ts`
- [ ] T053: add `tests/business/agents/test_task_adjudication.py`
- [ ] T054: add `tests/business/agents/test_task_idempotency.py`
- [ ] T055: add `tests/business/agents/test_task_idempotency_negative.py`
- [ ] T056: modify `tests/business/agents/test_task_recovery.py`
- [ ] T057: add `tests/integration/test_assistant_task_failure_bridge.py`
- [ ] T058: modify `frontend/tests/unit/assistant-task-store.test.ts`
- [ ] T059: add `src/business/task_collaboration/adjudication.py`
- [ ] T060: modify `src/business/task_collaboration/dispatcher.py`
- [ ] T061: modify `src/business/task_collaboration/recovery.py`
- [ ] T062: modify `src/business/task_collaboration/service.py`
- [ ] T063: add `src/business/task_collaboration/failure_bridge.py`
- [ ] T064: modify `src/business/services/assistant_failure_service.py`
- [ ] T065: modify `src/desktop_api/routers/assistant_tasks.py`
- [ ] T066: modify `src/desktop_api/schemas.py`
- [ ] T067: modify `src/desktop_api/ui_event_projector.py`
- [ ] T068: modify `frontend/src/api/assistantTasks.ts`
- [ ] T069: modify `frontend/src/state/assistantTaskStore.ts`
- [ ] T070: modify `frontend/src/screens/assistant/TaskGraphPanel.tsx`
- [ ] T071: modify `frontend/src/screens/assistant/AssistantScreen.tsx`
- [ ] T072: add `tests/business/agents/test_task_questions.py`
- [ ] T073: add `tests/business/agents/test_task_board_claims.py`
- [ ] T074: add `tests/business/agents/test_task_meetings.py`
- [ ] T075: modify `tests/desktop_api/test_assistant_task_api.py`
- [ ] T076: modify `tests/desktop_api/test_assistant_task_events.py`
- [ ] T077: modify `frontend/tests/unit/assistant-task-panels.test.tsx`
- [ ] T078: add `src/business/task_collaboration/questions.py`
- [ ] T079: add `src/business/task_collaboration/board.py`
- [ ] T080: add `src/business/task_collaboration/meetings.py`
- [ ] T081: modify `src/business/agents/tools/assistant_tools.py`
- [ ] T082: modify `src/business/orchestration/agent/orchestrator.py`
- [ ] T083: modify `src/desktop_api/ui_events.py`
- [ ] T084: modify `src/desktop_api/routers/assistant_tasks.py`
- [ ] T085: modify `src/desktop_api/schemas.py`
- [ ] T086: modify `frontend/src/api/assistantTasks.ts`
- [ ] T087: modify `frontend/src/api/uiEvents.ts`
- [ ] T088: modify `frontend/src/state/assistantTaskStore.ts`
- [ ] T089: add `frontend/src/screens/assistant/TaskBoardPanel.tsx`
- [ ] T090: add `frontend/src/screens/assistant/MeetingChannelDrawer.tsx`
- [ ] T091: modify `frontend/src/screens/assistant/AssistantScreen.tsx`
- [ ] T092: add `tests/business/agents/test_task_todos.py`
- [ ] T093: modify `tests/desktop_api/test_assistant_task_api.py`
- [ ] T094: modify `tests/desktop_api/test_assistant_task_events.py`
- [ ] T095: modify `frontend/tests/unit/assistant-task-panels.test.tsx`
- [ ] T096: modify `tests/guardrails/test_assistant_task_boundaries.py`
- [ ] T097: add `src/business/task_collaboration/todos.py`
- [ ] T098: modify `src/business/agents/tools/assistant_tools.py`
- [ ] T099: modify `src/desktop_api/ui_events.py`
- [ ] T100: modify `src/desktop_api/routers/assistant_tasks.py`
- [ ] T101: modify `src/desktop_api/schemas.py`
- [ ] T102: modify `frontend/src/api/assistantTasks.ts`
- [ ] T103: modify `frontend/src/api/uiEvents.ts`
- [ ] T104: modify `frontend/src/state/assistantTaskStore.ts`
- [ ] T105: add `frontend/src/screens/assistant/TodoChecklistPanel.tsx`
- [ ] T106: modify `frontend/src/screens/assistant/AssistantScreen.tsx`
- [ ] T107: modify `frontend/tests/unit/ui-events.test.ts`
- [ ] T108: modify `frontend/tests/unit/assistant-task-panels.test.tsx`
- [ ] T109: add `tests/integration/test_assistant_task_graph_smoke.py`
- [ ] T110: modify `frontend/tests/e2e/mock-api.ts`
- [ ] T111: modify `docs/ARCHITECTURE.md`
- [ ] T112: modify `docs/PROJECT_CONSTRAINTS.md`
- [ ] T113: modify root AI entry mirrors
- [ ] T114: modify backend AI entry mirrors
- [ ] T115: modify frontend AI entry mirrors
- [ ] T116: update `specs/023-unified-task-collaboration/quickstart.md` with backend verification
- [ ] T117: update `specs/023-unified-task-collaboration/quickstart.md` with frontend verification
- [ ] T118: run and fix Python formatting and lint for `src/`
- [ ] T119: run broad backend and guardrail regression for `tests/`
