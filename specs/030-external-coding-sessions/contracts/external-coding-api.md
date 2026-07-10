# API Contract: External Coding Sessions

Base prefix: `/api/external-coding`

All endpoints require the existing desktop session header. Errors use existing `ErrorResponse` shape.

## Models

### ExternalCodingSessionSummary

```json
{
  "codingSessionId": "ecs_123",
  "sessionId": "sess_1",
  "ownerType": "task",
  "ownerId": "tsk_1",
  "tool": "claude_code",
  "launchMode": "headless",
  "status": "plan_ready",
  "phase": "plan",
  "selectedReason": "Claude quota available; Codex quota exhausted",
  "quotaState": "available",
  "worktreePath": ".worktrees/coding/ecs_123",
  "branchName": "coding/ecs_123",
  "artifactDir": "data/coding_sessions/ecs_123",
  "planPreview": "Target restatement...",
  "resultPreview": null,
  "logTail": "last safe lines",
  "lastErrorCategory": null,
  "lastErrorMessage": null,
  "resumeCount": 0,
  "createdAt": "2026-07-09T10:00:00Z",
  "updatedAt": "2026-07-09T10:05:00Z",
  "completedAt": null
}
```

### ExternalCodingSessionDetail

Extends summary with:

```json
{
  "attempts": [],
  "quota": [],
  "mergeRecords": [],
  "rollbackDecisions": [],
  "availableActions": ["approve_plan", "reject_plan", "resume", "abandon"],
  "artifacts": {
    "handoff": {"path": "data/coding_sessions/ecs_123/HANDOFF.md", "preview": "..."},
    "plan": {"path": "data/coding_sessions/ecs_123/PLAN.md", "preview": "..."},
    "result": null
  }
}
```

## Endpoints

### POST `/sessions`

Create and start a plan-before-code session.

Request:

```json
{
  "sessionId": "sess_1",
  "ownerType": "task",
  "ownerId": "tsk_1",
  "objective": "Implement X",
  "context": "Relevant constraints",
  "toolPreference": "auto",
  "launchMode": "headless",
  "targetBranch": "030-external-coding-sessions",
  "targetWorktreePath": "E:/code/Exemplar/.worktrees/030-external-coding-sessions",
  "explicitExhaustedOverride": false
}
```

Response: `ExternalCodingSessionDetail`

Rules:
- `ownerType` and `ownerId` are required.
- `toolPreference` is `auto | claude_code | codex_cli`.
- If the explicitly selected tool is exhausted, API returns `409` unless
  `explicitExhaustedOverride` is `true`.

### GET `/sessions`

Query sessions by owner/session.

Query params:
- `sessionId`
- `ownerType`
- `ownerId`
- `status`
- `limit` default 20, max 100

Response:

```json
{"items": []}
```

### GET `/sessions/{codingSessionId}`

Return `ExternalCodingSessionDetail`.

### POST `/sessions/{codingSessionId}/refresh`

Inspect filesystem/process state and update status from artifacts/logs.

Response: `ExternalCodingSessionDetail`

### POST `/sessions/{codingSessionId}/plan-decision`

Request:

```json
{
  "decision": "approved",
  "decidedBy": "agent",
  "feedback": "Proceed. Keep API shape stable."
}
```

`decision`: `approved | rejected | clarification_requested`

Response: `ExternalCodingSessionDetail`

### POST `/sessions/{codingSessionId}/resume`

Resume an interrupted or approved session under the same fixed tool.

Request:

```json
{
  "instruction": "Continue from the approved plan and update RESULT.md.",
  "phase": "implement"
}
```

Response: `ExternalCodingSessionDetail`

### POST `/sessions/{codingSessionId}/abandon`

Request:

```json
{"reason": "Plan diverged from task objective."}
```

Response: `ExternalCodingSessionDetail`

### POST `/sessions/{codingSessionId}/review-outcome`

Record the dispatching agent's independent review/test result after external
completion.

Request:

```json
{
  "independentlyReviewed": true,
  "independentlyTested": false,
  "skippedReason": "Integration environment was unavailable."
}
```

If both checks are true, the response clears `reviewRecommended` and
`reviewSkippedReason`. If either is false, `skippedReason` is required and is
kept in the detail/final-reporting projection.

Response: `ExternalCodingSessionDetail`

### POST `/sessions/{codingSessionId}/escalate-to-user`

Move an interrupted session to `waiting_user` when the owning agent cannot
resolve the problem safely.

Request:

```json
{"reason": "The target branch has unrelated dirty changes."}
```

Response: `ExternalCodingSessionDetail`

### POST `/sessions/{codingSessionId}/merge-analysis`

Compute dirty/conflict risk without merging.

Request:

```json
{
  "targetBranch": "main",
  "targetWorktreePath": "E:/code/Exemplar"
}
```

Response:

```json
{
  "mergeRecordId": "ecm_123",
  "conflictRisk": "low",
  "dirtyFiles": [],
  "changedFiles": ["src/foo.py"],
  "overlapFiles": [],
  "preMergeHead": "abc123",
  "codingBranchHead": "def456",
  "status": "analysis_ready"
}
```

### POST `/sessions/{codingSessionId}/merge`

Apply merge if existing analysis is low risk or caller records an explicit agent裁定.

Request:

```json
{
  "mergeRecordId": "ecm_123",
  "agentDecision": "No dirty overlap; proceed."
}
```

Response: merge record.

### POST `/sessions/{codingSessionId}/rollback-plan`

Create a guided rollback proposal; does not apply risky actions.

Request:

```json
{
  "intentSummary": "User wants to undo this coding session only."
}
```

Response:

```json
{
  "rollbackId": "ecr_123",
  "codingSessionId": "ecs_123",
  "chosenStrategy": "revert_commit",
  "requiresConfirmation": true,
  "status": "proposed",
  "safeExplanation": "This will create a reverting commit for merge ecm_123."
}
```

### POST `/sessions/{codingSessionId}/confirm-rollback`

Apply a previously proposed rollback after explicit confirmation.

Request:

```json
{
  "rollbackId": "ecr_123",
  "confirmedBy": "agent"
}
```

Response: rollback decision with `status="applied"` and a path-redacted
`safeExplanation`. A stale, unsafe, or already-applied proposal is rejected.

## Public UI Event

Internal blinker event: `external_coding_session_changed`

Public type: `assistant.external_coding.changed`

Payload allowlist:

```json
{
  "codingSessionId": "ecs_123",
  "sessionId": "sess_1",
  "ownerType": "task",
  "ownerId": "tsk_1",
  "tool": "claude_code",
  "status": "plan_ready",
  "phase": "plan",
  "changeType": "plan_ready",
  "updatedAt": "2026-07-09T10:05:00Z"
}
```

No artifact body, raw logs, credential values, account ids or raw quota responses may appear in this event.

`changeType` is one of `created`, `start_failed`, `plan_ready`,
`plan_approved`, `plan_rejected`, `resumed`, `waiting_user`, `abandoned`,
`merge_analysis`, `merge_failed`, `merged`, `rollback_proposed`, `rolled_back`,
`rollback_failed`, `protocol_violation`, `plan_invalid`, `result_invalid`, `review_recorded`,
`missing_artifact`, or `completed`.
