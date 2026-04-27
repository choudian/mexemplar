# Contract: Assistant High-Risk Confirmation UI

This is an internal UI/business contract for the Auth Toast feature. It is not a network API and does not create persisted data.

## Worker -> UI Confirmation Signal

Existing channel remains:

```python
_confirm_action_signal = pyqtSignal(str, str)
register_confirm_mechanism(_confirm_action_signal)
```

Payload:

| Position | Name | Type | Description |
|----------|------|------|-------------|
| 1 | `request_id` | `str` | Unique id for the waiting Worker confirmation request |
| 2 | `message` | `str` | Sanitized display summary; no full file content or full tool parameters |

Rules:
- UI must not block the main window while handling this signal.
- UI must complete the request by calling the business result API exactly once unless the request has already timed out.
- Multiple signals are queued FIFO in UI.

## Business Result API

Current API must remain backward compatible:

```python
set_confirm_result(request_id: str, result: bool, source: str = "toast") -> None
```

Expected sources:

| Source | Meaning |
|--------|---------|
| `toast_accept` | User clicked "同意" |
| `toast_reject` | User clicked "拒绝" |
| `toast_allow_all` | User clicked "全部允许"; current request approved |
| `toast_timeout` | Auth toast timer expired |
| `top_toggle` | User enabled "免确认" before/while requests were pending |
| `auto_scope` | Request auto-approved because session scope was already enabled |

Rules:
- Unknown `request_id` must not crash UI.
- `result=False` means reject/cancel semantics for the Worker.
- `source` is used for structured logs and tests; it must not contain user content.

## Auto-Approve Scope API

```python
set_auto_approve_enabled(enabled: bool, source: str) -> None
is_auto_approve_enabled() -> bool
reset_auto_approve(source: str = "new_chat_reset") -> None
```

Rules:
- Default is disabled.
- State is process memory only.
- New chat must call `reset_auto_approve`.
- Enabling from either the top Toggle or "全部允许" must update the other visible entry point.

## UI Surface Contract

`AuthToastSurface` emits one terminal decision signal:

```python
decision_made(request_id: str, decision: str)
```

Allowed decisions:

| Decision | UI trigger | Business result |
|----------|------------|-----------------|
| `allow_all` | "全部允许" button | `True`, enable auto-approve |
| `accept` | "同意" button | `True` |
| `reject` | "拒绝" button | `False` |
| `timeout` | timer expires | `False` |

Rules:
- No close button.
- Outside clicks do not dismiss the surface.
- The surface is non-modal and must not call `exec()` on a dialog.
- The surface must be repositioned on main-window resize.
- It must not reuse or overwrite `MainWindow._active_toast`.

## Logging Contract

One structured log entry is emitted for every terminal decision:

```python
{
    "request_id": "...",
    "tool_name": "write_file|edit_file|exec",
    "decision": "accepted|rejected|timeout|auto_approved|confirm_error",
    "source": "toast_accept|toast_reject|toast_allow_all|toast_timeout|top_toggle|auto_scope|system_error",
    "elapsed_ms": 123,
    "summary": "sanitized summary"
}
```

Prohibited log content:
- Full file content passed to `write_file`
- Full `old_text` / `new_text` from `edit_file`
- Full multi-line command bodies beyond the approved first-line/truncated summary
- Secrets or API keys inferred from arguments
