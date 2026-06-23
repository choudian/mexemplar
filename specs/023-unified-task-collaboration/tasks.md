# Tasks: 统一任务模型 + 多范式协作

**Input**: Design documents from `specs/023-unified-task-collaboration/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/assistant-task-collaboration.md`, `quickstart.md`
**Tests**: Required by spec/quickstart because this feature replaces orchestration, persistence, recovery, events, and UI wiring.
**Organization**: Tasks are grouped by phase and user story. P1/P2 are MVP gates; P3/P4 must not start implementation before P1/P2 gate tests pass.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create scaffolding and isolate the new task collaboration surface without changing behavior.

- [X] T001 Create task collaboration package scaffolding in `src/business/task_collaboration/__init__.py`
- [X] T002 [P] Create task collaboration router placeholder in `src/desktop_api/routers/assistant_tasks.py`
- [X] T003 [P] Create frontend task API client placeholder in `frontend/src/api/assistantTasks.ts`
- [X] T004 [P] Create frontend task store placeholder in `frontend/src/state/assistantTaskStore.ts`
- [X] T005 [P] Create task graph panel placeholder in `frontend/src/screens/assistant/TaskGraphPanel.tsx`
- [X] T006 [P] Create backend task collaboration test package marker in `tests/business/task_collaboration/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the schema, repositories, shared contracts, config, cutover guard, and test harness required by every story.

**Critical**: No user story implementation starts until this phase is complete.

### Tests and Guards

- [X] T007 [P] Add v15/v16 migration coverage for all task collaboration tables and active-attempt indexes in `tests/data/test_assistant_task_migration.py` and `tests/data/test_migrations.py`
- [X] T008 [P] Add repository CRUD/transaction tests for Task, Attempt, Operation, Question, Adjudication, Claim, Meeting, and Todo in `tests/data/test_assistant_task_repositories.py`
- [X] T009 [P] Add table-driven state-machine tests for Task, Attempt, Operation, Claim, Adjudication, Stop, Cancel, and Recovery transitions in `tests/business/agents/test_task_state_machine.py`
- [X] T010 [P] Add layering and 100% dispatch guard tests for task collaboration boundaries in `tests/guardrails/test_assistant_task_boundaries.py`
- [X] T011 [P] Add guard test proving task UI/API does not derive task truth from `workflow_transitions` in `tests/guardrails/test_assistant_task_transition_source.py`
- [X] T012 [P] Add backend/frontend public event contract sync test for task event allowlists in `tests/desktop_api/test_assistant_task_event_contract_sync.py`

### Data, Config, Events

- [X] T013 Define SQLAlchemy ORM models for assistant task collaboration entities in `src/data/models_sqlite.py`
- [X] T014 Implement SQLite v15/v16 migrations with default clean-start cutover tables and active-attempt indexes in `src/data/migrations.py`
- [X] T015 [P] Implement Task and Edge repository methods in `src/data/repos/assistant_task_repository.py`
- [X] T016 [P] Implement TaskAttempt repository methods including lease/fence scans in `src/data/repos/assistant_task_attempt_repository.py`
- [X] T017 [P] Implement TaskOperation repository methods including non-failed operation-key uniqueness helpers in `src/data/repos/assistant_task_operation_repository.py`
- [X] T018 [P] Implement TaskQuestion repository methods including escalation and expiry queries in `src/data/repos/assistant_task_question_repository.py`
- [X] T019 [P] Implement TaskAdjudication repository methods in `src/data/repos/assistant_task_adjudication_repository.py`
- [X] T020 [P] Implement TaskClaim repository methods including atomic claim and lease expiry in `src/data/repos/assistant_task_board_repository.py`
- [X] T021 [P] Implement Meeting repository methods for channels and paged messages in `src/data/repos/assistant_meeting_repository.py`
- [X] T022 [P] Implement Todo repository methods in `src/data/repos/assistant_todo_repository.py`
- [X] T023 Define task collaboration enums, DTO dataclasses, projection helpers, and state validators in `src/business/task_collaboration/models.py`
- [X] T024 Add `assistant_tasks.*` config defaults and getters through UnifiedConfigManager in `src/data/unified_config.py`
- [X] T025 Add internal task collaboration blinker events in `src/utils/events.py`
- [X] T026 Implement default clean-start cutover guard for legacy delegation state in `src/business/task_collaboration/cutover.py`
- [X] T027 Preserve legacy `pending_assistant_tasks` compatibility for codify/bug queues in `src/data/repos/pending_task_repository.py`
- [X] T028 Register the assistant task router in the sidecar app in `src/desktop_api/app.py`

**Checkpoint**: Foundation ready. Schema, repositories, shared config, events, and cutover guard are in place; user-story tasks may begin in priority order.

---

## Phase 3: User Story 1 - 多步任务可观测、可恢复地完成 (Priority: P1) MVP Gate A

**Goal**: A complex request becomes a durable task graph with parallel execution, authoritative snapshots, graph events, crash recovery, and UI progress.

**Independent Test**: Start a controlled run with 3+ tasks across 2+ executors, observe graph progress, inject a pause/crash, and verify safe checkpoint resume or adjudication with no permanent running task or duplicate side effect.

### Tests for User Story 1

- [X] T029 [P] [US1] Add controlled async dispatch tests with fake executors in `tests/business/agents/test_task_dispatch_async.py`
- [X] T030 [P] [US1] Add crash recovery, fence, and late-result rejection tests in `tests/business/agents/test_task_recovery.py`
- [X] T031 [P] [US1] Add task graph snapshot API tests in `tests/desktop_api/test_assistant_task_api.py`
- [X] T032 [P] [US1] Add task graph UI event registry/projector tests in `tests/desktop_api/test_assistant_task_events.py`
- [X] T033 [P] [US1] Add clean-start cutover smoke test in `tests/integration/test_assistant_task_cutover.py`
- [X] T034 [P] [US1] Add frontend task graph store tests in `frontend/tests/unit/assistant-task-store.test.ts`
- [X] T035 [P] [US1] Add frontend task graph panel tests in `frontend/tests/unit/assistant-task-panels.test.tsx`
- [X] T036 [P] [US1] Add task graph E2E smoke with mock API in `frontend/tests/e2e/assistant-task-graph.spec.ts`

### Implementation for User Story 1

- [X] T037 [US1] Implement authoritative task graph facade, snapshot building, and graph version checks in `src/business/task_collaboration/service.py`
- [X] T038 [US1] Implement bounded async dispatcher, durable enqueue, parking, parent re-entry, and per-worker repository/session scope in `src/business/task_collaboration/dispatcher.py`
- [X] T039 [US1] Implement TaskAttempt lease recovery, fence token handling, checkpoint lookup, and stale result rejection in `src/business/task_collaboration/recovery.py`
- [X] T040 [US1] Implement graph snapshot DTO schemas and redacted projection fields in `src/desktop_api/schemas.py`
- [X] T041 [US1] Implement current graph and graph snapshot REST endpoints in `src/desktop_api/routers/assistant_tasks.py`
- [X] T042 [US1] Register `assistant.task_graph.changed` and task resync payload allowlists in `src/desktop_api/ui_events.py`
- [X] T043 [US1] Project internal task graph events into public UI event drafts in `src/desktop_api/ui_event_projector.py`
- [X] T044 [US1] Replace synchronous delegation tool return with durable accepted `taskId` / `graphId` output in `src/business/agents/tools/assistant_tools.py`
- [X] T045 [US1] Wire Orchestrator delegation entry points to `TaskDispatcher` without blocking child completion in `src/business/orchestration/agent/orchestrator.py`
- [X] T046 [US1] Stop using `build_subagent_list` as task truth for new task graph UI/API paths in `src/desktop_api/assistant_runtime.py`
- [X] T047 [US1] Implement typed task graph API functions and DTOs in `frontend/src/api/assistantTasks.ts`
- [X] T048 [US1] Mirror task graph public event types and validators in `frontend/src/api/uiEvents.ts`
- [X] T049 [US1] Implement graph snapshot, event application, resync handling, and derived display phases in `frontend/src/state/assistantTaskStore.ts`
- [X] T050 [US1] Implement accessible compact/expandable task graph UI in `frontend/src/screens/assistant/TaskGraphPanel.tsx`
- [X] T051 [US1] Mount the task graph panel and current-request progress strip in `frontend/src/screens/assistant/AssistantScreen.tsx`
- [X] T052 [US1] Add task graph mock API routes and event fixtures in `frontend/tests/e2e/mock-api.ts`

**Checkpoint**: US1 MVP Gate A passes when graph snapshots, parallel fake execution, recovery fences, late-result rejection, public graph events, and frontend graph UI all work independently.

---

## Phase 4: User Story 2 - 干完/卡住都交裁定,失败有交代,随时可叫停 (Priority: P2) MVP Gate B

**Goal**: Parent-side adjudication, stop/continue, terminal cancel, unsafe-recovery adjudication, and root failure bridge are implemented on top of the task graph.

**Independent Test**: Return, accept, abandon, stop, continue, cancel/replan race, unsafe recovery, and root graph failure all behave deterministically with safe user projections.

### Tests for User Story 2

- [X] T053 [P] [US2] Add parent-side adjudication accept/return/abandon tests in `tests/business/agents/test_task_adjudication.py`
- [X] T054 [P] [US2] Add idempotent operation recovery tests in `tests/business/agents/test_task_idempotency.py`
- [X] T055 [P] [US2] Add duplicate operation-key, unsafe retry, and stale fenced-result negative tests in `tests/business/agents/test_task_idempotency_negative.py`
- [X] T056 [P] [US2] Add stop/continue and cancel/replan race tests in `tests/business/agents/test_task_recovery.py`
- [X] T057 [P] [US2] Add root graph failure bridge integration tests in `tests/integration/test_assistant_task_failure_bridge.py`
- [X] T058 [P] [US2] Add frontend stop/continue/adjudication store and panel tests in `frontend/tests/unit/assistant-task-store.test.ts`

### Implementation for User Story 2

- [X] T059 [US2] Implement parent-side adjudication accept/return/abandon service in `src/business/task_collaboration/adjudication.py`
- [X] T060 [US2] Enforce side-effect operation records before execution and completion markers after success in `src/business/task_collaboration/dispatcher.py`
- [X] T061 [US2] Implement unsafe retry to parent adjudication and cancel/replan ordering in `src/business/task_collaboration/recovery.py`
- [X] T062 [US2] Implement graph stop, continue, cascading cancel, and late cancelled-success rejection in `src/business/task_collaboration/service.py`
- [X] T063 [US2] Bridge only root graph terminal failure to AssistantRunFailureService in `src/business/task_collaboration/failure_bridge.py`
- [X] T064 [US2] Wire root graph failure bridge into existing failure recovery service safely in `src/business/services/assistant_failure_service.py`
- [X] T065 [US2] Add stop, continue, and adjudication decision endpoints in `src/desktop_api/routers/assistant_tasks.py`
- [X] T066 [US2] Add adjudication, stop, cancel, and failure bridge DTOs in `src/desktop_api/schemas.py`
- [X] T067 [US2] Project adjudication, stop, cancel, and root failure events through allowlists in `src/desktop_api/ui_event_projector.py`
- [X] T068 [US2] Add stop/continue/adjudication methods to frontend task API in `frontend/src/api/assistantTasks.ts`
- [X] T069 [US2] Add stop/continue/adjudication state transitions to frontend task store in `frontend/src/state/assistantTaskStore.ts`
- [X] T070 [US2] Add user-facing stop/continue/review controls to graph UI in `frontend/src/screens/assistant/TaskGraphPanel.tsx`
- [X] T071 [US2] Render safe root graph failure summaries without raw diagnostics in `frontend/src/screens/assistant/AssistantScreen.tsx`

**Checkpoint**: US2 MVP Gate B passes when P1 still works and adjudication, stop/continue, cancel/replan ordering, unsafe recovery, and root failure bridge pass their tests.

---

## Phase 5: User Story 3 - 协调者临场切换协作范式(委派 / 会议 / 认领) (Priority: P3)

**Goal**: Coordinators can switch between directed delegation, open board claiming, agent-to-agent questions/resource requests, fallback temporary executors, and supervised two-party meetings.

**Independent Test**: Race two claimers for one board task, route an agent question through parent/user boundaries, and run a bounded two-party meeting to conclusion or timeout without capability expansion.

### Tests for User Story 3

- [X] T072 [P] [US3] Add persisted `ask_parent` and capability/resource request route tests in `tests/business/agents/test_task_questions.py`
- [X] T073 [P] [US3] Add atomic board claim, lease expiry, reject history, and fallback executor tests in `tests/business/agents/test_task_board_claims.py`
- [X] T074 [P] [US3] Add supervised meeting budget, conclusion, timeout, and message-only permission tests in `tests/business/agents/test_task_meetings.py`
- [X] T075 [P] [US3] Add board and meeting API contract tests in `tests/desktop_api/test_assistant_task_api.py`
- [X] T076 [P] [US3] Add board/meeting event contract tests in `tests/desktop_api/test_assistant_task_events.py`
- [X] T077 [P] [US3] Add frontend board and meeting panel tests in `frontend/tests/unit/assistant-task-panels.test.tsx`

### Implementation for User Story 3

- [X] T078 [US3] Implement persisted agent-to-agent question and capability request service in `src/business/task_collaboration/questions.py`
- [X] T079 [US3] Implement open board listing, atomic claim, release, expiry, reject history, and fallback selection in `src/business/task_collaboration/board.py`
- [X] T080 [US3] Implement supervised two-party meeting channel lifecycle and message pagination in `src/business/task_collaboration/meetings.py`
- [X] T081 [US3] Add `ask_parent`, `open_meeting_channel`, and `meeting_send_message` tool handlers in `src/business/agents/tools/assistant_tools.py`
- [X] T082 [US3] Enforce specialist capability-scope subset grants and meeting no-tool-proxy rule in `src/business/orchestration/agent/orchestrator.py`
- [X] T083 [US3] Register board, meeting, question, and resource request event types in `src/desktop_api/ui_events.py`
- [X] T084 [US3] Add task board and meeting REST endpoints in `src/desktop_api/routers/assistant_tasks.py`
- [X] T085 [US3] Add board, meeting, and question DTO schemas in `src/desktop_api/schemas.py`
- [X] T086 [US3] Add board and meeting methods to frontend task API in `frontend/src/api/assistantTasks.ts`
- [X] T087 [US3] Add board and meeting event validators to frontend public event contracts in `frontend/src/api/uiEvents.ts`
- [X] T088 [US3] Add board and meeting state slices to frontend task store in `frontend/src/state/assistantTaskStore.ts`
- [X] T089 [US3] Implement task board panel with claim/release states in `frontend/src/screens/assistant/TaskBoardPanel.tsx`
- [X] T090 [US3] Implement supervised meeting drawer with paged transcript and conclusion state in `frontend/src/screens/assistant/MeetingChannelDrawer.tsx`
- [X] T091 [US3] Integrate board and active meeting panels into Assistant screen only when relevant in `frontend/src/screens/assistant/AssistantScreen.tsx`

**Checkpoint**: US3 passes when board claiming is atomic, meetings are bounded and message-only, and agent-to-agent questions survive restart without persisting user answers.

---

## Phase 6: User Story 4 - 执行者私人清单(Todo)防遗忘 (Priority: P4)

**Goal**: Each assigned executor can maintain a private checklist for a single task; the checklist is persistent, visible to the user, and separate from the task graph/adjudication state.

**Independent Test**: A specialist creates, updates, reloads, and displays Todo items after restart while Todo state remains distinct from Task state and is excluded from brain memory.

### Tests for User Story 4

- [X] T092 [P] [US4] Add Todo persistence, ordering, and task-separation tests in `tests/business/agents/test_task_todos.py`
- [X] T093 [P] [US4] Add Todo API contract tests in `tests/desktop_api/test_assistant_task_api.py`
- [X] T094 [P] [US4] Add Todo event contract tests in `tests/desktop_api/test_assistant_task_events.py`
- [X] T095 [P] [US4] Add Todo panel and accessibility tests in `frontend/tests/unit/assistant-task-panels.test.tsx`
- [X] T096 [P] [US4] Add guard test proving Todo text is not distilled into brain memory in `tests/guardrails/test_assistant_task_boundaries.py`

### Implementation for User Story 4

- [X] T097 [US4] Implement private Todo checklist service in `src/business/task_collaboration/todos.py`
- [X] T098 [US4] Add `todo_update` tool handler with per-task executor ownership checks in `src/business/agents/tools/assistant_tools.py`
- [X] T099 [US4] Register Todo public event type and allowlist in `src/desktop_api/ui_events.py`
- [X] T100 [US4] Add Todo REST endpoints in `src/desktop_api/routers/assistant_tasks.py`
- [X] T101 [US4] Add Todo DTO schemas in `src/desktop_api/schemas.py`
- [X] T102 [US4] Add Todo methods to frontend task API in `frontend/src/api/assistantTasks.ts`
- [X] T103 [US4] Add Todo event validators to frontend UI event contracts in `frontend/src/api/uiEvents.ts`
- [X] T104 [US4] Add Todo state and optimistic update handling in `frontend/src/state/assistantTaskStore.ts`
- [X] T105 [US4] Implement Todo checklist panel with distinct Todo status labels in `frontend/src/screens/assistant/TodoChecklistPanel.tsx`
- [X] T106 [US4] Integrate Todo visibility into Assistant task graph details without creating task nodes in `frontend/src/screens/assistant/AssistantScreen.tsx`

**Checkpoint**: US4 passes when Todo persists across restart, stays visually/statefully distinct from Task, and does not feed brain distillation.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final integration, documentation, performance, and validation across all stories.

- [X] T107 [P] Add frontend event contract coverage for all task collaboration event payload examples in `frontend/tests/unit/ui-events.test.ts`
- [X] T108 [P] Add UI empty/loading/resync/focus scenarios for graph, board, meeting, and Todo in `frontend/tests/unit/assistant-task-panels.test.tsx`
- [X] T109 [P] Add 200-node graph snapshot performance coverage with fake data in `tests/integration/test_assistant_task_graph_smoke.py`
- [X] T110 [P] Add backend/frontend mock fixtures for task graph, board, meeting, and Todo E2E paths in `frontend/tests/e2e/mock-api.ts`
- [X] T111 Update active architecture documentation for task collaboration, cutover, event, and failure bridge behavior in `docs/ARCHITECTURE.md`
- [X] T112 Update development constraints for task collaboration recovery, retention, and dispatch boundaries in `docs/PROJECT_CONSTRAINTS.md`
- [X] T113 Sync root AI entry mirror with the new task collaboration feature summary in `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`
- [X] T114 Sync backend AI entry mirrors if implementation adds new backend constraints in `src/AGENTS.md`, `src/CLAUDE.md`, and `src/GEMINI.md`
- [X] T115 Sync frontend AI entry mirrors if implementation adds new frontend task UI constraints in `frontend/AGENTS.md`, `frontend/CLAUDE.md`, and `frontend/GEMINI.md`
- [X] T116 Run focused backend verification from quickstart and record any intentional exceptions in `specs/023-unified-task-collaboration/quickstart.md`
- [X] T117 Run frontend lint/unit/E2E verification from quickstart and record any intentional exceptions in `specs/023-unified-task-collaboration/quickstart.md`
- [X] T118 Run formatting and lint checks for changed Python paths and fix issues in `src/`
- [X] T119 Run broad regression for task-related backend and guardrail tests and fix issues in `tests/`

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 Setup has no dependencies.
- Phase 2 Foundational depends on Phase 1 and blocks all user stories.
- Phase 3 US1 depends on Phase 2 and is MVP Gate A.
- Phase 4 US2 depends on US1 core graph/recovery and is MVP Gate B.
- Phase 5 US3 depends on US1/US2 gate tests passing.
- Phase 6 US4 depends on stable task graph display projection and can start after US1/US2 gates.
- Phase 7 Polish depends on all selected story phases.

### User Story Dependencies

- US1 is the first shippable slice and must pass before P2 failure/adjudication gates are considered complete.
- US2 depends on US1 graph, dispatcher, recovery, and event foundations.
- US3 depends on US1 graph and US2 adjudication/stop/cancel semantics.
- US4 depends on US1 task ownership/projection and US2 safety boundaries; it does not depend on US3 meetings or board.

### Within Each User Story

- Write tests first and verify they fail before implementation.
- Data/repository work precedes business services.
- Business services precede desktop API endpoints and event projection.
- Backend API/event contracts precede frontend API/store/panel wiring.
- Complete and validate each checkpoint before moving to the next priority phase.

---

## Parallel Opportunities

- Setup placeholders T002-T006 can run in parallel.
- Foundational repository tasks T015-T022 can run in parallel after ORM/migration shape is agreed.
- US1 tests T029-T036 can be written in parallel; frontend components T050-T052 can proceed after API/store contracts T047-T049.
- US2 tests T053-T058 can be written in parallel; service/API/frontend tasks should follow T059-T067 ordering.
- US3 tests T072-T077 can be written in parallel; board, meeting, and question services T078-T080 can be implemented in parallel after foundational repos.
- US4 tests T092-T096 can be written in parallel; Todo backend and frontend work can proceed in parallel after API DTOs are stable.
- Polish documentation T111-T115 can run in parallel after behavior is implemented.

---

## Parallel Execution Examples

### User Story 1

```text
Task: T029 Add controlled async dispatch tests in tests/business/agents/test_task_dispatch_async.py
Task: T030 Add crash recovery tests in tests/business/agents/test_task_recovery.py
Task: T034 Add frontend task graph store tests in frontend/tests/unit/assistant-task-store.test.ts
Task: T035 Add frontend task graph panel tests in frontend/tests/unit/assistant-task-panels.test.tsx
```

### User Story 2

```text
Task: T053 Add adjudication tests in tests/business/agents/test_task_adjudication.py
Task: T054 Add idempotency tests in tests/business/agents/test_task_idempotency.py
Task: T055 Add idempotency negative tests in tests/business/agents/test_task_idempotency_negative.py
Task: T057 Add failure bridge tests in tests/integration/test_assistant_task_failure_bridge.py
```

### User Story 3

```text
Task: T072 Add question route tests in tests/business/agents/test_task_questions.py
Task: T073 Add board claim tests in tests/business/agents/test_task_board_claims.py
Task: T074 Add meeting tests in tests/business/agents/test_task_meetings.py
Task: T077 Add frontend board and meeting panel tests in frontend/tests/unit/assistant-task-panels.test.tsx
```

### User Story 4

```text
Task: T092 Add Todo persistence tests in tests/business/agents/test_task_todos.py
Task: T093 Add Todo API tests in tests/desktop_api/test_assistant_task_api.py
Task: T095 Add Todo panel tests in frontend/tests/unit/assistant-task-panels.test.tsx
Task: T096 Add Todo brain-boundary guard test in tests/guardrails/test_assistant_task_boundaries.py
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1 Setup.
2. Complete Phase 2 Foundational.
3. Complete Phase 3 US1 and validate MVP Gate A.
4. Complete Phase 4 US2 and validate MVP Gate B.
5. Stop for review before starting P3/P4 collaboration extras.

### Incremental Delivery

1. US1 delivers durable observable task graph and safe recovery.
2. US2 adds adjudication, stop/continue, cancel, and root failure bridge.
3. US3 adds board, meetings, and agent-to-agent question/resource routes.
4. US4 adds private Todo checklist.
5. Polish validates contract sync, documentation, performance, and regressions.

### Risk Controls

- Do not enable unified dispatch by default if any controlled smoke test finds duplicate side effects, permanent `running` tasks, or unsafe auto-replay.
- Keep `pending_assistant_tasks` as legacy background job infrastructure unless an explicit task renames it with a compatibility repository.
- Do not use `workflow_transitions` as task truth after cutover; keep it only as debug/audit breadcrumb.
- Do not mark delegate, meeting, Todo, or mutation tools as `is_concurrency_safe`.
