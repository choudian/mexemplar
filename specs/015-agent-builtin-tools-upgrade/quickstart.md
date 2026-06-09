# Quickstart: Agent Built-in Tools Upgrade

This quickstart is the implementation verification path for the feature. Commands assume the repository root is the active worktree.

## Prerequisites

- Python environment available through the project `uv` workflow.
- Tests run from `E:\code\Exemplar\.worktrees\015-agent-builtin-tools-upgrade`.
- No frontend dev server is required for the initial feature because core UI changes are out of scope.

## 1. Run focused unit tests

```powershell
uv run pytest `
  tests/business/agents/test_builtin_file_tools.py `
  tests/business/agents/test_builtin_search_tools.py `
  tests/business/agents/test_builtin_command_tools.py `
  tests/business/agents/test_builtin_output_governance.py `
  tests/data/test_tool_output_repository.py
```

Expected result:
- Text reads return bounded windows with baselines and redaction metadata.
- Binary/media reads return unsupported metadata without raw bytes.
- Existing-file writes/edits without a required baseline or with a stale baseline reject before mutation.
- Search pages are bounded, sorted, and exclude default ignored directories.
- Output references persist metadata and enforce retention states.
- Unified configuration getters return validated defaults for file, search, process, output, and retention limits.
- Visible envelopes and ordinary logs do not expose raw artifact paths, full command bodies, full file content, or secret-like values.

## 2. Run AgentLoop contract integration tests

```powershell
uv run pytest `
  tests/integration/test_agent_builtin_tool_contracts.py `
  tests/integration/test_agent_builtin_process_lifecycle.py `
  tests/integration/test_agent_loop_multi_tool_calls.py `
  tests/test_hook_protocol.py
```

Expected result:
- Every accepted, rejected, skipped, failed, compacted, or fallback built-in tool call creates exactly one paired tool result.
- Existing hook ordering and fail-closed confirmation behavior remain intact.
- Background processes can be started, inspected, waited, stopped, and closed within the same sidecar process session.
- Simulated post-restart process ids return `process_unavailable_after_restart`.
- Scripted Agent flows can follow file continuation metadata, reread after `baseline_required` / `baseline_stale`, and load a bounded raw-output reference.

## 3. Run guardrails

```powershell
uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py
```

Expected result:
- Business code does not directly write SQL for output references.
- UI, Tauri, and desktop API layers do not manage built-in tool execution state.
- External writes, deletes, patches, and execution are rejected before side effects.
- High-risk confirmation summaries remain redacted and fail closed.
- No migrated call site depends on legacy built-in parameter or result shapes.
- Mounted built-in tool schemas match `contracts/foundational-tools.md`, including required baselines for existing-file mutation.

## 4. Manual smoke scenarios

Use a temporary workspace fixture and ask an Agent flow to:

1. Read a small text file and a large text file in multiple windows.
2. Read a binary/media file and verify no raw bytes appear in the tool result.
3. Read a file containing values like `api_key=...`, `token=...`, `password=...`, and confirm redaction.
4. Edit a file with a fresh baseline, then try the same edit with a stale baseline after external modification.
5. Try to replace an existing file without a baseline and verify `baseline_required` before mutation.
6. Search filenames and content across a fixture containing ignored `node_modules`, `.git`, `dist`, `build`, and `__pycache__` directories.
7. Run a short synchronous command that succeeds and one that times out.
8. Start a background command, poll logs, wait or stop it, then close the process record.
9. Generate output larger than the visible cap, restart the sidecar, and load the raw output through `load_tool_output`.
10. Run retention cleanup and verify expired/missing/orphaned artifacts produce log-safe diagnostics.

Acceptance:
- Visible tool results remain compact, structured, and redacted.
- Full raw output is recoverable by reference until retention cleanup.
- Process control works only before sidecar restart.
- No mutation occurs outside the authorized workspace.
- Runtime health diagnostics cover compaction, raw-reference failures, stale rejections, process cleanup, confirmation fail-closed decisions, and retention cleanup without leaking sensitive details.

## 5. Broader regression before merge

```powershell
uv run pytest tests/
uv run black src tests
uv run flake8 src tests
```

If any command cannot run in the implementation environment, record the reason, risk, and follow-up in the PR or final implementation report.
