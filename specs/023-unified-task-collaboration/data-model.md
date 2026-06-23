# Data Model: 统一任务模型 + 多范式协作

## Enums

### TaskStatus

| Value | User meaning | Terminal |
|-------|--------------|----------|
| `pending_dispatch` | 待派/待认领 | No |
| `running` | 进行中 | No |
| `suspended` | 挂起 | No |
| `completed` | 完成 | Yes |
| `failed` | 失败 | Yes |
| `cancelled` | 取消 | Yes |

`awaiting_adjudication` is not a Task status. It is represented by `assistant_task_adjudications.status='pending'`.
While an item is pending parent-side adjudication, the Task remains `running` but has no active attempt. It moves to `completed`, `pending_dispatch`, or `failed` only after the parent decision.

### SuspendReason

| Value | Wake source |
|-------|-------------|
| `waiting_user` | user clarification/event; pending answer itself is not persisted |
| `waiting_system` | automatic retry when recoverable, except quota/billing can require explicit continue or TTL/budget |
| `user_stop` | explicit user continue |

### TaskEdgeType

`dependency`, `delegation`, `question`, `meeting_channel`, `resource_request`

### TaskQuestionKind

`clarification`, `resource_request`, `capability_request`

### TaskQuestionStatus

`open`, `escalated_to_parent`, `escalated_to_user`, `answered`, `cancelled`, `expired`

### AttemptStatus

`starting`, `running`, `succeeded`, `paused`, `failed`, `cancelled`, `fenced`

### OperationStatus

`planned`, `in_progress`, `completed`, `failed`, `unsafe_to_retry`

### AdjudicationDecision

`accepted`, `returned`, `abandoned`

### TodoStatus

`todo`, `doing`, `done`, `skipped`

## Entities

## AssistantTask

Authoritative durable work item for Assistant collaboration.

| Field | Type | Rules |
|-------|------|-------|
| task_id | string PK | Stable `tsk_*` id |
| graph_id | string indexed | One user request derived graph |
| root_task_id | string nullable indexed | Null for graph root |
| parent_task_id | string nullable indexed | Parent delegation owner |
| session_id | string indexed | Parent Assistant session |
| user_message_sequence | integer nullable | Root user message that created the graph |
| title | text | Sanitized display title |
| description | text | Full task description; UI/event projections must redact |
| status | TaskStatus | Six executor-side states only |
| suspend_reason | SuspendReason nullable | Required when status=`suspended` |
| assignee_type | string nullable | `ephemeral_subagent`, `specialist`, or null for board |
| assignee_id | string nullable | session/specialist id, null for open board |
| owner_session_id | string nullable |派活方/裁定方 session |
| capability_scope | JSON text nullable | Frozen allowed tool ids/methodology ids for this task |
| graph_version | integer | Monotonic fence for cancel/replan races |
| task_version | integer | Optimistic concurrency for claim/update |
| created_at / updated_at | datetime | Managed by Repository |
| completed_at / failed_at / cancelled_at | datetime nullable | Terminal timestamps |

Validation:

- `status='suspended'` requires `suspend_reason`.
- Terminal tasks cannot return to non-terminal states. A `returned` adjudication is only valid while the Task is still `running` with a pending adjudication; it sets the Task back to `pending_dispatch` with new instructions.
- `cancelled` is terminal and must not be revived by replan.
- Main Assistant may own and coordinate root tasks through `owner_session_id`, but it must not be an executor for user-work TaskAttempts.

DTO projections:

- `display_phase` is a snapshot/event projection only, not a DB/ORM column. It is derived from Task status plus attempt/adjudication/Todo context; example values include `running`, `reviewing`, `needs_attention`, `paused`, and `done`.
- `requires_review` and `safe_explanation` are likewise projection fields and must not leak fence, lease, attempt, or internal adjudication terminology.

## AssistantTaskEdge

Typed graph relation.

| Field | Type | Rules |
|-------|------|-------|
| edge_id | string PK | Stable id |
| graph_id | string indexed | Same graph as source/target |
| source_task_id | string indexed | Existing task |
| target_task_id | string indexed | Existing task |
| edge_type | TaskEdgeType | Closed enum |
| propagation | string | `blocking`, `cancel_cascade`, `message_only`, `none` |
| created_at | datetime | |

Validation:

- `dependency` edges cannot create cycles.
- `delegation` respects hub + one-level extension topology.
- `meeting_channel` edges are message-only and must not change capability scope.
- `resource_request` edges cannot grant capability by themselves; grants are stored in persisted question/resource request resolution and bounded by parent capability scope.

## AssistantTaskQuestion

Persisted agent-to-agent question, resource request, or capability request route. User-facing pending clarification cards and user answers remain process memory only.

| Field | Type | Rules |
|-------|------|-------|
| question_id | string PK | Stable `qst_*` id |
| graph_id | string indexed | |
| task_id | string indexed | Asking task |
| parent_task_id | string nullable indexed | Parent or supervisor task |
| asker_type / asker_id | string | Executor asking |
| recipient_type / recipient_id | string nullable | Parent executor or null while escalating |
| kind | TaskQuestionKind | Closed enum |
| status | TaskQuestionStatus | Closed enum |
| question_text | text | Persisted for agent-to-agent routing; public projection redacts |
| safe_answer_summary | text nullable | Agent-to-agent answer summary only; no raw user answer |
| capability_delta | JSON text nullable | Granted subset, must be within parent capability scope |
| escalated_to_user | boolean | True when the next hop is the in-memory user clarification mechanism |
| user_request_id | string nullable | Process-local clarification id; invalid across restart |
| expires_at | datetime nullable | |
| created_at / updated_at | datetime | |
| resolved_at | datetime nullable | |

Validation:

- `escalated_to_user=true` must not persist the user's pending answer or final raw answer.
- On restart with `status='escalated_to_user'`, the Task stays `suspended/waiting_user` and a new user clarification must be issued when interaction resumes.
- Capability grants must be a subset of the parent Task's frozen `capability_scope`.

## AssistantTaskAttempt

One runtime execution of a Task.

| Field | Type | Rules |
|-------|------|-------|
| attempt_id | string PK | Stable `att_*` id |
| task_id | string indexed | Parent Task |
| executor_type | string | `ephemeral_subagent` or `specialist`; main Assistant is coordinator only |
| executor_id | string | session or specialist id |
| status | AttemptStatus | Closed enum |
| lease_owner | string | sidecar process/run id |
| lease_expires_at | datetime indexed | Recovery scan boundary |
| heartbeat_at | datetime nullable | Updated during long work |
| fence_token | integer | Monotonic token; late results with old token rejected |
| checkpoint_ref | text nullable | Repository-owned checkpoint/idempotency marker |
| result_ref | text nullable | Safe result summary/reference |
| error_category | text nullable | Safe category only |
| created_at / updated_at | datetime | |
| started_at / finished_at | datetime nullable | |

Validation:

- At most one active attempt per Task (`starting/running/paused`) unless the older one is fenced.
- Restart recovery fences expired active attempts and changes Task to `suspended/waiting_system`; if no checkpoint is usable, creates a pending adjudication for the parent.
- Result completion must match current `fence_token`.
- Active attempts are not allowed for main Assistant/coordinator owner rows.

## AssistantTaskOperation

Idempotency record for side-effecting steps inside a TaskAttempt.

| Field | Type | Rules |
|-------|------|-------|
| operation_id | string PK | Stable `op_*` id |
| task_id | string indexed | |
| attempt_id | string indexed | |
| operation_key | string | Stable semantic key for the side effect |
| operation_type | string | e.g. `tool_call`, `file_write`, `external_action`, `message_send` |
| idempotency_scope | string | `task`, `graph`, `external`, `unknown` |
| status | OperationStatus | Closed enum |
| safe_summary | text | Redacted projection |
| result_ref | text nullable | Private result reference |
| created_at / updated_at | datetime | |
| completed_at | datetime nullable | |

Validation:

- `(task_id, operation_key)` must be unique for non-`failed` operations.
- Side-effecting execution must write `planned` or `in_progress` before the effect and `completed` after success.
- Recovery may retry only when the operation is `completed` with idempotent semantics or the operation is still pre-effect.
- `unknown` idempotency scope or `unsafe_to_retry` forces parent adjudication instead of automatic retry.

## AssistantTaskAdjudication

Parent-side pending decision item.

| Field | Type | Rules |
|-------|------|-------|
| adjudication_id | string PK | |
| task_id | string indexed | Delivered/stuck Task |
| graph_id | string indexed | |
| parent_session_id | string indexed | Decision owner |
| status | string | `pending`, `decided` |
| delivered_status | string | `done`, `stuck`, `failed_input` |
| safe_summary | text | Redacted result/stuck reason |
| raw_result_ref | text nullable | Private reference, not UI payload |
| decision | AdjudicationDecision nullable | Set once |
| instruction | text nullable | Required for `returned` |
| decided_by | string nullable | `agent` or `user` |
| created_at / decided_at | datetime nullable | |

Validation:

- One pending adjudication per Task.
- `returned` reopens Task with instruction and increments task version.
- `abandoned` marks Task failed and cascades cancel to its children. The parent (adjudicator) already knows about the decision since it made it; if the child failure makes the parent task also unable to complete, the failure propagates up the delegation chain through the parent's own adjudication path, ultimately bridging to a run-level failure at the root.

## AssistantTaskClaim

Board/assignment lease and rejection history.

| Field | Type | Rules |
|-------|------|-------|
| claim_id | string PK | |
| task_id | string indexed | Open or claimed Task |
| claimer_type | string | executor type |
| claimer_id | string | executor id |
| status | string | `claimed`, `released`, `rejected`, `completed`, `expired` |
| lease_expires_at | datetime nullable | Required for `claimed` |
| reject_reason | text nullable | Safe short reason |
| task_version | integer | Version observed at claim |
| created_at / updated_at | datetime | |

Validation:

- Claim is atomic: task must still have null assignee and matching task_version.
- Prior `rejected` claimers are excluded from automatic reassignment unless parent overrides.

## AssistantMeetingChannel

Supervised direct channel for two executors.

| Field | Type | Rules |
|-------|------|-------|
| channel_id | string PK | |
| graph_id | string indexed | |
| parent_task_id | string indexed | Owning task |
| supervisor_session_id | string indexed | Parent who can inspect |
| participant_a_type / participant_a_id | string | |
| participant_b_type / participant_b_id | string | |
| status | string | `open`, `concluded`, `closed_timeout`, `closed_abandoned` |
| turn_budget | integer | From config |
| time_budget_seconds | integer | From config |
| turns_used | integer | |
| conclusion | text nullable | Required for `concluded` |
| created_at / closed_at | datetime nullable | |

Validation:

- Exactly two participants.
- Messages only; no tool proxying or capability changes.
- Exceeding budget or detected mutual wait closes channel and creates parent adjudication.

## AssistantMeetingMessage

| Field | Type | Rules |
|-------|------|-------|
| message_id | string PK | |
| channel_id | string indexed | |
| sender_type / sender_id | string | Must be participant |
| content | text | Sanitized before public projection |
| sequence | integer | Monotonic per channel |
| created_at | datetime | |

## AssistantTodoItem

Private checklist for one executor's assigned Task.

| Field | Type | Rules |
|-------|------|-------|
| todo_id | string PK | |
| task_id | string indexed | Owning Task |
| executor_type | string | `ephemeral_subagent` or `specialist`; no main Assistant Todo ownership |
| executor_id | string | |
| text | text | Safe projection required |
| status | TodoStatus | Does not share TaskStatus |
| sort_order | integer | Stable display order |
| created_at / updated_at | datetime | |
| completed_at | datetime nullable | |

Validation:

- Todo does not create Task edges, adjudication items, or board claims.
- Todo is session-level persistence and must not feed brain distillation as memory.

## Index Requirements

The v15/v16 migrations must create indexes that support local snapshot, recovery, and active-attempt capacity targets. v15 creates the task collaboration tables and regular indexes; v16 adds the active TaskAttempt partial unique indexes:

- `assistant_tasks(graph_id, status)`
- `assistant_tasks(graph_id, parent_task_id)`
- `assistant_tasks(session_id, user_message_sequence)`
- `assistant_tasks(graph_id, task_version)`
- `assistant_task_edges(graph_id, source_task_id)`
- `assistant_task_edges(graph_id, target_task_id)`
- `assistant_task_attempts(task_id, status)`
- `assistant_task_attempts(status, lease_expires_at)`
- `assistant_task_attempts(task_id)` unique where status in `starting/running`
- `assistant_task_attempts(executor_type, executor_id)` unique where status in `starting/running`

> **Design note**: `paused` is intentionally excluded from the active-attempt partial unique indexes. When an attempt is paused, the executor slot is released—another attempt may start on the same task or executor (e.g., resume creates a new attempt). Including `paused` would prevent capacity=1 from being released on pause, contradicting the intended semantics.
- `assistant_task_operations(task_id, operation_key)`
- `assistant_task_adjudications(task_id, status)`
- `assistant_task_adjudications(parent_session_id, status)`
- `assistant_task_claims(task_id, status)`
- `assistant_task_claims(status, lease_expires_at)`
- `assistant_task_questions(task_id, status)`
- `assistant_task_questions(graph_id, status)`
- `assistant_task_questions(status, expires_at)`
- `assistant_meeting_messages(channel_id, sequence)`
- `assistant_todo_items(task_id, sort_order)`

## State Transitions

### Task

```text
pending_dispatch -> running
pending_dispatch -> cancelled
running -> suspended
running -> pending_dispatch  # returned adjudication
running -> completed         # accepted adjudication
running -> failed            # abandoned adjudication or unrecoverable graph failure
running -> cancelled
suspended -> running
suspended -> cancelled
completed -> [terminal]
failed -> [terminal]
cancelled -> [terminal]
```

### Attempt Recovery

```text
running lease expired on startup
  -> attempt=fenced
  -> task=suspended(waiting_system)
  -> if checkpoint missing: create adjudication(delivered_status=stuck)

late result for fenced token
  -> reject idempotently
  -> no task mutation
```

### Question / Resource Request

```text
open -> escalated_to_parent
open -> answered
escalated_to_parent -> escalated_to_user
escalated_to_parent -> answered
escalated_to_user -> answered       # answer summary only; raw user answer stays process-local
escalated_to_user -> expired        # restart/timeout/cancel; task remains suspended(waiting_user)
open/escalated_to_parent -> cancelled
```

### Side-Effect Operation

```text
planned -> in_progress
in_progress -> completed
in_progress -> failed
in_progress -> unsafe_to_retry
unsafe_to_retry -> [parent adjudication required]
completed -> [stable idempotency marker]
```

### Stop vs Cancel

- Stop: current user request graph only; active attempts receive cooperative stop and tasks become `suspended/user_stop`.
- Continue: resumes `suspended/user_stop` tasks in that graph.
- Cancel: terminal cascade from abandoned direction; cancelled downstream tasks are never revived by replan.
