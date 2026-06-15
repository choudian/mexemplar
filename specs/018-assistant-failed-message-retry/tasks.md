# Tasks: Assistant Failed Message Retry

**Input**: Design documents from `specs/018-assistant-failed-message-retry/`

## Phase 1: Setup And Contracts

- [X] T001 Persist active feature state in `.specify/feature.json` and validate Spec Kit prerequisites
- [X] T002 [P] Add v14 migration and ORM contract tests in `tests/data/test_migrations.py`
- [X] T003 [P] Add failure classifier and redaction tests in `tests/business/services/test_assistant_failure_classifier.py`
- [X] T004 [P] Add retry REST/event contract tests in `tests/desktop_api/test_assistant_api.py` and `tests/desktop_api/test_assistant_events.py`

## Phase 2: Foundational Data And Business Services

- [X] T005 Add `AssistantRunFailure` ORM model in `src/data/models_sqlite.py`
- [X] T006 Add v14 `assistant_run_failures` migration in `src/data/migrations.py`
- [X] T007 Implement `AssistantRunFailureRepository` in `src/data/repos/assistant_run_failure_repository.py` and export it
- [X] T008 Implement safe failure classification in `src/business/services/assistant_failure_classifier.py`
- [X] T009 Implement Repository-backed `AssistantFailureService` in `src/business/services/assistant_failure_service.py`
- [X] T010 Add Repository state-machine, duplicate retry, and startup recovery tests in `tests/data/test_assistant_run_failure_repository.py`

## Phase 3: User Story 1 - Recover A Failed Turn (Priority: P1)

**Goal**: Persist terminal failures, restore them on history load, and retry the original message.

**Independent Test**: Fail a turn, reload history, retry, and observe card removal after success.

- [X] T011 [US1] Extend chat display models and service lookup in `src/business/services/chat_service.py`
- [X] T012 [US1] Extend Assistant DTOs and retry schemas in `src/desktop_api/schemas.py`
- [X] T013 [US1] Extend `assistant.message` safe payload contract in `src/desktop_api/ui_events.py`
- [X] T014 [US1] Persist and publish terminal failures in correct order in `src/desktop_api/assistant_runtime.py`
- [X] T015 [US1] Add retry endpoint and HTTP mappings in `src/desktop_api/routers/assistant.py`
- [X] T016 [US1] Recover interrupted `retrying` records during sidecar startup in `src/desktop_api/app.py`
- [X] T017 [US1] Add runtime ordering, success resolution, repeat-failure, and no-raw-detail tests in `tests/desktop_api/test_assistant_runtime.py`

## Phase 4: User Story 2 - Edit Before Retrying (Priority: P2)

**Goal**: Support inline edit-and-retry without mutating the original message.

**Independent Test**: Edit a failed request, submit it, and verify a new user message owns any new failure.

- [X] T018 [P] [US2] Add typed retry API and failure DTO in `frontend/src/api/assistant.ts`
- [X] T019 [US2] Add retry request state and authoritative event reconciliation in `frontend/src/state/assistantStore.ts`
- [X] T020 [P] [US2] Create inline recovery UI in `frontend/src/screens/assistant/AssistantFailureCard.tsx`
- [X] T021 [US2] Attach recovery cards to user bubbles in `frontend/src/screens/assistant/AssistantScreen.tsx`
- [X] T022 [US2] Add styles in the existing Assistant stylesheet
- [X] T023 [US2] Add history, retry, edit/cancel, loading, dedupe, success, repeat-failure, and no-Toast tests in `frontend/tests/unit/assistant-failure-retry.test.tsx`

## Phase 5: User Story 3 - Inspect Available Diagnostics (Priority: P3)

**Goal**: Open session-filtered Debug Inspector and explain unavailable historical detail.

**Independent Test**: Navigate from a failed card with and without captured traces.

- [X] T024 [US3] Parse `sessionId` and filter/auto-select traces and flows in `frontend/src/screens/debug/DebugScreen.tsx`
- [X] T025 [US3] Add Debug Inspector session filter tests in `frontend/tests/unit/debug-screen.test.tsx`
- [X] T026 [US3] Add mock E2E for failure, unchanged retry, edited retry, and debug navigation in `frontend/tests/e2e/assistant-failure-retry.spec.ts`

## Phase 6: Documentation And Validation

- [X] T027 [P] Update `docs/ARCHITECTURE.md` and `docs/PROJECT_CONSTRAINTS.md`
- [X] T028 [P] Synchronize root, `src/`, and `frontend/` `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`
- [X] T029 Archive the completed local TODO under `_archive/completed-summaries/` when the source TODO exists
- [X] T030 Run focused pytest, Vitest, Playwright, lint, Black, flake8, and `git diff --check`
- [X] T031 Review implementation against `spec.md`, `plan.md`, and `tasks.md`, fix findings, and mark all completed tasks

## Dependencies

- T005-T010 block all user stories.
- US1 is the backend MVP and blocks frontend retry submission.
- US2 depends on US1 contracts.
- US3 depends only on the failure card and existing Debug API.
- Documentation and final validation follow all user stories.

## Implementation Strategy

Implement data/state safety first, then runtime/API wiring, then the inline UI, then diagnostics. Preserve the existing automatic retry and dispatch paths throughout.
