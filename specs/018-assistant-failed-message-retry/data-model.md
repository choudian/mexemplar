# Data Model: Assistant Failed Message Retry

## AssistantRunFailure

| Field | Type | Notes |
|-------|------|-------|
| `failure_id` | text PK | Generated stable identifier |
| `session_id` | text | Assistant session |
| `message_sequence` | integer | Triggering user display message |
| `category` | text | `authentication`, `invalid_request`, `quota`, `network`, `provider`, `iteration_limit`, `internal` |
| `safe_message` | text | Allowlisted user-facing reason |
| `safe_suggestion` | text | Allowlisted action suggestion |
| `internal_code` | text nullable | Stable internal classification code |
| `exception_type` | text nullable | Exception class name only |
| `attempt_count` | integer | Starts at 1 and increments per manual retry attempt |
| `status` | text | `failed`, `retrying`, `resolved` |
| `created_at` | datetime | First failure time |
| `updated_at` | datetime | Last transition time |
| `failed_at` | datetime | Most recent terminal failure |
| `resolved_at` | datetime nullable | Success or supersession time |

## State Transitions

```text
new terminal failure -> failed
failed --atomic retry claim--> retrying
retrying --successful Assistant run--> resolved
retrying --terminal failure--> failed (attempt_count preserved)
retrying --user cancellation--> failed (remains actionable)
failed --normal new message / edited retry--> resolved
retrying --sidecar startup recovery--> failed
```

## Invariants

- At most one `failed|retrying` row is current per session.
- Current failure must point to an existing user message sequence.
- `attempt_count >= 1`.
- Only safe projection fields are returned to ordinary chat APIs/events.
- `exception_type` is a class name, not an exception body.
