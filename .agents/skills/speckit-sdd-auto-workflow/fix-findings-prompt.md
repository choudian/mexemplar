# Fix Findings Prompt

Role: repair Spec Kit documents for approved findings.

Inputs:

- finding JSON array
- target document paths
- current stage

Allowed edits:

- Edit `spec.md`, `plan.md`, or `tasks.md` only.
- Do not edit source code.
- Do not repair high-risk `plan.md` findings about architecture, technology stack, data storage, or security. Mark those as requiring a plan rerun.

Procedure:

1. Group findings by target document and anchor.
2. Apply minimal document edits that satisfy each `suggested_fix`.
3. Preserve existing requirement IDs and task IDs when possible.
4. If a spec fix requires user input, add an explicit `NEEDS CLARIFICATION` marker and report it.
5. Keep changes consistent across repeated references within the edited document.
6. Return a short JSON summary. Do not include unrelated commentary.

Output schema:

```json
{
  "changed_files": ["spec.md"],
  "fixed_finding_keys": ["spec.md#FR-3|HIGH|auth requirements"],
  "requires_new_clarify": false,
  "requires_plan_rerun": false,
  "summary": "Added authentication requirement and updated the acceptance scenario."
}
```
