---
name: "speckit-sdd-auto-workflow"
description: "Automate a full Spec Kit spec-driven development workflow in Codex. Use when the user provides feature requirements and wants Codex to run specify, clarify, plan, tasks, implementation, checklist/analyze quality loops, review, and gated human decisions end to end."
compatibility: "Requires spec-kit project structure with .specify/ directory and Codex skills installed under .agents/skills"
metadata:
  author: "github-spec-kit"
  source: "src/specify_cli/integrations/codex/skills/speckit-sdd-auto-workflow/SKILL.md"
---

# Spec Kit SDD Auto Workflow

Use this skill to orchestrate one feature through the Spec Kit SDD lifecycle:

`$speckit-specify` -> `$speckit-clarify` -> `$speckit-plan` -> `$speckit-tasks` -> `$speckit-implement`

Run quality loops between those commands. Pause only for required user decisions.

## Codex Boundaries

- Treat this as a natural-language workflow. There is no hidden function call API.
- Use the installed Spec Kit skills when possible. If nested skill invocation is unavailable, follow the corresponding `SKILL.md` instructions directly.
- Use Codex sub-agents only when the user explicitly authorizes delegation in the current session. Otherwise, run the same review/fix passes yourself, sequentially.
- Keep all state inside the current feature directory, normally `specs/<feature-id>/`.
- Do not edit implementation code before the final human approval gate.
- Never bypass the final gate after any upstream rollback.

## Bundled Prompts

Load these files only when entering the matching step:

- `checklist-runner-prompt.md`: turn generated checklist questions into findings.
- `fix-findings-prompt.md`: repair spec, plan, or tasks findings.
- `plan-decision-review-prompt.md`: extract high-risk plan decisions and infer project type.
- `impl-review-prompt.md`: review implemented code against spec, plan, and tasks.
- `code-fix-prompt.md`: fix code-only implementation findings.
- `state-and-checkpoint.md`: state schema, checkpoint protocol, quotas, and rollback rules.

## Preflight

1. Verify `.specify/` exists. If missing, stop and ask the user to initialize Spec Kit.
2. Verify `.specify/memory/constitution.md` exists. If missing, stop and ask the user to create or initialize the constitution.
3. If resuming, resolve `FEATURE_DIR` from existing state or Spec Kit prerequisite scripts.
4. If starting new work, run `$speckit-specify` with the user's requirement text, then resolve the generated `FEATURE_DIR`.
5. Initialize or load `FEATURE_DIR/.sdd-state.json`.

Runtime files:

- `FEATURE_DIR/.sdd-state.json`
- `FEATURE_DIR/.history/`
- `FEATURE_DIR/deferred-clarifications.md`
- `FEATURE_DIR/known-issues.md`

## Stage A: Spec Convergence

Goal: `spec.md` has no CRITICAL or HIGH findings.

1. Run the clarify loop with `$speckit-clarify`.
2. Exit the clarify loop when any condition is true:
   - output contains `No critical ambiguities detected`
   - coverage summary has `Outstanding == 0`
   - Outstanding count does not decrease for 2 consecutive rounds
3. If unresolved items remain after stagnation, write them to `deferred-clarifications.md` and store `deferred_path` in state.
4. Archive old checklist files into `.history/A/round-<a>/` before generating new ones.
5. Generate baseline checklists: `completeness`, `clarity`, `consistency`, `security`.
6. Run each generated checklist with `checklist-runner-prompt.md`.
7. Dedupe findings, ignore known issues, and route fixes.
8. If any fix adds a new `NEEDS CLARIFICATION`, return to the clarify loop.
9. Increment counter `a` after one complete checklist plus fix round.

Stage A cannot use `$speckit-analyze` because tasks do not exist yet.

## Stage B: Plan Convergence

Goal: `plan.md` and `research.md` are aligned with `spec.md`, with high-risk decisions approved.

1. Run `$speckit-plan`.
2. Use `plan-decision-review-prompt.md` on `research.md` and `plan.md`.
3. If high-risk architecture, stack, storage, or security decisions need user approval, pause and ask once with the alternatives.
4. If the user changes a high-risk decision, pass the decision as a planning hint and rerun `$speckit-plan`.
5. Store inferred `project_type` in state the first time it is available. Respect manual state overrides.
6. Archive old checklists into `.history/B/round-<b>/`.
7. Generate baseline dimensions plus project-type dimensions.
8. Run each checklist with `checklist-runner-prompt.md`.
9. Route findings:
   - `target=spec`: mark plan stale, archive it, return to Stage A.
   - `target=plan` and high-risk area: rerun `$speckit-plan`, then repeat decision review.
   - `target=plan` and not high-risk: use `fix-findings-prompt.md`, then repeat Stage B checklist.
10. Increment counter `b` after one complete checklist plus fix round. Plan reruns do not increment `b`.

Stage B cannot use `$speckit-analyze` because tasks do not exist yet.

## Stage C: Tasks Convergence

Goal: `spec.md`, `plan.md`, and `tasks.md` are mutually consistent.

1. Run `$speckit-tasks`.
2. Archive old checklists into `.history/C/round-<c>/`.
3. Generate baseline dimensions plus project-type dimensions.
4. Run each checklist with `checklist-runner-prompt.md`.
5. Run `$speckit-analyze` read-only.
6. Parse analyze table rows into the finding schema:
   - `Severity` -> `severity`
   - first file in `Location(s)` -> `target`
   - full `Location(s)` -> `target_anchor`
   - `Summary` -> `description`
   - `Recommendation` -> `suggested_fix`
7. Split multi-location analyze findings into one finding per file.
8. Cap analyze findings at top 50 by severity and record overflow in state.
9. Route findings:
   - `target=spec`: archive stale plan/tasks and return to Stage A.
   - `target=plan`: archive stale tasks and return to Stage B.
   - `target=tasks`: use `fix-findings-prompt.md`, then repeat Stage C.
10. Increment counter `c` after one complete checklist plus analyze plus fix round.

## Final Gate

Only open this gate after CRITICAL and HIGH findings are zero.

Show the user:

- concise summaries of `spec.md`, `plan.md`, and `tasks.md`
- high-risk decisions and current `project_type`
- deferred clarifications
- remaining MEDIUM and LOW findings
- state counters, rollback count, and overflow warnings

User choices:

- approve: increment `gate_passes` and enter Stage D
- change spec: return to Stage A
- change plan: return to Stage B
- change tasks: return to Stage C
- reject: stop and archive current state

## Stage D: Implementation And Review

1. Run `$speckit-implement`.
2. If implementation fails twice, pause and report the error.
3. Run the hard gate: tests plus compile/type/lint checks appropriate for the repository.
4. If the hard gate fails, use `code-fix-prompt.md` and rerun checks.
5. Pause if the hard gate fails 3 consecutive times or if the git diff is unchanged after a fix attempt.
6. Review implementation with `impl-review-prompt.md` across:
   - functional coverage
   - code quality
   - security
   - test coverage
7. Route findings:
   - `target=code`: use `code-fix-prompt.md`, then repeat hard gate.
   - `target=spec`, `target=plan`, or `target=tasks`: pause and ask whether to roll back upstream or record as a known issue.
8. If the user accepts rollback, return to the furthest upstream selected stage and require a new final gate later.
9. If the user rejects rollback, write the finding key to `known-issues.md`.
10. Increment counter `d` after one complete implementation review plus fix round.

## Finding Schema

Every finding must be JSON-compatible:

```json
{
  "severity": "CRITICAL | HIGH | MEDIUM | LOW",
  "target": "spec | plan | tasks | code",
  "target_anchor": "spec.md#FR-3 | src/auth.ts:42",
  "description": "Concrete problem",
  "suggested_fix": "Concrete fix"
}
```

`target` and `target_anchor` are required. Do not use `unknown`.

## Dedupe And Routing

1. Collect all finding JSON.
2. Compute `finding_key = target_anchor + severity + first three topic nouns`.
3. Load `known-issues.md` and drop matching keys.
4. Group by key and keep the highest-severity representative.
5. Route by `target`.
6. If the same key triggers rollback more than 2 times, pause and ask the user.

## Checklist Dimensions

Baseline for all stages:

- `completeness`
- `clarity`
- `consistency`
- `security`

Additional dimensions by `project_type`:

- `web-frontend`: `ux`, `a11y`, `performance`
- `cli-tool`: no extra dimensions
- `library`: `api-contract`
- `api-service`: `performance`, `api-contract`, `reliability`
- `mobile`: `ux`, `a11y`, `performance`, `offline-handling`

In Stage A, use only baseline dimensions because no plan exists yet.

When `$speckit-checklist` asks its 1 to 3 setup questions, use default automation answers: Standard depth, Reviewer audience for code-related features otherwise Author, and focus on the top 2 clusters.

## Completion Report

At the end, report:

- code and tests changed
- hard gate commands and results
- final `spec.md`, `plan.md`, and `tasks.md`
- deferred clarifications and known issues
- finding counts fixed by stage and severity
- overflow warnings
- total elapsed time and counters
- whether rollback protection was triggered
- suggested commit strategy: one commit per accepted stage, no amend after upstream rollback
