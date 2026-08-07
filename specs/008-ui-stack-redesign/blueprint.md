# Blueprint: UI Stack Redesign

**Branch**: `008-ui-stack-redesign` | **Date**: 2026-05-10
**Mode**: scaffold
**Total Tasks**: 119 | **Files**: 107 new scaffolded, 19 existing/manual, 0 missing, 0 deleted

## Key Decisions

- Use Tauri 2 plus React for the accepted desktop shell, with Python kept as the semantic backend through a sidecar API. → T002, T004, T010, T017, T019, T039
- Keep UI access behind typed bridge contracts; frontend and desktop API adapters must not reach repositories, SQLite, DuckDB, config files, or keyring directly. → T009, T013, T022, T024, T029, T095
- Preserve backend blinker semantics by adapting events to a frontend stream instead of introducing UI callbacks in lower layers. → T012, T041, T048, T058, T064, T081
- Treat every visible prototype control as either a real business workflow or a real validation/business error before acceptance. → T024, T095, T096, T104, T107
- Remove legacy PyQt launch paths only after the redesigned shell, bridge, packaging, and guard tests pass. → T028, T109, T110, T111

## Implementation Order

```text
Phase 1 Setup
Phase 2 Foundation depends on Phase 1
User Story 1 shell depends on Phase 2
User Stories 2 through 5 depend on Phase 2 and integrate through User Story 1 shell
Phase 8 polish depends on all P1 user stories
```

---

## Scaffolded Files

| File | Status |
|------|--------|
| `build_tauri.bat` | Created by scaffold mode |
| `docs/local/2026-05-10-ui-stack-redesign-validation.md` | Created by scaffold mode |
| `docs/local/_archive/design-drafts/2026-05-10-ui-tech-stack-decision.md` | Created by scaffold mode |
| `frontend/index.html` | Created by scaffold mode |
| `frontend/package.json` | Created by scaffold mode |
| `frontend/postcss.config.js` | Created by scaffold mode |
| `frontend/src/api/assistant.ts` | Created by scaffold mode |
| `frontend/src/api/client.ts` | Created by scaffold mode |
| `frontend/src/api/compositions.ts` | Created by scaffold mode |
| `frontend/src/api/settings.ts` | Created by scaffold mode |
| `frontend/src/api/skills.ts` | Created by scaffold mode |
| `frontend/src/api/teaching.ts` | Created by scaffold mode |
| `frontend/src/app/AppShell.tsx` | Created by scaffold mode |
| `frontend/src/app/BackendStatus.tsx` | Created by scaffold mode |
| `frontend/src/app/CustomTitlebar.tsx` | Created by scaffold mode |
| `frontend/src/app/NavRail.tsx` | Created by scaffold mode |
| `frontend/src/app/routes.tsx` | Created by scaffold mode |
| `frontend/src/components/primitives.tsx` | Created by scaffold mode |
| `frontend/src/main.tsx` | Created by scaffold mode |
| `frontend/src/screens/assistant/AssistantScreen.tsx` | Created by scaffold mode |
| `frontend/src/screens/assistant/ConfirmationToast.tsx` | Created by scaffold mode |
| `frontend/src/screens/assistant/ExecutionSummary.tsx` | Created by scaffold mode |
| `frontend/src/screens/assistant/MessageComposer.tsx` | Created by scaffold mode |
| `frontend/src/screens/assistant/SafeMarkdown.tsx` | Created by scaffold mode |
| `frontend/src/screens/assistant/SessionSidebar.tsx` | Created by scaffold mode |
| `frontend/src/screens/compositions/CompositionEditor.tsx` | Created by scaffold mode |
| `frontend/src/screens/compositions/CompositionListScreen.tsx` | Created by scaffold mode |
| `frontend/src/screens/compositions/MemberSelector.tsx` | Created by scaffold mode |
| `frontend/src/screens/settings/SettingControls.tsx` | Created by scaffold mode |
| `frontend/src/screens/settings/SettingsActions.tsx` | Created by scaffold mode |
| `frontend/src/screens/settings/SettingsScreen.tsx` | Created by scaffold mode |
| `frontend/src/screens/skills/SkillCards.tsx` | Created by scaffold mode |
| `frontend/src/screens/skills/SkillListScreen.tsx` | Created by scaffold mode |
| `frontend/src/screens/teaching/IntentStage.tsx` | Created by scaffold mode |
| `frontend/src/screens/teaching/LearningStage.tsx` | Created by scaffold mode |
| `frontend/src/screens/teaching/RecordingModePicker.tsx` | Created by scaffold mode |
| `frontend/src/screens/teaching/RecordingStage.tsx` | Created by scaffold mode |
| `frontend/src/screens/teaching/TeachingScreen.tsx` | Created by scaffold mode |
| `frontend/src/screens/teaching/TrialStage.tsx` | Created by scaffold mode |
| `frontend/src/state/assistantStore.ts` | Created by scaffold mode |
| `frontend/src/state/compositionsStore.ts` | Created by scaffold mode |
| `frontend/src/state/settingsStore.ts` | Created by scaffold mode |
| `frontend/src/state/shellStore.ts` | Created by scaffold mode |
| `frontend/src/state/skillsStore.ts` | Created by scaffold mode |
| `frontend/src/state/teachingStore.ts` | Created by scaffold mode |
| `frontend/src/styles/theme.css` | Created by scaffold mode |
| `frontend/src/test/setup.ts` | Created by scaffold mode |
| `frontend/tailwind.config.ts` | Created by scaffold mode |
| `frontend/tests/e2e/app-shell.spec.ts` | Created by scaffold mode |
| `frontend/tests/e2e/assistant.spec.ts` | Created by scaffold mode |
| `frontend/tests/e2e/no-sample-data.spec.ts` | Created by scaffold mode |
| `frontend/tests/e2e/performance-and-health.spec.ts` | Created by scaffold mode |
| `frontend/tests/e2e/settings.spec.ts` | Created by scaffold mode |
| `frontend/tests/e2e/skills-compositions.spec.ts` | Created by scaffold mode |
| `frontend/tests/e2e/teaching.spec.ts` | Created by scaffold mode |
| `frontend/tests/e2e/visible-controls.spec.ts` | Created by scaffold mode |
| `frontend/tests/unit/app-shell.test.tsx` | Created by scaffold mode |
| `frontend/tests/unit/assistant-screen.test.tsx` | Created by scaffold mode |
| `frontend/tests/unit/settings-screen.test.tsx` | Created by scaffold mode |
| `frontend/tests/unit/skills-compositions.test.tsx` | Created by scaffold mode |
| `frontend/tests/unit/teaching-screen.test.tsx` | Created by scaffold mode |
| `frontend/tsconfig.json` | Created by scaffold mode |
| `frontend/vite.config.ts` | Created by scaffold mode |
| `frontend/vitest.config.ts` | Created by scaffold mode |
| `scripts/build_desktop_sidecar.ps1` | Created by scaffold mode |
| `src-tauri/Cargo.toml` | Created by scaffold mode |
| `src-tauri/capabilities/default.json` | Created by scaffold mode |
| `src-tauri/src/lib.rs` | Created by scaffold mode |
| `src-tauri/src/sidecar.rs` | Created by scaffold mode |
| `src-tauri/src/window.rs` | Created by scaffold mode |
| `src-tauri/tauri.conf.json` | Created by scaffold mode |
| `src/business/services/desktop_bootstrap_service.py` | Created by scaffold mode |
| `src/business/services/recording_readiness_service.py` | Created by scaffold mode |
| `src/business/services/settings_actions_service.py` | Created by scaffold mode |
| `src/business/services/settings_service.py` | Created by scaffold mode |
| `src/business/services/skill_composition/ui_adapter.py` | Created by scaffold mode |
| `src/business/services/teaching_service.py` | Created by scaffold mode |
| `src/desktop_api/__init__.py` | Created by scaffold mode |
| `src/desktop_api/__main__.py` | Created by scaffold mode |
| `src/desktop_api/app.py` | Created by scaffold mode |
| `src/desktop_api/assistant_runtime.py` | Created by scaffold mode |
| `src/desktop_api/confirmations.py` | Created by scaffold mode |
| `src/desktop_api/events.py` | Created by scaffold mode |
| `src/desktop_api/routers/__init__.py` | Created by scaffold mode |
| `src/desktop_api/routers/assistant.py` | Created by scaffold mode |
| `src/desktop_api/routers/compositions.py` | Created by scaffold mode |
| `src/desktop_api/routers/health.py` | Created by scaffold mode |
| `src/desktop_api/routers/settings.py` | Created by scaffold mode |
| `src/desktop_api/routers/skills.py` | Created by scaffold mode |
| `src/desktop_api/routers/teaching.py` | Created by scaffold mode |
| `src/desktop_api/schemas.py` | Created by scaffold mode |
| `tests/desktop_api/conftest.py` | Created by scaffold mode |
| `tests/desktop_api/test_app_contract.py` | Created by scaffold mode |
| `tests/desktop_api/test_assistant_api.py` | Created by scaffold mode |
| `tests/desktop_api/test_assistant_events.py` | Created by scaffold mode |
| `tests/desktop_api/test_compositions_api.py` | Created by scaffold mode |
| `tests/desktop_api/test_health_bootstrap.py` | Created by scaffold mode |
| `tests/desktop_api/test_settings_api.py` | Created by scaffold mode |
| `tests/desktop_api/test_sidecar_token_security.py` | Created by scaffold mode |
| `tests/desktop_api/test_skills_api.py` | Created by scaffold mode |
| `tests/desktop_api/test_teaching_api.py` | Created by scaffold mode |
| `tests/desktop_api/test_teaching_events.py` | Created by scaffold mode |
| `tests/guardrails/test_legacy_pyqt_launch.py` | Created by scaffold mode |
| `tests/guardrails/test_legacy_pyqt_removal.py` | Created by scaffold mode |
| `tests/guardrails/test_ui_stack_boundaries.py` | Created by scaffold mode |
| `tests/integration/test_legacy_local_data_safety.py` | Created by scaffold mode |
| `tests/integration/test_settings_secret_storage.py` | Created by scaffold mode |

## Existing Files Requiring Manual Changes

| File | Handling |
|------|----------|
| `AGENTS.md` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `BUILD_README.txt` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `CLAUDE.md` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `INSTALL.md` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `README.md` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `build_executable.py` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `config.example.comments.md` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `config.example.json` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `docs/ARCHITECTURE.md` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `docs/PROJECT_CONSTRAINTS.md` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `installer.iss` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `mexemplar_gui.bat` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `mexemplar_gui.py` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `pyproject.toml` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `src/business/services/chat_service.py` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `src/business/services/skills_service.py` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `src/data/config_models.py` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `src/main.py` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |
| `start.bat` | Do not overwrite in scaffold mode; apply the task-specific changes described below during implementation |

---

## Phase 1: Setup (Shared Infrastructure)

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T001 | Directory-only or command task | FR-020, FR-023 | Spec, plan, tasks | Implement Create frontend source and test directories in frontend/src/, frontend/tests/unit/, and frontend/tests/e2e/ following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T002 | `frontend/package.json` | FR-020, FR-023 | Spec, plan, tasks | Implement Initialize React/Vite package metadata and scripts in frontend/package.json following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T003 | `frontend/tsconfig.json`<br>`frontend/vite.config.ts`<br>`frontend/tailwind.config.ts`<br>`frontend/postcss.config.js`<br>`frontend/vitest.config.ts` | FR-020, FR-023 | Spec, plan, tasks | Implement Configure TypeScript, Vite, Tailwind, PostCSS, and test setup in frontend/tsconfig.json, frontend/vite.config.ts, frontend/tailwind.config.ts, frontend/postcss.config.js, and frontend/vitest.config.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T004 | `src-tauri/Cargo.toml`<br>`src-tauri/tauri.conf.json`<br>`src-tauri/capabilities/default.json` | FR-020, FR-023 | Spec, plan, tasks | Implement Scaffold Tauri configuration and capabilities in src-tauri/Cargo.toml, src-tauri/tauri.conf.json, and src-tauri/capabilities/default.json following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T005 | `pyproject.toml` | FR-020, FR-023 | Spec, plan, tasks | Implement Add FastAPI, Uvicorn, Pydantic, and PyInstaller sidecar dependencies in pyproject.toml following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T006 | `src/desktop_api/__init__.py`<br>`src/desktop_api/routers/__init__.py` | FR-020, FR-023 | Spec, plan, tasks | Implement Create Python sidecar API package skeleton in src/desktop_api/__init__.py and src/desktop_api/routers/__init__.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T007 | `frontend/package.json` | FR-020, FR-023 | Spec, plan, tasks | Implement Add frontend lint, unit test, e2e test, tauri dev, and tauri build scripts in frontend/package.json following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T008 | `docs/local/_archive/design-drafts/2026-05-10-ui-tech-stack-decision.md` | FR-020, FR-023 | Spec, plan, tasks | Implement Copy or record the UI stack decision input artifact in docs/local/_archive/design-drafts/2026-05-10-ui-tech-stack-decision.md following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Phase 2: Foundational (Blocking Prerequisites)

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T009 | `src/desktop_api/schemas.py` | FR-020, FR-023 | Previous phase gates | Implement Define shared Pydantic DTOs for health, errors, paging, shell bootstrap, events, skills, compositions, and settings in src/desktop_api/schemas.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T010 | `src/desktop_api/app.py` | FR-020, FR-023 | Previous phase gates | Implement Implement FastAPI app factory, loopback CORS policy, auth-token middleware, and router registration in src/desktop_api/app.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T011 | `src/desktop_api/__main__.py` | FR-020, FR-023 | Previous phase gates | Implement Implement sidecar process entrypoint with random localhost port and runtime token handling in src/desktop_api/__main__.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T012 | `src/desktop_api/events.py` | FR-020, FR-023 | Previous phase gates | Implement Implement backend event queue and blinker-to-UI event stream adapter in src/desktop_api/events.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T013 | `frontend/src/api/client.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement typed frontend API runtime, token header injection, error normalization, and event-stream client in frontend/src/api/client.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T014 | `frontend/src/state/shellStore.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement global shell, route, and backend-status stores in frontend/src/state/shellStore.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T015 | `frontend/src/components/primitives.tsx` | FR-020, FR-023 | Previous phase gates | Implement Port shared design primitives from the prototype into frontend/src/components/primitives.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T016 | `frontend/src/styles/theme.css` | FR-020, FR-023 | Previous phase gates | Implement Implement theme tokens, density tokens, and global CSS baseline in frontend/src/styles/theme.css following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T017 | `src-tauri/src/sidecar.rs` | FR-020, FR-023 | Previous phase gates | Implement Implement Tauri sidecar lifecycle module with PyInstaller binary launch, port/token handoff, and shutdown cleanup in src-tauri/src/sidecar.rs following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T018 | `src-tauri/src/window.rs` | FR-020, FR-023 | Previous phase gates | Implement Implement scoped Tauri window command module for minimize, maximize/restore, close, and drag handling in src-tauri/src/window.rs following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T019 | `src-tauri/src/lib.rs` | FR-020, FR-023 | Previous phase gates | Implement Wire Tauri plugin-shell, plugin-http, and window command initialization in src-tauri/src/lib.rs following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T020 | `tests/desktop_api/conftest.py` | FR-020, FR-023 | Previous phase gates | Implement Add Python API test fixtures for token-authenticated FastAPI clients in tests/desktop_api/conftest.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T021 | `frontend/src/test/setup.ts` | FR-020, FR-023 | Previous phase gates | Implement Add frontend unit test setup, Tauri API mocks, and API client mocks in frontend/src/test/setup.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T022 | `tests/guardrails/test_ui_stack_boundaries.py` | FR-020, FR-023 | Previous phase gates | Implement Add architecture guard test scaffolding for frontend/API storage-boundary imports in tests/guardrails/test_ui_stack_boundaries.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T023 | `scripts/build_desktop_sidecar.ps1` | FR-020, FR-023 | Previous phase gates | Implement Add sidecar build helper for copying target-triple PyInstaller output in scripts/build_desktop_sidecar.ps1 following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T024 | `src/desktop_api/app.py`<br>`tests/desktop_api/test_app_contract.py` | FR-020, FR-023 | Previous phase gates | Implement Add repository-wide route registration and OpenAPI smoke test for src/desktop_api/app.py in tests/desktop_api/test_app_contract.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Phase 3: User Story 1 - Use The Redesigned App Shell (Priority: P1) MVP

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T025 | `tests/desktop_api/test_health_bootstrap.py` | FR-020, FR-023 | Previous phase gates | Implement Add backend health/bootstrap contract tests in tests/desktop_api/test_health_bootstrap.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T026 | `frontend/tests/unit/app-shell.test.tsx` | FR-020, FR-023 | Previous phase gates | Implement Add frontend shell navigation and state-preservation tests in frontend/tests/unit/app-shell.test.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T027 | `frontend/tests/e2e/app-shell.spec.ts` | FR-020, FR-023 | Previous phase gates | Implement Add Tauri launch, five-route navigation, and custom chrome smoke tests in frontend/tests/e2e/app-shell.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T028 | `tests/guardrails/test_legacy_pyqt_launch.py` | FR-020, FR-023 | Previous phase gates | Implement Add guard tests proving normal launch paths do not open legacy PyQt windows in tests/guardrails/test_legacy_pyqt_launch.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T029 | `src/business/services/desktop_bootstrap_service.py` | FR-020, FR-023 | Previous phase gates | Implement Implement shell bootstrap business service using existing services and no repository leakage in src/business/services/desktop_bootstrap_service.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T030 | `src/desktop_api/routers/health.py` | FR-020, FR-023 | Previous phase gates | Implement Implement health and bootstrap endpoints in src/desktop_api/routers/health.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T031 | `src-tauri/src/sidecar.rs` | FR-020, FR-023 | Previous phase gates | Implement Complete Tauri sidecar startup, health polling, and shutdown integration in src-tauri/src/sidecar.rs following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T032 | `src-tauri/src/window.rs` | FR-020, FR-023 | Previous phase gates | Implement Complete branded custom window action wiring in src-tauri/src/window.rs following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T033 | `frontend/src/app/AppShell.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement React app shell layout in frontend/src/app/AppShell.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T034 | `frontend/src/app/NavRail.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement persistent navigation rail with real counts and screen routes in frontend/src/app/NavRail.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T035 | `frontend/src/app/CustomTitlebar.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement custom red/yellow/green titlebar and drag region in frontend/src/app/CustomTitlebar.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T036 | `frontend/src/app/BackendStatus.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement backend readiness, degraded, failed, and shutdown states in frontend/src/app/BackendStatus.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T037 | `frontend/src/app/routes.tsx` | FR-020, FR-023 | Previous phase gates | Implement Register five primary screen routes and real loading/error placeholders in frontend/src/app/routes.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T038 | `frontend/src/main.tsx` | FR-020, FR-023 | Previous phase gates | Implement Wire React root, API bootstrap, event client startup, and shell store hydration in frontend/src/main.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T039 | `src-tauri/tauri.conf.json` | FR-020, FR-023 | Previous phase gates | Implement Configure Tauri app metadata, window dimensions, custom decorations, and externalBin sidecar path in src-tauri/tauri.conf.json following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Phase 4: User Story 2 - Work In The Redesigned AI Assistant (Priority: P1)

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T040 | `tests/desktop_api/test_assistant_api.py` | FR-020, FR-023 | Previous phase gates | Implement Add assistant sessions, messages, rename, delete, and confirmation contract tests in tests/desktop_api/test_assistant_api.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T041 | `tests/desktop_api/test_assistant_events.py` | FR-020, FR-023 | Previous phase gates | Implement Add assistant progress and confirmation event-stream tests in tests/desktop_api/test_assistant_events.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T042 | `frontend/tests/unit/assistant-screen.test.tsx` | FR-020, FR-023 | Previous phase gates | Implement Add frontend assistant timeline, session sidebar, composer, and confirmation tests in frontend/tests/unit/assistant-screen.test.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T043 | `frontend/tests/e2e/assistant.spec.ts` | FR-020, FR-023 | Previous phase gates | Implement Add assistant happy-path e2e test with controlled backend fixture and under-2-minute assertion in frontend/tests/e2e/assistant.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T044 | `src/business/services/chat_service.py` | FR-020, FR-023 | Previous phase gates | Implement Extend ChatService with search, rename, delete/archive, and display DTO helpers in src/business/services/chat_service.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T045 | `src/desktop_api/routers/assistant.py` | FR-020, FR-023 | Previous phase gates | Implement Implement assistant REST endpoints for sessions, messages, and confirmation decisions in src/desktop_api/routers/assistant.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T046 | `src/desktop_api/assistant_runtime.py` | FR-020, FR-023 | Previous phase gates | Implement Implement assistant worker dispatch adapter that preserves AgentOrchestrator semantics in src/desktop_api/assistant_runtime.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T047 | `src/desktop_api/confirmations.py` | FR-020, FR-023 | Previous phase gates | Implement Implement high-risk confirmation DTO mapping without raw file or command leakage in src/desktop_api/confirmations.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T048 | `src/desktop_api/events.py` | FR-020, FR-023 | Previous phase gates | Implement Map assistant progress, final message, error, and confirmation blinker events in src/desktop_api/events.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T049 | `frontend/src/api/assistant.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement typed assistant API client functions in frontend/src/api/assistant.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T050 | `frontend/src/state/assistantStore.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement assistant session, timeline, draft, progress, and confirmation state in frontend/src/state/assistantStore.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T051 | `frontend/src/screens/assistant/AssistantScreen.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement redesigned assistant screen and timeline composition in frontend/src/screens/assistant/AssistantScreen.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T052 | `frontend/src/screens/assistant/SessionSidebar.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement conversation list, search, rename, delete, and empty states in frontend/src/screens/assistant/SessionSidebar.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T053 | `frontend/src/screens/assistant/MessageComposer.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement message composer and send-state handling in frontend/src/screens/assistant/MessageComposer.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T054 | `frontend/src/screens/assistant/SafeMarkdown.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement safe assistant markdown rendering in frontend/src/screens/assistant/SafeMarkdown.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T055 | `frontend/src/screens/assistant/ExecutionSummary.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement compact/expandable execution summaries in frontend/src/screens/assistant/ExecutionSummary.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T056 | `frontend/src/screens/assistant/ConfirmationToast.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement non-modal high-risk confirmation surface independent from normal toasts in frontend/src/screens/assistant/ConfirmationToast.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Phase 5: User Story 3 - Teach A Skill In The Redesigned Flow (Priority: P1)

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T057 | `tests/desktop_api/test_teaching_api.py` | FR-020, FR-023 | Previous phase gates | Implement Add teaching readiness, run creation, recording stop, health decision, intent, and trial API tests in tests/desktop_api/test_teaching_api.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T058 | `tests/desktop_api/test_teaching_events.py` | FR-020, FR-023 | Previous phase gates | Implement Add teaching progress, recording progress, trial progress, and failure event-stream tests in tests/desktop_api/test_teaching_events.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T059 | `frontend/tests/unit/teaching-screen.test.tsx` | FR-020, FR-023 | Previous phase gates | Implement Add frontend teaching stage, recording mode, health review, and trial progress tests in frontend/tests/unit/teaching-screen.test.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T060 | `frontend/tests/e2e/teaching.spec.ts` | FR-020, FR-023 | Previous phase gates | Implement Add teaching fixture e2e test through trial-ready state with under-5-minute assertion in frontend/tests/e2e/teaching.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T061 | `src/business/services/teaching_service.py` | FR-020, FR-023 | Previous phase gates | Implement Implement teaching workflow facade over AgentOrchestrator and existing recording services in src/business/services/teaching_service.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T062 | `src/business/services/recording_readiness_service.py` | FR-020, FR-023 | Previous phase gates | Implement Implement recording readiness service for browser, extension, and desktop prerequisites in src/business/services/recording_readiness_service.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T063 | `src/desktop_api/routers/teaching.py` | FR-020, FR-023 | Previous phase gates | Implement Implement teaching endpoints for readiness, runs, recording, desktop health decisions, intent, and trial start in src/desktop_api/routers/teaching.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T064 | `src/desktop_api/events.py` | FR-020, FR-023 | Previous phase gates | Implement Map recording, teaching, trial, desktop sanity, and failure events to frontend DTOs in src/desktop_api/events.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T065 | `frontend/src/api/teaching.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement typed teaching API client functions in frontend/src/api/teaching.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T066 | `frontend/src/state/teachingStore.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement teaching workflow state machine in frontend/src/state/teachingStore.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T067 | `frontend/src/screens/teaching/TeachingScreen.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement redesigned teaching screen shell in frontend/src/screens/teaching/TeachingScreen.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T068 | `frontend/src/screens/teaching/RecordingModePicker.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement browser, extension, and desktop mode cards with readiness/setup actions in frontend/src/screens/teaching/RecordingModePicker.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T069 | `frontend/src/screens/teaching/RecordingStage.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement recording active view, timers, stop action, and desktop sanity choices in frontend/src/screens/teaching/RecordingStage.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T070 | `frontend/src/screens/teaching/IntentStage.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement intent confirmation questions and answer submission view in frontend/src/screens/teaching/IntentStage.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T071 | `frontend/src/screens/teaching/LearningStage.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement learning progress, retry, blocked, and failure states in frontend/src/screens/teaching/LearningStage.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T072 | `frontend/src/screens/teaching/TrialStage.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement trial validation progress and publish-threshold view in frontend/src/screens/teaching/TrialStage.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Phase 6: User Story 4 - Manage Skills And Skill Compositions (Priority: P1)

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T073 | `tests/desktop_api/test_skills_api.py` | FR-020, FR-023 | Previous phase gates | Implement Add skills category, trial, metadata, delete, retry, and dismiss API tests in tests/desktop_api/test_skills_api.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T074 | `tests/desktop_api/test_compositions_api.py` | FR-020, FR-023 | Previous phase gates | Implement Add composition list, create, update, AI helper, trial, publish, and needs-review API tests in tests/desktop_api/test_compositions_api.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T075 | `frontend/tests/unit/skills-compositions.test.tsx` | FR-020, FR-023 | Previous phase gates | Implement Add frontend Skill List and Skill Composition tests in frontend/tests/unit/skills-compositions.test.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T076 | `frontend/tests/e2e/skills-compositions.spec.ts` | FR-020, FR-023 | Previous phase gates | Implement Add e2e test for pending/published/failed skills plus range and ordered composition creation in frontend/tests/e2e/skills-compositions.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T077 | `src/business/services/skills_service.py` | FR-020, FR-023 | Previous phase gates | Implement Extend SkillsService with UI DTOs, failure dismiss, and validation-action helpers in src/business/services/skills_service.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T078 | `src/desktop_api/routers/skills.py` | FR-020, FR-023 | Previous phase gates | Implement Implement skills endpoints for categories, trial start, metadata update, delete, failure retry, and failure dismiss in src/desktop_api/routers/skills.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T079 | `src/business/services/skill_composition/ui_adapter.py` | FR-020, FR-023 | Previous phase gates | Implement Implement composition UI DTO adapter over SkillCompositionService in src/business/services/skill_composition/ui_adapter.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T080 | `src/desktop_api/routers/compositions.py` | FR-020, FR-023 | Previous phase gates | Implement Implement composition endpoints for list, create, update, generate applicability, recommend order, trial, and publish in src/desktop_api/routers/compositions.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T081 | `src/desktop_api/events.py` | FR-020, FR-023 | Previous phase gates | Implement Map skills changed, failure changed, composition review, and trial events to frontend DTOs in src/desktop_api/events.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T082 | `frontend/src/api/skills.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement typed skills API client functions in frontend/src/api/skills.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T083 | `frontend/src/api/compositions.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement typed composition API client functions in frontend/src/api/compositions.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T084 | `frontend/src/state/skillsStore.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement skill list state and action reducers in frontend/src/state/skillsStore.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T085 | `frontend/src/state/compositionsStore.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement composition list/editor/trial state in frontend/src/state/compositionsStore.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T086 | `frontend/src/screens/skills/SkillListScreen.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement redesigned Skill List tabs, counts, empty states, and actions in frontend/src/screens/skills/SkillListScreen.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T087 | `frontend/src/screens/skills/SkillCards.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement pending, published, and failed skill cards in frontend/src/screens/skills/SkillCards.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T088 | `frontend/src/screens/compositions/CompositionListScreen.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement composition list, review badges, and create entry points in frontend/src/screens/compositions/CompositionListScreen.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T089 | `frontend/src/screens/compositions/CompositionEditor.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement composition editor for name, description, mode, applicability, trial, and publish in frontend/src/screens/compositions/CompositionEditor.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T090 | `frontend/src/screens/compositions/MemberSelector.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement member selector, ordered reorder controls, and range/ordered validation display in frontend/src/screens/compositions/MemberSelector.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Phase 7: User Story 5 - Configure The App In The Redesigned Settings (Priority: P1)

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T091 | `tests/desktop_api/test_settings_api.py` | FR-020, FR-023 | Previous phase gates | Implement Add settings schema, values, non-secret update, secret write/delete, and actions API tests in tests/desktop_api/test_settings_api.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T092 | `tests/integration/test_settings_secret_storage.py` | FR-020, FR-023 | Previous phase gates | Implement Add keyring masking and no-plaintext secret regression tests in tests/integration/test_settings_secret_storage.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T093 | `frontend/tests/unit/settings-screen.test.tsx` | FR-020, FR-023 | Previous phase gates | Implement Add frontend settings section, validation, action, and secret masking tests in frontend/tests/unit/settings-screen.test.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T094 | `frontend/tests/e2e/settings.spec.ts` | FR-020, FR-023 | Previous phase gates | Implement Add e2e settings test for non-secret save, secret test, invalid value feedback, and visible actions in frontend/tests/e2e/settings.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T095 | `src/business/services/settings_service.py` | FR-020, FR-023 | Previous phase gates | Implement Implement settings schema/value facade over UnifiedConfigManager and keyring-backed secret methods in src/business/services/settings_service.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T096 | `src/business/services/settings_actions_service.py` | FR-020, FR-023 | Previous phase gates | Implement Implement real settings action handlers for test connection, backup, export, clear memory, updates, docs, changelog, and certificate install in src/business/services/settings_actions_service.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T097 | `src/desktop_api/routers/settings.py` | FR-020, FR-023 | Previous phase gates | Implement Implement settings endpoints for schema, values, non-secret updates, secret writes/deletes, and actions in src/desktop_api/routers/settings.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T098 | `src/data/config_models.py` | FR-020, FR-023 | Previous phase gates | Implement Add or normalize config defaults for all design-visible non-secret settings in src/data/config_models.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T099 | `config.example.json`<br>`config.example.comments.md` | FR-020, FR-023 | Previous phase gates | Implement Update configuration examples and comments for new settings in config.example.json and config.example.comments.md following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T100 | `frontend/src/api/settings.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement typed settings API client functions in frontend/src/api/settings.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T101 | `frontend/src/state/settingsStore.ts` | FR-020, FR-023 | Previous phase gates | Implement Implement settings state, dirty tracking, validation errors, and secret presence state in frontend/src/state/settingsStore.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T102 | `frontend/src/screens/settings/SettingsScreen.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement redesigned Settings shell with AI, Recording, Data, and About sections in frontend/src/screens/settings/SettingsScreen.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T103 | `frontend/src/screens/settings/SettingControls.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement reusable setting controls, masked secret input, and validation feedback in frontend/src/screens/settings/SettingControls.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T104 | `frontend/src/screens/settings/SettingsActions.tsx` | FR-020, FR-023 | Previous phase gates | Implement Implement settings action buttons and unavailable-state feedback in frontend/src/screens/settings/SettingsActions.tsx following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Phase 8: Polish & Cross-Cutting Concerns

| Task | Files | Requirements | Dependencies | Blueprint | Verification |
|------|-------|--------------|--------------|-----------|--------------|
| T105 | `frontend/tests/e2e/no-sample-data.spec.ts` | FR-004, FR-018, FR-019, FR-023, FR-027 | Previous phase gates | Implement Add no-sample-data and no-fake-counts audit e2e test in frontend/tests/e2e/no-sample-data.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T106 | `frontend/tests/e2e/performance-and-health.spec.ts` | FR-004, FR-018, FR-019, FR-023, FR-027 | Previous phase gates | Implement Add launch performance and backend degraded/failed/shutdown smoke tests in frontend/tests/e2e/performance-and-health.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T107 | `frontend/tests/e2e/visible-controls.spec.ts` | FR-004, FR-018, FR-019, FR-023, FR-027 | Previous phase gates | Implement Add full visible-control wiring audit test for five screens in frontend/tests/e2e/visible-controls.spec.ts following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T108 | `build_tauri.bat`<br>`build_executable.py`<br>`installer.iss`<br>`BUILD_README.txt` | FR-020, FR-023 | Previous phase gates | Implement Add packaging build path for Tauri plus Python sidecar in build_tauri.bat, build_executable.py, installer.iss, and BUILD_README.txt following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T109 | `src/main.py`<br>`mexemplar_gui.py`<br>`mexemplar_gui.bat`<br>`start.bat` | FR-022, FR-023 | Previous phase gates | Implement Remove or replace normal legacy PyQt launch entry points in src/main.py, mexemplar_gui.py, mexemplar_gui.bat, and start.bat following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T110 | Directory-only or command task | FR-022, FR-023 | Previous phase gates | Implement Remove retired primary PyQt UI modules and leave no launchable maintained fallback in src/ui/ following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T111 | `tests/guardrails/test_legacy_pyqt_removal.py` | FR-022, FR-023 | Previous phase gates | Implement Update or remove obsolete PyQt UI tests and add replacement guard coverage in tests/ui/ and tests/guardrails/test_legacy_pyqt_removal.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T112 | `docs/ARCHITECTURE.md` | FR-020, FR-023 | Previous phase gates | Implement Update runtime architecture documentation for Tauri/React/Python sidecar in docs/ARCHITECTURE.md following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T113 | `docs/PROJECT_CONSTRAINTS.md` | FR-020, FR-023 | Previous phase gates | Implement Update project constraints for frontend/API bridge, sidecar auth, settings safety, and legacy PyQt removal in docs/PROJECT_CONSTRAINTS.md following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T114 | `AGENTS.md`<br>`CLAUDE.md`<br>`README.md`<br>`INSTALL.md`<br>`BUILD_README.txt` | FR-020, FR-023 | Previous phase gates | Implement Update agent and contributor guidance for the new UI stack in AGENTS.md, CLAUDE.md, README.md, INSTALL.md, and BUILD_README.txt following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T115 | Directory-only or command task | FR-020, FR-023 | Previous phase gates | Implement Run Python formatting, linting, and tests for src/ and tests/ using uv run black src/ tests/, uv run flake8 src/ tests/, and uv run pytest tests/ following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T116 | Directory-only or command task | FR-020, FR-023 | Previous phase gates | Implement Run frontend lint, unit tests, e2e tests, and Tauri build for frontend/ and src-tauri/ using npm run lint, npm run test, npm run test:e2e, and npm run tauri build following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T117 | `tests/integration/test_legacy_local_data_safety.py` | FR-004, FR-018, FR-019, FR-023, FR-027 | Previous phase gates | Implement Add legacy local data non-mutation fixture and launch safety test in tests/integration/test_legacy_local_data_safety.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T118 | `tests/desktop_api/test_sidecar_token_security.py` | FR-004, FR-018, FR-019, FR-023, FR-027 | Previous phase gates | Implement Add sidecar runtime token non-persistence and no-log regression tests in tests/desktop_api/test_sidecar_token_security.py following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |
| T119 | `docs/local/2026-05-10-ui-stack-redesign-validation.md` | FR-020, FR-023 | Previous phase gates | Implement Record quickstart validation results and any accepted exceptions in docs/local/2026-05-10-ui-stack-redesign-validation.md following the layer boundary and bridge contracts from spec.md, plan.md, data-model.md, and contracts/desktop-backend-api.md. | Run the focused test or command named by the task, then include it in the quickstart validation sequence. |

---

## Manual Modification Guidance

- `pyproject.toml`: add FastAPI, Uvicorn, Pydantic, and PyInstaller dependencies while preserving existing project metadata and dev dependency groups. → T005
- `src/business/services/chat_service.py`: add search, rename, delete/archive, and display DTO helpers on top of the existing repository-backed service methods. → T044
- `src/business/services/skills_service.py`: add UI DTOs, failure dismissal, validation action helpers, and metadata update paths without exposing repositories to UI adapters. → T077
- `src/data/config_models.py`: add or normalize defaults for design-visible non-secret settings while keeping secret values outside config files. → T098
- `src/main.py`, `mexemplar_gui.py`, `mexemplar_gui.bat`, and `start.bat`: replace normal PyQt launch paths after the Tauri shell acceptance gates pass. → T109
- `build_executable.py`, `installer.iss`, and `BUILD_README.txt`: preserve existing packaging behavior while adding Tauri plus Python sidecar build and bundle steps. → T108
- `config.example.json` and `config.example.comments.md`: document new non-secret defaults and never include secret values. → T099
- `docs/ARCHITECTURE.md`, `docs/PROJECT_CONSTRAINTS.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `INSTALL.md`, `BUILD_README.txt`: update active documentation to describe the accepted Tauri plus sidecar runtime and constraints. → T112, T113, T114

## Checklist

- [ ] T001: Create frontend source and test directories in frontend/src/, frontend/tests/unit/, and frontend/tests/e2e/
- [ ] T002: Initialize React/Vite package metadata and scripts in frontend/package.json
- [ ] T003: Configure TypeScript, Vite, Tailwind, PostCSS, and test setup in frontend/tsconfig.json, frontend/vite.config.ts, frontend/tailwind.config.ts, frontend/postcss.config.js, and frontend/vitest.config.ts
- [ ] T004: Scaffold Tauri configuration and capabilities in src-tauri/Cargo.toml, src-tauri/tauri.conf.json, and src-tauri/capabilities/default.json
- [ ] T005: Add FastAPI, Uvicorn, Pydantic, and PyInstaller sidecar dependencies in pyproject.toml
- [ ] T006: Create Python sidecar API package skeleton in src/desktop_api/__init__.py and src/desktop_api/routers/__init__.py
- [ ] T007: Add frontend lint, unit test, e2e test, tauri dev, and tauri build scripts in frontend/package.json
- [ ] T008: Copy or record the UI stack decision input artifact in docs/local/_archive/design-drafts/2026-05-10-ui-tech-stack-decision.md
- [ ] T009: Define shared Pydantic DTOs for health, errors, paging, shell bootstrap, events, skills, compositions, and settings in src/desktop_api/schemas.py
- [ ] T010: Implement FastAPI app factory, loopback CORS policy, auth-token middleware, and router registration in src/desktop_api/app.py
- [ ] T011: Implement sidecar process entrypoint with random localhost port and runtime token handling in src/desktop_api/__main__.py
- [ ] T012: Implement backend event queue and blinker-to-UI event stream adapter in src/desktop_api/events.py
- [ ] T013: Implement typed frontend API runtime, token header injection, error normalization, and event-stream client in frontend/src/api/client.ts
- [ ] T014: Implement global shell, route, and backend-status stores in frontend/src/state/shellStore.ts
- [ ] T015: Port shared design primitives from the prototype into frontend/src/components/primitives.tsx
- [ ] T016: Implement theme tokens, density tokens, and global CSS baseline in frontend/src/styles/theme.css
- [ ] T017: Implement Tauri sidecar lifecycle module with PyInstaller binary launch, port/token handoff, and shutdown cleanup in src-tauri/src/sidecar.rs
- [ ] T018: Implement scoped Tauri window command module for minimize, maximize/restore, close, and drag handling in src-tauri/src/window.rs
- [ ] T019: Wire Tauri plugin-shell, plugin-http, and window command initialization in src-tauri/src/lib.rs
- [ ] T020: Add Python API test fixtures for token-authenticated FastAPI clients in tests/desktop_api/conftest.py
- [ ] T021: Add frontend unit test setup, Tauri API mocks, and API client mocks in frontend/src/test/setup.ts
- [ ] T022: Add architecture guard test scaffolding for frontend/API storage-boundary imports in tests/guardrails/test_ui_stack_boundaries.py
- [ ] T023: Add sidecar build helper for copying target-triple PyInstaller output in scripts/build_desktop_sidecar.ps1
- [ ] T024: Add repository-wide route registration and OpenAPI smoke test for src/desktop_api/app.py in tests/desktop_api/test_app_contract.py
- [ ] T025: Add backend health/bootstrap contract tests in tests/desktop_api/test_health_bootstrap.py
- [ ] T026: Add frontend shell navigation and state-preservation tests in frontend/tests/unit/app-shell.test.tsx
- [ ] T027: Add Tauri launch, five-route navigation, and custom chrome smoke tests in frontend/tests/e2e/app-shell.spec.ts
- [ ] T028: Add guard tests proving normal launch paths do not open legacy PyQt windows in tests/guardrails/test_legacy_pyqt_launch.py
- [ ] T029: Implement shell bootstrap business service using existing services and no repository leakage in src/business/services/desktop_bootstrap_service.py
- [ ] T030: Implement health and bootstrap endpoints in src/desktop_api/routers/health.py
- [ ] T031: Complete Tauri sidecar startup, health polling, and shutdown integration in src-tauri/src/sidecar.rs
- [ ] T032: Complete branded custom window action wiring in src-tauri/src/window.rs
- [ ] T033: Implement React app shell layout in frontend/src/app/AppShell.tsx
- [ ] T034: Implement persistent navigation rail with real counts and screen routes in frontend/src/app/NavRail.tsx
- [ ] T035: Implement custom red/yellow/green titlebar and drag region in frontend/src/app/CustomTitlebar.tsx
- [ ] T036: Implement backend readiness, degraded, failed, and shutdown states in frontend/src/app/BackendStatus.tsx
- [ ] T037: Register five primary screen routes and real loading/error placeholders in frontend/src/app/routes.tsx
- [ ] T038: Wire React root, API bootstrap, event client startup, and shell store hydration in frontend/src/main.tsx
- [ ] T039: Configure Tauri app metadata, window dimensions, custom decorations, and externalBin sidecar path in src-tauri/tauri.conf.json
- [ ] T040: Add assistant sessions, messages, rename, delete, and confirmation contract tests in tests/desktop_api/test_assistant_api.py
- [ ] T041: Add assistant progress and confirmation event-stream tests in tests/desktop_api/test_assistant_events.py
- [ ] T042: Add frontend assistant timeline, session sidebar, composer, and confirmation tests in frontend/tests/unit/assistant-screen.test.tsx
- [ ] T043: Add assistant happy-path e2e test with controlled backend fixture and under-2-minute assertion in frontend/tests/e2e/assistant.spec.ts
- [ ] T044: Extend ChatService with search, rename, delete/archive, and display DTO helpers in src/business/services/chat_service.py
- [ ] T045: Implement assistant REST endpoints for sessions, messages, and confirmation decisions in src/desktop_api/routers/assistant.py
- [ ] T046: Implement assistant worker dispatch adapter that preserves AgentOrchestrator semantics in src/desktop_api/assistant_runtime.py
- [ ] T047: Implement high-risk confirmation DTO mapping without raw file or command leakage in src/desktop_api/confirmations.py
- [ ] T048: Map assistant progress, final message, error, and confirmation blinker events in src/desktop_api/events.py
- [ ] T049: Implement typed assistant API client functions in frontend/src/api/assistant.ts
- [ ] T050: Implement assistant session, timeline, draft, progress, and confirmation state in frontend/src/state/assistantStore.ts
- [ ] T051: Implement redesigned assistant screen and timeline composition in frontend/src/screens/assistant/AssistantScreen.tsx
- [ ] T052: Implement conversation list, search, rename, delete, and empty states in frontend/src/screens/assistant/SessionSidebar.tsx
- [ ] T053: Implement message composer and send-state handling in frontend/src/screens/assistant/MessageComposer.tsx
- [ ] T054: Implement safe assistant markdown rendering in frontend/src/screens/assistant/SafeMarkdown.tsx
- [ ] T055: Implement compact/expandable execution summaries in frontend/src/screens/assistant/ExecutionSummary.tsx
- [ ] T056: Implement non-modal high-risk confirmation surface independent from normal toasts in frontend/src/screens/assistant/ConfirmationToast.tsx
- [ ] T057: Add teaching readiness, run creation, recording stop, health decision, intent, and trial API tests in tests/desktop_api/test_teaching_api.py
- [ ] T058: Add teaching progress, recording progress, trial progress, and failure event-stream tests in tests/desktop_api/test_teaching_events.py
- [ ] T059: Add frontend teaching stage, recording mode, health review, and trial progress tests in frontend/tests/unit/teaching-screen.test.tsx
- [ ] T060: Add teaching fixture e2e test through trial-ready state with under-5-minute assertion in frontend/tests/e2e/teaching.spec.ts
- [ ] T061: Implement teaching workflow facade over AgentOrchestrator and existing recording services in src/business/services/teaching_service.py
- [ ] T062: Implement recording readiness service for browser, extension, and desktop prerequisites in src/business/services/recording_readiness_service.py
- [ ] T063: Implement teaching endpoints for readiness, runs, recording, desktop health decisions, intent, and trial start in src/desktop_api/routers/teaching.py
- [ ] T064: Map recording, teaching, trial, desktop sanity, and failure events to frontend DTOs in src/desktop_api/events.py
- [ ] T065: Implement typed teaching API client functions in frontend/src/api/teaching.ts
- [ ] T066: Implement teaching workflow state machine in frontend/src/state/teachingStore.ts
- [ ] T067: Implement redesigned teaching screen shell in frontend/src/screens/teaching/TeachingScreen.tsx
- [ ] T068: Implement browser, extension, and desktop mode cards with readiness/setup actions in frontend/src/screens/teaching/RecordingModePicker.tsx
- [ ] T069: Implement recording active view, timers, stop action, and desktop sanity choices in frontend/src/screens/teaching/RecordingStage.tsx
- [ ] T070: Implement intent confirmation questions and answer submission view in frontend/src/screens/teaching/IntentStage.tsx
- [ ] T071: Implement learning progress, retry, blocked, and failure states in frontend/src/screens/teaching/LearningStage.tsx
- [ ] T072: Implement trial validation progress and publish-threshold view in frontend/src/screens/teaching/TrialStage.tsx
- [ ] T073: Add skills category, trial, metadata, delete, retry, and dismiss API tests in tests/desktop_api/test_skills_api.py
- [ ] T074: Add composition list, create, update, AI helper, trial, publish, and needs-review API tests in tests/desktop_api/test_compositions_api.py
- [ ] T075: Add frontend Skill List and Skill Composition tests in frontend/tests/unit/skills-compositions.test.tsx
- [ ] T076: Add e2e test for pending/published/failed skills plus range and ordered composition creation in frontend/tests/e2e/skills-compositions.spec.ts
- [ ] T077: Extend SkillsService with UI DTOs, failure dismiss, and validation-action helpers in src/business/services/skills_service.py
- [ ] T078: Implement skills endpoints for categories, trial start, metadata update, delete, failure retry, and failure dismiss in src/desktop_api/routers/skills.py
- [ ] T079: Implement composition UI DTO adapter over SkillCompositionService in src/business/services/skill_composition/ui_adapter.py
- [ ] T080: Implement composition endpoints for list, create, update, generate applicability, recommend order, trial, and publish in src/desktop_api/routers/compositions.py
- [ ] T081: Map skills changed, failure changed, composition review, and trial events to frontend DTOs in src/desktop_api/events.py
- [ ] T082: Implement typed skills API client functions in frontend/src/api/skills.ts
- [ ] T083: Implement typed composition API client functions in frontend/src/api/compositions.ts
- [ ] T084: Implement skill list state and action reducers in frontend/src/state/skillsStore.ts
- [ ] T085: Implement composition list/editor/trial state in frontend/src/state/compositionsStore.ts
- [ ] T086: Implement redesigned Skill List tabs, counts, empty states, and actions in frontend/src/screens/skills/SkillListScreen.tsx
- [ ] T087: Implement pending, published, and failed skill cards in frontend/src/screens/skills/SkillCards.tsx
- [ ] T088: Implement composition list, review badges, and create entry points in frontend/src/screens/compositions/CompositionListScreen.tsx
- [ ] T089: Implement composition editor for name, description, mode, applicability, trial, and publish in frontend/src/screens/compositions/CompositionEditor.tsx
- [ ] T090: Implement member selector, ordered reorder controls, and range/ordered validation display in frontend/src/screens/compositions/MemberSelector.tsx
- [ ] T091: Add settings schema, values, non-secret update, secret write/delete, and actions API tests in tests/desktop_api/test_settings_api.py
- [ ] T092: Add keyring masking and no-plaintext secret regression tests in tests/integration/test_settings_secret_storage.py
- [ ] T093: Add frontend settings section, validation, action, and secret masking tests in frontend/tests/unit/settings-screen.test.tsx
- [ ] T094: Add e2e settings test for non-secret save, secret test, invalid value feedback, and visible actions in frontend/tests/e2e/settings.spec.ts
- [ ] T095: Implement settings schema/value facade over UnifiedConfigManager and keyring-backed secret methods in src/business/services/settings_service.py
- [ ] T096: Implement real settings action handlers for test connection, backup, export, clear memory, updates, docs, changelog, and certificate install in src/business/services/settings_actions_service.py
- [ ] T097: Implement settings endpoints for schema, values, non-secret updates, secret writes/deletes, and actions in src/desktop_api/routers/settings.py
- [ ] T098: Add or normalize config defaults for all design-visible non-secret settings in src/data/config_models.py
- [ ] T099: Update configuration examples and comments for new settings in config.example.json and config.example.comments.md
- [ ] T100: Implement typed settings API client functions in frontend/src/api/settings.ts
- [ ] T101: Implement settings state, dirty tracking, validation errors, and secret presence state in frontend/src/state/settingsStore.ts
- [ ] T102: Implement redesigned Settings shell with AI, Recording, Data, and About sections in frontend/src/screens/settings/SettingsScreen.tsx
- [ ] T103: Implement reusable setting controls, masked secret input, and validation feedback in frontend/src/screens/settings/SettingControls.tsx
- [ ] T104: Implement settings action buttons and unavailable-state feedback in frontend/src/screens/settings/SettingsActions.tsx
- [ ] T105: Add no-sample-data and no-fake-counts audit e2e test in frontend/tests/e2e/no-sample-data.spec.ts
- [ ] T106: Add launch performance and backend degraded/failed/shutdown smoke tests in frontend/tests/e2e/performance-and-health.spec.ts
- [ ] T107: Add full visible-control wiring audit test for five screens in frontend/tests/e2e/visible-controls.spec.ts
- [ ] T108: Add packaging build path for Tauri plus Python sidecar in build_tauri.bat, build_executable.py, installer.iss, and BUILD_README.txt
- [ ] T109: Remove or replace normal legacy PyQt launch entry points in src/main.py, mexemplar_gui.py, mexemplar_gui.bat, and start.bat
- [ ] T110: Remove retired primary PyQt UI modules and leave no launchable maintained fallback in src/ui/
- [ ] T111: Update or remove obsolete PyQt UI tests and add replacement guard coverage in tests/ui/ and tests/guardrails/test_legacy_pyqt_removal.py
- [ ] T112: Update runtime architecture documentation for Tauri/React/Python sidecar in docs/ARCHITECTURE.md
- [ ] T113: Update project constraints for frontend/API bridge, sidecar auth, settings safety, and legacy PyQt removal in docs/PROJECT_CONSTRAINTS.md
- [ ] T114: Update agent and contributor guidance for the new UI stack in AGENTS.md, CLAUDE.md, README.md, INSTALL.md, and BUILD_README.txt
- [ ] T115: Run Python formatting, linting, and tests for src/ and tests/ using uv run black src/ tests/, uv run flake8 src/ tests/, and uv run pytest tests/
- [ ] T116: Run frontend lint, unit tests, e2e tests, and Tauri build for frontend/ and src-tauri/ using npm run lint, npm run test, npm run test:e2e, and npm run tauri build
- [ ] T117: Add legacy local data non-mutation fixture and launch safety test in tests/integration/test_legacy_local_data_safety.py
- [ ] T118: Add sidecar runtime token non-persistence and no-log regression tests in tests/desktop_api/test_sidecar_token_security.py
- [ ] T119: Record quickstart validation results and any accepted exceptions in docs/local/2026-05-10-ui-stack-redesign-validation.md
