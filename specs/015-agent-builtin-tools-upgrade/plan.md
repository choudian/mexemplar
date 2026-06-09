# Implementation Plan: Agent Built-in Tools Upgrade

**Branch**: `015-agent-builtin-tools-upgrade` | **Date**: 2026-06-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/015-agent-builtin-tools-upgrade/spec.md`

## Summary

Upgrade the shared Agent foundational tools from ad hoc string handlers into a stable built-in tool subsystem with versioned result envelopes, workspace-aware permission decisions, paginated and redacted file/search output, baseline-validated mutations, session-scoped process management, and persistent raw-output references. The implementation keeps `AgentLoop` tool-call pairing semantics intact by making result governance a single save-time boundary, while the existing `builtin_general_tools.py` remains the public registry facade during migration.

## Technical Context

**Language/Version**: Python 3.11+ source, Python 3.12 runtime; no frontend or Rust changes planned for the core delivery
**Primary Dependencies**: existing `AgentLoop` / `ToolDefinition` hook protocol, `pathlib`, `subprocess` / `threading`, SQLAlchemy SQLite repositories, `get_unified_config()`, pytest
**Storage**: SQLite metadata for persistent tool-output references via Repository + filesystem blobs under the application data directory; background process records stay in memory for the current sidecar process only
**Testing**: pytest unit, integration, and guardrail tests under `tests/business/agents/`, `tests/integration/`, `tests/data/`, and `tests/guardrails/`
**Target Platform**: Desktop Python sidecar, Windows-first because current desktop runtime is Windows-oriented; path policy should remain portable where `pathlib` can support it
**Project Type**: Desktop application with Python Agent runtime and local FastAPI sidecar
**Performance Goals**: bounded visible tool results below configured conversation caps; file/search pages avoid loading unbounded repository content; 100,000+ character command output compacts while retaining a raw reference
**Constraints**: authorized workspace boundary; high-risk confirmation remains fail-closed and session-scoped; every tool call produces exactly one paired result; no raw binary/media or secret-like values in ordinary Agent-visible text; all new configuration goes through unified config
**Scale/Scope**: shared built-ins used by Assistant, ephemeral subagents, specialists, and any PM/Programmer/Trial flow that receives the shared built-ins; user-created business tools and recording data tools are out of scope except for contract-preservation guard tests

## Constitution Check

*GATE: Pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Layered Boundaries & Event Coordination | PASS | Core changes stay in `src/business/agents/tools/`, `src/execution/`, and `src/data/`; no UI/Tauri dependency is introduced. No new blinker/UI events are required for the initial feature. |
| II. Data Boundary & Persistence Discipline | PASS | Persistent output-reference metadata uses a new SQLite Repository and migration. Business code will not write SQL directly. DuckDB and `network_requests` are not touched. |
| III. Unified Config & Secret Handling | PASS | New thresholds, retention limits, workspace/output caps, and command defaults are listed in the Configuration Contract below and read through `get_unified_config()` / `UnifiedConfigManager`; no new keyring secrets are introduced. |
| IV. Verifiable Delivery | PASS | Plan includes focused tests for file windows, stale mutations, patch validation, search pagination, permission fail-closed behavior, process lifecycle, output compaction/recovery, and AgentLoop pairing. |
| V. Living Docs & Spec-Driven Delivery | PASS | Feature artifacts live in `specs/015-agent-builtin-tools-upgrade/`. Update `docs/PROJECT_CONSTRAINTS.md` for new built-in tool boundaries and `docs/ARCHITECTURE.md` only if process/output-reference architecture becomes current truth beyond this feature. |

**Post-Design Re-check**: PASS. Phase 0/1 design keeps UI out of core execution state, stores durable raw-output metadata behind a Repository, uses unified config for all tunables, and defines automated acceptance coverage for every high-risk path.

## Configuration Contract

All configurable values are read through `get_unified_config()` / `UnifiedConfigManager`, with defaults added to `src/data/config_models.py`, typed getters added to `src/data/unified_config.py`, examples added to `config.example.json`, and constraints documented in `docs/PROJECT_CONSTRAINTS.md`. Settings UI exposure is **No** for the initial delivery unless explicitly noted; these are runtime engineering limits, not user-facing tuning knobs.

| Key | Default | Validation | Getter / Owner | Template & Docs | UI |
|-----|---------|------------|----------------|-----------------|----|
| `agent_tools.file.default_max_lines` | `200` | positive int, max `1000` | `get_agent_tools_file_default_max_lines()` | `config.example.json`, project constraints | No |
| `agent_tools.file.max_window_chars` | `50000` | positive int, max `250000` | `get_agent_tools_file_max_window_chars()` | same | No |
| `agent_tools.file.max_decode_bytes` | `1048576` | positive int, max `10485760` | `get_agent_tools_file_max_decode_bytes()` | same | No |
| `agent_tools.output.visible_char_cap` | `12000` | positive int, max `50000` | `get_agent_tools_output_visible_char_cap()` | same | No |
| `agent_tools.output.raw_reference_threshold_chars` | `20000` | positive int, >= visible cap | `get_agent_tools_output_raw_reference_threshold_chars()` | same | No |
| `agent_tools.output.max_artifact_bytes` | `10485760` | positive int, max `104857600` | `get_agent_tools_output_max_artifact_bytes()` | same | No |
| `agent_tools.output.retention_days` | `14` | positive int, max `90` | `get_agent_tools_output_retention_days()` | same | No |
| `agent_tools.search.default_page_size` | `100` | positive int, max `500` | `get_agent_tools_search_default_page_size()` | same | No |
| `agent_tools.search.max_files_scanned` | `50000` | positive int | `get_agent_tools_search_max_files_scanned()` | same | No |
| `agent_tools.search.max_bytes_per_file` | `1048576` | positive int | `get_agent_tools_search_max_bytes_per_file()` | same | No |
| `agent_tools.search.max_elapsed_ms` | `30000` | positive int | `get_agent_tools_search_max_elapsed_ms()` | same | No |
| `agent_tools.process.default_timeout_ms` | `30000` | positive int | `get_agent_tools_process_default_timeout_ms()` | same | No |
| `agent_tools.process.max_timeout_ms` | `600000` | positive int, >= default | `get_agent_tools_process_max_timeout_ms()` | same | No |
| `agent_tools.process.log_tail_chars` | `4000` | positive int, max output cap | `get_agent_tools_process_log_tail_chars()` | same | No |
| `agent_tools.process.max_background_processes` | `16` | positive int | `get_agent_tools_process_max_background_processes()` | same | No |

Fixed constants with rationale:

- Authorized workspace source is not a config file setting in this feature. It is resolved from Agent runtime context so subagents and specialists inherit the active session boundary; tests may inject it through runtime context fixtures.
- Outside-workspace reads are always high-risk exceptional access. This policy is fixed to avoid accidentally weakening the workspace boundary through local configuration.
- Outside-workspace mutation, deletion, patching, and execution are always denied. This is a fixed safety rule from the specification.

## Raw Output Artifact Security Model

- **Storage root**: raw blobs live under the existing application data directory in a dedicated `tool_outputs/` subtree selected by data-layer helpers, never from tool arguments. Ordinary envelopes expose only opaque `referenceId`, kind, size, content type, digest, and expiry metadata.
- **Repository boundary**: SQLite metadata is written and read only through `ToolOutputRepository`; business and execution code must not issue direct SQL. Blob paths are internal and must not enter Agent-visible text, public UI events, ordinary logs, or confirmation summaries.
- **Creation sequence**: write blob content to a temporary file, close it, compute `sha256`, atomically rename/finalize the blob, then commit active metadata in SQLite. On any failure, remove temp/final blobs where possible and return a compact visible fallback with a `compaction_failed_fallback` warning and no active reference.
- **Retention**: `expiresAt = createdAt + agent_tools.output.retention_days`. Cleanup marks metadata expired and removes blobs; later cleanup passes retry blob deletion for already-expired rows. Missing blobs produce `output_reference_not_found` or `output_reference_expired`, not raw filesystem details.
- **Authorization**: `load_tool_output` checks the owning session/workspace context before loading a reference. A future cross-session load path must be specified separately; the initial contract is owner-session/workspace scoped.
- **Sensitive data**: raw blobs may contain sensitive local output by design, so visible previews and metadata must be redacted. Encryption is deferred for this local-only desktop feature, but file permissions should be private best effort on supported platforms and the deferral must be documented in `docs/PROJECT_CONSTRAINTS.md`.
- **Leak tests**: automated tests must prove ordinary envelopes/logs do not include raw artifact paths, full command bodies, full file content, unredacted secret-like values, or base64/media payloads.

## AgentLoop Result Governance Boundary

Result governance is implemented as a single persistence boundary, not a post-hook. The implementation should add one internal wrapper, for example `AgentLoop._persist_tool_result(...)` or `ContextManager.save_tool_result_governed(...)`, that applies envelope validation, redaction, compaction, raw-reference creation, fallback warnings, and exactly-one-result pairing before delegating to the existing message repository.

Every current save path must either route through this wrapper or document a narrow exemption:

- ordinary batch success/failure after `_execute_tool_call`
- `_save_error` for unknown tools, invalid mixed batches, skipped calls, pre-hook rejection, and contract violations
- solo interrupting tool success and interrupting contract failures
- handler exception converted to standardized error
- compaction/artifact failure fallback
- injected internal tools only if explicitly exempted from built-in output governance

The wrapper must never create a second tool result for the same `tool_call_id`. If governance fails, it returns one safe fallback envelope with warning metadata.

## ProcessManager Failure Modes

- **Stream pumping**: stdout/stderr are drained by background reader threads or nonblocking pipes into bounded ring buffers to avoid subprocess deadlock.
- **Log caps**: recent logs respect `agent_tools.process.log_tail_chars` and remain in a bounded in-memory ring buffer. The initial process lifecycle implementation does not retain a complete log stream or create durable references from `process_logs`.
- **Duplicate detection**: background start computes a duplicate key from normalized command, cwd, and session id. If a matching running process exists, the result points to the existing `processId` instead of starting another process.
- **Termination**: graceful stop is attempted first; forced stop must terminate the process tree on Windows and the child process group on POSIX where available.
- **Timeouts**: sync commands return `timeout`; background waits return current status without killing unless the process-level timeout policy requires termination.
- **stdin**: `process_send_input` is allowed only for records started with stdin enabled and bounded input; otherwise it returns `permission_denied`.
- **Shutdown cleanup**: sidecar shutdown attempts to terminate or mark background records closed. After restart, old ids are not manageable live processes and return `process_unavailable_after_restart`.

## Search and File Traversal Limits

Search and file reading must enforce hard caps from the configuration contract: maximum lines/chars returned, bytes decoded per file, files scanned, elapsed time, and page size. When a cap is hit, results remain valid but include skipped/truncated metadata and continuation guidance where possible. The search adapter may use native traversal or an optimized `rg --json` backend behind the same structured contract; if large-repo fixtures exceed the elapsed/file caps with native traversal, tasks should prefer the optimized adapter.

## Migration, Cleanup, and Recovery

- Add the next SQLite schema migration for tool output reference metadata with indexes on `reference_id`, `session_id`, `tool_call_id`, `status`, and `expires_at`.
- Add `ToolOutputRepository` APIs for create, get authorized metadata, mark expired, mark deleted, and cleanup expired/orphaned records.
- Cleanup handles both orphaned metadata with missing blobs and orphaned blobs with missing metadata, reporting log-safe diagnostics only.
- Migrations are forward-only unless the project later introduces reversible migration infrastructure. Rollback recovery is to stop using new built-ins, leave metadata inert, and let cleanup remove expired blobs.
- Update `docs/PROJECT_CONSTRAINTS.md` with the new built-in tool boundaries, raw artifact security model, fixed workspace policy, and non-UI-exposed tuning knobs.

## Runtime Health Metadata

Implementation must emit log-safe structured diagnostics or counters for:

- compacted output count and fallback count
- raw reference create/load failures
- stale or missing baseline rejections
- outside-workspace read confirmations and fail-closed decisions
- process records started, reused as duplicates, timed out, stopped, and cleaned on shutdown
- retention cleanup expired metadata, removed blobs, missing blobs, and orphaned blobs

These diagnostics must not include raw command bodies, local blob paths, file contents, credentials, raw stack traces, or runtime tokens.

## Project Structure

### Documentation (this feature)

```text
specs/015-agent-builtin-tools-upgrade/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── foundational-tools.md
│   └── tool-result-envelope.schema.json
└── tasks.md              # Created by /speckit-tasks, not by this command
```

### Source Code (repository root)

```text
src/
├── business/
│   └── agents/
│       ├── agent_loop.py                 # preserve one-result-per-tool-call save boundary
│       └── tools/
│           ├── builtin_general_tools.py  # public registry facade; migrated call sites keep importing here
│           ├── builtin_contracts.py      # envelope, error codes, limits, reference DTOs
│           ├── builtin_permissions.py    # workspace/risk classification and confirmation summaries
│           ├── file_tools.py             # read/write/edit/patch handlers
│           ├── search_tools.py           # filename/content search handlers
│           ├── command_tools.py          # exec + process tool handlers
│           └── output_governance.py      # redaction, compaction, raw-reference creation
├── execution/
│   ├── command_runner.py                 # synchronous command execution boundary
│   └── process_manager.py                # session-scoped background process registry
└── data/
    ├── models_sqlite.py                  # tool output reference metadata model
    ├── migrations.py                     # next SQLite schema migration
    ├── unified_config.py                 # typed getters for new built-in tool settings
    └── repos/
        └── tool_output_repository.py     # Repository for raw-output reference metadata

tests/
├── business/
│   └── agents/
│       ├── test_builtin_file_tools.py
│       ├── test_builtin_search_tools.py
│       ├── test_builtin_command_tools.py
│       ├── test_builtin_output_governance.py
│       └── test_builtin_general_tools.py # existing web_fetch and facade regression tests
├── data/
│   └── test_tool_output_repository.py
├── guardrails/
│   └── test_agent_builtin_tool_boundaries.py
└── integration/
    ├── test_agent_builtin_tool_contracts.py
    └── test_agent_builtin_process_lifecycle.py
```

**Structure Decision**: Keep `builtin_general_tools.py` as the stable import/registry surface, but move implementation into focused modules so permission, file mutation, process lifecycle, and output governance can be tested independently. Durable metadata belongs to `src/data/repos/`; live process handles belong to `src/execution/`; Agent-facing schemas and summaries belong to `src/business/agents/tools/`.

## Complexity Tracking

No constitution violations are planned.

## Phase 0 Research Output

Research decisions are recorded in [research.md](./research.md). All technical-context uncertainties are resolved.

## Phase 1 Design Output

Design artifacts are recorded in:

- [data-model.md](./data-model.md)
- [contracts/foundational-tools.md](./contracts/foundational-tools.md)
- [contracts/tool-result-envelope.schema.json](./contracts/tool-result-envelope.schema.json)
- [quickstart.md](./quickstart.md)

## Implementation Strategy

1. **Slice 1**: Introduce the versioned envelope, stable error-code catalog, configuration getters, workspace runtime context, AgentLoop result-governance wrapper, bounded/redacted `read_file`, and baseline-required existing-file `write_file`/`edit_file`.
2. **Slice 2**: Add structured `search_files`, `search_content`, and `apply_patch` inside the authorized workspace, with traversal caps and required baselines for update/delete operations.
3. **Slice 3**: Add synchronous command execution output governance and session-scoped background process management.
4. **Slice 4**: Add persistent output references, `ToolOutputRepository`, retention cleanup, and `load_tool_output`, then route oversized built-in results through raw-reference creation before they reach Agent-visible messages.
5. Remove legacy parameter/result assumptions from affected call sites and tests in the same delivery slice.

## Test Strategy

- Unit tests for path resolution, workspace escapes, symlink behavior, binary detection, redaction, line-window pagination, baseline hashing, newline/BOM preservation, patch validation, search pagination, and output compaction.
- Integration tests with `AgentLoop` multi-tool batches to prove accepted, rejected, compacted, failed, skipped, and fallback calls each create exactly one paired tool result.
- Data tests for output-reference metadata persistence, retention cleanup, and post-restart lookup.
- Process tests for background start, poll, log windows, wait, stop, send input, close, duplicate-start prevention, and unavailable-after-restart handling.
- Guardrail tests to keep UI/desktop API out of built-in execution state, prevent direct SQL in business code, preserve fail-closed confirmation semantics, and assert no legacy built-in parameter/result compatibility remains.
- Schema and prompt/tool-description guard tests proving mounted built-in schemas match the contract and describe continuation metadata, required baselines, and output references.
- Leak tests proving visible envelopes, confirmation summaries, and ordinary logs omit raw artifact paths, full local file content, full command bodies, base64/media payloads, runtime tokens, and secret-like values.
- Large fixture tests for traversal caps, elapsed-time caps, skipped-file metadata, and optional optimized search backend behavior.
