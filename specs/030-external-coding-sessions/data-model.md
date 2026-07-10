# Data Model: 外部 Coding Session

**Revision note (2026-07-10)**: Finalized after implementation. V1 only creates and applies `revert_commit`; other enum values remain reserved for forward compatibility and are rejected by the service.

## Entity: ExternalCodingSession

Durable owner-bound coding assignment.

| Field | Type | Notes |
|-------|------|-------|
| `coding_session_id` | TEXT PK | Generated id, prefix `ecs` |
| `session_id` | TEXT nullable | Assistant conversation scope when known |
| `owner_type` | TEXT | `task` or `workflow` |
| `owner_id` | TEXT | Task id or workflow id; required |
| `parent_session_id` | TEXT nullable | Dispatching assistant/subagent session |
| `tool` | TEXT | `claude_code` or `codex_cli`; immutable after create |
| `launch_mode` | TEXT | `headless` or `interactive` |
| `status` | TEXT | See lifecycle |
| `phase` | TEXT | `plan`, `implement`, `merge`, `rollback`, `done` |
| `selected_reason` | TEXT nullable | Safe selection rationale |
| `quota_state` | TEXT nullable | Last normalized quota state |
| `external_session_ref` | TEXT nullable | Claude/Codex session/thread id when available |
| `worktree_path` | TEXT | `.worktrees/coding/<id>` |
| `branch_name` | TEXT | `coding/<id>` |
| `base_commit` | TEXT nullable | Worktree creation HEAD; missing legacy values fail closed during plan checks |
| `target_branch` | TEXT nullable | Branch to merge into |
| `target_worktree_path` | TEXT nullable | Target worktree |
| `artifact_dir` | TEXT | `data/coding_sessions/<id>` |
| `handoff_path` | TEXT | `HANDOFF.md` |
| `plan_path` | TEXT nullable | `PLAN.md` |
| `result_path` | TEXT nullable | `RESULT.md` |
| `plan_approved_at` | TEXT nullable | ISO time |
| `plan_approved_by` | TEXT nullable | `agent` or `user` |
| `last_error_category` | TEXT nullable | Safe enum-like category |
| `last_error_message` | TEXT nullable | Redacted safe summary |
| `resume_count` | INTEGER | Incremented on resume |
| `review_recommended` | BOOLEAN | Defaults true |
| `review_skipped_reason` | TEXT nullable | Required if final summary skips review/test |
| `created_at` / `updated_at` / `completed_at` | TEXT | ISO timestamps |

Indexes:
- `(owner_type, owner_id, updated_at)`
- `(session_id, updated_at)`
- `(status, updated_at)`

Constraints:
- `tool IN ('claude_code', 'codex_cli')`
- `launch_mode IN ('headless', 'interactive')`
- `owner_type IN ('task', 'workflow')`
- status/phase check constraints match business enums

## Entity: ExternalCodingAttempt

One concrete process invocation or resume attempt.

| Field | Type | Notes |
|-------|------|-------|
| `attempt_id` | TEXT PK | Prefix `eca` |
| `coding_session_id` | TEXT indexed | No FK required; repository enforces |
| `phase` | TEXT | `plan` or `implement` |
| `launch_mode` | TEXT | Copied from session or override |
| `command_summary` | TEXT | Redacted executable + safe args summary |
| `external_session_ref` | TEXT nullable | Captured from CLI output if available |
| `status` | TEXT | `running`, `succeeded`, `interrupted`, `failed` |
| `pid` | INTEGER nullable | Runtime pid if managed |
| `exit_code` | INTEGER nullable | Process exit code |
| `started_at` / `finished_at` | TEXT | ISO timestamps |
| `log_path` | TEXT nullable | Bounded file artifact |
| `log_tail` | TEXT nullable | Redacted tail for quick display |
| `error_category` | TEXT nullable | `quota_exhausted`, `network`, `login_required`, `model_unavailable`, `missing_artifact`, `protocol_violation`, `process_error`, `unknown` |
| `error_message` | TEXT nullable | Safe summary |

## Entity: ExternalCodingQuotaObservation

Normalized quota signal.

| Field | Type | Notes |
|-------|------|-------|
| `observation_id` | TEXT PK | Prefix `ecq` |
| `tool` | TEXT | `claude_code` or `codex_cli` |
| `state` | TEXT | `available`, `low`, `exhausted`, `unknown` |
| `source` | TEXT | Safe source label, no path/token |
| `confidence` | REAL | `0.0` to `1.0` |
| `reset_at` | TEXT nullable | ISO time if known |
| `checked_at` | TEXT | ISO time |
| `safe_detail` | TEXT nullable | Redacted detail |

## Entity: ExternalCodingMergeRecord

Audit for applying a coding session branch back to target.

| Field | Type | Notes |
|-------|------|-------|
| `merge_record_id` | TEXT PK | Prefix `ecm` |
| `coding_session_id` | TEXT indexed | Session id |
| `target_branch` | TEXT | Target branch |
| `target_worktree_path` | TEXT | Target worktree |
| `pre_merge_head` | TEXT | Commit hash before merge |
| `coding_branch_head` | TEXT | Coding branch head |
| `dirty_files_json` | TEXT | Target dirty files |
| `changed_files_json` | TEXT | Coding branch changes |
| `overlap_files_json` | TEXT | Dirty/change overlap |
| `conflict_risk` | TEXT | `low`, `overlap`, `conflict_predicted`, `unknown` |
| `agent_decision` | TEXT nullable | Safe裁定摘要 |
| `status` | TEXT | `analysis_ready`, `merged`, `blocked`, `failed`, `rolled_back` |
| `merge_commit` | TEXT nullable | Commit hash if merge creates one |
| `error` | TEXT nullable | Safe error summary |
| `created_at` / `merged_at` | TEXT nullable | ISO timestamps |

## Entity: ExternalCodingRollbackDecision

Audit for guided rollback choice.

| Field | Type | Notes |
|-------|------|-------|
| `rollback_id` | TEXT PK | Prefix `ecr` |
| `coding_session_id` | TEXT indexed | Session id |
| `merge_record_id` | TEXT nullable | Related merge |
| `intent_summary` | TEXT | Safe user/agent intent summary |
| `chosen_strategy` | TEXT | Enum reserves `revert_commit`, `reverse_patch`, `reset_hard`, `manual`; V1 service only creates/applies `revert_commit` |
| `requires_confirmation` | BOOLEAN | True for history-changing/high-risk |
| `confirmed_by` | TEXT nullable | `agent` or `user` |
| `status` | TEXT | `proposed`, `applied`, `blocked`, `failed` |
| `created_at` / `applied_at` | TEXT nullable | ISO timestamps |

## Lifecycle

```text
created
  -> planning
  -> plan_ready
  -> plan_approved | plan_rejected
  -> implementing
  -> completed
  -> merge_ready
  -> merged
```

Interruptions may occur from `planning` or `implementing`:

```text
planning/implementing -> interrupted -> planning/implementing
interrupted -> waiting_user
interrupted -> abandoned
```

Failure and protocol states:

```text
planning -> interrupted(protocol_violation) when worktree changed before PLAN approval
implementing -> interrupted(missing_artifact) when process exits without valid RESULT.md
any active state -> failed for unrecoverable internal errors
any non-merged state -> abandoned by agent/user
merged -> rollback_proposed -> rolled_back
```

Invariants:
- `tool` is immutable for a session.
- `owner_type` + `owner_id` must be present at create time.
- `completed` requires valid `RESULT.md`.
- `merged` requires a merge record with `status='merged'`.
- V1 rollback requires a clean recorded target, exact eligible merge commit and successful `git revert`; all non-`revert_commit` strategies fail closed.
- Raw credentials and raw quota endpoint responses are never fields in these entities.
