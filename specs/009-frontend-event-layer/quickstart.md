# Quickstart: Frontend Event Layer

## Backend Contract Checks

```powershell
uv run python -m pytest tests/desktop_api/test_ui_event_layer.py tests/desktop_api/test_ui_event_subscribers.py tests/desktop_api/test_trial_preview_events.py -q
```

Expected coverage:

- Registered event types only.
- Payload safety rejection.
- Two subscribers receive the same event for 20 trials.
- Slow subscriber overflow produces `backend.resync_required` without blocking a healthy subscriber.
- Reconnect with `lastSeenSequence` replays covered gaps and requests resync for missing gaps.
- Trial preview approve, deny, timeout, duplicate/conflict paths are deterministic.

## Frontend Contract Checks

```powershell
cd frontend
npm run test -- teaching-screen.test.tsx ui-events.test.ts
```

Expected coverage:

- Stores consume registered UI event types.
- Teaching stage changes do not depend on `payload.sourceEvent`.
- Event parsing ignores invalid frames and handles resync-required events.

## Guardrails

```powershell
uv run python -m pytest tests/guardrails/test_frontend_event_contract.py -q
```

Expected coverage:

- Frontend source does not use `sourceEvent` for display decisions.
- Backend direct publish paths go through registry validation and envelope creation.

## Broader Regression Gate

```powershell
uv run python -m pytest tests/desktop_api tests/guardrails -q
uv run python -m py_compile src/desktop_api/app.py src/desktop_api/events.py src/desktop_api/ui_events.py
cd frontend
npm run test
```

