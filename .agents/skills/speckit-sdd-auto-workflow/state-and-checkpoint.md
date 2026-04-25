# State And Checkpoint Protocol

State file: `FEATURE_DIR/.sdd-state.json`

Example:

```json
{
  "feature_id": "003-user-auth",
  "current_stage": "A",
  "counters": { "a": 0, "b": 0, "c": 0, "d": 0, "total": 0 },
  "extra_quotas": { "a": 0, "b": 0, "c": 0, "d": 0, "total": 0 },
  "stale_files": [],
  "known_issues": [],
  "deferred_path": "specs/003-user-auth/deferred-clarifications.md",
  "gate_passes": 0,
  "project_type": null,
  "checklist_dimensions": ["completeness", "clarity", "consistency", "security"],
  "overflow_warnings": [],
  "constitution_hash": "",
  "last_checkpoint": "stage:A:start",
  "rollback_counts": {}
}
```

Counter definitions:

- `a`: increment after one Stage A checklist plus fix round. Clarify subrounds do not count.
- `b`: increment after one Stage B checklist plus fix round. Plan reruns do not count.
- `c`: increment after one Stage C checklist plus analyze plus fix round.
- `d`: increment after one Stage D review plus fix round. Hard-gate test/fix retries do not count.
- `total`: `a + b + c + d`.

Base limits:

- `a <= 10`
- `b <= 10`
- `c <= 10`
- `d <= 5`
- `total <= 30`

Extra quota:

- When a limit is hit, pause with reason, counters, and remaining findings.
- If the user chooses continue, add 5 to that stage quota and 5 to total quota.
- A stage can receive at most two quota extensions.
- If the user chooses abandon, stop and archive current artifacts.

Checkpoints:

- Save after each completed sub-step:
  - `stage:A:clarify-done`
  - `stage:A:checklist:<dimension>`
  - `stage:A:fix-done`
  - `stage:B:plan-done`
  - `stage:B:decision-review-done`
  - `stage:C:analyze-done`
  - `stage:GATE:approved`
  - `stage:D:hard-gate-done`
  - `stage:D:review-done`
- If multiple review passes are delegated, include a stable pass number such as `stage:D:review:security`.
- On resume, compare current git diff and document hashes with the checkpoint snapshot when available.
- If there are manual edits, rerun the current stage review/fan-out. Do not rerun earlier stages unless the edit changed their inputs.

Rollback rules:

- Return to Stage A: archive `plan.md` and `tasks.md` to `.history/rollback-<n>/` and mark them stale.
- Return to Stage B: archive `tasks.md` to `.history/rollback-<n>/` and mark it stale.
- Return to Stage C from Stage D: keep code, but require a new final gate before further implementation changes.
- Counters do not reset on rollback.
- If one finding key triggers rollback more than 2 times, pause and ask the user.
- If constitution hash changes after a stage exits, mark downstream artifacts stale and ask whether to return to Stage A.
