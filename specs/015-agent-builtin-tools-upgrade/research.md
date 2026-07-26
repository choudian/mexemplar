# Phase 0 Research: Agent Built-in Tools Upgrade

## Decision: Use a versioned tool result envelope for every upgraded built-in tool

**Rationale**: Existing built-ins return tool-specific JSON strings or plain standardized errors. A shared envelope gives AgentLoop, tests, and future tooling one stable place for tool identity, outcome, error codes, permission metadata, truncation, verification, and raw-output references. Handlers can still return a JSON string to preserve the current `ToolDefinition.handler -> str` runtime contract.

**Alternatives considered**:
- Return Python objects from handlers. Rejected because `AgentLoop` currently persists string content and many tests assert tool result text.
- Keep per-tool JSON shapes. Rejected because FR-001, FR-021, and FR-024 require common governance metadata.

## Decision: Keep `builtin_general_tools.py` as registry facade and split implementation modules

**Rationale**: Many call sites import `BUILTIN_GENERAL_TOOLS` from the existing module. Keeping that facade avoids unnecessary import churn while allowing file, search, command, permission, and output governance code to be tested independently.

**Alternatives considered**:
- Replace the module with a package in one step. Rejected because it increases migration risk without improving the public contract.
- Keep all implementation in one file. Rejected because path policy, patching, process lifecycle, and compaction would become hard to verify.

> **Amendment 2026-07-26**: The "outside-workspace mutation is rejected" stance below is
> reversed for `write/edit/delete/patch` under a user-enabled process-session "allow_all"
> toggle — they now route through the high-risk confirmation chain (audited
> `auto_approved`/`auto_scope`), still rejected by default. Outside-workspace execution is
> unchanged (still rejected). See `docs/PROJECT_CONSTRAINTS.md` and the controlled-exception
> registry in `.specify/memory/constitution.md`.

## Decision: Enforce workspace policy with canonical resolved paths before handler mutation or execution

**Rationale**: The spec distinguishes external reads from external writes/deletes/patches/execution. A central policy object can resolve relative traversal, absolute paths, hidden/system/link targets, and symlink escapes consistently before any handler side effect. Outside-workspace reads become high-risk confirmation candidates; outside-workspace mutation and execution are rejected.

**Alternatives considered**:
- Leave checks in each handler. Rejected because current behavior already duplicates path logic and misses workspace authorization.
- Let the shell or OS fail unsafe operations. Rejected because FR-003 and FR-007 require explicit classification and stable error codes before side effects.

## Decision: Use raw-byte content hashes as file baselines

**Rationale**: A baseline must detect stale mutations even when line endings, encodings, or timestamps behave differently across platforms. The read tool returns a baseline id derived from raw bytes plus metadata such as size and modified time for debugging. Existing-file replace, edit, delete, and patch update/delete operations require a current baseline by default; new file creation may omit it only when the target path does not exist.

**Alternatives considered**:
- Use only modified time. Rejected because timestamp granularity and copy operations can miss changes.
- Use decoded text hashes. Rejected because encoding fallback and newline normalization can hide byte-level changes that matter for safe writes.
- Make baseline optional for existing-file replacement. Rejected because it weakens the feature's primary stale-write safety promise.

## Decision: Preserve text style during edits by carrying source style metadata through mutation planning

**Rationale**: Existing `edit_file` reads and writes UTF-8 text directly, which can change line endings or markers. The upgraded edit flow should detect BOM, dominant newline, final newline, and leading file marker style, apply replacements to decoded text, then encode back using the detected style unless the caller explicitly creates a new file.

**Alternatives considered**:
- Always write UTF-8 with `\n`. Rejected because FR-011 requires preserving detectable style.
- Require callers to provide style options. Rejected because Agents should not need to infer routine file formatting manually.

## Decision: Implement search as structured repository traversal, not ad hoc shell parsing

**Rationale**: File-name and content search need deterministic sorting, default ignore directories, bounded pages, stable error codes, and continuation metadata. Native traversal and text scanning keep the contract independent of shell quoting and platform-specific output formats. An optimized adapter may use `rg --json` behind the same structured contract when large-repository fixtures exceed configured traversal or elapsed-time caps.

**Alternatives considered**:
- Shell out to `rg` and parse text output. Rejected because FR-014/FR-015 require stable pagination and error metadata.
- Reuse `exec` for search. Rejected because command output governance is not a search API.

## Decision: Keep background process records process-local and persist only recoverable output artifacts

**Rationale**: Clarification says process records are valid only within the current sidecar process session. Live handles cannot survive restart, so `ProcessManager` should live in `src/execution/` memory. Oversized logs or outputs that need post-restart recovery become `ToolOutputReference` artifacts with durable metadata and blob storage.

**Alternatives considered**:
- Persist process records in SQLite and restore them. Rejected because live OS process control is not recoverable after sidecar restart.
- Store all logs only in memory. Rejected because FR-021/FR-023 require persistent raw-output references.

## Decision: Store raw-output references as SQLite metadata plus filesystem blobs

**Rationale**: SQLite is appropriate for lookup, ownership, retention, and cleanup metadata; filesystem blobs are better for large text/media payloads and avoid bloating transaction tables. Business logic accesses metadata through `ToolOutputRepository`; ordinary Agent-visible text receives only reference ids and bounded previews.

**Alternatives considered**:
- Store raw output directly in `messages.content`. Rejected because it conflicts with conversation caps and redaction boundaries.
- Store large blobs directly in SQLite BLOB columns. Rejected because command/media output can grow large and cleanup is simpler with file-backed artifacts plus metadata.

## Decision: Define tool caps and retention through explicit unified configuration keys

**Rationale**: Constitution requires runtime settings to flow through unified config. File windows, search traversal, visible output caps, raw-reference thresholds, retention days, and process limits are operationally important and must have deterministic defaults, validation, template entries, and documentation before implementation tasks are generated.

**Alternatives considered**:
- Hard-code thresholds in handler modules. Rejected because it violates project configuration governance and makes tuning unsafe.
- Expose the settings in the frontend immediately. Rejected for the initial delivery because these are engineering guardrails, not user-facing workflow preferences.

## Decision: Run result compaction at a single AgentLoop save boundary, not as a post-hook pipeline

**Rationale**: Existing post-hook semantics intentionally do not form a result pipeline and errors fall back to the original handler result. FR-022 requires exactly one paired tool result across success, failure, rejection, fallback, and compaction. A dedicated governance step immediately before saving the tool result can compact, redact, create raw references, and still return one final envelope string.

**Alternatives considered**:
- Add a global post-hook for compaction. Rejected because injected tools skip hooks, post-hook exceptions revert to original output, and multiple post-hooks would make result ownership ambiguous.
- Compact later in memory compression. Rejected because oversized raw output would already have entered the persisted conversation.

## Decision: No public UI event changes in the initial plan

**Rationale**: Core built-in execution state remains internal to the Agent runtime. Existing confirmation UI behavior must be retained, but new user-visible process/output management is not required by the spec. If later UI observability is added, it must go through `src/desktop_api/ui_events.py` Registry and typed payloads.

**Alternatives considered**:
- Emit new process events immediately. Rejected because the feature can be tested through tool contracts without expanding the public UI event surface.
