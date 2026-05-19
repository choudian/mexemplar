# Implementation Plan: Frontend Event Layer

**Branch**: `009-frontend-event-layer` | **Date**: 2026-05-16 | **Spec**: `specs/009-frontend-event-layer/spec.md`
**Input**: Feature specification from `specs/009-frontend-event-layer/spec.md`

## Summary

Refactor the desktop event stream so React consumes a backend-owned public UI event contract instead of internal backend event names. The implementation will add a validated UI event registry/projection layer in `src/desktop_api/`, replace the single shared event queue with a per-subscriber event hub, add same-session replay and resync-required semantics, expose typed frontend event consumption, and close the desktop trial preview loop with explicit approve/deny/timeout behavior.

The source design document named in the original input, `docs/design/todo-frontend-event-layer.md`, is not present in this worktree. The clarified `spec.md` is therefore the authoritative source for this implementation.

## Technical Context

**Language/Version**: Python 3.12 runtime target, TypeScript 5.x, React 18, Rust/Tauri 2 unchanged  
**Primary Dependencies**: FastAPI, Pydantic, blinker, React, Zustand, Vite/Vitest, Playwright E2E mocks  
**Storage**: No new persistent storage; UI events remain desktop-session memory only  
**Testing**: `uv run python -m pytest`, `uv run python -m py_compile`, `npm run test`, targeted frontend unit tests; E2E only if UI shell behavior changes  
**Target Platform**: Windows desktop app through Tauri + localhost FastAPI sidecar  
**Project Type**: desktop-app with local API bridge and web frontend  
**Performance Goals**: Two concurrent subscribers receive each event in at least 20 automated trials; reconnect preserves state across at least 10 simulated disconnect/resync cycles; slow subscriber handling does not block healthy subscribers  
**Constraints**: Runtime session token remains required for event streams; token never appears in URLs/payloads/logs/errors; frontend must not read repositories/config/keyring; event payloads must be allowlisted and user-safe  
**Scale/Scope**: Current desktop session, five main screens, internal backend events from teaching, recording, trial, skills, compositions, settings, assistant, and backend resync

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. Layered Boundaries & Event Coordination | Does the design preserve `UI -> business -> execution -> data/driver` direction, and are all cross-module notifications routed through `src/utils/events.py`? | PASS: backend workflows continue emitting internal blinker events in `src/utils/events.py`; `src/desktop_api/` projects them into public UI events; frontend consumes only desktop API contracts |
| II. Data Boundary & Persistence Discipline | Are SQLite and DuckDB responsibilities explicit, are Repository boundaries preserved, and do `network_requests` reads keep filtering/desensitization contracts? | PASS: no schema, repository, SQLite, or DuckDB access is added; event payload safety rejects raw query/recording data |
| III. Unified Config & Secret Handling | Do all new settings flow through `UnifiedConfigManager`, and do all secrets stay out of code/config files? | PASS: no new persistent config or secrets; runtime token remains header-only and is rejected from UI event payloads |
| IV. Verifiable Delivery | Does the plan include automated coverage for deterministic logic plus wiring smoke/guard tests for architecture rewires? | PASS: plan includes registry validation, payload safety tests, per-subscriber/replay tests, frontend typed consumer tests, and guard tests against `sourceEvent` display decisions |
| V. Living Docs & Spec-Driven Delivery | Are required active docs identified for update, and are temporary notes confined to `docs/local/`? | PASS: update `docs/ARCHITECTURE.md`, `docs/PROJECT_CONSTRAINTS.md`, and root AI entry mirrors if behavior/constraints change |

Post-design re-check: PASS. The selected design keeps the public UI event layer inside the desktop API adapter and does not introduce lower-layer frontend dependencies, persistent event storage, new configuration, or raw data access.

## Project Structure

### Documentation (this feature)

```text
specs/009-frontend-event-layer/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui-events.md
└── tasks.md
```

### Source Code (repository root)

```text
src/
├── desktop_api/
│   ├── app.py                 # SSE endpoint accepts last-seen sequence and emits resync outcomes
│   ├── events.py              # per-subscriber hub and blinker adapter
│   ├── schemas.py             # UI event envelope and decision DTOs
│   └── ui_events.py           # registry, projection, safety validation, preview request manager
└── utils/
    └── events.py              # internal blinker event names remain backend-only

frontend/
├── src/
│   ├── api/client.ts          # typed event stream client and reconnect metadata
│   ├── api/uiEvents.ts        # discriminated union matching backend registry contract
│   ├── app/AppShell.tsx       # event stream resync handling
│   └── state/*.ts             # stores consume registered UI event types only
└── tests/unit/
    ├── app-shell-events.test.tsx
    ├── teaching-screen.test.tsx
    └── ui-events.test.ts

tests/
├── desktop_api/
│   ├── test_ui_event_layer.py
│   ├── test_ui_event_subscribers.py
│   └── test_trial_preview_events.py
└── guardrails/
    └── test_frontend_event_contract.py
```

**Structure Decision**: Keep the public UI event projection in `src/desktop_api/` because it is the adapter between backend facts and React contracts. Do not move frontend event types into business/execution/recording layers. The React side receives a generated-or-validated contract artifact but owns only local UI state transitions.

## Complexity Tracking

No constitution violations are required.

