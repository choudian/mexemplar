# Quickstart: 外部 Coding Session

## Preconditions

- Worktree branch: `030-external-coding-sessions`
- Python deps installed through the repo's normal `uv` environment.
- Frontend deps installed in `frontend/`.
- Claude Code / Codex CLI are optional for automated tests; tests use fake adapters unless explicitly marked integration.

## Local Validation Flow

1. Run migrations/repository tests.

```powershell
uv run pytest tests/data/test_external_coding_session_repository.py tests/data/test_external_coding_baseline_migration.py
```

2. Run business state-machine and adapter tests.

```powershell
uv run pytest tests/business/external_coding tests/execution/test_external_coding_quota.py
```

3. Run API contract and event registry tests.

```powershell
uv run pytest tests/desktop_api/test_external_coding_sessions_api.py tests/desktop_api/test_external_coding_ui_event.py tests/desktop_api/test_ui_event_layer.py
```

4. Run guardrails.

```powershell
uv run pytest tests/guardrails/test_external_coding_guardrails.py
```

5. Run the persisted task-snapshot and UI-event closed-loop test.

```powershell
uv run pytest tests/integration/test_external_coding_closed_loop.py
```

6. Run frontend unit tests for task detail rendering, actions and event parsing.

```powershell
Set-Location frontend
npm run test -- externalCodingSessions
```

7. Optional manual smoke can use the business tests' fake adapter fixtures as the reference path. A dedicated `dev_smoke` CLI is intentionally not required for MVP.

Expected result:
- `data/coding_sessions/<id>/HANDOFF.md` and `PLAN.md` exist after plan stage.
- Session status reaches `plan_ready`.
- Approving plan and resuming with fake implementation writes `RESULT.md`.
- Session reaches `completed`; merge analysis reports low/overlap/conflict instead of merging blindly.

## Manual Real CLI Smoke

Only run after fake adapter validation.

1. Confirm command availability:

```powershell
claude --version
codex --version
```

2. Start desktop sidecar/app normally.

3. Ask an assistant task owner to start an external coding session for a tiny code/doc change.

4. Verify:
- The chosen tool and quota state are visible in task detail.
- `PLAN.md` appears before any implementation is approved.
- A plan-phase write is flagged as protocol violation.
- `RESULT.md` is required before `completed`.
- Merge analysis records target dirty files and changed files before merge.

## Rollback Smoke

After a test merge, request "撤回这次 coding session 的改动".

Expected:
- The service proposes a rollback strategy with safe explanation.
- History-changing actions require explicit confirmation.
- The rollback audit record is persisted.
