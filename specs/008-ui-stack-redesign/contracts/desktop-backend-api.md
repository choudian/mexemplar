# Contract: Desktop Backend API

This contract defines the internal boundary between the Tauri/React UI and the packaged Python sidecar. It is not a public network API. All endpoints bind to `127.0.0.1` on a per-launch random port and require `X-Mexemplar-Session: <runtime-token>` unless explicitly marked otherwise.

## Transport Rules

- Base URL is provided by Tauri after sidecar startup: `http://127.0.0.1:{port}`.
- Every request includes `X-Mexemplar-Session`.
- Responses use JSON UTF-8.
- Backend errors use:

```json
{
  "error": {
    "code": "string",
    "message": "user-facing message",
    "details": {}
  }
}
```

- Frontend must treat `401/403` as sidecar authorization failure and move shell state to `failed`.
- Frontend must not call repositories, SQLite, DuckDB, config files, or keyring directly.

## Common DTOs

### BackendConnectionState

```json
{
  "status": "starting|ready|degraded|failed|shutting_down",
  "message": "string",
  "checks": [
    {"name": "config|sqlite|recording_recovery|events|sidecar", "status": "ok|degraded|failed", "message": "string"}
  ],
  "serverTime": "2026-05-10T00:00:00Z"
}
```

### PageResult

```json
{
  "items": [],
  "nextCursor": "string|null",
  "hasMore": true
}
```

## Health And Bootstrap

### GET `/api/health`

Returns `BackendConnectionState`.

### GET `/api/bootstrap`

Returns initial shell data.

```json
{
  "connection": {},
  "user": {"displayName": "string", "statusLabel": "本地版 · 已就绪"},
  "navigation": {
    "pendingSkillCount": 0,
    "publishedSkillCount": 0,
    "failureCount": 0,
    "compositionCount": 0
  },
  "settingsSummary": {
    "theme": "sage",
    "dark": false,
    "density": "comfy"
  }
}
```

## Event Stream

### GET `/api/events`

Server-sent events or WebSocket equivalent. The implementation may choose SSE first; payload shape must stay stable.

```json
{
  "eventId": "evt_123",
  "type": "assistant.progress|assistant.confirmation|teaching.progress|recording.progress|trial.progress|skills.changed|settings.changed|backend.health",
  "scope": {"sessionId": "ast_x", "workflowId": "rec_x"},
  "payload": {},
  "createdAt": "2026-05-10T00:00:00Z"
}
```

Event adapter source is `src/utils/events.py`; lower backend layers must not import Tauri or frontend code.

## AI Assistant

### GET `/api/assistant/sessions?query=&limit=200`

Returns conversation list with real titles/previews.

### POST `/api/assistant/sessions`

Creates a new assistant session.

Request:

```json
{"toolIds": ["tool_1"], "title": "optional"}
```

Response:

```json
{"sessionId": "ast_abc123"}
```

### PATCH `/api/assistant/sessions/{sessionId}`

Renames a session.

Request:

```json
{"title": "New title"}
```

### DELETE `/api/assistant/sessions/{sessionId}`

Deletes or archives a session according to business service semantics.

### GET `/api/assistant/sessions/{sessionId}/messages?limit=10&beforeSequence=123`

Returns displayable messages only.

```json
{
  "items": [
    {"sequence": 1, "role": "user|assistant", "content": "string", "createdAt": "2026-05-10T00:00:00Z", "rendering": "plain_text|safe_markdown"}
  ],
  "hasMoreBefore": false,
  "nextBeforeSequence": 1
}
```

### POST `/api/assistant/sessions/{sessionId}/messages`

Sends a user message and starts/resumes the Assistant worker.

Request:

```json
{"content": "string"}
```

Response:

```json
{"accepted": true, "sessionId": "ast_abc123"}
```

Assistant progress, final messages, errors, and confirmations are delivered through `/api/events`.

### POST `/api/assistant/confirmations/{requestId}/decision`

Approves or denies a high-risk action.

Request:

```json
{"decision": "approve|deny"}
```

Validation:

- Must preserve backend `request_id` semantics.
- Must not include raw file contents, full replacement text, or multiline command bodies in DTOs or logs.

## Skill Teaching

### GET `/api/teaching/readiness`

Returns mode-specific setup state for `browser`, `extension`, and `desktop`.

### POST `/api/teaching/runs`

Starts a teaching run shell state before recording.

Request:

```json
{"mode": "browser|extension|desktop"}
```

Response:

```json
{"workflowId": "rec_abc123", "stage": "selecting", "readiness": {}}
```

### POST `/api/teaching/runs/{workflowId}/recording/start`

Starts the selected recording mode. Desktop mode must only run after the Tauri window minimize callback has completed.

Request:

```json
{"mode": "browser|extension|desktop", "windowMinimized": true}
```

### POST `/api/teaching/runs/{workflowId}/recording/stop`

Stops recording and returns summary/sanity-check requirements.

### POST `/api/teaching/runs/{workflowId}/recording/desktop-health-decision`

Request:

```json
{"decision": "continue|discard|rerecord"}
```

### POST `/api/teaching/runs/{workflowId}/intent/reply`

Answers PM intent questions.

### POST `/api/teaching/runs/{workflowId}/intent/confirm`

Confirms intent and starts learning.

### POST `/api/teaching/runs/{workflowId}/trial/start`

Starts trial validation for the generated skill.

Progress and failures are delivered through `/api/events`.

## Skills

### GET `/api/skills?category=pending|published|failed`

Returns real skill/failure categories and counts.

### POST `/api/skills/{toolId}/trial`

Starts trial validation for a pending skill.

### PATCH `/api/skills/{toolId}`

Updates skill metadata through `SkillsService`.

Request:

```json
{"name": "string", "description": "string"}
```

### DELETE `/api/skills/{toolId}`

Deletes a skill only if business validation allows it.

### POST `/api/skills/failures/{workflowId}/retry`

Retries a teaching failure using existing retry coordinator semantics.

### POST `/api/skills/failures/{workflowId}/dismiss`

Ignores/dismisses a failure record.

## Skill Compositions

### GET `/api/compositions`

Lists compositions with members, persisted lifecycle `status`, presentation-only `displayStatus`, and `needsReview`.

### POST `/api/compositions`

Creates a draft composition.

Request:

```json
{
  "name": "string",
  "description": "string",
  "mode": "range|ordered",
  "applicability": "string",
  "members": [{"toolId": "tool_1", "selectedOrder": 0, "executionOrder": 0}]
}
```

### PUT `/api/compositions/{compositionId}`

Updates metadata, mode, applicability, and member order.

### POST `/api/compositions/{compositionId}/generate-applicability`

Generates scenario text from selected members through business LLM helper.

### POST `/api/compositions/{compositionId}/recommend-order`

Returns recommended ordered member list for ordered mode.

### POST `/api/compositions/{compositionId}/trial`

Starts composition trial.

### POST `/api/compositions/{compositionId}/publish`

Publishes if validation passes.

Validation:

- `applicability` required for publish.
- Ordered mode requires contiguous execution order.
- Members must reference published skills.
- `needsReview` compositions return `displayStatus: "needs_review"` and are hidden from Assistant until re-reviewed.

## Settings

### GET `/api/settings/schema`

Returns sections, labels, supported values, validation rules, and action availability for AI, Recording, Data, and About.

### GET `/api/settings/values`

Returns current non-secret settings and masked secret state.

```json
{
  "values": {"ai.model": "claude-sonnet-4-5-20250929"},
  "secrets": {"ai.api_key": {"present": true, "masked": "••••••••"}},
  "status": {"recording.desktop.vision_model": "available|missing_secret|invalid|unavailable"}
}
```

### PATCH `/api/settings/values`

Updates non-secret settings through `UnifiedConfigManager`.

### POST `/api/settings/secrets/{secretKey}`

Writes a secret through keyring-backed business/config methods. Response never includes the secret.

### DELETE `/api/settings/secrets/{secretKey}`

Clears a secret.

### POST `/api/settings/actions/{actionName}`

Runs a real supported Settings action.

Allowed action names:

- `test_ai_connection`
- `browse_data_directory`
- `backup_data`
- `export_all_data`
- `clear_assistant_memory`
- `check_updates`
- `open_changelog`
- `open_documentation`
- `install_extension_certificate`

Each action must either complete a real workflow or return a real validation/business error. No action may silently no-op.

## Window Commands

Tauri owns real window actions. The React chrome calls Tauri window APIs or scoped commands for:

- `minimize`
- `toggle_maximize`
- `close`
- `start_dragging`

These commands are not proxied through Python.
