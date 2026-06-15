# Implementation Plan: Assistant Failed Message Retry

**Branch**: `018-assistant-failed-message-retry` | **Date**: 2026-06-15 | **Spec**: [spec.md](spec.md)

## Summary

Add a persistent terminal-failure record linked to the user message that started an Assistant turn, expose only a safe failure projection through existing message history/events, and add a guarded retry endpoint. React renders an inline recovery card and uses the existing hidden Debug Inspector for session-scoped diagnostics.

## Technical Context

**Language/Version**: Python 3.11+ / runtime 3.12; TypeScript 5; React 18
**Primary Dependencies**: FastAPI, Pydantic, SQLAlchemy, Zustand, Vitest, React Testing Library, Playwright
**Storage**: SQLite v14 migration; no DuckDB or config change
**Testing**: pytest, Vitest, Playwright, ESLint, Black, flake8
**Target Platform**: Tauri 2 desktop app with localhost FastAPI sidecar
**Project Type**: desktop-app with API service and React frontend
**Performance Goals**: Failure lookup joins only the visible message page; retry state transition is a single atomic conditional update
**Constraints**: No raw provider details in normal DTO/events; no fallback model; replay gaps reload authoritative state
**Scale/Scope**: Single-user local desktop sessions, paginated chat history, one active Assistant run per session

## Design

### Data And Repository

- Add ORM model and v14 migration for `assistant_run_failures`.
- Enforce status/category values with checks and a partial unique index allowing one current `failed|retrying` record per session.
- Add `AssistantRunFailureRepository` operations for create-or-replace current failure, page lookup by message sequence, compare-and-set retry start, retry success, retry failure, supersede on normal send, and startup recovery.
- Keep internal diagnostic fields in the row but exclude them from `FailureSummary`.

### Business Service

- Add `AssistantFailureService` as the business facade used by `AssistantRuntime` and the router.
- Centralize exception/result classification in `assistant_failure_classifier.py`.
- Resolve the original user message through `ChatService`/Repository-backed service methods; the router never reads Repository state.
- Retry without content reuses the original message text. Edited retry resolves the old failure and dispatches a new turn.

### Runtime And Publication

- Capture the latest display sequence before dispatch as today.
- On terminal failure, first publish all display messages after that sequence, persist/classify the failure against the latest new user message, then publish the same user message with its failure projection, followed by failed progress.
- On success, resolve the source retry record.
- Normal sends supersede any prior unresolved failure before dispatch.
- Do not emit `assistant.error` for terminal run failures.

### API And Events

- Add `POST /api/assistant/sessions/{sessionId}/retry`.
- Extend Pydantic and TypeScript `AssistantMessage` with optional `failure`.
- Extend `assistant.message` registry validation to allow a bounded nested failure object.
- Map missing session to 404, stale/non-current target to 409, and empty edited content to 422.

### Frontend

- Add retry API client and store state keyed by `sessionId:messageSequence`.
- Keep failure state on authoritative `AssistantMessage` objects; event updates replace the matching message.
- Render a compact inline recovery card under user content. Use the existing visual language and stable layout, with clear loading and keyboard-accessible controls.
- Edit mode uses local component state so drafts do not pollute the global composer.
- Debug action uses `history.pushState` to `/debug?sessionId=...`.
- Debug Inspector reads the query parameter, filters trace/flow requests, auto-selects the newest failed trace, and displays a historical-unavailable note when appropriate.

## Constitution Check

| Principle | Result | Evidence |
|-----------|--------|----------|
| I. Layered Boundaries & Event Coordination | PASS | React -> typed API -> router -> `AssistantFailureService` -> Repository. No new cross-module blinker event. |
| II. Data Boundary & Persistence Discipline | PASS | SQLite v14 plus dedicated Repository; no router SQL and no DuckDB changes. |
| III. Unified Config & Secret Handling | PASS | No config keys. Classifier projection excludes raw exception text, endpoint, response body, and credentials. |
| IV. Verifiable Delivery | PASS | Migration, Repository state machine, concurrency, runtime ordering, API mapping, UI, E2E, and no-Toast tests are required. |
| V. Living Docs & Spec-Driven Delivery | PASS | Update architecture, constraints, and root/src/frontend AI mirrors; archive the local completed TODO when present. |

## Project Structure

```text
specs/018-assistant-failed-message-retry/
├── spec.md
├── plan.md
├── tasks.md
├── data-model.md
├── research.md
├── quickstart.md
├── contracts/rest-api.md
└── checklists/requirements.md

src/
├── business/services/assistant_failure_service.py
├── business/services/assistant_failure_classifier.py
├── data/models_sqlite.py
├── data/migrations.py
├── data/repos/assistant_run_failure_repository.py
├── desktop_api/assistant_runtime.py
├── desktop_api/routers/assistant.py
├── desktop_api/schemas.py
└── desktop_api/ui_events.py

frontend/
├── src/api/assistant.ts
├── src/state/assistantStore.ts
├── src/screens/assistant/AssistantFailureCard.tsx
├── src/screens/assistant/AssistantScreen.tsx
├── src/screens/debug/DebugScreen.tsx
└── tests/
```

## Compatibility And Rollout

- Existing databases migrate from v13 to v14 without backfill because historical failures were not persisted.
- Existing message DTO consumers tolerate absent `failure`.
- Startup recovery converts only `retrying` rows to `failed`.
- No behavior changes for PM, Programmer, Trial, cancellation, waiting-for-user, or paused subagent results.

## Complexity Tracking

No constitution exceptions.
