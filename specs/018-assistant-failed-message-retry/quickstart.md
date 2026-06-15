# Quickstart: Assistant Failed Message Retry

## Backend

```powershell
uv run python -m pytest tests/data/test_assistant_run_failure_repository.py tests/data/test_migrations.py tests/business/services/test_assistant_failure_classifier.py tests/desktop_api/test_assistant_runtime.py tests/desktop_api/test_assistant_api.py tests/desktop_api/test_assistant_events.py -q
```

## Frontend

```powershell
cd frontend
npm run test -- assistant-failure-retry assistant-screen debug-screen
npm run test:e2e -- assistant-failure-retry
npm run lint
```

## Manual Acceptance

1. Start a conversation and force a terminal model failure.
2. Confirm the user message remains visible with one inline recovery card and no duplicate Toast.
3. Restart the app and reopen the conversation; confirm the card remains.
4. Retry unchanged and confirm success removes the card.
5. Force another failure, edit the request, and confirm a new user turn is created.
6. Open debug information and confirm session filtering and the trace-unavailable explanation.
