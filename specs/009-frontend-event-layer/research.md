# Research: Frontend Event Layer

## Decision: Backend UI Event Registry Owns The Public Contract

**Rationale**: The backend already owns business semantics and the desktop API is the adapter boundary. A registry in `src/desktop_api/` can map internal blinker events and direct runtime publications to stable UI event types while keeping frontend-specific contracts out of business/execution/recording layers.

**Alternatives considered**:

- Reuse internal event names directly in React: rejected because it preserves the current `sourceEvent` coupling and violates the clarified public contract.
- Put registry definitions in frontend TypeScript only: rejected because backend payload safety and event publication validation must run before events leave the sidecar.

## Decision: Per-Subscriber In-Memory Event Hub With Same-Session Replay

**Rationale**: UI events are session notifications, not persisted facts. An in-memory hub can assign session-scoped monotonic sequences, copy each event to every active subscriber, maintain a bounded replay buffer, and close only slow/overflowed subscribers with a resync-required event.

**Alternatives considered**:

- Single shared queue: rejected because subscribers steal events from one another.
- Persistent event log: rejected because the spec explicitly scopes UI events to the current desktop session and requires authoritative snapshots for recovery.

## Decision: Resync Is A First-Class Registered UI Event

**Rationale**: When a replay gap, session mismatch, or buffer loss occurs, the frontend needs a deterministic state recovery path. A registered `backend.resync_required` event keeps this explicit and avoids fabricating UI state from stale events.

**Alternatives considered**:

- Silent reconnect with bootstrap only: rejected because tests need a visible signal and stores need to know to refresh authoritative snapshots.
- Replay across process restarts: rejected because event sequence values are only meaningful within one desktop session.

## Decision: Publish-Time Payload Safety Validation

**Rationale**: The sidecar must reject unsafe payloads before serialization. The registry can define allowlisted payload keys and scan values for obvious secret/runtime-token/code/command/raw-data indicators.

**Alternatives considered**:

- Frontend redaction: rejected because sensitive fields would already have crossed the trust boundary.
- Global string stripping: rejected because it silently changes semantics; unsafe public UI events should fail closed or publish a separate safe summary/resync event.

## Decision: Desktop Trial Preview Uses Backend-Generated `expires_at`

**Rationale**: The backend owns the pending workflow and can define a single expiry/deadline for all subscribers. Broadcasting to all scoped subscribers and accepting only the first valid decision gives deterministic behavior when multiple windows are open.

**Alternatives considered**:

- Frontend-only timeout: rejected because the backend workflow would not have a trustworthy fail-closed deadline.
- First subscriber only: rejected because the clarified spec requires all active subscribers in scope to see the request.

## Decision: TypeScript Contract Is Validated Against Registry Export

**Rationale**: A lightweight backend registry export plus frontend discriminated union keeps both sides aligned without introducing a new code generation dependency. Guard tests can fail when a backend event type lacks a frontend handler or example payload.

**Alternatives considered**:

- Manual docs only: rejected because it cannot prevent drift.
- Full OpenAPI generator: deferred because the event stream contract is narrower than the REST API and can be validated with simpler fixtures.

