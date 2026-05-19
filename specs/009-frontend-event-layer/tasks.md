# Tasks: Frontend Event Layer

**Input**: Design documents from `specs/009-frontend-event-layer/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/ui-events.md`, `quickstart.md`

**Tests**: Required. The specification requires automated contract, guard, subscriber, replay, safety, and frontend handler coverage.

**Organization**: Tasks are grouped by user story to enable independent implementation and validation.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish shared contract surfaces and test scaffolding before changing behavior.

- [X] T001 Add public UI event contract notes to `docs/ARCHITECTURE.md`
- [X] T002 Add frontend event-layer guardrails to `docs/PROJECT_CONSTRAINTS.md`
- [X] T003 [P] Create frontend event contract module scaffold in `frontend/src/api/uiEvents.ts`
- [X] T004 [P] Create backend UI event registry/projection scaffold in `src/desktop_api/ui_events.py`
- [X] T005 [P] Add UI event layer test scaffold in `tests/desktop_api/test_ui_event_layer.py`
- [X] T006 [P] Add frontend event contract guard scaffold in `tests/guardrails/test_frontend_event_contract.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before user-story behavior can be implemented.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 Extend `UiEvent` and trial preview decision DTOs in `src/desktop_api/schemas.py`
- [X] T008 Implement registered UI event definitions, payload allowlists, and safe example export in `src/desktop_api/ui_events.py`
- [X] T009 Implement publish-time payload safety validation in `src/desktop_api/ui_events.py`
- [X] T010 Replace the single event queue with a per-subscriber event hub and bounded replay buffer in `src/desktop_api/events.py`
- [X] T011 Preserve thread-safe direct UI event publication for assistant/runtime adapters in `src/desktop_api/events.py`
- [X] T012 Update `/api/events` SSE endpoint to accept same-session replay metadata in `src/desktop_api/app.py`
- [X] T013 Add backend contract tests for registered-only publication and unsafe payload rejection in `tests/desktop_api/test_ui_event_layer.py`
- [X] T014 Add subscriber delivery and replay tests in `tests/desktop_api/test_ui_event_subscribers.py`
- [X] T015 Add guard tests preventing unregistered direct publish bypass paths in `tests/guardrails/test_frontend_event_contract.py`

**Checkpoint**: Backend event hub, registry validation, and basic replay semantics are ready.

---

## Phase 3: User Story 1 - Frontend Consumes Semantic UI Events (Priority: P1)

**Goal**: React stores consume stable registered UI event types rather than internal backend event names.

**Independent Test**: Trigger backend teaching, recording, trial, skills, compositions, settings, and assistant events; frontend handlers update state without referencing `payload.sourceEvent`.

### Tests for User Story 1

- [X] T016 [P] [US1] Add backend projection tests for teaching/recording/trial/skills/settings/compositions/assistant in `tests/desktop_api/test_ui_event_layer.py`
- [X] T017 [P] [US1] Add frontend contract parser and examples tests in `frontend/tests/unit/ui-events.test.ts`
- [X] T018 [P] [US1] Update teaching screen unit test to use `teaching.stage_changed` events in `frontend/tests/unit/teaching-screen.test.tsx`
- [X] T019 [P] [US1] Add guard assertion that `frontend/src/` does not use `sourceEvent` for display decisions in `tests/guardrails/test_frontend_event_contract.py`

### Implementation for User Story 1

- [X] T020 [US1] Implement internal-event-to-UI-event projection in `src/desktop_api/ui_events.py`
- [X] T021 [US1] Wire the blinker adapter through the projection layer in `src/desktop_api/events.py`
- [X] T022 [US1] Define frontend discriminated UI event union and parser helpers in `frontend/src/api/uiEvents.ts`
- [X] T023 [US1] Update `frontend/src/state/teachingStore.ts` to consume `teaching.stage_changed`, `recording.progress`, and `trial.progress` payloads
- [X] T024 [US1] Update `frontend/src/state/assistantStore.ts`, `frontend/src/state/skillsStore.ts`, `frontend/src/state/compositionsStore.ts`, and `frontend/src/state/settingsStore.ts` to consume typed events
- [X] T025 [US1] Update `frontend/src/app/AppShell.tsx` event dispatch to route typed registered events only

**Checkpoint**: P1 works independently; frontend no longer depends on internal event names.

---

## Phase 4: User Story 2 - Reconnect And Per-Subscriber Recovery (Priority: P2)

**Goal**: Multiple event subscribers receive independent copies, slow subscribers resync without blocking healthy subscribers, and reconnect behavior uses same-session sequence replay or authoritative resync.

**Independent Test**: Two subscribers receive the same event for 20 consecutive trials; a slow/overflowed subscriber receives `backend.resync_required`; reconnect with covered gaps replays buffered events, while uncovered gaps request resync.

### Tests for User Story 2

- [X] T026 [P] [US2] Add two-subscriber non-stealing test loop in `tests/desktop_api/test_ui_event_subscribers.py`
- [X] T027 [P] [US2] Add slow subscriber overflow test in `tests/desktop_api/test_ui_event_subscribers.py`
- [X] T028 [P] [US2] Add reconnect replay and gap-resync tests in `tests/desktop_api/test_ui_event_subscribers.py`
- [X] T029 [P] [US2] Add frontend invalid-frame/resync handling tests in `frontend/tests/unit/ui-events.test.ts`

### Implementation for User Story 2

- [X] T030 [US2] Implement subscriber queue registration, broadcast, overflow close, and cleanup in `src/desktop_api/events.py`
- [X] T031 [US2] Implement same-session `lastSeenSequence` replay and `backend.resync_required` control events in `src/desktop_api/events.py`
- [X] T032 [US2] Update `frontend/src/api/client.ts` event stream parsing to track `sequence/sessionId`, ignore invalid frames, and pass replay metadata on reconnect
- [X] T033 [US2] Update `frontend/src/app/AppShell.tsx` to refresh authoritative bootstrap state on `backend.resync_required`
- [X] T034 [US2] Add current teaching run snapshot support in `src/business/services/teaching_service.py` and `src/desktop_api/routers/teaching.py`
- [X] T035 [US2] Add frontend authoritative refresh helpers for teaching, skills, compositions, and settings stores in `frontend/src/state/`

**Checkpoint**: P2 works independently; subscribers do not compete and recovery is explicit.

---

## Phase 5: User Story 3 - Trial Preview Confirmation Safety Loop (Priority: P3)

**Goal**: Desktop trial preview requests are broadcast to scoped subscribers, expire on backend-generated deadlines, and return deterministic approve/deny/timeout outcomes to the waiting workflow.

**Independent Test**: A preview request can be approved, denied, timed out, duplicated, or conflicted; all non-approve outcomes fail closed.

### Tests for User Story 3

- [X] T036 [P] [US3] Add trial preview approval/denial tests in `tests/desktop_api/test_trial_preview_events.py`
- [X] T037 [P] [US3] Add trial preview timeout and duplicate/conflict tests in `tests/desktop_api/test_trial_preview_events.py`
- [X] T038 [P] [US3] Add frontend trial preview event typing tests in `frontend/tests/unit/ui-events.test.ts`
- [X] T039 [P] [US3] Add teaching screen preview confirmation controls test in `frontend/tests/unit/teaching-screen.test.tsx`

### Implementation for User Story 3

- [X] T040 [US3] Implement backend pending trial preview request manager in `src/desktop_api/ui_events.py`
- [X] T041 [US3] Register `desktop_trial_preview_ready` as an interactive backend listener that publishes `trial.preview_requested` and waits for a decision in `src/desktop_api/events.py`
- [X] T042 [US3] Add `POST /api/teaching/trial-preview/{request_id}/decision` in `src/desktop_api/routers/teaching.py`
- [X] T043 [US3] Add frontend trial preview decision client function in `frontend/src/api/teaching.ts`
- [X] T044 [US3] Add frontend store state for `trial.preview_requested` and `trial.preview_resolved` in `frontend/src/state/teachingStore.ts`
- [X] T045 [US3] Render trial preview confirmation controls in `frontend/src/screens/teaching/TrialStage.tsx`

**Checkpoint**: P3 works independently; preview confirmation cannot default-approve.

---

## Phase 6: User Story 4 - Contract Drift And Safety Verification (Priority: P4)

**Goal**: Maintainers can verify backend registry, frontend event types, example payloads, and guardrails stay aligned.

**Independent Test**: Contract tests fail if an event exists only on one side, if unsafe fields enter examples, or if code bypasses validation/envelope creation.

### Tests for User Story 4

- [X] T046 [P] [US4] Add backend registry export consistency tests in `tests/desktop_api/test_ui_event_layer.py`
- [X] T047 [P] [US4] Add frontend/backend event type drift guard in `tests/guardrails/test_frontend_event_contract.py`
- [X] T048 [P] [US4] Add payload safety example coverage in `tests/desktop_api/test_ui_event_layer.py`

### Implementation for User Story 4

- [X] T049 [US4] Export backend registry examples in `src/desktop_api/ui_events.py`
- [X] T050 [US4] Export frontend event type list/examples in `frontend/src/api/uiEvents.ts`
- [X] T051 [US4] Update `tests/desktop_api/test_app_contract.py` if the event schema changed

**Checkpoint**: P4 works independently; drift and bypasses are test-visible.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Active documentation, validation, and Spec Kit completion artifacts.

- [X] T052 [P] Update `docs/ARCHITECTURE.md` with backend-owned UI event projection and per-subscriber event stream semantics
- [X] T053 [P] Update `docs/PROJECT_CONSTRAINTS.md` with public UI event registry and `sourceEvent` prohibition
- [X] T054 [P] Ensure root `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` remain synchronized for the active 009 plan pointer
- [X] T055 Run backend event-layer validation from `specs/009-frontend-event-layer/quickstart.md`
- [X] T056 Run frontend event-layer validation from `specs/009-frontend-event-layer/quickstart.md`
- [X] T057 Run guardrail validation from `specs/009-frontend-event-layer/quickstart.md`
- [X] T058 Run `/speckit.verify.run`, `/speckit.cleanup.run`, and archive the completed feature

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Phase 1 and blocks all user stories.
- **US1 (Phase 3)**: Depends on Phase 2 and establishes semantic event consumption.
- **US2 (Phase 4)**: Depends on Phase 2; frontend resync integration also depends on US1 typed dispatch.
- **US3 (Phase 5)**: Depends on Phase 2; frontend preview handling depends on US1 typed events.
- **US4 (Phase 6)**: Depends on US1 and the registry export from Phase 2.
- **Polish (Phase 7)**: Depends on desired user stories.

### User Story Dependencies

- **User Story 1 (P1)**: Required for final cutover.
- **User Story 2 (P2)**: Required for reliable event streaming.
- **User Story 3 (P3)**: Required for interactive preview confirmation.
- **User Story 4 (P4)**: Required for drift and safety verification.

### Parallel Opportunities

- T003-T006 can run in parallel.
- T013-T015 can run in parallel after T008-T012.
- Test tasks within each story marked `[P]` can run in parallel.
- Documentation tasks T048-T050 can run in parallel after behavior is settled.

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2.
2. Complete User Story 1 to remove `sourceEvent` UI coupling.
3. Validate backend projection and frontend typed handlers.

### Incremental Delivery

1. Add per-subscriber hub and replay semantics for User Story 2.
2. Add trial preview confirmation loop for User Story 3.
3. Add drift and bypass guardrails for User Story 4.
4. Run quickstart gates, verify, cleanup, and archive.

## Notes

- Do not introduce persistent event storage.
- Do not add new frontend dependencies for contract generation unless tests show manual contract drift cannot be controlled.
- Keep internal blinker event names in backend-only code; React must consume public UI event types.
