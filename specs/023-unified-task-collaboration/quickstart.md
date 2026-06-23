# Quickstart: 统一任务模型 + 多范式协作

## Prerequisites

- Worktree: `E:\code\Exemplar\.worktrees\023-unified-task-collaboration`
- Branch: `023-unified-task-collaboration`
- Python/Node dependencies installed as in the base project.

## Implementation Order

Tasks must stay grouped by P1/P2/P3/P4 and keep phase dependencies intact. P3/P4 tasks may be listed early for planning, but implementation waits for P1/P2 gate tests.

1. Add SQLite v15/v16 migrations, compatibility handling for legacy `pending_assistant_tasks`, and the default clean-start cutover guard unless backfill is explicitly selected before schema work.
2. Add ORM models, repositories, indexes and state-machine tests for Task, Attempt, Operation, Question, Adjudication, Claim, Meeting and Todo.
3. Add `business/task_collaboration` services with fake executor tests, including bounded dispatcher workers and per-worker repository/session scope.
4. Cut Orchestrator delegation tools over to accepted `taskId` async dispatch while keeping Main Assistant as graph coordinator, not user-work executor.
5. Add checkpoint/idempotency enforcement before side effects and parent adjudication for unsafe recovery.
6. Add public UI events, projector, schemas and typed snapshot APIs with derived display phases and safe redacted summaries; update backend registry and frontend event contracts in the same slice.
7. Add React task graph/board/meeting/todo state and panels, including empty, loading, resync, keyboard focus and accessible action states.
8. Add failure bridge from root graph terminal failure to `assistant_run_failures`, with partial failures kept graph-local.
9. Add guardrails proving UI/API no longer derives task truth from `workflow_transitions`.
10. Update active docs if implementation changes architecture or project constraints.

## Focused Verification

```powershell
uv run python -m pytest tests/data/test_assistant_task_migration.py -q
uv run python -m pytest tests/data/test_migrations.py -q
uv run python -m pytest tests/data/test_assistant_task_repositories.py -q
uv run python -m pytest tests/business/agents/test_task_state_machine.py -q
uv run python -m pytest tests/business/agents/test_task_dispatch_async.py -q
uv run python -m pytest tests/business/agents/test_task_recovery.py -q
uv run python -m pytest tests/business/agents/test_task_idempotency.py -q
uv run python -m pytest tests/business/agents/test_task_idempotency_negative.py -q
uv run python -m pytest tests/business/agents/test_task_questions.py -q
uv run python -m pytest tests/business/agents/test_task_adjudication.py -q
uv run python -m pytest tests/business/agents/test_task_board_claims.py -q
uv run python -m pytest tests/business/agents/test_task_meetings.py -q
uv run python -m pytest tests/business/agents/test_task_todos.py -q
uv run python -m pytest tests/desktop_api/test_assistant_task_api.py -q
uv run python -m pytest tests/desktop_api/test_assistant_task_events.py -q
uv run python -m pytest tests/desktop_api/test_assistant_task_event_contract_sync.py -q
uv run python -m pytest tests/integration/test_assistant_task_cutover.py -q
uv run python -m pytest tests/integration/test_assistant_task_failure_bridge.py -q
uv run python -m pytest tests/integration/test_assistant_task_reentry_flow.py -q
uv run python -m pytest tests/guardrails/test_assistant_task_boundaries.py -q
uv run python -m pytest tests/guardrails/test_assistant_task_transition_source.py -q
```

Frontend:

```powershell
cd frontend
npm run test -- uiEvents
npm run test -- assistant-task-store
npm run test -- assistant-task-panels
npm run test:e2e -- assistant-task-graph
```

## Scenario Smoke Tests

### P1: Migration and cutover guard

1. Run v15/v16 migrations on a DB containing legacy `pending_assistant_tasks` and `workflow_transitions` rows.
2. Assert legacy background jobs remain available through the compatibility repository or renamed table.
3. Enable unified dispatch with the default clean-start guard, unless backfill was explicitly selected before implementation.
4. Assert API and React stores read task truth only from the task collaboration snapshot, not `workflow_transitions`.
5. Assert rollback can disable unified dispatch without deleting legacy audit rows.

### P1: Parallel observable graph

1. Start a controlled assistant run with one root request and three child tasks.
2. Two independent child tasks use fake executors with known delays.
3. Assert the graph snapshot contains all nodes and dependency edges.
4. Assert both independent attempts overlap and finish faster than serial baseline.
5. Assert UI events update node statuses before the final assistant message.

### P2: Crash recovery and adjudication

1. Create a running TaskAttempt with expired lease and no terminal result.
2. Simulate sidecar startup recovery.
3. Assert old attempt is `fenced`.
4. Assert Task becomes `suspended/waiting_system`.
5. If checkpoint is absent, assert parent adjudication is created.
6. Submit a late result with the old fence token and assert it is rejected without state mutation.

### P2: Idempotency and failure bridge

1. Create a side-effecting operation with `operation_key` before executing the effect.
2. Mark the operation completed and restart recovery.
3. Assert the dispatcher does not repeat the completed side effect.
4. Mark another operation `unsafe_to_retry` and assert recovery creates parent adjudication instead of automatic retry.
5. Fail a child task and assert no `assistant_run_failures` row is created until the root graph reaches terminal failure.
6. Attempt to create two non-failed operations with the same `(task_id, operation_key)` and assert the second write is rejected.
7. Submit a stale fenced result after a later successful attempt and assert no success UI event is emitted.

### P2: Stop current request graph

1. Create two active graphs in the same Assistant session.
2. Stop graph A with matching run id.
3. Assert only graph A tasks become `suspended/user_stop`.
4. Assert graph B remains running.
5. Continue graph A and assert attempts resume from checkpoint.

### P3: Agent-to-agent question route

1. Have a child executor call `ask_parent` with `kind=resource_request`.
2. Assert an `AssistantTaskQuestion` route is persisted and bounded by the parent's frozen capability scope.
3. Escalate a clarification to the user and restart the process before the user answers.
4. Assert the Task remains `suspended/waiting_user` and the clarification is reissued without a persisted raw answer.

### P3: Board claim and meeting channel

1. Create one open board task and race two claimers.
2. Assert exactly one claim succeeds.
3. Open a two-party meeting and send messages until conclusion.
4. Assert no participant receives extra tool authorization through the meeting.
5. Exhaust meeting budget and assert channel closes with parent adjudication.

### P4: Todo

1. Assign one long task to a specialist.
2. Create three Todo items, mark one `doing`, then `done`.
3. Restart service and reload todos.
4. Assert Todo states persist and do not appear as Task nodes or adjudication items.

### P4: Display projection and privacy

1. Create a running task with pending parent review.
2. Assert snapshot returns `displayPhase=reviewing`, `requiresReview=true` and a safe explanation.
3. Assert UI events and snapshots do not expose `TaskAttempt`, fence token, lease, local paths, raw tool output or internal adjudication terminology.
4. Assert Todo text and meeting messages do not enter brain memory or long-term assistant context outside the ordinary message/reference path.
5. Archive or delete the Assistant session and assert normal task graph/board/meeting/Todo APIs hide the rows through null/404 responses without revealing debug/audit retention.

### P4: UI states and event contract sync

1. Register backend task collaboration events and regenerate/update frontend event type definitions.
2. Assert backend event allowlists and frontend validators accept the same public payload fields.
3. Render empty graph, empty board, loading meeting, visible Todo, and resync-required states.
4. Assert keyboard focus remains on the relevant control after stop, continue, adjudication, claim, and Todo update actions.

## Broad Regression

```powershell
uv run python -m pytest tests/desktop_api tests/business/agents tests/data tests/guardrails -q
cd frontend
npm run lint
npm run test
```

## Current Verification Record

2026-06-17 final implementation checkpoint:

- Backend task-focused gate: `80 passed` with the combined targeted pytest command covering migration, repositories, state machine, dispatcher, recovery, adjudication, idempotency, questions, board, meetings, Todo, task APIs/events, contract sync, cutover, root failure bridge, 200-node graph snapshot smoke, orchestrator wiring and guardrails.
- Frontend task collaboration unit gate: `39 passed` for `assistant-task-store`, `assistant-task-panels`, and `ui-events`.
- Frontend full unit gate: `npm run test` passed with `264 passed` across 36 test files.
- Frontend E2E smoke: `assistant-task-graph` passed, including graph, board and Todo mock API paths.
- Frontend lint/build: `npm run lint` passed; `npm run build` passed with only the existing Vite chunk-size warning.
- Python formatting/lint: Black ran on changed Python task-collaboration paths; focused Flake8 over changed Python paths passed.
- Known warning noise: pytest still reports dependency deprecations from FastAPI TestClient, mitmproxy/pyparsing and ldap3/pyasn1; these are outside this feature.
