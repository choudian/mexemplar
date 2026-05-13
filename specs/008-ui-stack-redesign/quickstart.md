# Quickstart: UI Stack Redesign

This quickstart describes the target developer workflow once the planned stack is scaffolded.

## Prerequisites

- Windows development machine with WebView2 runtime
- Python 3.11+ with `uv`
- Node.js LTS and npm/pnpm
- Rust stable toolchain compatible with Tauri 2
- Tauri CLI through the selected package manager

## Initial Setup

```powershell
uv sync
cd frontend
npm install
cd ..
```

Build the Python sidecar for local Tauri development:

```powershell
uv run pyinstaller --clean build_exe.spec
```

The implementation may wrap this in a repository script, but the output must be copied or linked into `src-tauri/binaries/` using the target-triple naming required by Tauri sidecars.

## Run In Development

Start the Tauri app, which starts the Python sidecar automatically:

```powershell
cd frontend
npm run tauri dev
```

Expected result:

- The app opens into the redesigned Mexemplar shell.
- AI Assistant is selected by default.
- Backend state reaches `ready` or a clear recoverable `degraded/failed` state.
- The user can navigate AI Assistant, Skill Teaching, Skill List, Skill Composition, and Settings without opening PyQt windows.

## Backend Contract Checks

Run Python sidecar/API tests:

```powershell
uv run pytest tests/desktop_api tests/integration
```

Minimum coverage:

- Health/bootstrap token behavior
- Assistant session/message display DTOs
- Event stream adapter for assistant progress and confirmation
- Teaching readiness and desktop recording health decision routing
- Skill category/action routing
- Composition validation/publish routing
- Settings non-secret and secret paths

## Frontend Checks

Run frontend static and component checks:

```powershell
cd frontend
npm run lint
npm run test
```

Minimum coverage:

- App shell route switching and preserved local state
- Custom window chrome buttons call real Tauri window actions in tests/mocks
- Keyboard-only route navigation, form operation, confirmation handling, and custom chrome actions expose visible focus and accessible names/states
- Empty/loading/error states for all five screens
- Assistant timeline safe rendering and execution summary expansion
- No prototype sample records or fake counts in accepted normal states

## Desktop Smoke Checks

Run packaged/dev desktop smoke tests:

```powershell
cd frontend
npm run test:e2e
```

Smoke scenarios:

- Launch reaches interactive ready state within the configured acceptance threshold.
- Navigate all five primary screens.
- Send an assistant message through a mocked or controlled backend path.
- Trigger and resolve a high-risk confirmation without modal dialogs.
- Start/stop a controlled teaching fixture and reach trial-ready state.
- Create range and ordered compositions from published fixture skills.
- Save a non-secret setting and write/test a secret without exposing plaintext.
- Minimize, maximize/restore, and close through red/yellow/green custom controls.
- Traverse every visible control listed in `specs/008-ui-stack-redesign/control-inventory.md` and verify it is wired, disabled with a real product reason, or removed by approved baseline change.

## Guardrail Checks

Run architecture/removal guards:

```powershell
uv run pytest tests/guardrails
```

Required guards:

- Frontend and `src/desktop_api` do not import repositories/storage engines directly.
- Recording data still flows through existing filtering/service boundaries.
- Settings write paths use `get_unified_config()` and keyring methods for secrets.
- Runtime sidecar tokens are not persisted or written to normal logs.
- No normal launch path imports `src.ui.main_window` after acceptance.
- Legacy PyQt entry points are removed or fail with an explicit unsupported message after acceptance.

## Packaging Check

```powershell
cd frontend
npm run tauri build
```

Expected result:

- Tauri app bundles the Python sidecar.
- Normal users do not manually start the backend.
- Backend startup, ready, degraded, failed, and shutdown states are visible in the shell.
- Fresh-install acceptance runs without requiring legacy local data.

## Active Documentation Updates

Before implementation is accepted, update:

- `docs/ARCHITECTURE.md` with Tauri/React/Python sidecar runtime structure.
- `docs/PROJECT_CONSTRAINTS.md` with frontend/API bridge guardrails and legacy PyQt removal boundary.
- `AGENTS.md` with current UI stack reality and feature plan reference.
- Packaging docs (`README.md`, `INSTALL.md`, `BUILD_README.txt`, build scripts) to reflect Tauri + sidecar.
- Config examples/templates for any new design-visible settings.
