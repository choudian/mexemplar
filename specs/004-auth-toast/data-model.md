# Data Model: 高危操作确认 Toast 化（Auth Toast）

This feature does not add persistent database schema. The following entities are runtime-only objects/state used by the business confirmation helper and UI layer.

## AuthConfirmationRequest

Represents one high-risk Assistant tool confirmation request.

| Field | Type | Owner | Rules |
|-------|------|-------|-------|
| `request_id` | `str` | business | UUID string; unique per confirmation request; used to isolate Worker wait/result |
| `tool_name` | `str` | business | One of `write_file`, `edit_file`, `exec` for this feature |
| `summary` | `str` | business | Sanitized display/log summary; includes path or command first line; excludes full content |
| `created_at` | monotonic timestamp | business | Used to compute wait duration |
| `event` | `threading.Event` | business | Worker wait primitive; one event per request |
| `result` | `bool` | business | Defaults to `False`; `True` only for accepted/auto-approved decisions |
| `decision` | enum string | business | `accepted`, `rejected`, `timeout`, `auto_approved`, `confirm_error` |
| `source` | enum string | business/UI | `toast_accept`, `toast_reject`, `toast_timeout`, `toast_allow_all`, `top_toggle`, `auto_scope`, `system_error` |

### Validation Rules

- `request_id` must map to at most one pending request.
- `summary` must be generated from allowlisted fields and truncated before logging/display.
- Missing or unknown `request_id` in `set_confirm_result` is ignored safely and logged at debug/warning level only.
- Timeout resolves as `result = False` and `decision = timeout`.

### State Transitions

```text
created
  -> queued_in_ui
  -> displayed
  -> accepted       (toast "同意")
  -> rejected       (toast "拒绝")
  -> auto_approved  (toast "全部允许", top Toggle, or pre-existing auto scope)
  -> timeout        (UI timer or Worker wait timeout)
  -> confirm_error  (signal/dispatch failure)
```

Each request reaches exactly one terminal decision.

## AutoApproveScope

Represents the current Assistant session's "全部允许 / 免确认" state.

| Field | Type | Owner | Rules |
|-------|------|-------|-------|
| `enabled` | `bool` | business | Default `False`; true means all Assistant high-risk tools auto-approve |
| `session_id` | `Optional[str]` | UI/business boundary | Optional current chat session identity used for reset diagnostics; not persisted |
| `updated_at` | monotonic timestamp | business | For logging/debugging only |
| `source` | enum string | UI/business | `toast_allow_all`, `top_toggle`, `new_chat_reset`, `startup_default` |

### Validation Rules

- State resets to `False` when the user starts a new chat.
- State is not written to config, SQLite, DuckDB, or secrets storage.
- When enabled, new high-risk requests do not emit confirmation UI and log `auto_approved`.
- When enabled while requests are queued in UI, queued Assistant requests are completed as auto-approved immediately.

## AuthToastSurface

UI component for one visible confirmation request.

| Field | Type | Owner | Rules |
|-------|------|-------|-------|
| `request_id` | `str` | UI | Matches an `AuthConfirmationRequest` |
| `tool_name_label` | label text | UI | Derived from sanitized summary/message |
| `summary_label` | label text | UI | Word-wrapped, truncated safe summary |
| `timeout_timer` | `QTimer` | UI | Single-shot; fires no later than Worker timeout |
| `buttons` | three controls | UI | `全部允许`, `同意`, `拒绝` only |

### Validation Rules

- No normal close button.
- No outside-click dismissal.
- At most one visible auth confirmation surface at a time.
- Ordinary Toast and auth toast use independent references/lifecycle and must not delete each other.

## AuthToastQueue

UI-owned FIFO queue for confirmation requests emitted while another auth toast is visible.

| Field | Type | Owner | Rules |
|-------|------|-------|-------|
| `pending` | queue/list | UI | FIFO order by signal arrival |
| `active_request_id` | `Optional[str]` | UI | One visible request at a time |

### State Rules

- Signal arrival enqueues if another auth toast is active.
- Closing the active auth toast by explicit decision or timeout displays the next queued request.
- Clicking "全部允许" completes the active request and all queued Assistant requests as auto-approved, then clears the queue.
