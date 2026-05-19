# Contract: Public Desktop UI Events

## Stream

`GET /api/events`

Headers:

- `X-Mexemplar-Session`: required runtime session token.
- `Last-Event-ID`: optional SSE event id from the same desktop session.

Query parameters:

- `lastSeenSequence`: optional integer sequence from the same desktop session.
- `eventSessionId`: optional backend event-session id from the previous connection.

## Envelope

```json
{
  "eventId": "evt_123",
  "sequence": 42,
  "sessionId": "ui_sess_abc",
  "causationId": "workflow_1",
  "type": "teaching.stage_changed",
  "scope": { "workflowId": "workflow_1" },
  "payload": { "stage": "learning", "message": "Skill learning started" },
  "createdAt": "2026-05-16T00:00:00Z"
}
```

## Registered Event Types

| Type | Category | Required scope | Payload summary |
|------|----------|----------------|-----------------|
| `assistant.message` | notification | `sessionId` | Displayable assistant/user message |
| `assistant.progress` | notification | `sessionId` | Assistant status and headline |
| `assistant.error` | notification | `sessionId` | User-safe error message |
| `assistant.confirmation` | interactive | `sessionId` | Existing high-risk confirmation request |
| `recording.progress` | notification | `workflowId` | Recording status, action count, or degradation summary |
| `teaching.stage_changed` | notification | `workflowId` | Authoritative teaching stage |
| `teaching.progress` | notification | `workflowId` | User-safe teaching progress message |
| `trial.progress` | notification | `workflowId` | Trial status and success/published summary |
| `trial.preview_requested` | interactive | `workflowId` | Trial preview confirmation request with `expires_at` |
| `trial.preview_resolved` | interactive | `workflowId` | Trial preview decision/terminal outcome |
| `skills.changed` | notification | optional `toolId` | Skill catalog invalidation |
| `compositions.changed` | notification | optional `compositionId` | Composition catalog invalidation |
| `settings.changed` | notification | optional | Settings invalidation |
| `backend.resync_required` | control | optional | Reason and affected domains to refresh |

## Trial Preview Decision

`POST /api/teaching/trial-preview/{request_id}/decision`

```json
{ "decision": "approve" }
```

Response:

```json
{
  "requestId": "preview_1",
  "decision": "approve",
  "accepted": true,
  "status": "accepted"
}
```

Duplicate or late decisions return `accepted: false` with `status` set to `already_resolved`, `expired`, or `conflict`.
Terminal preview resolution events use `status` values `approved`, `denied`, `timeout`, `disconnect`, `overflow`, or `shutdown`; every non-`approved` terminal status is treated as denial by the waiting backend workflow.

## Safety Rules

- Event payloads are allowlist-only.
- Payloads must not contain runtime tokens, secrets, full code, full command bodies, unredacted stack traces, database paths, raw query results, or unfiltered recording data.
- Unsafe events are rejected before publication. If frontend state recovery is required, publish a separate safe registered summary or `backend.resync_required` event.
