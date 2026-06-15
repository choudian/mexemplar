# Feature Specification: Assistant Failed Message Retry

**Feature Branch**: `018-assistant-failed-message-retry`
**Created**: 2026-06-15
**Status**: Approved
**Input**: Persist terminal Assistant failures and let users retry the failed message, optionally after editing it, without exposing sensitive diagnostics.

## User Scenarios & Testing

### User Story 1 - Recover A Failed Turn (Priority: P1)

When an Assistant turn ends in failure, the user sees a recovery card directly below the user message that triggered the failed turn. The card explains the problem in safe language and offers an immediate retry.

**Why this priority**: A failed turn currently leaves only an optimistic user message and a generic error state, so the user cannot recover the exact request reliably.

**Independent Test**: Force a terminal Assistant failure, reload the conversation, click retry, and verify the same user request is dispatched and the card disappears after success.

**Acceptance Scenarios**:

1. **Given** an Assistant turn fails terminally, **When** the failure is persisted and published, **Then** the triggering user message appears with a failure card containing a friendly reason, suggestion, attempt count, retry action, edit action, and debug action.
2. **Given** the application restarts after a failed turn, **When** the conversation history is loaded, **Then** the same unresolved failure card is restored from backend data.
3. **Given** an unresolved failed message, **When** the user retries without editing and the retry succeeds, **Then** the failure becomes resolved and the old card is removed.

---

### User Story 2 - Edit Before Retrying (Priority: P2)

The user can edit the failed request before retrying. The original user message remains unchanged and the edited content starts a new user turn.

**Why this priority**: Some failures are best recovered by simplifying or correcting the request, while preserving the original transcript for auditability.

**Independent Test**: Open edit mode on a failed card, change the text, submit it, and verify a new user message is created while the original remains unchanged.

**Acceptance Scenarios**:

1. **Given** a failed user message, **When** the user edits and submits non-empty content, **Then** the original failure is resolved and a new user turn is dispatched with the edited content.
2. **Given** edit mode is open, **When** the user cancels, **Then** no request is sent and the failure card remains actionable.
3. **Given** a retry request is in flight, **When** the user clicks retry again, **Then** duplicate dispatch is prevented and the card displays a processing state.
4. **Given** an edited retry fails, **When** the new turn reaches a terminal failure, **Then** the original card stays removed and a new failure card appears on the new user message.

---

### User Story 3 - Inspect Available Diagnostics (Priority: P3)

The user can open Debug Inspector scoped to the failed conversation. When traces were captured, the newest matching failed trace is selected; otherwise the UI explains that historical raw details cannot be reconstructed.

**Why this priority**: Recovery needs a safe escalation path without leaking raw provider responses into normal chat DTOs or events.

**Independent Test**: Open the debug action from a failed card with and without trace capture enabled and verify session filtering, trace selection, and the unavailable-history explanation.

**Acceptance Scenarios**:

1. **Given** a failed card for a session with captured traces, **When** the user opens debug information, **Then** `/debug?sessionId=<session>` loads traces filtered to that session and selects the newest failed trace.
2. **Given** trace capture was not enabled for the failed request, **When** the user opens debug information, **Then** Debug Inspector states that historical raw details cannot be backfilled.

### Edge Cases

- A retry targets a failure that has already been resolved, superseded, or moved to another user message.
- Two retry requests arrive concurrently for the same failure.
- The process exits while a failure is in `retrying`.
- The session or original user message no longer exists.
- The user submits empty or whitespace-only edited content.
- Event replay has a gap and the frontend must reload authoritative messages.
- Failure classification receives nested exceptions, provider-specific status attributes, or unsafe raw text.
- The user sends a normal new message instead of using retry; prior unresolved cards must no longer remain current.

## Requirements

### Functional Requirements

- **FR-001**: The system MUST persist every terminal Assistant turn failure before publishing the terminal failed progress state.
- **FR-002**: A failure record MUST identify the Assistant session and triggering user message sequence, and store category, safe message, safe suggestion, internal status code, exception type, attempt count, status, and timestamps.
- **FR-003**: Failure status MUST follow `failed -> retrying -> resolved|failed`; interrupted `retrying` records MUST recover to `failed` during sidecar startup.
- **FR-004**: The system MUST classify terminal failures into authentication, invalid request, quota/rate limit, network, provider/server, iteration limit, and internal categories.
- **FR-005**: Normal chat DTOs and UI events MUST NOT include raw provider responses, endpoint URLs, credentials, API keys, stack traces, or exception message bodies.
- **FR-006**: On failure, the backend MUST publish any newly persisted display messages, including the triggering user message, before publishing `assistant.progress(status=failed)`.
- **FR-007**: `AssistantMessage` and `assistant.message` MAY include one unresolved failure object with `category`, `message`, `suggestion`, `attemptCount`, and `failedAt`.
- **FR-008**: The retry endpoint MUST accept `{ messageSequence, content? }`; omitted `content` retries the original text, while supplied content creates a new user turn without mutating the original message.
- **FR-009**: Retry MUST reject a non-current failure with conflict, reject empty edited content, and reject a missing or non-Assistant session.
- **FR-010**: Concurrent retries for one failure MUST allow at most one transition to `retrying`.
- **FR-011**: Manual retry count MUST not be capped and MUST preserve the existing automatic provider retry policy without adding fallback-model switching.
- **FR-012**: A successful retry MUST resolve the source failure and remove its card from authoritative message history.
- **FR-013**: A failed edited retry MUST associate the new unresolved failure with the new user message, not the original message.
- **FR-014**: Sending a new normal message MUST resolve any prior unresolved failure in the same session before dispatching the new turn.
- **FR-015**: The frontend MUST render the recovery card immediately below its user bubble with retry, edit-and-retry, cancel-edit, and debug actions.
- **FR-016**: Retry controls MUST be disabled while the request is submitting and MUST return to an actionable state when the retry API itself fails.
- **FR-017**: Assistant terminal run failures MUST not populate the global `lastError` path that produces duplicate error Toasts; API, loading, and Debug Inspector failures retain existing Toast/error behavior.
- **FR-018**: The debug action MUST navigate to `/debug?sessionId=<sessionId>`, filter trace/flow lists by session, and auto-select the newest failed trace when available.
- **FR-019**: Debug Inspector MUST explicitly state that historical raw detail is unavailable when trace capture was not armed before the failure.
- **FR-020**: On `backend.resync_required`, the frontend MUST reload authoritative messages and MUST NOT infer failure state from local progress events.

### Key Entities

- **Assistant Run Failure**: Persistent record for one terminal failed Assistant turn, keyed to its session and user message sequence.
- **Failure Summary**: Safe user-facing projection containing category, message, suggestion, attempt count, and failure time.
- **Retry Request**: User action targeting one current failed message with optional replacement content.

### Constraints & Compatibility

- **CC-001**: Business data stays in SQLite and is accessed through a Repository and business service; desktop API routers do not access the database directly.
- **CC-002**: Existing automatic LLM retry behavior remains unchanged; no backup model selection is introduced.
- **CC-003**: Failure classification may inspect exception structure internally, but only allowlisted safe projections reach ordinary logs, DTOs, and UI events.
- **CC-004**: UI event replay remains notification-only; persisted message/failure state is authoritative after restart or replay gaps.
- **CC-005**: Existing cancellation, paused subagent, confirmation, queueing, and 100% Assistant dispatch semantics remain unchanged.

## Architecture Impact

### Layer Impact

- [x] **UI** (`frontend/src/`)
- [x] **Desktop API Bridge** (`src/desktop_api/`)
- [x] **Business** (`src/business/`)
- [ ] **Execution** (`src/execution/`)
- [x] **Data** (`src/data/`)
- [ ] **Recording** (`src/recording/`)
- [ ] **Utils** (`src/utils/`)

### Agent Impact

- Affected Agent: Assistant.
- No new Agent tools or prompt changes.
- `AssistantRuntime` gains terminal-failure persistence and retry dispatch orchestration.
- Existing automatic provider retries and subagent resumability remain intact.

### Data Store Impact

- **SQLite**: v14 `assistant_run_failures` table and `AssistantRunFailureRepository`.
- **DuckDB**: No change.
- **Config**: No new keys.
- **Secrets**: No new secret storage; classification output is explicitly sanitized.

### Event Impact

- No new blinker events.
- `assistant.message` gains optional `failure`.
- `assistant.progress` remains the terminal run status signal.
- `assistant.error` is no longer emitted for ordinary terminal Assistant run failures.

## Success Criteria

### Measurable Outcomes

- **SC-001**: 100% of tested terminal Assistant failures are restored after application restart on the correct user message.
- **SC-002**: Concurrent duplicate retry tests produce exactly one accepted retry transition and one Assistant dispatch.
- **SC-003**: All classifier fixtures return the expected safe category without exposing fixture secrets, endpoints, or raw response text.
- **SC-004**: Original and edited retry journeys complete through backend, unit UI, and mock E2E tests.
- **SC-005**: Assistant failure journeys produce no duplicate global error Toast.
- **SC-006**: Focused pytest, Vitest, Playwright E2E, lint, formatting, and `git diff --check` pass.

## Assumptions

- Every terminal Assistant failure is manually retryable.
- Only the latest unresolved failure in a session is current and actionable.
- A normal new user message supersedes the previous unresolved failure.
- Debug trace capture is runtime-only and cannot reconstruct historical raw detail.
