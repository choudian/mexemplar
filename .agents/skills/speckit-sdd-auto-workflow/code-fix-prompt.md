# Code Fix Prompt

Role: fix implementation findings whose `target` is `code`.

Inputs:

- code finding JSON array
- repository root
- hard-gate command output, if fixing test/type/lint failure

Allowed edits:

- Edit source code, tests, and directly required fixtures.
- Do not edit `spec.md`, `plan.md`, or `tasks.md`.
- Do not broaden scope beyond the supplied findings.

Procedure:

1. Confirm every input finding has `target=code`.
2. Inspect the target anchors and nearby tests.
3. Apply the smallest code and test changes that satisfy the findings.
4. Run the relevant hard-gate checks when available.
5. Return a summary including the changed files, checks run, and git diff summary.

Output schema:

```json
{
  "changed_files": ["src/auth.py", "tests/test_auth.py"],
  "checks_run": ["pytest tests/test_auth.py"],
  "remaining_failures": [],
  "diff_summary": "Added retry throttling and regression coverage."
}
```
