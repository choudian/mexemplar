# Tasks: 外部 Coding Session（Claude Code / Codex CLI）

**Input**: Design documents from `specs/030-external-coding-sessions/`  
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/external-coding-api.md`, `quickstart.md`

**Tests**: Included because the feature touches orchestration, persistence, configuration, events, API and UI.

**Organization**: Tasks are grouped by user story. US1 is the MVP because no implementation should start before an external plan is reviewed.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create feature scaffolding and shared test locations.

- [X] T001 Create `src/business/external_coding/` package with `__init__.py`, `models.py`, `artifacts.py`, `validators.py`, `quota_probe.py`, `git_ops.py`, `cli_adapters.py`, and `service.py`.
- [X] T002 Create `tests/business/external_coding/` package and fake adapter fixtures for deterministic CLI/session tests.
- [X] T003 Create frontend placeholders `frontend/src/api/externalCodingSessions.ts` and `frontend/src/state/externalCodingSessionStore.ts`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Persistence, configuration, events and execution boundaries used by all stories.

**CRITICAL**: No user story work can be complete until this phase is complete.

- [X] T004 Add SQLite v27 migration in `src/data/migrations.py` for external coding session, attempt, quota observation, merge record and rollback decision tables, plus v28 worktree baseline hardening.
- [X] T005 Add ORM models in `src/data/models_sqlite.py` matching `data-model.md` constraints and indexes.
- [X] T006 Add `ExternalCodingSessionRepository` in `src/data/repos/external_coding_session_repository.py` with create/get/list/update/attempt/quota/merge/rollback methods.
- [X] T007 Add unified config defaults/getters in `src/data/unified_config.py` for tool paths, launch defaults, artifact/worktree roots, timeouts, log tail and quota probe behavior.
- [X] T008 Add `external_coding_session_changed` internal event in `src/utils/events.py`.
- [X] T009 Register `assistant.external_coding.changed` in `src/desktop_api/ui_events.py` and project safe payloads in `src/desktop_api/ui_event_projector.py`.
- [X] T010 Add execution adapter `src/execution/external_coding_process.py` for managed process launch, bounded stdout/stderr capture and safe command summary.
- [X] T011 Add artifact, semantic validator, quota, git and CLI adapter domain logic in `src/business/external_coding/`.

**Checkpoint**: Foundation ready: database, config, events, execution adapter and domain helpers are available.

---

## Phase 3: User Story 1 - Agent 启动 session 并先审计划 (Priority: P1) MVP

**Goal**: Agent can create an owner-bound session, get `PLAN.md`, inspect it, and approve/reject before implementation.

**Independent Test**: Create a fake tool plan session for a task owner; verify durable session, worktree/artifact paths, `planning -> plan_ready`, plan semantic validation and plan-phase write violation.

### Tests for User Story 1

- [X] T012 [P] [US1] Add repository/migration tests in `tests/data/test_external_coding_session_repository.py`.
- [X] T013 [P] [US1] Add validator and artifact tests in `tests/business/external_coding/test_plan_artifacts.py`.
- [X] T014 [P] [US1] Add service start/plan-ready tests in `tests/business/external_coding/test_service_plan_flow.py`.
- [X] T015 [P] [US1] Add agent tool owner guard tests in `tests/business/external_coding/test_external_coding_tools.py`.

### Implementation for User Story 1

- [X] T016 [US1] Implement `ExternalCodingSessionService.start_session`, handoff writing, worktree creation and plan attempt startup in `src/business/external_coding/service.py`.
- [X] T017 [US1] Implement `refresh_session` plan detection, semantic `PLAN.md` validation and plan-phase dirty diff detection in `src/business/external_coding/service.py`.
- [X] T018 [US1] Add agent tools `start_external_coding_session`, `inspect_external_coding_session`, and `decide_external_coding_plan` in `src/business/agents/tools/external_coding_tools.py`.
- [X] T019 [US1] Wire external coding tools into assistant/specialist configured tool surfaces without exposing them to unowned sessions.
- [X] T020 [US1] Add Desktop API create/list/get/refresh/plan-decision endpoints in `src/desktop_api/routers/external_coding_sessions.py` and include router in `src/desktop_api/app.py`.
- [X] T021 [US1] Extend backend/frontend task snapshot types so related task detail can show external coding session summaries.

**Checkpoint**: US1 works independently and prevents implementation before plan approval.

---

## Phase 4: User Story 2 - 实现、完成和中断恢复 (Priority: P2)

**Goal**: Approved sessions run implementation attempts, classify interruptions, preserve resume context and require valid `RESULT.md` for completion.

**Independent Test**: Fake adapter exits without result, with quota error, and with valid result; verify interrupted/completed states and fixed tool lifetime.

### Tests for User Story 2

- [X] T022 [P] [US2] Add attempt interruption/completion tests in `tests/business/external_coding/test_service_attempts.py`.
- [X] T023 [P] [US2] Add process adapter tests in `tests/business/external_coding/test_cli_adapters.py`.
- [X] T024 [P] [US2] Add API resume/abandon tests in `tests/desktop_api/test_external_coding_sessions_api.py`.

### Implementation for User Story 2

- [X] T025 [US2] Implement `resume_session`, `abandon_session`, fixed-tool enforcement, resume count and safe interruption categories in `ExternalCodingSessionService`.
- [X] T026 [US2] Implement `RESULT.md` semantic validation, changed-file summary and completion snapshot generation.
- [X] T027 [US2] Extend API and agent tools for resume/abandon and detail inspection.
- [X] T028 [US2] Add status-change events for plan_ready/interrupted/completed/waiting_user states.

**Checkpoint**: US1 + US2 support plan, approval, implementation, interruption and completion.

---

## Phase 5: User Story 3 - 自动合并和按意图回滚 (Priority: P3)

**Goal**: Exemplar analyzes dirty/conflict risk, performs accepted low-risk merge itself and records rollback decisions.

**Independent Test**: Use temporary git repos/worktrees to verify dirty no-overlap proceeds, dirty overlap blocks silent merge, and rollback plan records confirmation requirements.

### Tests for User Story 3

- [X] T029 [P] [US3] Add git merge analysis tests in `tests/business/external_coding/test_git_ops.py`.
- [X] T030 [P] [US3] Add merge/rollback service tests in `tests/business/external_coding/test_service_merge.py`.
- [X] T031 [P] [US3] Add guardrail test that external coding tools never merge/push/reset/clean target branch in `tests/guardrails/test_external_coding_guardrails.py`.

### Implementation for User Story 3

- [X] T032 [US3] Implement merge analysis, changed-file/dirty overlap detection and merge record persistence in `src/business/external_coding/git_ops.py` and service.
- [X] T033 [US3] Implement Exemplar-owned merge action with audit fields and conflict/risk blocking.
- [X] T034 [US3] Implement rollback-plan proposal and confirmation metadata in service/repository/API.
- [X] T035 [US3] Add API and agent tools for merge-analysis, merge and rollback-plan.

**Checkpoint**: Completed sessions can be safely analyzed, merged by Exemplar, and rolled back through guided decisions.

---

## Phase 6: User Story 4 - 自动选择工具并关注 quota (Priority: P4)

**Goal**: Agent defaults to a suitable available tool while avoiding exhausted tools and never exposing raw credential data.

**Independent Test**: Inject quota states and verify selection ordering, override handling and DTO/event redaction.

### Tests for User Story 4

- [X] T036 [P] [US4] Add quota probe and selection tests in `tests/business/external_coding/test_quota_probe.py`.
- [X] T037 [P] [US4] Add secret redaction guard tests for quota observations and UI events in `tests/guardrails/test_external_coding_guardrails.py`.

### Implementation for User Story 4

- [X] T038 [US4] Implement normalized quota probes for Claude Code/Codex CLI with safe fallback to `unknown`.
- [X] T039 [US4] Implement automatic tool selection with `available > unknown > low > exhausted` ordering and explicit exhausted override behavior.
- [X] T040 [US4] Persist quota observations and include only safe normalized status in API/UI.

**Checkpoint**: Auto-selection is quota-aware and secret-safe.

---

## Phase 7: UI, Docs and Polish

**Purpose**: User-visible task detail, active docs and validation.

- [X] T041 [P] Add frontend API client, event parser/types and store updates in `frontend/src/api/` and `frontend/src/state/`.
- [X] T042 [P] Render external coding session summary/actions in `frontend/src/screens/assistant/TaskNodeCard.tsx` with bounded previews/log tail.
- [X] T043 [P] Add frontend unit tests in `frontend/tests/unit/externalCodingSessions.test.tsx`.
- [X] T044 Update `docs/ARCHITECTURE.md`, `docs/PROJECT_CONSTRAINTS.md`, `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and affected module AI entry docs if implementation behavior differs from current runtime overview.
- [X] T045 Run quickstart validation commands from `specs/030-external-coding-sessions/quickstart.md` and record any skipped checks with reason.

---

## Dependencies & Execution Order

### Phase Dependencies

- Phase 1 has no dependencies.
- Phase 2 depends on Phase 1 and blocks all user stories.
- US1 depends on Phase 2.
- US2 depends on US1 because implementation requires an approved plan.
- US3 depends on US2 because merge requires a completed session.
- US4 depends on Phase 2 but should land before final US1 integration so auto-selection is active at session start.
- Phase 7 depends on backend API/event contracts and task snapshot shape.

### Parallel Opportunities

- T012-T015 can be written in parallel after T004-T011.
- T022-T024 can be written in parallel after US1 service/API shape exists.
- T029-T031 can be written in parallel after git/repository helpers exist.
- T036-T037 can be written in parallel after quota model/config exists.
- T041-T043 can proceed once API schemas and event type are stable.

### MVP Cut

MVP is Phase 1 + Phase 2 + US1. It creates owner-bound sessions, captures `PLAN.md`, surfaces plan status and prevents unreviewed implementation.
