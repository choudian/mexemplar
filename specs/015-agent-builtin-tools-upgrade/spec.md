# Feature Specification: Agent Built-in Tools Upgrade

**Feature Branch**: `015-agent-builtin-tools-upgrade`
**Created**: 2026-06-08
**Status**: Completed
**Input**: User description: "Upgrade Agent built-in foundational tools for file reading, writing, editing, searching, terminal/process execution, permission handling, and tool-result output governance so long-running Agent workflows have stable contracts, pagination/truncation, safety boundaries, recoverability, and testability."

## Clarifications

### Session 2026-06-08

- Q: How should built-in tools handle paths outside the authorized workspace? -> A: Outside-workspace reads require high-risk confirmation; outside-workspace writes, deletes, patches, and execution are rejected.
- Q: How long should background process records remain manageable? -> A: Background process records are valid only within the current sidecar process session and become invalid after sidecar restart.
- Q: Should oversized or sensitive raw tool outputs be recoverable after sidecar restart? -> A: Raw tool outputs and media references should be persistently recoverable across sidecar restarts, subject to retention and cleanup policy.
- Q: How should existing built-in tool calls be handled during the contract upgrade? -> A: Do not preserve legacy parameter or result compatibility; affected call sites must migrate to the new contract in the same delivery slice.

## Problem Evidence & MVP Scope

### Observed Failure Modes Driving This Feature

- Existing built-in file tools return inconsistent tool-specific JSON or plain error strings, making long-running Agent sessions hard to test and recover after failures.
- Large file/command outputs can enter message history before compression, crowding out useful context and increasing the risk of orphaned or unpaired tool results.
- Current file mutation tools can overwrite files without proving the Agent observed the latest content, which leaves stale-write and concurrent-edit failures silent until user review.
- Long-running commands such as tests, build steps, or dev servers are currently difficult to distinguish from timed-out one-shot commands, so Agents can duplicate work or lose process state.
- Permission handling is split across handlers and hooks, so workspace escape, high-risk confirmation, and safe summaries are not governed by one contract.

### MVP and Delivery Slices

- **Slice 1 (MVP / P1 gate)**: shared result envelope, stable error catalog, workspace path policy, bounded/redacted `read_file`, baseline-required existing-file `write_file`/`edit_file`, and AgentLoop one-result-per-tool-call guard tests.
- **Slice 2 (P2 search/patch gate)**: `search_files`, `search_content`, and `apply_patch` using the same workspace, baseline, pagination, and verification contracts.
- **Slice 3 (P2 command/process gate)**: synchronous `exec`, session-scoped background process lifecycle tools, duplicate-start prevention, and process shutdown cleanup.
- **Slice 4 (P3 output recovery gate)**: result compaction, persistent raw-output references, `load_tool_output`, retention cleanup, and raw-artifact security tests.

Each slice must migrate its affected call sites completely to the new request/result contract before it is considered delivered. Later slices must not reintroduce a legacy/new dual compatibility window for tool families already migrated.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Safe File Inspection (Priority: P1)

As an Agent working on a user task, I need to inspect files in bounded, navigable windows so I can understand project context without overloading the conversation or accidentally exposing sensitive content.

**Why this priority**: Most engineering workflows begin with reading files. If reads are ambiguous, oversized, unsafe, or hard to continue, every later tool workflow becomes unreliable.

**Independent Test**: Can be fully tested by asking an Agent to read a small text file, a large text file, a binary file, and a file containing common secret-like values; the Agent receives structured, bounded results with continuation metadata and safe redaction.

**Acceptance Scenarios**:

1. **Given** a text file with more lines than the default read window, **When** the Agent reads it, **Then** the result includes the requested content window, line metadata, truncation status, and a clear way to request the next window.
2. **Given** a binary or unsupported media file, **When** the Agent attempts to read it as text, **Then** the result refuses unsafe text rendering and identifies the file type outcome without returning raw binary content.
3. **Given** a text file containing common credential patterns, **When** the Agent reads it, **Then** sensitive values are redacted while the surrounding useful context remains available.

---

### User Story 2 - Recoverable File Changes (Priority: P1)

As an Agent modifying project files, I need writes and edits to be validated against the content I inspected so I do not overwrite newer changes or silently corrupt files.

**Why this priority**: File mutation is high impact. The feature must prevent stale writes, preserve file style, and provide enough evidence for users and downstream Agents to verify what changed.

**Independent Test**: Can be fully tested by reading a file, applying a targeted edit with the observed baseline, modifying the file concurrently before a second edit, and verifying that the stale edit is rejected while the valid edit reports a change summary and readback status.

**Acceptance Scenarios**:

1. **Given** an existing file and a matching baseline identifier from a prior read, **When** the Agent writes or edits that file, **Then** the operation succeeds only after the baseline is accepted and the result includes old/new identifiers plus verification status.
2. **Given** a file changed after the Agent last read it, **When** the Agent attempts to write or edit using the old baseline, **Then** the operation is rejected as stale and instructs the Agent to read the current content before retrying.
3. **Given** a file with established line-ending or text-marker style, **When** the Agent applies an edit, **Then** unchanged file style is preserved and the result summarizes only the changed regions.
4. **Given** an existing file and no baseline identifier, **When** the Agent attempts to replace, edit, delete, or patch-update that file, **Then** the operation is rejected before mutation with a baseline-required result and a recommendation to read the current file window first.

---

### User Story 3 - First-Class Search and Patch Workflows (Priority: P2)

As an Agent navigating a repository, I need built-in search and multi-file patch capabilities so I can locate relevant files and apply coherent changes without relying on ad hoc shell parsing.

**Why this priority**: Search and multi-file edits are common after safe reads and writes are available. Making them structured reduces repeated file reads, command noise, and malformed patch attempts.

**Independent Test**: Can be fully tested by searching a sample repository for files and text matches, then applying a multi-file add/update/delete patch inside the authorized workspace and verifying all results are bounded, structured, and safely scoped.

**Acceptance Scenarios**:

1. **Given** a repository containing many files and ignored dependency/build directories, **When** the Agent searches for matching files, **Then** the result returns a bounded, sorted file list and indicates whether additional results remain.
2. **Given** a text search pattern with multiple matches across files, **When** the Agent searches content, **Then** the result groups matches by file, includes line context when requested, and provides pagination metadata.
3. **Given** a multi-file patch whose targets are all inside the authorized workspace, **When** the Agent applies it, **Then** the result reports affected files, operation types, verification status, and any rejected change with a stable error code.

---

### User Story 4 - Manage Long-Running Commands (Priority: P2)

As an Agent running project commands, I need terminal execution and process management to distinguish quick commands from long-running work so I can start, inspect, wait for, and stop processes without duplicating or losing them.

**Why this priority**: Tests, dev servers, and build commands often exceed a single synchronous command window. Process lifecycle support makes Agent workflows observable and recoverable.

**Independent Test**: Can be fully tested by running a short read-only command, a command that times out, and a long-running process; the Agent can inspect logs, wait for completion, and terminate the process with clear status and output metadata.

**Acceptance Scenarios**:

1. **Given** a low-risk command in the authorized workspace, **When** the Agent runs it, **Then** the result includes command status, exit outcome, bounded output, and truncation metadata.
2. **Given** a long-running command started in background mode during the current sidecar session, **When** the Agent polls it later in that same session, **Then** the process status and recent logs are available without starting a duplicate process.
3. **Given** a command classified as elevated risk, **When** the Agent attempts to run it, **Then** the user receives a clear confirmation summary and the command fails closed if confirmation cannot be obtained.

---

### User Story 5 - Compact and Recover Tool Results (Priority: P3)

As an Agent receiving large tool outputs, I need important failures and summaries preserved in the conversation while complete raw output remains recoverable by reference even after a sidecar restart.

**Why this priority**: Large raw outputs can crowd out useful context or hide the real failure. Compression and references improve long-running sessions after the core tools are reliable.

**Independent Test**: Can be fully tested by generating large successful output, large failing output, and unrecognized output; the Agent receives compact results that retain critical details and can retrieve the original output through a reference before and after sidecar restart.

**Acceptance Scenarios**:

1. **Given** a command produces large successful output, **When** the result enters the Agent conversation, **Then** the visible result is compact and includes size, truncation, and persistent raw-output reference metadata when needed.
2. **Given** a command produces failure output, **When** the result is compacted, **Then** the visible result preserves failure names, critical diagnostics, and enough tail context for next action.
3. **Given** output cannot be classified confidently, **When** the result is compacted, **Then** the system uses a conservative fallback that keeps head/tail context, marks the fallback mode, and preserves a raw-output reference.

### Edge Cases

- If the Agent requests the same file window repeatedly in one run, the system should identify the repeated read and return enough metadata to prevent a loop while preserving the ability to continue intentionally.
- If a path attempts to escape the authorized workspace through relative traversal, absolute paths, or symbolic links, read-only inspection is an exceptional escape hatch that should require high-risk confirmation with a safe summary, while writes, deletes, patches, and execution against that path should be rejected.
- If multiple tool calls try to mutate the same file concurrently, file mutation should be serialized or rejected so no write silently overwrites another.
- If a tool result hook, compression step, or artifact write fails, the original tool call must still produce exactly one paired result with a clear warning and safe fallback content.
- If a background process outlives the initiating Agent turn within the same sidecar session, later inspection should show whether it is still active, completed, timed out, or was terminated.
- If the sidecar restarts, previous background process records should be marked unavailable rather than treated as manageable live processes.
- If media or binary output is produced, raw bytes or base64 data should not enter the Agent conversation directly, but recoverable references should remain valid across sidecar restart until retention cleanup removes them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a stable, structured success and failure contract for built-in foundational tools, including tool identity, outcome, user-actionable data, permission scope, truncation status, and stable error codes.
- **FR-002**: The system MUST migrate affected built-in tool call sites to the new contract in the same delivery slice and MUST NOT preserve legacy parameter or result-format compatibility as an acceptance requirement.
- **FR-003**: The system MUST resolve file paths against an authorized workspace boundary and classify attempts that target external, system, hidden, or linked locations before reading, writing, deleting, or executing against them; outside-workspace reads require high-risk confirmation, while outside-workspace writes, deletes, patches, and execution are rejected.
- **FR-004**: The system MUST support bounded text file reading with line-window navigation, total/remaining indicators, optional line numbering, and clear behavior for large files.
- **FR-005**: The system MUST detect unsupported binary or media reads and return metadata or an explicit unsupported outcome without placing raw binary content into the Agent conversation.
- **FR-006**: The system MUST redact common sensitive values from read and output results while preserving surrounding context needed for the Agent to continue.
- **FR-007**: The system MUST detect repeated read requests for the same bounded content window within a run and return loop-prevention metadata without blocking legitimate follow-up reads.
- **FR-008**: The system MUST support file creation and replacement with post-write verification and a concise change summary; creating a new file may omit a baseline, but replacing an existing file MUST require a current baseline unless a future explicit force mode is separately specified, high-risk confirmed, and tested.
- **FR-009**: The system MUST reject existing-file mutations before content changes when the caller omits a required baseline or provides a baseline that no longer matches the current file; this applies to replace, edit, delete, and update/delete patch operations.
- **FR-010**: The system MUST support targeted file edits using single or multiple non-overlapping replacement operations, with an explicit mode for replacing all matching occurrences.
- **FR-011**: The system MUST preserve unchanged file text style, including line-ending convention and leading file markers, during edits whenever the original file style is detectable.
- **FR-012**: The system MUST return useful failure context for failed edits, including nearby candidate locations when available and a recommendation to reread an appropriate content window.
- **FR-013**: The system MUST support multi-file patch operations for adding, updating, and deleting files inside the authorized workspace, with dry-run-equivalent validation before mutation, required baselines for update/delete operations, and verification after mutation.
- **FR-014**: The system MUST provide structured file-name search with bounded results, common generated/dependency directories excluded by default, deterministic sorting, and continuation metadata.
- **FR-015**: The system MUST provide structured content search with match grouping, line numbers, optional context, multiple output modes, bounded results, and continuation metadata.
- **FR-016**: The system MUST classify built-in tools and command requests by risk level so read-only, workspace-mutating, and elevated-risk actions can be allowed, confirmed, or denied consistently.
- **FR-017**: The system MUST retain the existing high-risk confirmation behavior, including fail-closed handling when confirmation is unavailable or interrupted.
- **FR-018**: The system MUST provide terminal execution results that include status, exit outcome, timeout classification, bounded output, and whether additional raw output is available.
- **FR-019**: The system MUST support background process lifecycle operations for listing, polling, reading logs, waiting, stopping, sending input, and closing process records within the current sidecar process session.
- **FR-020**: The system MUST prevent duplicate long-running process starts when the Agent is attempting to inspect or continue an existing process.
- **FR-021**: The system MUST compact large tool results before they enter the Agent conversation while preserving critical success/failure facts and a persistently recoverable reference to full raw output when needed.
- **FR-022**: The system MUST ensure every executed tool call still produces exactly one paired tool result after compression, fallback, rejection, or failure handling.
- **FR-023**: The system MUST keep full raw output, media payloads, and sensitive local details out of ordinary Agent-visible text unless explicitly requested through an authorized reference-loading path, and persistent references must be governed by retention and cleanup policy.
- **FR-024**: The system MUST expose enough metadata for later debugging and testing of tool permissions, truncation, compression mode, verification status, and artifact references.
- **FR-025**: The system MUST provide automated coverage for file reading, file mutation, search, patching, command execution, process lifecycle, permission boundaries, confirmation fail-closed behavior, and tool-result compaction.
- **FR-026**: The system MUST define all new runtime tunables for tool caps, retention, workspace policy, process limits, and output governance through the unified configuration boundary or explicitly mark them as fixed constants with rationale.
- **FR-027**: The system MUST expose log-safe runtime health metadata for compacted outputs, raw-reference creation/load failures, stale mutation rejections, process cleanup, confirmation fail-closed decisions, and retention cleanup failures.

### Key Entities *(include if feature involves data)*

- **Built-in Foundational Tool**: A shared Agent capability for file access, search, patching, terminal execution, process lifecycle, or result recovery.
- **Tool Result Envelope**: The structured outcome returned by a built-in tool, including success or failure data, user-actionable metadata, and stable error information.
- **Authorized Workspace**: The file and command boundary within which normal read and write operations may occur without elevated handling.
- **Permission Decision**: The classification and outcome for a tool request, including read-only, workspace mutation, elevated-risk, allowed, rejected, or confirmation-required status.
- **File Baseline**: A caller-provided identifier representing the file content previously observed by the Agent and used to detect stale mutations.
- **Patch Summary**: A concise description of multi-file changes, including operation type, affected path, verification status, and rejection reason when applicable.
- **Process Record**: A tracked command execution that may continue beyond the initiating tool call and can later be inspected, waited on, or stopped during the current sidecar session.
- **Tool Output Reference**: A persistently recoverable pointer to full raw output or media metadata that is not placed directly into the Agent conversation and remains valid across sidecar restart until retention cleanup removes it.

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: The scope is limited to Agent built-in foundational tools; user-created business tools, recorded workflow tools, and specialist methodology assets are not redefined by this feature.
- **CC-002**: Existing AgentLoop tool-call and tool-result pairing semantics must be preserved for single-tool and multi-tool turns.
- **CC-003**: Existing high-risk confirmation semantics must remain session-scoped, fail-closed, and must not persist "allow all" decisions outside the current process session.
- **CC-004**: Tool permission and confirmation summaries must avoid logging or displaying full file contents, full replacement text, complete multi-line command bodies, credentials, or raw large outputs.
- **CC-005**: UI and desktop API layers must not directly manage built-in tool execution state; any future user-visible state must pass through the established bridge and public event contracts.
- **CC-006**: Configuration and storage choices introduced for retention, thresholds, or persistent artifact references must use the project's unified configuration and secure-data boundaries.
- **CC-007**: Search, file mutation, patching, and terminal capabilities must reject attempts to mutate or execute against targets outside the authorized workspace; read-only outside-workspace inspection is the only external-path operation eligible for high-risk confirmation.
- **CC-008**: The migration may be staged by tool family, but each delivered slice must switch its affected call sites fully to the new contract rather than maintaining a dual legacy/new compatibility window.
- **CC-009**: Outside-workspace reads are exceptional access, not normal Agent workflow; tool descriptions and confirmation summaries must present them as high-risk inspection only and must not encourage broad filesystem exploration.

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

Which layers are affected? Check all that apply:

- [ ] **UI** (`frontend/src/`, `src-tauri/`) — React screens, state, API client, Tauri shell, or window commands
- [ ] **Desktop API Bridge** (`src/desktop_api/`) — FastAPI routers, schemas, event stream adapters, or sidecar contracts
- [x] **Business** (`src/business/`) — agents, orchestration, services, memory
- [x] **Execution** (`src/execution/`) — tool execution sandbox
- [x] **Data** (`src/data/`) — models, repositories, migrations, config
- [ ] **Recording** (`src/recording/`) — recorder, filtering, browser extension
- [x] **Utils** (`src/utils/`) — events, helpers

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: Assistant and any Agent using shared built-in foundational tools; PM, Programmer, and Trial are affected only when they receive these shared built-ins.
- New tools or modified tool handlers? Built-in file, search, patch, terminal, process, and output-recovery capabilities are in scope.
- System prompt changes needed? Agent-facing tool descriptions must explain bounded reads, baseline-based mutations, permission outcomes, process lifecycle, and output references.
- Orchestrator dispatch changes? Tool filtering and confirmation behavior must honor the new permission classification without breaking existing dynamic tool assembly.

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): Persistent output-reference metadata may be introduced only through Repository boundaries with explicit retention rules; process control state must not be persisted as long-term business data.
- **DuckDB** (`src/recording/filtering/`): No recording analysis data changes are in scope.
- **Config** (`src/data/unified_config.py`): Thresholds, retention limits, workspace policy, and output caps must be configurable through the unified configuration boundary if they are not fixed constants.
- **Secrets** (keyring): No new secret values are required; any sensitive values discovered in files, command output, or artifacts must be redacted from ordinary results.

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: None required by the specification unless implementation exposes process or tool-output state to another backend module.
- Modified event payloads: None expected for the core feature.
- New event listeners: None expected for the core feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In test fixtures covering small text, large text, binary, media, and secret-like files, 100% of read attempts return bounded structured outcomes with correct continuation, refusal, or redaction behavior.
- **SC-002**: In mutation safety tests, 100% of existing-file replace/edit/delete/update attempts without a required baseline or with an outdated baseline are rejected before file content changes.
- **SC-003**: In patch boundary tests, 100% of patch operations targeting outside the authorized workspace are rejected before mutation.
- **SC-004**: In search fixtures with generated/dependency directories, search results exclude default ignored locations and return no more than the configured page size while reporting whether more results exist.
- **SC-005**: In command-output tests with at least 100,000 characters of output, visible tool results remain below the configured conversation cap while preserving raw-output recovery for every oversized result before and after sidecar restart.
- **SC-006**: In failure-output tests for representative command categories, the compacted visible result preserves the failing item name, primary error message, and final summary in 100% of cases.
- **SC-007**: In multi-tool AgentLoop tests, every executed, rejected, interrupted, compacted, or fallback built-in tool call produces exactly one paired tool result.
- **SC-008**: In high-risk action tests, confirmation failures, timeouts, or disconnections deny the action in 100% of cases.
- **SC-009**: For each delivered tool family, 100% of affected internal call sites and tests use the new built-in tool contract, with no remaining dependency on legacy parameter or result formats.
- **SC-010**: In Agent continuation tests, the Agent can use returned `nextPageToken` or line-window metadata, `baseline_required` / `baseline_stale` next-action guidance, and `load_tool_output` references to continue successfully in 100% of scripted scenarios.
- **SC-011**: Runtime health tests verify log-safe counters or structured diagnostics for compacted outputs, raw-reference create/load failures, stale mutation rejections, process cleanup, confirmation fail-closed outcomes, and retention cleanup failures without exposing raw secrets or local artifact paths.

## Assumptions

- The authorized workspace defaults to the current Agent workspace root for the active session unless a future plan explicitly narrows or expands that boundary.
- Cross-workspace or system-path reads are exceptional and proceed only after high-risk confirmation; all external mutation, deletion, patching, or execution attempts are rejected.
- The first delivery slice prioritizes stable result contracts, path safety, paginated reads, baseline-required existing-file mutations, and AgentLoop pairing before search, terminal, and compaction enhancements.
- No force mutation mode is included in the MVP. If a later plan introduces one, it must be explicit in the tool schema, high-risk confirmed, and covered by confirmation-summary leak tests.
- Process records are session-scoped to the current sidecar process; sidecar restart invalidates process management records rather than restoring live process control.
- Raw output and media references are persistently recoverable only through authorized tool paths, remain available across sidecar restart until retention cleanup, and are not shown as ordinary UI text or ordinary Agent conversation content.
- User-facing UI changes are out of scope for the initial specification unless planning discovers a required bridge for observability or confirmation display.
