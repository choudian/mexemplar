# Contracts: Assistant Task Collaboration

All routes require the existing sidecar runtime token and live under the Python sidecar. Routers are adapters only; they call business services and never access repositories directly.

## REST Snapshots and Commands

### GET `/api/assistant/sessions/{sessionId}/task-graphs/{graphId}`

Returns the authoritative graph snapshot for resync and initial render.

```json
{
  "graphId": "tg_123",
  "sessionId": "ast_1",
  "userMessageSequence": 12,
  "version": 7,
  "tasks": [
    {
      "taskId": "tsk_1",
      "parentTaskId": null,
      "title": "整理报销",
      "descriptionPreview": "整理本月报销...",
      "status": "running",
      "displayPhase": "reviewing",
      "requiresReview": true,
      "safeExplanation": "等待上级检查结果",
      "suspendReason": null,
      "assignee": { "type": "specialist", "id": "sp_1", "label": "财务专员" },
      "adjudicationId": null,
      "updatedAt": "2026-06-17T12:00:00Z"
    }
  ],
  "edges": [
    { "sourceTaskId": "tsk_1", "targetTaskId": "tsk_2", "type": "dependency" }
  ],
  "adjudications": []
}
```

Safety:

- `descriptionPreview`, labels, summaries and errors are redacted projections.
- `displayPhase`, `requiresReview` and `safeExplanation` are derived UI projections; they do not add Task states and must not expose internal adjudication, attempt, fence or lease terminology.
- No raw provider error, stack trace, API key, runtime token, full command, full code, local DB path, or raw tool output appears.

### GET `/api/assistant/sessions/{sessionId}/task-graphs/current`

Returns the graph for the current active user request, or `{ "graph": null }` if none exists. Used by Assistant screen resync.

### POST `/api/assistant/sessions/{sessionId}/task-graphs/{graphId}/stop`

Stops the current user request graph, not the whole session.

Request:

```json
{ "runId": "optional-current-run-id" }
```

Response:

```json
{ "accepted": true, "graphId": "tg_123", "affectedTaskCount": 4 }
```

Semantics:

- Cooperative stop at safe points.
- Matching tasks become `suspended` with `suspendReason=user_stop`.
- Other sessions or unrelated request graphs are untouched.

### POST `/api/assistant/sessions/{sessionId}/task-graphs/{graphId}/continue`

Resumes tasks suspended by `user_stop` in the graph.

Response:

```json
{ "accepted": true, "graphId": "tg_123", "resumedTaskCount": 4 }
```

### POST `/api/assistant/sessions/{sessionId}/task-adjudications/{adjudicationId}/decision`

Used for explicit user intervention only; normal parent-side adjudication is agent-driven.

Request:

```json
{
  "decision": "accepted",
  "instruction": ""
}
```

`decision` is one of `accepted`, `returned`, `abandoned`. `instruction` is required for `returned`.

### GET `/api/assistant/sessions/{sessionId}/task-board`

Returns open/claimed board tasks relevant to the session.

```json
{
  "items": [
    {
      "taskId": "tsk_9",
      "graphId": "tg_123",
      "title": "核对发票",
      "status": "pending_dispatch",
      "claimStatus": "open",
      "assignee": null,
      "updatedAt": "2026-06-17T12:00:00Z"
    }
  ]
}
```

### GET `/api/assistant/sessions/{sessionId}/meetings/{channelId}?afterSequence=&limit=`

Returns a supervised meeting transcript projection.

```json
{
  "channelId": "mtg_1",
  "status": "open",
  "participants": [
    { "type": "specialist", "id": "sp_a", "label": "专员 A" },
    { "type": "specialist", "id": "sp_b", "label": "专员 B" }
  ],
  "turnsUsed": 3,
  "turnBudget": 12,
  "messages": [
    { "sequence": 1, "senderId": "sp_a", "content": "需要确认字段含义", "createdAt": "2026-06-17T12:00:00Z" }
  ],
  "nextAfterSequence": null,
  "conclusion": null
}
```

`limit` defaults to 50 and is capped by unified config. Messages are sorted by stable `sequence`.

### GET `/api/assistant/sessions/{sessionId}/tasks/{taskId}/todos`

Returns private checklist items for one assigned Task.

```json
{
  "taskId": "tsk_1",
  "items": [
    { "todoId": "todo_1", "text": "收集发票", "status": "done", "sortOrder": 1 }
  ]
}
```

## Public UI Events

All events are registered in `src/desktop_api/ui_events.py` and projected through `src/desktop_api/ui_event_projector.py`.

### `assistant.task_graph.changed`

Required payload keys: `graphId`, `changeType`.

Allowed payload:

```json
{
  "graphId": "tg_123",
  "taskId": "tsk_1",
  "changeType": "task_updated",
  "status": "running",
  "displayPhase": "reviewing",
  "requiresReview": true,
  "safeExplanation": "等待上级检查结果",
  "suspendReason": null,
  "sequence": 42
}
```

`changeType`: `graph_created`, `task_created`, `task_updated`, `edge_created`, `adjudication_created`, `adjudication_decided`, `graph_completed`

### `assistant.task_board.changed`

Required payload keys: `taskId`, `changeType`.

`changeType`: `opened`, `claimed`, `released`, `expired`, `completed`, `rejected`

### `assistant.meeting.changed`

Required payload keys: `channelId`, `changeType`.

`changeType`: `opened`, `message_added`, `concluded`, `closed_timeout`, `closed_abandoned`

### `assistant.todo.changed`

Required payload keys: `taskId`, `todoId`, `changeType`.

`changeType`: `created`, `updated`, `deleted`, `reordered`

## Agent Tool Contracts

These tools are normal AgentLoop tool calls. They are side-effecting and must not be marked `is_concurrency_safe`.

### `delegate_task`

Directed delegation or open board placement.

Input:

```json
{
  "task": "整理报销单",
  "context": "用户希望邮件给财务",
  "assignee": { "type": "specialist", "id": "sp_finance" },
  "dependencies": ["tsk_prev"],
  "toolWhitelist": ["search_tools"]
}
```

Open board task uses `"assignee": null`.

Output:

```json
{
  "accepted": true,
  "taskId": "tsk_1",
  "graphId": "tg_123",
  "assignment": "directed"
}
```

### `ask_parent`

Executor asks its parent to clarify goals or request a resource/capability.

Input:

```json
{
  "taskId": "tsk_1",
  "question": "发票按日期还是金额排序？",
  "kind": "clarification"
}
```

`kind` is one of `clarification`, `resource_request`, `capability_request`.

If the question reaches the user, the existing user clarification mechanism is used; pending user answers are not persisted. Persisted `AssistantTaskQuestion` rows store routing state and safe answer summaries for agent-to-agent hops only.

### `open_meeting_channel`

Supervisor opens a message-only two-party channel.

Input:

```json
{
  "taskId": "tsk_parent",
  "participantA": { "type": "specialist", "id": "sp_a" },
  "participantB": { "type": "specialist", "id": "sp_b" },
  "goal": "对齐字段含义"
}
```

Output includes `channelId`, `turnBudget`, `timeBudgetSeconds`.

### `meeting_send_message`

Input:

```json
{
  "channelId": "mtg_1",
  "content": "我建议按日期排序。",
  "conclusion": ""
}
```

When `conclusion` is non-empty, channel can move to `concluded`.

### `todo_update`

Input:

```json
{
  "taskId": "tsk_1",
  "items": [
    { "todoId": "todo_1", "text": "收集发票", "status": "done", "sortOrder": 1 }
  ]
}
```

Todo statuses are independent from Task statuses.

## Failure and Resync Rules

- `backend.resync_required` domains include `assistant_tasks`, `assistant_task_board`, `assistant_meetings` and `assistant_todos`; unknown task-collaboration domains fall back to the current graph snapshot.
- Root graph terminal failure is the only task-collaboration condition that may create or update `assistant_run_failures`; partial task failures remain graph-local and surface through adjudication or task snapshot state.
- Archived or deleted Assistant sessions are outside normal task API scope: current graph returns null or endpoints return 404 without leaking whether task collaboration rows still exist for debug/audit.
- API 404 for a graph/task/adjudication means the item is not in the session scope or no longer available; it must not leak existence across sessions.
- Late attempt completion with a fenced token is accepted as an idempotent no-op by business service and does not emit a success UI event.
