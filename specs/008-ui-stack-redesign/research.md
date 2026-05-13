# Research: UI Stack Redesign

## Decision: Use Tauri 2 + React + TypeScript + Vite for the accepted desktop UI

**Rationale**: The approved prototype is already React and modern CSS. Tauri 2 lets the product use native desktop packaging and window control while rendering the UI with browser-grade layout, transitions, `oklch`, `color-mix`, flexbox, and component composition. This directly addresses the PyQt Widget/QSS fidelity ceiling documented in `D:\develop\code\Exemplar\docs\local\2026-05-10-ui-tech-stack-decision.md`.

**Alternatives considered**:

- Continue PyQt6: rejected because it recreates modern web UI primitives by hand and cannot faithfully match the prototype.
- QWebEngineView hybrid: acceptable only as a transitional spike, rejected for the accepted end state because it leaves two UI stacks alive.
- Electron: rejected because the app does not need Node as its backend and package size/runtime overhead is materially higher.
- Flutter Desktop: rejected because it would require translating the React prototype into Dart rather than reusing the design source.

## Decision: Keep Python as the semantic backend through a packaged sidecar

**Rationale**: Existing business, data, recording, memory, and Agent orchestration behavior is the product source of truth. Tauri's sidecar pattern supports bundling a PyInstaller-built Python executable and launching it with scoped permissions. This avoids a high-risk rewrite of Agent and recording internals while allowing the UI stack to change.

**Alternatives considered**:

- Rewrite backend in Rust: rejected for this feature because it would combine a UI migration with a semantic backend rewrite.
- Direct Tauri commands for each business operation: rejected because it would spread Python process integration across Rust commands and make existing Python service tests less reusable.
- Keep the Python GUI process and embed web UI: rejected because accepted state must remove the legacy PyQt primary UI.

## Decision: Use FastAPI localhost contracts for the React-to-Python bridge

**Rationale**: FastAPI provides typed request/response models, generated OpenAPI contracts, and straightforward REST plus streaming endpoints. It keeps the bridge testable with normal Python integration tests and avoids frontend knowledge of repositories or storage layout.

**Alternatives considered**:

- Raw WebSocket-only protocol: rejected because most screen operations are request/response CRUD or commands and benefit from explicit schemas.
- Direct SQLite/DuckDB access from Tauri plugins: rejected by constitution and because it bypasses repositories, filtering, config, and secret handling.
- Tauri invoke-only IPC: rejected for the first implementation because the Python sidecar still needs a process boundary and FastAPI better matches typed bridge contracts.

## Decision: Protect the local sidecar API with loopback bind, per-launch token, and scoped Tauri permissions

**Rationale**: Although the backend only binds to localhost, other local processes can call localhost ports. Tauri should start the sidecar on a random available port and pass a random per-launch token via environment or argv. Every API and event-stream request must include the token. Tauri capabilities should scope shell execution to the sidecar and HTTP/window permissions to what the UI actually needs.

**Alternatives considered**:

- Rely on localhost only: rejected because it is not an authorization boundary.
- Persist an API token in config: rejected because the token is a runtime process secret, not user configuration.
- Expose unauthenticated health and action endpoints: rejected because health can leak product state and action endpoints are high-risk.

## Decision: Adapt backend blinker events into a frontend event stream

**Rationale**: Backend cross-module notifications already use `src/utils/events.py`. A `src/desktop_api/events.py` adapter can subscribe to approved events and push typed UI events over SSE or WebSocket without changing lower-layer dependencies. This preserves the existing `UI -> business -> execution -> data/driver` dependency direction.

**Alternatives considered**:

- Emit events directly from data/execution layers to Tauri: rejected because lower layers must not call UI.
- Poll all progress from the frontend: rejected because assistant, recording, trial, confirmation, and health updates are event-driven and polling would add latency and duplicated state.
- Replace blinker with a new frontend bus: rejected because existing backend semantics and tests depend on blinker.

## Decision: Use Zustand for local UI state and keep server state authoritative

**Rationale**: The frontend needs route state, draft input, transient panel state, selected IDs, optimistic UI flags, and sidecar connection status. Product data remains authoritative in Python services and is refreshed through typed endpoints/events. This keeps the frontend thin enough to migrate safely while still supporting the design's rich interactions.

**Alternatives considered**:

- Put all state in React component state: rejected because five screens need shared shell/session/health state.
- Introduce a large state framework immediately: rejected because the product is a single-window desktop app and server state remains in Python.
- Persist UI state in localStorage by default: rejected for secrets and because same-window navigation preservation does not require durable persistence.

## Decision: Use custom Tauri window chrome for branded red/yellow/green controls

**Rationale**: The spec requires preserving the prototype's red/yellow/green controls on Windows as branded custom chrome. Tauri supports custom titlebars, drag regions, and window actions from the frontend while the Rust shell owns the real window.

**Alternatives considered**:

- Native Windows caption buttons: rejected by clarification and visual baseline.
- Visual-only dots with native hidden controls: rejected because each visible control must perform a real action.
- PyQt custom chrome: rejected because the accepted UI stack is Tauri/React.

## Decision: Remove PyQt only after new-shell acceptance gates pass

**Rationale**: The spec allows PyQt to exist during implementation but requires no maintained fallback after acceptance. Removal must be gated by smoke tests proving the Tauri shell launches, reaches all five screens, handles backend failures, and performs real window actions. Guard tests then prevent reintroducing the old GUI entry points as normal launch paths.

**Alternatives considered**:

- Remove PyQt at scaffold time: rejected because the replacement shell needs bridge and packaging validation first.
- Keep PyQt fallback indefinitely: rejected by spec and clarification.

## Official References Used

- Tauri sidecar/external binary documentation: https://v2.tauri.app/zh-cn/develop/sidecar/
- Tauri shell plugin and sidecar permissions: https://v2.tauri.app/fr/plugin/shell/
- Tauri custom window documentation: https://v2.tauri.app/ko/learn/window-customization/
- Tauri HTTP plugin reference: https://v2.tauri.app/reference/javascript/http/
- FastAPI OpenAPI documentation behavior: https://fastapi.tiangolo.com/em/reference/openapi/docs/
- FastAPI CORS middleware documentation: https://fastapi.tiangolo.com/tutorial/cors/
