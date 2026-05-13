# Tasks: UI Stack Redesign

**Input**: Design documents from `/specs/008-ui-stack-redesign/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, control-inventory.md, contracts/desktop-backend-api.md, quickstart.md
**Tests**: Required by FR-023 and SC-008. Test tasks are included before implementation tasks in each user story.
**Organization**: Tasks are grouped by user story to enable independent implementation and testing. Major tasks trace to FR/CC/SC identifiers through their phase/story labels and to prototype-visible controls through `control-inventory.md`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Initialize the Tauri/React frontend, Python sidecar API package, and tooling directories.

- [x] T001 Create frontend source and test directories in frontend/src/, frontend/tests/unit/, and frontend/tests/e2e/
- [x] T002 Initialize React/Vite package metadata and scripts in frontend/package.json
- [x] T003 [P] Configure TypeScript, Vite, Tailwind, PostCSS, and test setup in frontend/tsconfig.json, frontend/vite.config.ts, frontend/tailwind.config.ts, frontend/postcss.config.js, and frontend/vitest.config.ts
- [x] T004 [P] Scaffold Tauri configuration and capabilities in src-tauri/Cargo.toml, src-tauri/tauri.conf.json, and src-tauri/capabilities/default.json
- [x] T005 Add FastAPI, Uvicorn, Pydantic, and PyInstaller sidecar dependencies in pyproject.toml
- [x] T006 Create Python sidecar API package skeleton in src/desktop_api/__init__.py and src/desktop_api/routers/__init__.py
- [x] T007 [P] Add frontend lint, unit test, e2e test, tauri dev, and tauri build scripts in frontend/package.json
- [x] T008 Copy or record the UI stack decision input artifact in docs/local/2026-05-10-ui-tech-stack-decision.md and verify specs/008-ui-stack-redesign/control-inventory.md matches the approved prototype

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build shared bridge, auth, event, runtime, and test foundations required by all user stories.

**CRITICAL**: No user story work should begin until this phase is complete.

- [x] T009 Define shared Pydantic DTOs for health, errors, paging, shell bootstrap, events, skills, compositions, and settings in src/desktop_api/schemas.py
- [x] T010 Implement FastAPI app factory, loopback CORS policy, auth-token middleware, and router registration in src/desktop_api/app.py
- [x] T011 Implement sidecar process entrypoint with random localhost port and runtime token handling in src/desktop_api/__main__.py
- [x] T012 Implement backend event queue and blinker-to-UI event stream adapter in src/desktop_api/events.py
- [x] T013 [P] Implement typed frontend API runtime, token header injection, error normalization, and event-stream client in frontend/src/api/client.ts
- [x] T014 [P] Implement global shell, route, and backend-status stores in frontend/src/state/shellStore.ts
- [x] T015 [P] Port shared design primitives from the prototype into frontend/src/components/primitives.tsx with focus states, accessible names/states, and keyboard-operable variants
- [x] T016 [P] Implement theme tokens, density tokens, accessible contrast, reduced-motion handling, and global CSS baseline in frontend/src/styles/theme.css
- [x] T017 Implement Tauri sidecar lifecycle module with PyInstaller binary launch, port/token handoff, and shutdown cleanup in src-tauri/src/sidecar.rs
- [x] T018 [P] Implement scoped Tauri window command module for minimize, maximize/restore, close, and drag handling in src-tauri/src/window.rs
- [x] T019 Wire Tauri plugin-shell, plugin-http, and window command initialization in src-tauri/src/lib.rs
- [x] T020 [P] Add Python API test fixtures for token-authenticated FastAPI clients in tests/desktop_api/conftest.py
- [x] T021 [P] Add frontend unit test setup, Tauri API mocks, and API client mocks in frontend/src/test/setup.ts
- [x] T022 [P] Add architecture guard test scaffolding for frontend/API storage-boundary imports in tests/guardrails/test_ui_stack_boundaries.py
- [x] T023 [P] Add sidecar build helper for copying target-triple PyInstaller output in scripts/build_desktop_sidecar.ps1
- [x] T024 Add repository-wide route registration and OpenAPI smoke test for src/desktop_api/app.py in tests/desktop_api/test_app_contract.py

**Checkpoint**: Foundation ready; user stories can now start in priority order or in parallel with careful file ownership.

---

## Phase 3: User Story 1 - Use The Redesigned App Shell (Priority: P1) MVP

**Goal**: Launch into the redesigned Mexemplar shell with persistent navigation, backend readiness states, and branded custom window controls.

**Independent Test**: Launch the app, confirm AI Assistant is selected by default, navigate all five primary screens, see recoverable backend state, and use red/yellow/green controls for close/minimize/maximize/restore without PyQt fallback.

### Tests for User Story 1

- [x] T025 [P] [US1] Add backend health/bootstrap contract tests in tests/desktop_api/test_health_bootstrap.py
- [x] T026 [P] [US1] Add frontend shell navigation, same-window state-preservation, focus, and keyboard tests in frontend/tests/unit/app-shell.test.tsx
- [x] T027 [P] [US1] Add Tauri launch, five-route navigation, keyboard traversal, and custom chrome smoke tests in frontend/tests/e2e/app-shell.spec.ts
- [x] T028 [P] [US1] Add guard tests proving normal launch paths do not open legacy PyQt windows in tests/guardrails/test_legacy_pyqt_launch.py

### Implementation for User Story 1

- [x] T029 [US1] Implement shell bootstrap business service using existing services and no repository leakage in src/business/services/desktop_bootstrap_service.py
- [x] T030 [US1] Implement health and bootstrap endpoints in src/desktop_api/routers/health.py
- [x] T031 [US1] Complete Tauri sidecar startup, health polling, and shutdown integration in src-tauri/src/sidecar.rs
- [x] T032 [US1] Complete branded custom window action wiring in src-tauri/src/window.rs
- [x] T033 [US1] Implement React app shell layout in frontend/src/app/AppShell.tsx
- [x] T034 [P] [US1] Implement persistent navigation rail with real counts and screen routes in frontend/src/app/NavRail.tsx
- [x] T035 [P] [US1] Implement custom red/yellow/green titlebar and drag region in frontend/src/app/CustomTitlebar.tsx
- [x] T036 [P] [US1] Implement backend readiness, degraded, failed, and shutdown states in frontend/src/app/BackendStatus.tsx
- [x] T037 [US1] Register five primary screen routes and real loading/error placeholders in frontend/src/app/routes.tsx
- [x] T038 [US1] Wire React root, API bootstrap, event client startup, and shell store hydration in frontend/src/main.tsx
- [x] T039 [US1] Configure Tauri app metadata, window dimensions, custom decorations, and externalBin sidecar path in src-tauri/tauri.conf.json

**Checkpoint**: User Story 1 is independently launchable and navigable with backend health states.

---

## Phase 4: User Story 2 - Work In The Redesigned AI Assistant (Priority: P1)

**Goal**: Support conversations, history management, message sending, assistant responses, execution summaries, and non-modal high-risk confirmations in the redesigned assistant screen.

**Independent Test**: Start a conversation, send a message, receive a response, expand an execution summary, search/rename/delete sessions, and approve/deny a high-risk action without modal dialogs.

### Tests for User Story 2

- [x] T040 [P] [US2] Add assistant sessions, messages, rename, delete, and confirmation contract tests in tests/desktop_api/test_assistant_api.py
- [x] T041 [P] [US2] Add assistant progress and confirmation event-stream tests in tests/desktop_api/test_assistant_events.py
- [x] T042 [P] [US2] Add frontend assistant timeline, session sidebar, composer, and confirmation tests in frontend/tests/unit/assistant-screen.test.tsx
- [x] T043 [P] [US2] Add assistant happy-path e2e test with controlled backend fixture and under-2-minute assertion in frontend/tests/e2e/assistant.spec.ts

### Implementation for User Story 2

- [x] T044 [US2] Extend ChatService with search, rename, delete/archive, and display DTO helpers in src/business/services/chat_service.py
- [x] T045 [US2] Implement assistant REST endpoints for sessions, messages, and confirmation decisions in src/desktop_api/routers/assistant.py
- [x] T046 [US2] Implement assistant worker dispatch adapter that preserves AgentOrchestrator semantics in src/desktop_api/assistant_runtime.py
- [x] T047 [US2] Implement high-risk confirmation DTO mapping without raw file or command leakage in src/desktop_api/confirmations.py
- [x] T048 [US2] Map assistant progress, final message, error, and confirmation blinker events in src/desktop_api/events.py
- [x] T049 [P] [US2] Implement typed assistant API client functions in frontend/src/api/assistant.ts
- [x] T050 [P] [US2] Implement assistant session, timeline, draft, progress, and confirmation state in frontend/src/state/assistantStore.ts
- [x] T051 [US2] Implement redesigned assistant screen and timeline composition in frontend/src/screens/assistant/AssistantScreen.tsx
- [x] T052 [P] [US2] Implement conversation list, search, rename, delete, and empty states in frontend/src/screens/assistant/SessionSidebar.tsx
- [x] T053 [P] [US2] Implement message composer, send-state handling, and accepted attachment/voice-control disposition in frontend/src/screens/assistant/MessageComposer.tsx
- [x] T054 [P] [US2] Implement safe assistant markdown rendering in frontend/src/screens/assistant/SafeMarkdown.tsx
- [x] T055 [P] [US2] Implement compact/expandable execution summaries in frontend/src/screens/assistant/ExecutionSummary.tsx
- [x] T056 [P] [US2] Implement non-modal high-risk confirmation surface independent from normal toasts in frontend/src/screens/assistant/ConfirmationToast.tsx

**Checkpoint**: User Story 2 supports the complete redesigned AI Assistant workflow without legacy ChatWidget UI.

---

## Phase 5: User Story 3 - Teach A Skill In The Redesigned Flow (Priority: P1)

**Goal**: Guide users through browser, extension, and desktop recording; intent confirmation; learning progress; failure handling; and trial validation.

**Independent Test**: Use a controlled recording fixture to select a mode, start/stop recording, handle desktop health review if needed, confirm intent, observe learning progress, and reach trial-ready state.

### Tests for User Story 3

- [x] T057 [P] [US3] Add teaching readiness, run creation, recording stop, health decision, intent, and trial API tests in tests/desktop_api/test_teaching_api.py
- [x] T058 [P] [US3] Add teaching progress, recording progress, trial progress, and failure event-stream tests in tests/desktop_api/test_teaching_events.py
- [x] T059 [P] [US3] Add frontend teaching stage, recording mode, health review, and trial progress tests in frontend/tests/unit/teaching-screen.test.tsx
- [x] T060 [P] [US3] Add teaching fixture e2e test through trial-ready state with under-5-minute assertion in frontend/tests/e2e/teaching.spec.ts

### Implementation for User Story 3

- [x] T061 [US3] Implement teaching workflow facade over AgentOrchestrator and existing recording services in src/business/services/teaching_service.py
- [x] T062 [P] [US3] Implement recording readiness service for browser, extension, and desktop prerequisites in src/business/services/recording_readiness_service.py
- [x] T063 [US3] Implement teaching endpoints for readiness, runs, recording, desktop health decisions, intent, and trial start in src/desktop_api/routers/teaching.py
- [x] T064 [US3] Map recording, teaching, trial, desktop sanity, and failure events to frontend DTOs in src/desktop_api/events.py
- [x] T065 [P] [US3] Implement typed teaching API client functions in frontend/src/api/teaching.ts
- [x] T066 [P] [US3] Implement teaching workflow state machine in frontend/src/state/teachingStore.ts
- [x] T067 [US3] Implement redesigned teaching screen shell in frontend/src/screens/teaching/TeachingScreen.tsx
- [x] T068 [P] [US3] Implement browser, extension, and desktop mode cards with readiness/setup actions in frontend/src/screens/teaching/RecordingModePicker.tsx
- [x] T069 [P] [US3] Implement recording active view, timers, stop action, and desktop sanity choices in frontend/src/screens/teaching/RecordingStage.tsx
- [x] T070 [P] [US3] Implement intent confirmation questions and answer submission view in frontend/src/screens/teaching/IntentStage.tsx
- [x] T071 [P] [US3] Implement learning progress, retry, blocked, and failure states in frontend/src/screens/teaching/LearningStage.tsx
- [x] T072 [P] [US3] Implement trial validation progress and publish-threshold view in frontend/src/screens/teaching/TrialStage.tsx

**Checkpoint**: User Story 3 is usable as a redesigned teaching flow with real backend recording and Agent semantics.

---

## Phase 6: User Story 4 - Manage Skills And Skill Compositions (Priority: P1)

**Goal**: Display pending, published, and failed skills; route skill actions through business workflows; create, try, publish, and review range/ordered skill compositions.

**Independent Test**: Inspect all skill categories, start trial validation, retry/ignore failures, create range and ordered compositions, reorder ordered members, require scenario text, publish valid compositions, and see stale compositions marked for review.

### Tests for User Story 4

- [x] T073 [P] [US4] Add skills category, trial, metadata, delete, retry, and dismiss API tests in tests/desktop_api/test_skills_api.py
- [x] T074 [P] [US4] Add composition list, create, update, AI helper, trial, publish, and needs-review API tests in tests/desktop_api/test_compositions_api.py
- [x] T075 [P] [US4] Add frontend Skill List and Skill Composition tests, including tab/action keyboard operation, in frontend/tests/unit/skills-compositions.test.tsx
- [x] T076 [P] [US4] Add e2e test for pending/published/failed skills plus range and ordered composition creation in frontend/tests/e2e/skills-compositions.spec.ts

### Implementation for User Story 4

- [x] T077 [US4] Extend SkillsService with UI DTOs, failure dismiss, and validation-action helpers in src/business/services/skills_service.py
- [x] T078 [US4] Implement skills endpoints for categories, trial start, metadata update, delete, failure retry, and failure dismiss in src/desktop_api/routers/skills.py
- [x] T079 [P] [US4] Implement composition UI DTO adapter over SkillCompositionService in src/business/services/skill_composition/ui_adapter.py
- [x] T080 [US4] Implement composition endpoints for list, create, update, generate applicability, recommend order, trial, and publish in src/desktop_api/routers/compositions.py
- [x] T081 [US4] Map skills changed, failure changed, composition review, and trial events to frontend DTOs in src/desktop_api/events.py
- [x] T082 [P] [US4] Implement typed skills API client functions in frontend/src/api/skills.ts
- [x] T083 [P] [US4] Implement typed composition API client functions in frontend/src/api/compositions.ts
- [x] T084 [P] [US4] Implement skill list state and action reducers in frontend/src/state/skillsStore.ts
- [x] T085 [P] [US4] Implement composition list/editor/trial state in frontend/src/state/compositionsStore.ts
- [x] T086 [US4] Implement redesigned Skill List tabs, counts, empty states, and actions in frontend/src/screens/skills/SkillListScreen.tsx
- [x] T087 [P] [US4] Implement pending, published, and failed skill cards in frontend/src/screens/skills/SkillCards.tsx
- [x] T088 [US4] Implement composition list, review badges, and create entry points in frontend/src/screens/compositions/CompositionListScreen.tsx
- [x] T089 [US4] Implement composition editor for name, description, mode, applicability, trial, and publish in frontend/src/screens/compositions/CompositionEditor.tsx
- [x] T090 [P] [US4] Implement member selector, ordered reorder controls, and range/ordered validation display in frontend/src/screens/compositions/MemberSelector.tsx

**Checkpoint**: User Story 4 covers the learned-skill lifecycle without direct data-store editing.

---

## Phase 7: User Story 5 - Configure The App In The Redesigned Settings (Priority: P1)

**Goal**: Expose AI, recording, data, and product settings through real configuration, secret-storage, validation, and business actions.

**Independent Test**: Navigate settings sections, save valid non-secret settings, write/test secrets without plaintext exposure, see invalid/unavailable feedback, and invoke every design-visible action through a real workflow or real validation/business error.

### Tests for User Story 5

- [x] T091 [P] [US5] Add settings schema, values, non-secret update, secret write/delete, and actions API tests in tests/desktop_api/test_settings_api.py
- [x] T092 [P] [US5] Add keyring masking and no-plaintext secret regression tests in tests/integration/test_settings_secret_storage.py
- [x] T093 [P] [US5] Add frontend settings section, validation, action, keyboard operation, and secret masking tests in frontend/tests/unit/settings-screen.test.tsx
- [x] T094 [P] [US5] Add e2e settings test for non-secret save, secret test, invalid value feedback, and visible actions in frontend/tests/e2e/settings.spec.ts

### Implementation for User Story 5

- [x] T095 [US5] Implement settings schema/value facade over UnifiedConfigManager and keyring-backed secret methods in src/business/services/settings_service.py
- [x] T096 [P] [US5] Implement real settings action handlers for test connection, backup, export, clear memory, updates, docs, changelog, and certificate install in src/business/services/settings_actions_service.py
- [x] T097 [US5] Implement settings endpoints for schema, values, non-secret updates, secret writes/deletes, and actions in src/desktop_api/routers/settings.py
- [x] T098 [US5] Add or normalize config defaults for all design-visible non-secret settings in src/data/config_models.py
- [x] T099 [US5] Update configuration examples and comments for new settings in config.example.json and config.example.comments.md
- [x] T100 [P] [US5] Implement typed settings API client functions in frontend/src/api/settings.ts
- [x] T101 [P] [US5] Implement settings state, dirty tracking, validation errors, and secret presence state in frontend/src/state/settingsStore.ts
- [x] T102 [US5] Implement redesigned Settings shell with AI, Recording, Data, and About sections in frontend/src/screens/settings/SettingsScreen.tsx
- [x] T103 [P] [US5] Implement reusable setting controls, masked secret input, and validation feedback in frontend/src/screens/settings/SettingControls.tsx
- [x] T104 [P] [US5] Implement settings action buttons and unavailable-state feedback in frontend/src/screens/settings/SettingsActions.tsx

**Checkpoint**: User Story 5 exposes real configuration and settings actions without unsafe storage or direct file editing.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Acceptance hardening, PyQt removal, packaging, active docs, and end-to-end validation across all stories.

- [x] T105 [P] Add no-sample-data and no-fake-counts audit e2e test in frontend/tests/e2e/no-sample-data.spec.ts
- [x] T106 [P] Add launch performance and backend degraded/failed/shutdown smoke tests in frontend/tests/e2e/performance-and-health.spec.ts
- [x] T107 [P] Add full visible-control wiring, keyboard accessibility, and unavailable-state audit test for five screens in frontend/tests/e2e/visible-controls.spec.ts
- [x] T108 Add packaging build path for Tauri plus Python sidecar in build_tauri.bat, build_executable.py, installer.iss, and BUILD_README.txt
- [x] T109 Remove or replace normal legacy PyQt launch entry points in src/main.py, mexemplar_gui.py, mexemplar_gui.bat, and start.bat
- [x] T110 Remove retired primary PyQt UI modules and leave no launchable maintained fallback in src/ui/
- [x] T111 Update or remove obsolete PyQt UI tests and add replacement guard coverage in tests/ui/ and tests/guardrails/test_legacy_pyqt_removal.py
- [x] T112 [P] Update runtime architecture documentation for Tauri/React/Python sidecar in docs/ARCHITECTURE.md
- [x] T113 [P] Update project constraints for frontend/API bridge, sidecar auth, settings safety, and legacy PyQt removal in docs/PROJECT_CONSTRAINTS.md
- [x] T114 [P] Update agent and contributor guidance for the new UI stack in AGENTS.md, CLAUDE.md, README.md, INSTALL.md, and BUILD_README.txt
- [x] T115 Run Python formatting, linting, and tests for src/ and tests/ using uv run black src/ tests/, uv run flake8 src/ tests/, and uv run pytest tests/
- [x] T116 Run frontend lint, unit tests, e2e tests, and Tauri build for frontend/ and src-tauri/ using npm run lint, npm run test, npm run test:e2e, and npm run tauri build
- [x] T117 [P] Add legacy local data non-mutation fixture and launch safety test in tests/integration/test_legacy_local_data_safety.py
- [x] T118 [P] Add sidecar runtime token non-persistence and no-log regression tests in tests/desktop_api/test_sidecar_token_security.py
- [x] T119 Record quickstart validation results and any accepted exceptions in docs/local/2026-05-10-ui-stack-redesign-validation.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: No dependencies; can start immediately.
- **Phase 2 Foundational**: Depends on Phase 1; blocks every user story.
- **Phase 3 US1**: Depends on Phase 2; MVP shell and launch path for all other stories.
- **Phase 4 US2**: Depends on Phase 2 and uses the shell from US1 for full e2e validation; backend/API work can start after Phase 2.
- **Phase 5 US3**: Depends on Phase 2 and uses the shell from US1 for full e2e validation; backend/API work can start after Phase 2.
- **Phase 6 US4**: Depends on Phase 2 and uses the shell from US1 for full e2e validation; composition trial behavior benefits from US3 test fixtures but remains independently testable.
- **Phase 7 US5**: Depends on Phase 2 and uses the shell from US1 for full e2e validation.
- **Phase 8 Polish**: Depends on all required P1 stories being complete.

### User Story Dependencies

- **US1**: MVP; no other story dependency after foundation.
- **US2**: Independently testable with controlled assistant fixtures after foundation, but final e2e uses US1 shell.
- **US3**: Independently testable with controlled recording fixtures after foundation, but final e2e uses US1 shell.
- **US4**: Independently testable with fixture skills/compositions after foundation, but final e2e uses US1 shell.
- **US5**: Independently testable with fixture config/keyring after foundation, but final e2e uses US1 shell.

### Within Each User Story

- Write and run story-specific tests first; they should fail before implementation.
- Implement backend business/service adapters before FastAPI routers.
- Implement frontend API clients and stores before screen components.
- Complete screen integration before e2e validation.
- Validate each story checkpoint before moving to the next priority if working sequentially.

---

## Parallel Opportunities

- Setup tasks T003, T004, T007, and T008 can run in parallel with different file ownership.
- Foundational tasks T013-T016 and T020-T023 can run in parallel after T009-T012 interfaces are agreed.
- Backend API tests, frontend unit tests, and e2e tests within each story are parallelizable because they use different files.
- After Phase 2, US2-US5 backend/API slices can proceed in parallel while US1 shell is being finished; final e2e validation should wait for US1.
- Polish documentation tasks T112-T114 can run in parallel with T105-T107 test hardening.

## Parallel Example: User Story 2

```text
Task: "T040 [US2] Add assistant sessions, messages, rename, delete, and confirmation contract tests in tests/desktop_api/test_assistant_api.py"
Task: "T041 [US2] Add assistant progress and confirmation event-stream tests in tests/desktop_api/test_assistant_events.py"
Task: "T042 [US2] Add frontend assistant timeline, session sidebar, composer, and confirmation tests in frontend/tests/unit/assistant-screen.test.tsx"
Task: "T043 [US2] Add assistant happy-path e2e test with controlled backend fixture in frontend/tests/e2e/assistant.spec.ts"
```

## Parallel Example: User Story 4

```text
Task: "T082 [US4] Implement typed skills API client functions in frontend/src/api/skills.ts"
Task: "T083 [US4] Implement typed composition API client functions in frontend/src/api/compositions.ts"
Task: "T084 [US4] Implement skill list state and action reducers in frontend/src/state/skillsStore.ts"
Task: "T085 [US4] Implement composition list/editor/trial state in frontend/src/state/compositionsStore.ts"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 Setup.
2. Complete Phase 2 Foundational bridge/runtime work.
3. Complete Phase 3 User Story 1.
4. Stop and validate launch, navigation, backend readiness, and custom chrome.
5. Use the shell as the integration host for the remaining P1 stories.

### Incremental Delivery

1. Deliver US1 shell and backend readiness.
2. Add US2 Assistant workflow and validate chat/confirmation semantics.
3. Add US3 Teaching workflow and validate recording/Agent/trial flow.
4. Add US4 Skills and Composition lifecycle.
5. Add US5 Settings and real design-visible actions.
6. Complete Polish phase, remove legacy PyQt entry points, and run full quickstart validation.

### Parallel Team Strategy

1. One owner handles Tauri/Rust shell files under src-tauri/.
2. One owner handles Python bridge files under src/desktop_api/ and business service adapters under src/business/services/.
3. One owner handles frontend shared app/state/API files under frontend/src/app/, frontend/src/api/, and frontend/src/state/.
4. Screen owners work in disjoint frontend/src/screens/<screen>/ folders after shared contracts are stable.
5. Test owners work in tests/desktop_api/, tests/guardrails/, and frontend/tests/ without editing implementation files.

## Notes

- [P] means the task edits different files and has no dependency on another incomplete task in the same phase.
- [US#] labels map to the five user stories in spec.md.
- Tests are included because the specification explicitly requires regression coverage.
- Do not bypass repositories, UnifiedConfigManager, keyring, recording filters, or blinker event boundaries.
- Do not remove PyQt launch paths until Tauri shell acceptance and guard tests pass.

---

## Tech Debt Tasks (Generated by /speckit.cleanup)

**Generated**: 2026-05-13
**Source**: Post-implementation cleanup of 008-ui-stack-redesign
**Priority**: Address before next feature iteration

### Detected Issues

- [ ] TD001 Extract desktop orchestrator construction from `src/desktop_api/orchestrator_runtime.py` into a business-owned factory/service so the FastAPI adapter depends only on business entry points and does not assemble config, LLM client, and `AgentOrchestrator` directly.
