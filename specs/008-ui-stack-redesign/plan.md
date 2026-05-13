# Implementation Plan: UI Stack Redesign

**Branch**: `008-ui-stack-redesign` | **Date**: 2026-05-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/008-ui-stack-redesign/spec.md`

**Note**: This plan replaces the legacy PyQt widget shell with a Tauri 2 + React + TypeScript desktop surface backed by the existing Python business/data stack exposed through a controlled sidecar API.

## Summary

Implement the full Mexemplar desktop redesign as one accepted product surface: AI Assistant, Skill Teaching, Skill List, Skill Composition, and Settings. The chosen approach is Tauri 2 for the desktop shell, React 18 + TypeScript + Vite for the UI, and a packaged Python FastAPI sidecar that exposes typed UI bridge contracts over localhost while preserving all existing business, repository, configuration, secret-storage, recording, memory, and Agent orchestration boundaries.

The design prototype under `C:\Users\gaopan\Downloads\mexamplar` is the visual baseline, but all prototype sample data and no-op controls must be replaced with real business data, real empty/loading/error states, and real actions. The accepted end state removes legacy PyQt entry points and primary UI code; no maintained PyQt fallback remains.

## Technical Context

**Language/Version**: Python >=3.11 (current runtime target 3.12), Rust stable compatible with Tauri 2 plugins, TypeScript 5.x, React 18
**Primary Dependencies**: Tauri 2, React 18, Vite, Tailwind CSS, Zustand, FastAPI, Uvicorn, Pydantic, existing SQLAlchemy/Alembic, DuckDB, keyring, blinker, Playwright, LangChain, PyInstaller
**Storage**: SQLite via Repository/services for business data; DuckDB for recording/analysis data behind existing recording services/tools; keyring for secrets; `app_settings` through `UnifiedConfigManager`; no legacy local-data migration required
**Testing**: `pytest` for Python business/API/bridge behavior; frontend unit/component tests with Vitest + React Testing Library; Playwright desktop smoke tests for packaged or dev Tauri shell; guard tests for removed PyQt entry points and forbidden storage access
**Target Platform**: Windows desktop first, using system WebView2 through Tauri; fresh-install profile is the primary acceptance profile
**Project Type**: Desktop app with Tauri shell, React frontend, and Python sidecar backend
**Performance Goals**: 95% of normal launches reach interactive ready state within 10s on the target development machine, measured from packaged process start to an interactive shell with `ready` or recoverable `degraded` backend state; AI Assistant happy path under 2 minutes from app launch to visible assistant response plus expandable execution summary; Skill Teaching fixture path under 5 minutes from recording-mode selection to trial-ready state; navigation and typing remain immediately responsive during backend work
**Constraints**: UI must call typed bridge/API contracts only; no frontend or UI adapter may access repositories, SQLite, DuckDB, config files, or keyring directly; every visible design control in [control-inventory.md](./control-inventory.md) must be wired to a real business path, Tauri command, or real validation/business error; secrets never leave masked UI states; sidecar API binds to localhost with a per-launch auth token that is not persisted or logged; branded red/yellow/green custom window chrome must perform real close/minimize/maximize-restore actions; all interactive controls must be keyboard operable with visible focus and accessible names/states
**Scale/Scope**: Five primary screens, side navigation, custom chrome, assistant chat/history/progress/confirmations, three recording modes, teaching stages, skill management, composition CRUD/trial/publish, settings, packaging, health/recovery, and legacy PyQt removal

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required | Status |
|-----------|---------------|-------------------|--------|
| I. Layered Boundaries & Event Coordination | Does the design preserve `UI -> business -> execution -> data/driver` direction, and are all cross-module notifications routed through `src/utils/events.py`? | Tauri/React UI calls Python FastAPI bridge; bridge calls business services/orchestrator; business continues to use execution/data layers. Blinker remains the backend cross-module event mechanism; the API adds a backend-to-frontend event stream adapter rather than lower layers importing UI. | PASS |
| II. Data Boundary & Persistence Discipline | Are SQLite and DuckDB responsibilities explicit, are Repository boundaries preserved, and do `network_requests` reads keep filtering/desensitization contracts? | SQLite remains behind repositories/services; DuckDB remains behind recording services/tools and existing filtering contracts. No Tauri SQL plugin or frontend direct storage access is allowed. No new raw SQL exception is planned. | PASS |
| III. Unified Config & Secret Handling | Do all new settings flow through `UnifiedConfigManager`, and do all secrets stay out of code/config files? | Settings endpoints call `get_unified_config()` and keyring-backed secret methods. API keys are never returned in plaintext; frontend stores only masked display state and transient form input. New settings visible in the design require config defaults/templates and docs updates. | PASS |
| IV. Verifiable Delivery | Does the plan include automated coverage for deterministic logic plus wiring smoke/guard tests for architecture rewires? | Planned coverage includes Python API/service tests, frontend component tests, event-stream/confirmation tests, Tauri smoke tests, launch/health failure tests, no-sample-data checks, and guard tests proving PyQt entry points are removed and UI cannot import repositories/storage engines. | PASS |
| V. Living Docs & Spec-Driven Delivery | Are required active docs identified for update, and are temporary notes confined to `docs/local/`? | This feature owns `specs/008-ui-stack-redesign/*`; implementation must update `docs/ARCHITECTURE.md`, `docs/PROJECT_CONSTRAINTS.md`, `AGENTS.md`, packaging docs, and user-facing install/run docs when code reality changes. The local UI stack decision input is recorded in `docs/local/2026-05-10-ui-tech-stack-decision.md`; durable acceptance traceability lives in `control-inventory.md`. | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/008-ui-stack-redesign/
├── plan.md
├── research.md
├── data-model.md
├── control-inventory.md
├── quickstart.md
├── contracts/
│   └── desktop-backend-api.md
└── tasks.md                 # Created by /speckit.tasks, not this command
```

### Source Code (repository root)

```text
frontend/
├── package.json             # Vite/Tauri frontend scripts and test scripts
├── index.html
├── src/
│   ├── main.tsx
│   ├── app/                 # App shell, route registry, custom chrome
│   ├── api/                 # Typed client for Python sidecar contracts
│   ├── components/          # Shared primitives adapted from design prototype
│   ├── screens/             # assistant, teach, skills, compositions, settings
│   ├── state/               # Zustand stores for local UI/session state
│   ├── styles/              # Tailwind/theme tokens/design baseline
│   └── test/                # Frontend fixtures and component helpers
└── tests/
    ├── unit/
    └── e2e/

src-tauri/
├── Cargo.toml
├── tauri.conf.json          # Tauri app config, custom window, externalBin
├── capabilities/
│   └── default.json         # Scoped shell/http/window permissions
├── binaries/                # PyInstaller sidecar output by target triple
└── src/
    ├── lib.rs
    ├── sidecar.rs           # Python sidecar lifecycle, port/token handoff
    └── window.rs            # Custom chrome commands and window state

src/
├── desktop_api/             # FastAPI sidecar adapter; no UI widget imports
│   ├── app.py               # App factory, auth token middleware, CORS scope
│   ├── schemas.py           # Pydantic request/response DTOs
│   ├── events.py            # blinker -> SSE/WebSocket adapter
│   └── routers/
│       ├── health.py
│       ├── assistant.py
│       ├── teaching.py
│       ├── skills.py
│       ├── compositions.py
│       └── settings.py
├── business/
│   ├── services/            # Existing services extended for UI contracts
│   └── orchestration/agent/ # Existing AgentOrchestrator remains source of truth
├── data/                    # Existing repositories/config/keyring boundaries
├── execution/               # Existing tool/trial execution
├── recording/               # Existing browser/extension/desktop recording
├── ui/                      # Legacy PyQt exists only during migration, removed by acceptance
└── utils/

tests/
├── desktop_api/             # FastAPI contract and event-stream tests
├── integration/             # backend bridge and launch/health tests
├── ui/                      # Legacy PyQt tests removed or replaced by frontend/e2e coverage
└── guardrails/              # Layer/import/removal guard tests
```

**Structure Decision**: Add a separate `frontend/` tree for Vite/React because the repository's existing `src/` is the Python package. Add `src-tauri/` for the Rust desktop shell. Add `src/desktop_api/` as a Python sidecar adapter that calls existing business services and emits typed contracts; it must not become a data access layer. Keep existing `src/business`, `src/data`, `src/execution`, `src/recording`, and `src/utils` as the semantic source of truth. Remove `src/ui` entry points and primary PyQt UI code only after the new Tauri shell passes acceptance gates.

## Phase 0 Research Summary

Research decisions are recorded in [research.md](./research.md). Key resolved decisions:

- Use Tauri 2 + React + TypeScript + Vite to match the approved React/CSS prototype and avoid rebuilding modern layout/animation primitives in PyQt widgets.
- Package the existing Python runtime as a PyInstaller sidecar and expose a localhost FastAPI contract to the frontend.
- Protect the local sidecar API with loopback bind, per-launch auth token, scoped Tauri permissions, and masked secret DTOs.
- Preserve backend event semantics by adapting `src/utils/events.py` blinker events into a frontend event stream.
- Use guard tests and packaging smoke tests as acceptance gates before removing PyQt entry points.

## Phase 1 Design Summary

Design artifacts are recorded in:

- [data-model.md](./data-model.md)
- [control-inventory.md](./control-inventory.md)
- [contracts/desktop-backend-api.md](./contracts/desktop-backend-api.md)
- [quickstart.md](./quickstart.md)

The frontend/server contract is intentionally coarse-grained by user workflow rather than mirroring repositories. This keeps the UI independent of database shape and allows existing Python services to enforce validation, state transitions, configuration safety, and event boundaries. `control-inventory.md` is the acceptance trace for prototype-visible controls; implementation and tests must keep that inventory synchronized when a control is wired, disabled by real product state, or removed by an approved baseline change.

## Post-Design Constitution Re-Check

| Principle | Result | Notes |
|-----------|--------|-------|
| I. Layered Boundaries & Event Coordination | PASS | `src/desktop_api` is a business-facing adapter; Tauri/React remains UI. Event stream is an adapter over backend blinker events, not a replacement event bus. |
| II. Data Boundary & Persistence Discipline | PASS | Contracts expose DTOs only. No frontend SQL, Tauri SQL plugin, DuckDB access, or repository imports are allowed. |
| III. Unified Config & Secret Handling | PASS | Settings contract separates non-secret values from secret update/test actions; API keys are write-only/masked. |
| IV. Verifiable Delivery | PASS | Quickstart defines Python, frontend, integration, e2e, smoke, and guard validation commands. |
| V. Living Docs & Spec-Driven Delivery | PASS | Active docs to update are listed; `AGENTS.md` SPECKIT marker is updated to this plan. |

## Dependency, Security, And Acceptance Traceability

| Area | Dependency or artifact | Acceptance/setup linkage |
|------|------------------------|--------------------------|
| Design baseline | 2026-05-09 prototype files under `C:\Users\gaopan\Downloads\mexamplar` and [control-inventory.md](./control-inventory.md) | Review uses prototype layout/flow plus inventory control IDs; T008 verifies inventory currency and T107 audits visible-control wiring. |
| Desktop runtime | WebView2, Tauri 2, Rust stable, `src-tauri/tauri.conf.json`, scoped capabilities | Quickstart prerequisites, T004/T017-T019/T027/T039/T116 validate launch, permissions, sidecar lifecycle, custom chrome, and build. |
| Python sidecar | Python 3.11+, FastAPI, Uvicorn, Pydantic, PyInstaller | T005/T009-T012/T017/T023/T024 and `tests/desktop_api` validate typed contracts, auth, event stream, and packaging handoff. |
| Sidecar security | Loopback bind, random per-launch port, runtime token, no token persistence/logging, scoped Tauri HTTP/shell/window permissions | T010/T011/T017/T018/T024/T118 validate token enforcement, non-persistence, log safety, CORS scope, and window command scope. |
| Secret handling | keyring-backed secret methods and masked frontend DTOs | T091/T092/T095/T097/T103 validate write-only secret updates, masked display, and no plaintext regression. |
| Frontend quality | React 18, TypeScript, Vite, Tailwind, Zustand, Vitest, React Testing Library, Playwright | T002/T003/T013-T016/T021/T026/T042/T059/T075/T093/T105-T107/T116 cover frontend setup, keyboard/accessibility behavior, component tests, and e2e acceptance. |
| Fresh install and legacy safety | Fresh profile, no data migration requirement, no silent legacy data mutation | T028/T109-T111/T117 and SC-012 validate no normal PyQt fallback and no silent legacy data mutation. |

## Complexity Tracking

No constitution violations are planned.
