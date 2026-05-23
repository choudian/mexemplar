# Tasks: Assistant Brain Redesign

**Input**: Design documents from `specs/010-assistant-brain-redesign/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`
**Tests**: Required by the specification for Segment state machine, Repository CRUD, distillation, context injection, specialist logic, smoke tests, and guardrails.
**Organization**: Tasks are grouped by user story so each story can be implemented and verified as an independent increment.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the minimal package and module entry points needed by later phases.

- [X] T001 Create the backend brain package entry point in `src/business/brain/__init__.py`
- [X] T002 [P] Create the backend brain test package entry point in `tests/business/brain/__init__.py`
- [X] T003 [P] Create the frontend brain screen barrel in `frontend/src/screens/BrainScreen/index.ts`
- [X] T004 [P] Create the frontend specialist screen barrel in `frontend/src/screens/SpecialistScreen/index.ts`
- [X] T005 [P] Create the typed brain API module scaffold in `frontend/src/api/brain.ts`
- [X] T006 [P] Create the frontend brain unit test setup file in `frontend/tests/unit/brain/setup.ts`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared schema, events, configuration, and desktop bridge wiring that all stories depend on.

**Critical**: No user story implementation should begin until this phase is complete.

### Tests for Foundational Work

- [X] T007 [P] Add v11 migration and ORM model coverage in `tests/data/test_brain_migration.py`
- [X] T008 [P] Add brain blinker event contract coverage in `tests/utils/test_brain_events.py`
- [X] T009 [P] Add architecture guardrails for brain layering and unchanged recording agents in `tests/guardrails/test_brain_guardrails.py`

### Implementation for Foundational Work

- [X] T010 Add `BrainSegment`, `BrainMemoryEntry`, `BrainSpecialist`, `BrainSpecialistVersion`, `BrainRecruitmentSignal`, and `FeedbackSignal` ORM models in `src/data/models_sqlite.py`
- [X] T011 Add `migrate_to_v11()` and register version 11 in `_MIGRATIONS` in `src/data/migrations.py`
- [X] T012 [P] Add `brain.*` configuration defaults and typed access helpers in `src/data/unified_config.py`
- [X] T013 [P] Add `brain.*` example configuration entries in `config.example.json` and `config.example.comments.md`
- [X] T014 [P] Document the Settings UI exposure decision for `brain.*` tuning knobs in `docs/PROJECT_CONSTRAINTS.md`
- [X] T015 [P] Define `brain_zone_changed`, `brain_specialist_changed`, `segment_boundary_triggered`, `segment_idle_trigger`, `brain_specialist_recruited`, and `brain_context_ready` in `src/utils/events.py`
- [X] T016 [P] Define shared brain constants and dataclasses in `src/business/brain/models.py`
- [X] T017 [P] Create the Segment boundary service shell in `src/business/brain/segment_service.py`
- [X] T018 [P] Add brain UI event projections and resync domain support in `src/desktop_api/ui_events.py`
- [X] T019 Register the brain desktop router in `src/desktop_api/app.py`
- [X] T020 Create the `/api/brain` router scaffold in `src/desktop_api/routers/brain.py`

**Checkpoint**: Database schema, configuration, events, and API routing are ready for story work.

---

## Phase 3: User Story 1 - 跨对话延续的工作记忆 (Priority: P1) - MVP

**Goal**: Deliver the base brain architecture with hot zone, persistent zone, Segment distillation, cold-start icebreaker, and next-session context injection.

**Independent Test**: User chats about a topic, closes or idles the conversation, the Segment is sealed and distilled, and a later assistant session can reference the prior context without the user repeating it.

### Tests for User Story 1

- [X] T021 [P] [US1] Add BrainRepository CRUD and atomic Segment transition tests in `tests/data/test_brain_repository.py`
- [X] T022 [P] [US1] Add Segment state machine and crash reset tests in `tests/business/brain/test_segment_state_machine.py`
- [X] T023 [P] [US1] Add Segment boundary source tests for window close, new session, and token/message limit in `tests/business/brain/test_segment_state_machine.py`
- [X] T024 [P] [US1] Add regression coverage proving delegation events do not seal Segments in `tests/business/brain/test_segment_state_machine.py`
- [X] T025 [P] [US1] Add P1 hot/persistent distillation schema tests in `tests/business/brain/test_distillation_service.py`
- [X] T026 [P] [US1] Add hot-zone and persistent-zone context injection tests in `tests/business/brain/test_context_builder.py`
- [X] T027 [P] [US1] Add Segment distillation integration smoke tests with a mocked LLM in `tests/integration/test_brain_distillation.py`
- [X] T028 [P] [US1] Add P1 zone summary, segment retry, and idle trigger API tests in `tests/desktop_api/test_brain_api.py`
- [X] T029 [P] [US1] Add frontend idle Segment trigger tests in `frontend/tests/unit/brain/assistantIdleSegment.test.tsx`
- [X] T030 [P] [US1] Add assistant reconnect context smoke coverage in `frontend/tests/e2e/brain-segment.spec.ts`

### Implementation for User Story 1

- [X] T031 [US1] Implement Memory Entry and Segment CRUD plus compare-and-swap status transitions in `src/data/repos/brain_repository.py`
- [X] T032 [US1] Export `BrainRepository` from `src/data/repos/__init__.py`
- [X] T033 [US1] Implement Segment sealing for `window_close`, `idle`, `new_session`, and `token_limit` in `src/business/brain/segment_service.py`
- [X] T034 [US1] Wire desktop window-close Segment boundary handoff in `src-tauri/src/main.rs` and `src/desktop_api/routers/assistant.py`
- [X] T035 [US1] Trigger new-session Segment boundaries when assistant sessions are created or switched in `frontend/src/state/assistantStore.ts`
- [X] T036 [US1] Trigger token/message limit Segment boundaries from assistant orchestration in `src/business/orchestration/agent/orchestrator.py`
- [X] T037 [US1] Implement P1 `distillation_output` schema, structural validation, all-empty retry, and transactional writes in `src/business/brain/distillation_service.py`
- [X] T038 [US1] Implement session-start context assembly with persistent-zone full injection and hot-zone top-N selection in `src/business/brain/context_builder.py`
- [X] T039 [US1] Implement pending Segment processing, distilling crash reset, and event wakeup in `src/business/brain/background_worker.py`
- [X] T040 [US1] Start and stop `BrainBackgroundWorker` during desktop API lifespan in `src/desktop_api/app.py`
- [X] T041 [US1] Replace legacy assistant summary injection with `BrainContextBuilder` output in `src/business/orchestration/agent/assistant_prompt_builder.py`
- [X] T042 [US1] Update the assistant system prompt for brain context sections and cold-start icebreaker behavior in `src/business/agents/prompts/assistant_prompt.py`
- [X] T043 [US1] Implement P1 `/api/brain/zones`, `/api/brain/zones/{zone}/entries`, `/api/brain/segments`, and `/api/brain/segments/{segment_id}/retry` in `src/desktop_api/routers/brain.py`
- [X] T044 [US1] Implement `POST /api/assistant/sessions/{session_id}/segment-idle` in `src/desktop_api/routers/assistant.py`
- [X] T045 [US1] Add `triggerAssistantSegmentIdle()` to the typed API client in `frontend/src/api/assistant.ts`
- [X] T046 [US1] Add frontend inactivity tracking and debounce state in `frontend/src/state/assistantStore.ts`
- [X] T047 [US1] Wire the idle timer lifecycle into the assistant page in `frontend/src/screens/assistant/AssistantScreen.tsx`

**Checkpoint**: User Story 1 is independently usable as the MVP.

---

## Phase 4: User Story 2 - 永久身份与可回溯的历史档案 (Priority: P2)

**Goal**: Activate long-term persistent experience, archive-zone writes, layered archive indexing, and explicit archive retrieval.

**Independent Test**: Existing assistant profile facts are visible as persistent-zone entries, and the assistant can retrieve an old event by explicitly calling archive retrieval.

### Tests for User Story 2

- [X] T048 [P] [US2] Add archive retrieval ranking and invalidated fallback tests in `tests/business/brain/test_retrieval_service.py`
- [X] T049 [P] [US2] Add hot-zone fade routing tests for `event` and `insight` entries in `tests/business/brain/test_decay_router.py`
- [X] T050 [P] [US2] Add revived-session positive weighting tests in `tests/business/brain/test_context_builder.py`
- [X] T051 [P] [US2] Add assistant `retrieve_archive` tool tests in `tests/business/agents/tools/test_assistant_brain_tools.py`
- [X] T052 [P] [US2] Add long-term context and archive retrieval integration tests in `tests/integration/test_brain_archive_retrieval.py`

### Implementation for User Story 2

- [X] T053 [US2] Extend phase-aware distillation to include `archive_zone` writes in `src/business/brain/distillation_service.py`
- [X] T054 [US2] Implement hot-zone fading and `event` versus `insight` routing in `src/business/brain/decay_router.py`
- [X] T055 [US2] Implement archive unit and time-layer aggregation jobs in `src/business/brain/archive_service.py`
- [X] T056 [US2] Implement explicit archive retrieval and invalidated fallback in `src/business/brain/retrieval_service.py`
- [X] T057 [US2] Add the `retrieve_archive(query)` assistant tool in `src/business/agents/tools/assistant_tools.py`
- [X] T058 [US2] Register `retrieve_archive` for assistant sessions in `src/business/orchestration/agent/orchestrator.py`
- [X] T059 [US2] Blend relevance, recency, effectiveness, and exploration allowance for hot-zone ranking in `src/business/brain/context_builder.py`
- [X] T060 [US2] Apply revived-session positive weighting during context and retrieval scoring in `src/business/brain/context_builder.py`
- [X] T061 [US2] Schedule hot-zone decay sweeps and archive layering jobs in `src/business/brain/background_worker.py`

**Checkpoint**: User Stories 1 and 2 both work without the management UI.

---

## Phase 5: User Story 3 - 100% 调度与可复用专员 (Priority: P3)

**Goal**: Switch assistant task behavior to dispatch, add ephemeral subagents, fixed specialists, structured replies, and specialist CRUD APIs.

**Independent Test**: A task request is delegated rather than executed inline, a user-created specialist is persisted, and later matching work is delegated to that specialist.

### Tests for User Story 3

- [X] T062 [P] [US3] Add assistant dispatch tool behavior tests in `tests/business/agents/test_assistant_dispatch_tools.py`
- [X] T063 [P] [US3] Add SpecialistService CRUD, whitelist, and versioning tests in `tests/business/brain/test_specialist_service.py`
- [X] T064 [P] [US3] Add SpecialistRepository persistence tests in `tests/data/test_specialist_repository.py`
- [X] T065 [US3] Add specialist REST contract tests in `tests/desktop_api/test_brain_api.py`
- [X] T066 [P] [US3] Add labeled assistant dispatch acceptance tests in `tests/integration/test_assistant_dispatch.py`
- [X] T067 [P] [US3] Extend guardrails to prove PM, Programmer, and Trial are excluded from assistant dispatch in `tests/guardrails/test_brain_guardrails.py`

### Implementation for User Story 3

- [X] T068 [US3] Add `EPHEMERAL_SUBAGENT` and `SPECIALIST` agent types and display names in `src/business/agents/config.py`
- [X] T069 [US3] Implement interrupting `reply_to_user(text, memory_entries_referenced)` in `src/business/agents/tools/assistant_tools.py`
- [X] T070 [US3] Implement `delegate_to_subagent`, `delegate_to_specialist`, and `create_specialist` in `src/business/agents/tools/assistant_tools.py`
- [X] T071 [US3] Implement specialist persistence and version history in `src/data/repos/specialist_repository.py`
- [X] T072 [US3] Export `SpecialistRepository` from `src/data/repos/__init__.py`
- [X] T073 [US3] Implement specialist CRUD, skill whitelist subset checks, and user-conversation creation in `src/business/brain/specialist_service.py`
- [X] T074 [US3] Add ephemeral subagent and specialist execution paths to `src/business/orchestration/agent/orchestrator.py`
- [X] T075 [US3] Register `reply_to_user`, delegation, and specialist creation tools for assistant sessions in `src/business/orchestration/agent/orchestrator.py`
- [X] T076 [US3] Batch-update `referenced_count` from `memory_entries_referenced` in `src/data/repos/brain_repository.py`
- [X] T077 [US3] Implement `/api/brain/specialists` create, list, update, and delete endpoints in `src/desktop_api/routers/brain.py`
- [X] T078 [US3] Enforce specialist whitelist subset validation against the assistant skill pool in `src/business/brain/specialist_service.py`
- [X] T079 [US3] Update the assistant prompt with task-versus-conversation classification and 100% dispatch rules in `src/business/agents/prompts/assistant_prompt.py`

**Checkpoint**: Assistant dispatch and user-created specialists are independently demonstrable.

---

## Phase 6: User Story 4 - 避坑、人格感知与自我校准 (Priority: P4)

**Goal**: Activate failure-zone retrieval, subconscious-zone context, prediction generation and verification, and memory invalidation.

**Independent Test**: A decision task triggers failure retrieval, subconscious entries can evolve, and prediction entries receive automatic verification status after the checkpoint.

### Tests for User Story 4

- [X] T080 [P] [US4] Add failure retrieval and invalidation tool tests in `tests/business/agents/tools/test_assistant_brain_tools.py`
- [X] T081 [P] [US4] Add subconscious ranking and prediction invisibility tests in `tests/business/brain/test_context_builder.py`
- [X] T082 [P] [US4] Add prediction generation and verification worker tests in `tests/business/brain/test_prediction_worker.py`
- [X] T083 [P] [US4] Add feedback signal persistence, prompt-injection, and silence no-op tests in `tests/business/brain/test_feedback_signals.py`
- [X] T084 [P] [US4] Add failure-zone and prediction self-calibration integration tests in `tests/integration/test_brain_self_calibration.py`

### Implementation for User Story 4

- [X] T085 [US4] Extend phase-aware distillation to include `subconscious_zone` and `failure_zone` writes in `src/business/brain/distillation_service.py`
- [X] T086 [US4] Implement system supersession, soft delete, invalidation, and feedback signal writes in `src/data/repos/brain_repository.py`
- [X] T087 [US4] Add `retrieve_failure_zone(context)` and `invalidate_memory_entry(entry_id, reason)` assistant tools in `src/business/agents/tools/assistant_tools.py`
- [X] T088 [US4] Register failure retrieval and invalidation tools for assistant sessions in `src/business/orchestration/agent/orchestrator.py`
- [X] T089 [US4] Implement prediction generation and verification service logic in `src/business/brain/prediction_service.py`
- [X] T090 [US4] Schedule prediction generation, prediction verification, subconscious distillation, and invalidation review jobs in `src/business/brain/background_worker.py`
- [X] T091 [US4] Load relevant feedback signals into distillation prompts in `src/business/brain/distillation_service.py`
- [X] T092 [US4] Load relevant feedback signals into recruitment prompts in `src/business/brain/specialist_service.py`
- [X] T093 [US4] Inject subconscious top-N entries and keep prediction-zone entries invisible in `src/business/brain/context_builder.py`
- [X] T094 [US4] Reject invalidation attempts for entries outside the current context window in `src/business/brain/retrieval_service.py`

**Checkpoint**: Avoidance, personality reference, and self-calibration behavior are independently testable.

---

## Phase 7: User Story 5 - 自动招人与大脑管理模块 (Priority: P5)

**Goal**: Deliver automatic specialist recruitment, toast notification, brain management UI, specialist management UI, skill-pool management, and full feedback loop visibility.

**Independent Test**: A repeated delegation pattern auto-creates a specialist with a reason, a toast appears without blocking work, and the user can view, edit, delete, and inspect all six-zone entries plus specialists and skill-pool permissions.

### Tests for User Story 5

- [X] T095 [P] [US5] Add automatic specialist recruitment tests in `tests/business/brain/test_specialist_recruitment.py`
- [X] T096 [P] [US5] Add brainStore zone, entry, segment, and skill-pool tests in `frontend/tests/unit/brain/brainStore.test.ts`
- [X] T097 [P] [US5] Add specialistStore CRUD and whitelist tests in `frontend/tests/unit/brain/specialistStore.test.ts`
- [X] T098 [P] [US5] Add BrainScreen view, edit, delete, reason, and evolution-chain tests in `frontend/tests/unit/brain/BrainScreen.test.tsx`
- [X] T099 [P] [US5] Add SpecialistScreen create, edit, delete, and whitelist tests in `frontend/tests/unit/brain/SpecialistScreen.test.tsx`
- [X] T100 [P] [US5] Add BrainToast non-modal recruitment notification tests in `frontend/tests/unit/brain/BrainToast.test.tsx`
- [X] T101 [P] [US5] Add end-to-end brain management smoke tests in `frontend/tests/e2e/brain.spec.ts`

### Implementation for User Story 5

- [X] T102 [US5] Implement sustained delegation pattern scanning and auto-recruitment in `src/business/brain/specialist_service.py`
- [X] T103 [US5] Emit `brain_specialist_recruited` after successful auto-recruitment in `src/business/brain/background_worker.py`
- [X] T104 [US5] Forward `brain_zone_changed`, `brain_specialist_recruited`, and `brain_context_ready` as SSE events in `src/desktop_api/events.py`
- [X] T105 [US5] Implement all brain REST contract functions in `frontend/src/api/brain.ts`
- [X] T106 [US5] Implement zone entries, segments, entry evolution, and skill-pool state in `frontend/src/state/brainStore.ts`
- [X] T107 [US5] Implement specialist list, edit draft, and whitelist state in `frontend/src/state/specialistStore.ts`
- [X] T108 [US5] Add `brain` and `brain-specialists` route IDs while preserving the `/brain/specialists` navigation target in `frontend/src/state/shellStore.ts`
- [X] T109 [US5] Register `brain` and `brain-specialists` route definitions with the `/brain/specialists` management URL mapping in `frontend/src/app/routes.tsx`
- [X] T110 [US5] Implement six-zone browsing, filtering, reasons, edit, and delete flows in `frontend/src/screens/BrainScreen/BrainScreen.tsx`
- [X] T111 [US5] Implement annotated evolution-chain diff display in `frontend/src/screens/BrainScreen/EntryEvolution.tsx`
- [X] T112 [US5] Implement the assistant skill-pool management panel without duplicating Skills or Compositions screens in `frontend/src/screens/BrainScreen/SkillPoolPanel.tsx`
- [X] T113 [US5] Implement specialist management page CRUD and whitelist editing in `frontend/src/screens/SpecialistScreen/SpecialistScreen.tsx`
- [X] T114 [US5] Implement recruitment toast with a `/brain/specialists` specialist link and visible reason in `frontend/src/components/BrainToast.tsx`
- [X] T115 [US5] Wire brain SSE events and the recruitment toast into the app shell in `frontend/src/app/AppShell.tsx`
- [X] T116 [US5] Implement entry edit, soft delete, evolution, segment retry, and skill-pool force-remove endpoints in `src/desktop_api/routers/brain.py`
- [X] T117 [US5] Implement skill-pool force removal and automatic specialist whitelist pruning in `src/business/brain/specialist_service.py`

**Checkpoint**: Full user-facing brain management and automatic recruitment are complete.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Update active documentation, keep AI entry mirrors synchronized, and run feature validation.

- [X] T118 [P] Update brain architecture documentation in `docs/ARCHITECTURE.md`
- [X] T119 [P] Update brain configuration and data-boundary constraints in `docs/PROJECT_CONSTRAINTS.md`
- [X] T120 [P] Synchronize backend module AI entry mirrors in `src/AGENTS.md`, `src/CLAUDE.md`, and `src/GEMINI.md`
- [X] T121 [P] Synchronize frontend module AI entry mirrors in `frontend/AGENTS.md`, `frontend/CLAUDE.md`, and `frontend/GEMINI.md`
- [X] T122 [P] Synchronize root AI entry mirrors for the new feature status in `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`
- [X] T123 Run backend P1-P5 unit and integration validation commands documented in `specs/010-assistant-brain-redesign/quickstart.md`
- [X] T124 Run frontend Vitest and Playwright validation commands documented in `specs/010-assistant-brain-redesign/quickstart.md`
- [X] T125 Run guardrail and architecture regression suites documented in `specs/010-assistant-brain-redesign/quickstart.md`
- [X] T126 Run Python compile and TypeScript checks documented in `specs/010-assistant-brain-redesign/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

1. Setup has no dependencies and can start immediately.
2. Foundational depends on Setup and blocks all user stories.
3. User Story 1 depends on Foundational and is the MVP.
4. User Story 2 depends on User Story 1 because archive writes and retrieval build on Segment distillation.
5. User Story 3 depends on User Stories 1 and 2 because dispatch uses brain context and archive retrieval.
6. User Story 4 depends on User Stories 1 through 3 because failure retrieval, subconscious context, invalidation, and prediction jobs use the established brain and reply metadata.
7. User Story 5 depends on User Stories 1 through 4 because the management UI and recruitment expose the full data and specialist loop.
8. Polish depends on whichever story set is being delivered.

### User Story Dependencies

| Story | Depends On | Reason |
|-------|------------|--------|
| US1 | Foundational | Needs v11 schema, events, config, and router wiring |
| US2 | US1 | Archive and decay operate on distilled Segment entries |
| US3 | US1, US2 | Dispatch and specialists use brain context and explicit retrieval |
| US4 | US1, US2, US3 | Invalidation, failure retrieval, and prediction need context, retrieval, and reply metadata |
| US5 | US1, US2, US3, US4 | UI exposes all zones, specialists, feedback, prediction status, and recruitment |

### Within Each User Story

1. Write tests first and confirm they fail.
2. Implement data/repository changes before business services.
3. Implement business services before desktop API endpoints.
4. Implement typed API clients before stores.
5. Implement stores before screens.
6. Complete and validate one story before proceeding to the next priority.

## Parallel Opportunities

Setup tasks marked `[P]` can run in parallel because they create separate files.

Foundational tests marked `[P]` can run in parallel. Foundational implementation tasks marked `[P]` touch separate files and can run after the relevant tests exist.

Within each user story, tests marked `[P]` can run in parallel because they target separate files. Implementation tasks that share the same file are intentionally not marked `[P]`.

After a story checkpoint is validated, later story test writing can begin while documentation updates for the completed story are prepared.

## Parallel Example: User Story 1

```text
Task: T021 Add BrainRepository CRUD and atomic Segment transition tests in tests/data/test_brain_repository.py
Task: T022 Add Segment state machine and crash reset tests in tests/business/brain/test_segment_state_machine.py
Task: T025 Add P1 hot/persistent distillation schema tests in tests/business/brain/test_distillation_service.py
Task: T026 Add hot-zone and persistent-zone context injection tests in tests/business/brain/test_context_builder.py
Task: T027 Add Segment distillation integration smoke tests with a mocked LLM in tests/integration/test_brain_distillation.py
Task: T028 Add P1 zone summary, segment retry, and idle trigger API tests in tests/desktop_api/test_brain_api.py
Task: T029 Add frontend idle Segment trigger tests in frontend/tests/unit/brain/assistantIdleSegment.test.tsx
Task: T030 Add assistant reconnect context smoke coverage in frontend/tests/e2e/brain-segment.spec.ts
```

## Parallel Example: User Story 5

```text
Task: T096 Add brainStore zone, entry, segment, and skill-pool tests in frontend/tests/unit/brain/brainStore.test.ts
Task: T097 Add specialistStore CRUD and whitelist tests in frontend/tests/unit/brain/specialistStore.test.ts
Task: T098 Add BrainScreen view, edit, delete, reason, and evolution-chain tests in frontend/tests/unit/brain/BrainScreen.test.tsx
Task: T099 Add SpecialistScreen create, edit, delete, and whitelist tests in frontend/tests/unit/brain/SpecialistScreen.test.tsx
Task: T100 Add BrainToast non-modal recruitment notification tests in frontend/tests/unit/brain/BrainToast.test.tsx
Task: T101 Add end-to-end brain management smoke tests in frontend/tests/e2e/brain.spec.ts
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup.
2. Complete Phase 2: Foundational.
3. Complete Phase 3: User Story 1.
4. Stop and validate SC-001, SC-003, SC-005, and SC-011.
5. Demo only the hot/persistent brain loop before adding archive, dispatch, or UI management.

### Incremental Delivery

1. Deliver US1 for working memory and persistent facts.
2. Deliver US2 for archive and long-term retrieval.
3. Deliver US3 for dispatch and user-created specialists.
4. Deliver US4 for failure/subconscious/prediction self-calibration.
5. Deliver US5 for automatic recruitment and complete management UI.

### Validation Gates

Each story is considered complete only after its tests pass and its checkpoint scenario can be demonstrated manually or through the quickstart commands in `specs/010-assistant-brain-redesign/quickstart.md`.

## Format Validation

All implementation tasks use the required checklist form `- [ ] T### [P?] [US?] Description with file path`. Setup, foundational, and polish tasks omit the `[US?]` label by design; user-story tasks include `[US1]` through `[US5]`.

---

## Tech Debt Tasks (Generated by /speckit.cleanup)

**Generated**: 2026-05-22
**Source**: Post-implementation cleanup of 010-assistant-brain-redesign
**Priority**: Address before next feature iteration

### Detected Issues

- [ ] TD001 [P] Add typed Pydantic request schemas for brain entry and specialist mutations in `src/desktop_api/routers/brain.py` and `src/desktop_api/schemas.py` - current public API handlers accept raw `dict` bodies, so malformed payloads rely on ad hoc validation instead of the desktop API schema layer.
- [ ] TD002 Audit and close transient Repository instances in long-running brain services in `src/business/brain/background_worker.py`, `src/business/brain/specialist_service.py`, `src/business/brain/segment_service.py`, and `src/business/brain/distillation_service.py` - worker/service code creates repositories outside context managers, which can leave SQLAlchemy sessions open during repeated background ticks.
- [ ] TD003 Expose BrainBackgroundWorker degraded startup state through desktop health/bootstrap coverage in `src/desktop_api/app.py` and `tests/desktop_api/test_health_bootstrap.py` - startup failures are currently warning-only and not visible to the frontend or health checks.

---

## Post-Implementation Fixes (2026-05-23)

**Commit**: `1b4777f` — 在 010 文档定稿和全部 T001-T126 完成后的增量修复与增强。

### Bug Fixes

- [X] PF-001 Batch execution cascade fix — `src/business/agents/agent_loop.py`, `src/business/agents/config.py`, `src/business/agents/tools/builtin_general_tools.py`, `src/business/agents/tools/dynamic_tool_manager.py` — Added `has_side_effects: bool = True` to `ToolDefinition`; tools currently marked side-effect-free (`web_search`, `web_fetch`, `read_file`, `list_dir`, dynamic user tools, composition tools, search tools) no longer cascade failure to subsequent calls. Dynamic user/composition tools are classified this way by current implementation only; future per-tool metadata should set `has_side_effects` from the tool's actual behavior.
- [X] PF-002 Distillation empty-result fix — `src/business/brain/distillation_service.py` — All-empty distillation results now trigger `_retry_or_fail_segment()` instead of silently marking `completed`.
- [X] PF-003 Distillation zone-key tolerance — `src/business/brain/distillation_service.py` — Unexpected zone keys in distillation output are treated as out-of-schema producer output: runtime logs a warning, ignores the unknown keys, and continues with requested active-zone payload instead of silently dropping the whole result.
- [X] PF-004 Prediction verification parsing — `src/business/brain/prediction_service.py` — `_parse_verification_response()` tightened to `startswith`-only matching to avoid false positives from keywords appearing mid-text.
- [X] PF-005 Session suspended recovery — `src/business/agents/agent_loop.py` — `suspended` status added to session recovery conditions alongside `completed` and `failed`.
- [X] PF-006 Brain router validation — `src/desktop_api/routers/brain.py` — Entry edit rejects empty content; specialist creation sanitizes tool_whitelist to non-empty strings only.

### Enhancements

- [X] PF-007 Auto-approve ("全部允许") — `frontend/src/api/assistant.ts`, `frontend/src/components/primitives.tsx`, `frontend/src/screens/assistant/MessageComposer.tsx`, `frontend/src/screens/assistant/ConfirmationToast.tsx`, `frontend/src/state/assistantStore.ts`, `src/desktop_api/routers/assistant.py`, `src/desktop_api/schemas.py` — Toggle in MessageComposer + button in ConfirmationToast + backend endpoint; session-level memory state per CC-006.
- [X] PF-008 Summary message role — `frontend/src/screens/assistant/AssistantScreen.tsx`, `frontend/src/api/assistant.ts`, `frontend/src/api/uiEvents.ts`, `src/data/repos/message_repository.py`, `src/desktop_api/assistant_runtime.py`, `src/desktop_api/routers/assistant.py`, `src/desktop_api/schemas.py`, `src/desktop_api/ui_events.py` — `role` expanded to include `"summary"`; rendered as collapsible `<details>` with SafeMarkdown.
- [X] PF-009 Builtin tool deps via tool_venv — `src/execution/tool_executor.py`, `src/business/agents/tools/builtin_general_tools.py`, `src/desktop_api/app.py` — `BUILTIN_TOOL_DEPS` + `ensure_builtin_deps()` pre-installs on startup; `web_search` runs in tool_venv subprocess.
- [X] PF-010 Teaching failure tracker logging — `src/business/orchestration/agent/teaching_failure_tracker.py` — Added info/warning logs at key decision points.
- [X] PF-011 Sidecar file logging — `src/desktop_api/__main__.py` — Activates `setup_logger()` on startup for file-based logging.
