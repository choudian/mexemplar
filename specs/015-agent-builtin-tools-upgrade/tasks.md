# Tasks: Agent Built-in Tools Upgrade

**Input**: Design documents from `/specs/015-agent-builtin-tools-upgrade/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/
**Tests**: Mandatory for this feature per spec.md "User Scenarios & Testing" and FR-025.
**Worktree**: `E:\code\Exemplar\.worktrees\015-agent-builtin-tools-upgrade`

**Organization**: Tasks are grouped by user story so each tool family can be implemented, tested, and accepted as an independently useful increment. The P1 gate requires both US1 and US2 because existing-file mutation depends on baselines produced by safe file reads.

## Phase 1: Setup (Shared Structure)

**Purpose**: Create the module/test structure required by the implementation plan without changing runtime behavior.

- [X] T001 Create shared built-in contract module skeleton in `src/business/agents/tools/builtin_contracts.py`
- [X] T002 [P] Create workspace permission module skeleton in `src/business/agents/tools/builtin_permissions.py`
- [X] T003 [P] Create file, search, command, and output-governance module skeletons in `src/business/agents/tools/file_tools.py`, `src/business/agents/tools/search_tools.py`, `src/business/agents/tools/command_tools.py`, and `src/business/agents/tools/output_governance.py`
- [X] T004 [P] Create execution boundary module skeletons in `src/execution/command_runner.py` and `src/execution/process_manager.py`
- [X] T005 [P] Create empty focused test files in `tests/business/agents/test_builtin_file_tools.py`, `tests/business/agents/test_builtin_search_tools.py`, `tests/business/agents/test_builtin_command_tools.py`, `tests/business/agents/test_builtin_output_governance.py`, `tests/data/test_tool_output_repository.py`, `tests/integration/test_agent_builtin_tool_contracts.py`, and `tests/integration/test_agent_builtin_process_lifecycle.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the shared envelope, configuration, permission, and AgentLoop save boundary required before any upgraded built-in tool can be accepted.

**Critical**: No user story implementation should start until this phase is complete because every upgraded tool must share the same result and permission contract.

### Foundational Tests

- [X] T006 [P] Add JSON-schema and stable error-code tests for the common envelope in `tests/integration/test_agent_builtin_tool_contracts.py`
- [X] T007 [P] Add unified configuration getter/default validation tests for all `agent_tools.*` keys in `tests/data/test_tool_output_repository.py`
- [X] T008 [P] Add workspace path classification and confirmation-summary safety tests in `tests/guardrails/test_agent_builtin_tool_boundaries.py`
- [X] T009 Add AgentLoop exactly-one-result tests for accepted, rejected, unknown, handler-exception, skipped, and fallback tool calls in `tests/integration/test_agent_builtin_tool_contracts.py`

### Foundational Implementation

- [X] T010 [P] Implement `ToolResultEnvelope`, `ToolError`, `PermissionDecision`, `ToolOutputReference`, `VerificationResult`, outcome constants, error-code catalog, and JSON serialization helpers in `src/business/agents/tools/builtin_contracts.py`
- [X] T011 [P] Implement canonical workspace resolution, external/hidden/system/symlink classification, risk decisions, and safe confirmation summaries in `src/business/agents/tools/builtin_permissions.py`
- [X] T012 [P] Add `AgentToolsFileConfig`, `AgentToolsOutputConfig`, `AgentToolsSearchConfig`, `AgentToolsProcessConfig`, and parent config fields in `src/data/config_models.py`
- [X] T013 Add typed getters and validation for every `agent_tools.*` key listed in plan.md in `src/data/unified_config.py`
- [X] T014 Update `agent_tools` defaults in `config.example.json`
- [X] T015 Implement AgentLoop governed tool-result persistence wrapper for ordinary results, standardized errors, pre-hook rejections, unknown tools, skipped tools, and solo interrupt contract failures in `src/business/agents/agent_loop.py`
- [X] T016 Route all existing `ctx.save_tool_result(...)` and `_save_error(...)` call sites through the governed persistence wrapper in `src/business/agents/agent_loop.py`
- [X] T017 Update `src/business/agents/tools/builtin_general_tools.py` to keep the public `BUILTIN_GENERAL_TOOLS` facade while delegating upgraded built-ins to focused modules
- [X] T018 Add guard tests preventing UI, Tauri, desktop API, or business code from directly managing built-in execution state or tool-output SQL in `tests/guardrails/test_agent_builtin_tool_boundaries.py`

**Checkpoint**: The shared envelope, workspace policy, config defaults, and AgentLoop save boundary exist and all subsequent tool handlers can return the new contract.

---

## Phase 3: User Story 1 - Safe File Inspection (Priority: P1)

**Goal**: Agents can inspect text files in bounded, redacted, navigable windows and safely refuse binary/media reads.

**Independent Test**: Ask an Agent to read a small text file, a large text file, a binary/media file, and a file containing secret-like values; each result is a structured envelope with continuation, baseline, refusal, repeat-read, and redaction metadata as appropriate.

### Tests for User Story 1

- [X] T019 [US1] Add read-file tests for small text, large line windows, `nextPageToken` or line-window continuation, baselines, and repeated-read metadata in `tests/business/agents/test_builtin_file_tools.py`
- [X] T020 [US1] Add binary/media refusal and decode-failure tests in `tests/business/agents/test_builtin_file_tools.py`
- [X] T021 [P] [US1] Add outside-workspace read confirmation and fail-closed integration tests in `tests/integration/test_agent_builtin_tool_contracts.py`
- [X] T022 [P] [US1] Add visible-result redaction and no-raw-binary leak tests in `tests/guardrails/test_agent_builtin_tool_boundaries.py`

### Implementation for User Story 1

- [X] T023 [US1] Implement raw-byte `FileBaseline` hashing, display-path normalization, encoding detection, and line-window metadata helpers in `src/business/agents/tools/file_tools.py`
- [X] T024 [US1] Implement bounded `read_file` text rendering with line numbering, total/remaining indicators, page guidance, and configured line/character caps in `src/business/agents/tools/file_tools.py`
- [X] T025 [US1] Implement binary/media detection, unsupported outcomes, decode failures, secret-like value redaction, and repeated-read advisory metadata in `src/business/agents/tools/file_tools.py`
- [X] T026 [US1] Apply workspace read policy, outside-workspace high-risk confirmation, and fail-closed result mapping for `read_file` in `src/business/agents/tools/builtin_permissions.py`
- [X] T027 [US1] Replace the legacy `read_file` schema, handler, and pre-hook wiring with the new contract in `src/business/agents/tools/builtin_general_tools.py`
- [X] T028 [US1] Update Agent-facing `read_file` tool description to explain bounded windows, baselines, redaction, unsupported binary behavior, and continuation metadata in `src/business/agents/tools/builtin_general_tools.py`
- [X] T029 [US1] Run the US1 portions of the focused test command documented in `specs/015-agent-builtin-tools-upgrade/quickstart.md`

**Checkpoint**: User Story 1 is functional and testable without file mutation, search, command execution, or raw-output recovery.

---

## Phase 4: User Story 2 - Recoverable File Changes (Priority: P1)

**Goal**: Agents can create files and mutate existing files only with a current observed baseline, with stale writes rejected before disk changes.

**Independent Test**: Read a file, edit it with the returned baseline, change it concurrently, retry with the stale baseline, and verify stale mutation is rejected while valid mutation returns change summary, old/new baselines, and verification status.

### Tests for User Story 2

- [X] T030 [US2] Add write-file create/replace tests for required baseline, stale baseline, verification, and safe change summaries in `tests/business/agents/test_builtin_file_tools.py`
- [X] T031 [US2] Add edit-file tests for single replacement, `replaceAll`, non-overlapping replacements, missing/ambiguous targets, newline/BOM/final-newline preservation, and stale baseline rejection in `tests/business/agents/test_builtin_file_tools.py`
- [X] T032 [P] [US2] Add multi-tool AgentLoop tests proving missing/stale mutation rejection still creates exactly one paired tool result in `tests/integration/test_agent_builtin_tool_contracts.py`
- [X] T033 [P] [US2] Add confirmation-summary leak tests for write/edit content and full replacement text in `tests/guardrails/test_agent_builtin_tool_boundaries.py`

### Implementation for User Story 2

- [X] T034 [US2] Implement existing-file baseline requirement, stale-baseline comparison, new-file creation without baseline, and post-write verification for `write_file` in `src/business/agents/tools/file_tools.py`
- [X] T035 [US2] Implement targeted `edit_file` replacement planning, `replaceAll`, non-overlap validation, candidate-location failure context, and style-preserving writeback in `src/business/agents/tools/file_tools.py`
- [X] T036 [US2] Add per-file mutation serialization or pre-mutation conflict rejection for write/edit operations in `src/business/agents/tools/file_tools.py`
- [X] T037 [US2] Apply workspace-mutation permission decisions, safe summaries, high-risk confirmation, and external mutation denial for write/edit in `src/business/agents/tools/builtin_permissions.py`
- [X] T038 [US2] Replace the legacy `write_file` and `edit_file` schemas, handlers, and pre-hook wiring with baseline-aware contracts in `src/business/agents/tools/builtin_general_tools.py`
- [X] T039 [US2] Remove legacy write/edit result-shape and handler-safety assumptions from `tests/test_hook_protocol.py`
- [X] T040 [US2] Run the US2 file mutation scenarios documented in `specs/015-agent-builtin-tools-upgrade/quickstart.md`

**Checkpoint**: The full P1/MVP gate is testable: safe reads produce baselines and all existing-file mutations require those baselines.

---

## Phase 5: User Story 3 - First-Class Search and Patch Workflows (Priority: P2)

**Goal**: Agents can search files/content and apply multi-file add/update/delete patches through structured built-ins instead of ad hoc shell parsing.

**Independent Test**: Search a fixture repository with ignored generated/dependency directories, search content with grouped line matches and context, then apply a multi-file patch inside the workspace and verify all results are bounded, structured, and safely scoped.

### Tests for User Story 3

- [X] T041 [US3] Add `search_files` tests for deterministic sorting, default ignored directories, page size caps, continuation tokens, hidden handling, and outside-workspace roots in `tests/business/agents/test_builtin_search_tools.py`
- [X] T042 [US3] Add `search_content` tests for literal/regex modes, grouped matches, line context, binary skips, redaction, elapsed/file caps, and continuation tokens in `tests/business/agents/test_builtin_search_tools.py`
- [X] T043 [P] [US3] Add `apply_patch` tests for add/update/delete validation, all-or-reject unsafe targets, required update/delete baselines, stale baseline rejection, and verification summaries in `tests/business/agents/test_builtin_file_tools.py`
- [X] T044 [P] [US3] Add search/patch boundary guard tests for ignored directories, direct SQL absence, and outside-workspace mutation rejection in `tests/guardrails/test_agent_builtin_tool_boundaries.py`

### Implementation for User Story 3

- [X] T045 [US3] Implement structured file traversal, default ignore rules, deterministic sorting, page tokens, scan caps, and result metadata in `src/business/agents/tools/search_tools.py`
- [X] T046 [US3] Implement structured content search with literal/regex modes, include globs, grouped line matches, bounded context, binary skip metadata, redaction, and continuation in `src/business/agents/tools/search_tools.py`
- [X] T047 [US3] Implement `PatchOperation` validation and dry-run planning for add/update/delete operations in `src/business/agents/tools/file_tools.py`
- [X] T048 [US3] Implement `apply_patch` mutation, verification, affected-file summaries, and per-operation stable error mapping in `src/business/agents/tools/file_tools.py`
- [X] T049 [US3] Apply workspace, baseline, and patch all-or-reject policy decisions for search roots and patch targets in `src/business/agents/tools/builtin_permissions.py`
- [X] T050 [US3] Register `search_files`, `search_content`, and `apply_patch` schemas and handlers in `src/business/agents/tools/builtin_general_tools.py`
- [X] T051 [US3] Update Agent-facing tool descriptions to prefer structured search and patch built-ins over shell parsing in `src/business/agents/tools/builtin_general_tools.py`
- [X] T052 [US3] Run the US3 search and patch scenarios documented in `specs/015-agent-builtin-tools-upgrade/quickstart.md`

**Checkpoint**: Search and patch workflows are independently usable after the P1 file safety foundation.

---

## Phase 6: User Story 4 - Manage Long-Running Commands (Priority: P2)

**Goal**: Agents can run synchronous commands and manage current-session background processes without duplicating or losing long-running work.

**Independent Test**: Run a short command, a timeout command, and a long-running background process; inspect logs, wait, stop, send input when enabled, close the record, and verify restart-unavailable behavior and elevated-risk confirmation.

### Tests for User Story 4

- [X] T053 [US4] Add synchronous `exec` tests for workspace cwd, success/failure exit status, timeout classification, bounded stdout/stderr, and elevated confirmation fail-closed in `tests/business/agents/test_builtin_command_tools.py`
- [X] T054 [P] [US4] Add background process lifecycle tests for start, list, poll, logs, wait, stop, send input, close, duplicate-start prevention, and unavailable-after-restart in `tests/integration/test_agent_builtin_process_lifecycle.py`
- [X] T055 [P] [US4] Add command/process boundary guard tests for external cwd/execution rejection, safe command summaries, process cleanup diagnostics, and no full command-body leakage in `tests/guardrails/test_agent_builtin_tool_boundaries.py`

### Implementation for User Story 4

- [X] T056 [US4] Implement synchronous command execution boundary with normalized cwd, timeout handling, bounded output, duration, and exit metadata in `src/execution/command_runner.py`
- [X] T057 [US4] Implement session-scoped `ProcessRecord` registry, stdout/stderr draining, bounded ring buffers, status transitions, and log windows in `src/execution/process_manager.py`
- [X] T058 [US4] Implement duplicate background start detection using normalized command, cwd, and session id in `src/execution/process_manager.py`
- [X] T059 [US4] Implement graceful/forced process stop, process-tree cleanup, stdin gating, close semantics, and sidecar-session cleanup fallback in `src/execution/process_manager.py`
- [X] T060 [US4] Implement `exec`, `process_list`, `process_poll`, `process_logs`, `process_wait`, `process_stop`, `process_send_input`, and `process_close` handlers in `src/business/agents/tools/command_tools.py`
- [X] T061 [US4] Apply command workspace policy, elevated-risk classification, fail-closed confirmation, and safe command summaries in `src/business/agents/tools/builtin_permissions.py`
- [X] T062 [US4] Register command and process schemas/handlers in `src/business/agents/tools/builtin_general_tools.py`
- [X] T063 [US4] Remove legacy `exec` timeout/output/result-shape assumptions from `tests/test_hook_protocol.py`
- [X] T064 [US4] Run the US4 command and process scenarios documented in `specs/015-agent-builtin-tools-upgrade/quickstart.md`

**Checkpoint**: Commands and current-session process records are observable and recoverable without relying on shell-output parsing.

---

## Phase 7: User Story 5 - Compact and Recover Tool Results (Priority: P3)

**Goal**: Large tool outputs enter Agent conversations as compact, redacted summaries while complete raw output remains recoverable through authorized persistent references across sidecar restarts.

**Independent Test**: Generate large successful output, large failure output, and unclassified output; verify compact visible results preserve critical facts and can load the original output by reference before and after sidecar restart until retention cleanup expires it.

### Tests for User Story 5

- [X] T065 [US5] Add output-governance tests for success compaction, failure diagnostic preservation, conservative fallback mode, warning metadata, and one-result fallback on governance failure in `tests/business/agents/test_builtin_output_governance.py`
- [X] T066 [P] [US5] Add `ToolOutputRepository` tests for create, authorize, load metadata, mark expired, mark deleted, cleanup expired rows, missing blobs, and orphaned blobs in `tests/data/test_tool_output_repository.py`
- [X] T067 [P] [US5] Add AgentLoop oversized-output and post-restart raw-reference recovery tests in `tests/integration/test_agent_builtin_tool_contracts.py`
- [X] T068 [P] [US5] Add raw artifact security leak tests for visible envelopes, confirmation summaries, ordinary logs, raw paths, full command bodies, base64/media payloads, runtime tokens, and secret-like values in `tests/guardrails/test_agent_builtin_tool_boundaries.py`

### Implementation for User Story 5

- [X] T069 [US5] Add `ToolOutputReference` ORM model and indexes for reference id, session id, tool call id, status, and expiry in `src/data/models_sqlite.py`
- [X] T070 [US5] Add forward-only v13 SQLite migration for tool-output reference metadata and indexes in `src/data/migrations.py`
- [X] T071 [US5] Implement `ToolOutputRepository` create/get-authorized/mark-expired/mark-deleted/cleanup APIs behind Repository boundaries in `src/data/repos/tool_output_repository.py`
- [X] T072 [US5] Implement private blob storage, temp-write/finalize, sha256 verification, missing-blob handling, orphan cleanup, and log-safe diagnostics in `src/data/repos/tool_output_repository.py`
- [X] T073 [US5] Implement redaction, output classification, visible-result caps, failure-tail preservation, fallback summaries, raw-reference creation, and warning metadata in `src/business/agents/tools/output_governance.py`
- [X] T074 [US5] Extend the AgentLoop governed persistence wrapper to apply output governance before saving built-in tool results in `src/business/agents/agent_loop.py`
- [X] T075 [US5] Implement `load_tool_output` authorization, bounded window loading, redaction, binary/media metadata refusal, expired/not-found errors, and safe envelope responses in `src/business/agents/tools/output_governance.py`
- [X] T076 [US5] Register `load_tool_output` schema and handler in `src/business/agents/tools/builtin_general_tools.py`
- [X] T077 [US5] Add retention cleanup entrypoints and runtime health counters for compaction, raw-reference failures, stale rejections, process cleanup, confirmation fail-closed, and cleanup failures in `src/business/agents/tools/output_governance.py`
- [X] T078 [US5] Run the US5 compaction, restart recovery, and retention cleanup scenarios documented in `specs/015-agent-builtin-tools-upgrade/quickstart.md`

**Checkpoint**: Large outputs are compact in conversation, raw artifacts are recoverable by authorized reference, and persistent references are governed by retention cleanup.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Final contract cleanup, active documentation, and whole-feature validation.

- [X] T079 [P] Update active built-in tool constraints, raw artifact security model, fixed workspace policy, and non-UI tuning knobs in `docs/PROJECT_CONSTRAINTS.md`
- [X] T080 [P] Update runtime architecture notes for the built-in tool subsystem, process manager, and persistent output references in `docs/ARCHITECTURE.md`
- [X] T081 [P] Update mirrored root AI entry documents with new built-in tool boundary guidance in `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md`
- [X] T082 [P] Update mirrored backend AI entry documents with Agent built-in tool upgrade guidance in `src/AGENTS.md`, `src/CLAUDE.md`, and `src/GEMINI.md`
- [X] T083 Remove all remaining legacy upgraded-tool parameter/result compatibility assumptions from `src/business/agents/tools/builtin_general_tools.py`
- [X] T084 Add a no-legacy-built-in-contract guard to `tests/guardrails/test_agent_builtin_tool_boundaries.py`
- [X] T085 Run the focused quickstart test groups from `specs/015-agent-builtin-tools-upgrade/quickstart.md`
- [X] T086 Run broad regression and formatting commands from `specs/015-agent-builtin-tools-upgrade/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup and blocks every user story.
- **US1 Safe File Inspection (Phase 3)**: Depends on Foundational.
- **US2 Recoverable File Changes (Phase 4)**: Depends on Foundational and should follow US1 in the P1 gate because mutation baselines are produced by `read_file`.
- **US3 Search and Patch (Phase 5)**: Depends on Foundational and benefits from US1/US2 file helpers.
- **US4 Commands and Processes (Phase 6)**: Depends on Foundational; can proceed in parallel with US3 after P1 if staffed.
- **US5 Output Recovery (Phase 7)**: Depends on Foundational and should follow US4 for command-output integration, but can start repository/migration tests earlier after Foundational.
- **Polish (Phase 8)**: Depends on all desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: First independently demonstrable read-only increment.
- **US2 (P1)**: Completes the Slice 1 MVP/P1 gate with baseline-safe mutation.
- **US3 (P2)**: Can start after P1 file safety helpers are stable.
- **US4 (P2)**: Can start after Foundational; integration with US5 raw references happens later.
- **US5 (P3)**: Completes persistent raw-output recovery and final AgentLoop output governance.

### Within Each User Story

- Write tests first and verify they fail for the current legacy behavior.
- Implement shared models/helpers before handlers.
- Wire handlers into `builtin_general_tools.py` only after focused module behavior is covered.
- Run the story-specific quickstart validation before moving to the next priority gate.

---

## Parallel Execution Examples

### User Story 1

```text
Task: T019 Add read-file window/baseline/repeat tests in tests/business/agents/test_builtin_file_tools.py
Task: T021 Add outside-workspace read integration tests in tests/integration/test_agent_builtin_tool_contracts.py
Task: T022 Add redaction/leak guard tests in tests/guardrails/test_agent_builtin_tool_boundaries.py
```

### User Story 2

```text
Task: T030 Add write-file baseline tests in tests/business/agents/test_builtin_file_tools.py
Task: T032 Add AgentLoop stale mutation pairing tests in tests/integration/test_agent_builtin_tool_contracts.py
Task: T033 Add confirmation-summary leak tests in tests/guardrails/test_agent_builtin_tool_boundaries.py
```

### User Story 3

```text
Task: T041 Add search_files tests in tests/business/agents/test_builtin_search_tools.py
Task: T043 Add apply_patch tests in tests/business/agents/test_builtin_file_tools.py
Task: T044 Add search/patch guard tests in tests/guardrails/test_agent_builtin_tool_boundaries.py
```

### User Story 4

```text
Task: T053 Add sync exec tests in tests/business/agents/test_builtin_command_tools.py
Task: T054 Add process lifecycle integration tests in tests/integration/test_agent_builtin_process_lifecycle.py
Task: T055 Add command/process boundary guard tests in tests/guardrails/test_agent_builtin_tool_boundaries.py
```

### User Story 5

```text
Task: T065 Add output governance tests in tests/business/agents/test_builtin_output_governance.py
Task: T066 Add repository persistence tests in tests/data/test_tool_output_repository.py
Task: T068 Add raw artifact leak tests in tests/guardrails/test_agent_builtin_tool_boundaries.py
```

---

## Implementation Strategy

### MVP First (P1 Gate)

1. Complete Phase 1 and Phase 2.
2. Complete US1 for bounded, redacted, baseline-producing file reads.
3. Complete US2 for baseline-required file creation/replacement/editing.
4. Stop and validate the P1 quickstart scenarios before search, commands, or output recovery.

### Incremental Delivery

1. **Slice 1**: Foundational + US1 + US2.
2. **Slice 2**: US3 structured search and patch workflows.
3. **Slice 3**: US4 command execution and current-session process management.
4. **Slice 4**: US5 compaction, persistent raw-output references, retention cleanup, and `load_tool_output`.
5. Polish with active docs, no-legacy guardrails, full quickstart validation, broad regression, formatting, and linting.

### Parallel Team Strategy

After Foundational is complete, US3 and US4 can be staffed in parallel once US1/US2 helpers are stable. US5 repository/migration work can begin after Foundational, but AgentLoop compaction wiring should wait until US4 command output behavior is stable.

---

## Notes

- `[P]` tasks use different files and have no dependency on incomplete tasks in the same phase.
- Every upgraded built-in family must migrate affected call sites fully to the new request/result contract in its delivery slice.
- Do not preserve a dual legacy/new compatibility window for migrated built-ins.
- Business code must use Repository APIs for SQLite metadata and `get_unified_config()` for every new tunable.
- Outside-workspace reads are exceptional high-risk inspection only; outside-workspace writes, deletes, patches, and execution are rejected before side effects.
