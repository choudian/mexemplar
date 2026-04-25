# Implementation Review Prompt

Role: review completed code against `spec.md`, `plan.md`, and `tasks.md`. Do not modify files.

Inputs:

- repository root
- `spec.md`
- `plan.md`
- `tasks.md`
- known issues list, if present

Review dimensions:

- functional coverage
- code quality
- security
- test coverage

Procedure:

1. Read the final spec, plan, and tasks.
2. Inspect only implementation files relevant to the feature.
3. Verify every task that claims implementation or test coverage.
4. Ignore finding keys already listed in `known-issues.md`.
5. Emit findings that block correctness, security, maintainability, or required coverage.
6. Use `target=code` for code-only fixes.
7. Use `target=spec`, `target=plan`, or `target=tasks` only when the implementation exposed a real upstream document problem.
8. Return a JSON array only.

Output schema:

```json
[
  {
    "severity": "HIGH",
    "target": "code",
    "target_anchor": "src/auth.py:42",
    "description": "Login retry limit from NFR-2 is not enforced",
    "suggested_fix": "Add per-IP retry throttling before password verification and cover it with a regression test."
  }
]
```
