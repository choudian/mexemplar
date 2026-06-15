# Research: Assistant Failed Message Retry

## Decision 1: Persist Failure Separately From Messages

Use a dedicated `assistant_run_failures` table linked by session and user message sequence.

**Rationale**: Message rows remain the transcript source while failure lifecycle and internal diagnostics require mutable state. Embedding failure JSON in `messages` would mix display history with retry coordination and make conditional transitions harder.

## Decision 2: One Current Failure Per Session

Only the latest unresolved `failed|retrying` record is current. A normal new message or edited retry resolves the old record.

**Rationale**: The product contract says a failure card represents the current recoverable fault, not a permanent error archive in chat.

## Decision 3: Atomic Retry Claim

Use a conditional Repository update from `failed` to `retrying`.

**Rationale**: Frontend loading state is not a concurrency boundary. The database transition prevents duplicate dispatch from repeated clicks or concurrent API requests.

## Decision 4: Safe Classification Projection

Classify from exception types, status-code attributes, result type, and conservative keyword matching. Persist only a stable internal code and exception class name; never persist raw response bodies or exception strings as user-facing text.

**Rationale**: Provider exceptions often include endpoint URLs, request bodies, or credentials. Friendly text must come from an allowlisted mapping.

## Decision 5: Reuse Existing Message Event

Republish the affected user message with optional `failure` rather than add a separate failure event.

**Rationale**: Message history remains authoritative and replay gaps already trigger message reload. A separate ephemeral event would require frontend reconciliation and could drift after restart.

## Decision 6: No Backup Model

Manual retry calls the same normal Assistant dispatch path and preserves current automatic retry policy.

**Rationale**: Model fallback changes cost, behavior, credentials, and observability beyond this feature's recovery scope.
