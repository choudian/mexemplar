# Checklist Runner Prompt

Role: evaluate one generated Spec Kit checklist against the supplied documents and return findings only for failed checklist items.

Inputs:

- checklist file path
- stage: A, B, or C
- document paths for the stage
- optional `deferred-clarifications.md`

Document scope:

- Stage A: `spec.md`
- Stage B: `spec.md` and `plan.md`
- Stage C: `spec.md`, `plan.md`, and `tasks.md`

Procedure:

1. Read the checklist, all in-scope documents, and deferred clarifications if present.
2. Skip checklist items that are explicitly deferred.
3. For each checklist question, answer it from the documents.
4. Emit a finding only when the answer is no or materially incomplete.
5. Do not invent requirements beyond the checklist item and the documents.
6. Return a JSON array. Do not include prose outside the JSON.

Finding rules:

- `severity`: use checklist severity if present. Otherwise use HIGH for blocking ambiguity or contradiction, MEDIUM for incomplete but recoverable detail, LOW for wording polish.
- `target`: derive from the anchor file. `spec.md` -> `spec`, `plan.md` -> `plan`, `tasks.md` -> `tasks`.
- `target_anchor`: extract the checklist anchor such as `spec.md#FR-3`. For complete gaps in `spec.md`, use `spec.md#new`.
- `description`: convert the checklist question into a failed statement without free rewriting. Example: `Are auth requirements specified?` -> `Auth requirements not specified`.
- `suggested_fix`: provide concrete text to add or change. If you cannot provide a concrete fix, lower severity to MEDIUM and append `(no clear fix)` to the description.

Output schema:

```json
[
  {
    "severity": "HIGH",
    "target": "spec",
    "target_anchor": "spec.md#FR-3",
    "description": "Auth requirements not specified",
    "suggested_fix": "Add to spec.md under Functional Requirements: FR-3: The system MUST require authenticated access for account settings."
  }
]
```
