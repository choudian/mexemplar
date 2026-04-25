# Plan Decision Review Prompt

Role: review `research.md` and `plan.md` after planning, identify high-risk decisions that need user confirmation, and infer the project type.

Inputs:

- `research.md`
- `plan.md`
- existing `.sdd-state.json` if present

High-risk decision categories:

- architecture
- technology stack
- data storage
- security

Procedure:

1. Extract all decisions from `research.md`.
2. Cross-check the relevant architecture and stack sections in `plan.md`.
3. Mark a decision as user-facing only when changing it later would invalidate substantial planning or implementation work.
4. For each user-facing decision, include the chosen option, rationale, alternatives, and the specific question to ask the user.
5. Infer `project_type` as one of: `web-frontend`, `cli-tool`, `library`, `api-service`, `mobile`.
6. If `.sdd-state.json` already has `project_type`, keep it unless the file explicitly says it is auto-generated and may be replaced.
7. Return JSON only.

Output schema:

```json
{
  "project_type": "api-service",
  "project_type_confidence": "high",
  "decisions_requiring_user": [
    {
      "category": "data storage",
      "decision": "Use PostgreSQL for transactional persistence",
      "rationale": "The plan requires relational constraints and migrations.",
      "alternatives": ["SQLite", "document database"],
      "question": "Should this feature use PostgreSQL for transactional persistence?"
    }
  ]
}
```
