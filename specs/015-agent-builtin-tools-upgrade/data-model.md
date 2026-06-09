# Data Model: Agent Built-in Tools Upgrade

## Entity: BuiltinToolRequest

Represents one Agent-requested built-in tool call after function-call argument parsing.

Fields:
- `tool_name`: stable built-in tool name.
- `tool_call_id`: provider tool-call id, used for AgentLoop pairing.
- `session_id`: Agent session id that owns the call.
- `agent_type`: PM, Programmer, Trial, Assistant, ephemeral subagent, or specialist.
- `arguments`: raw parsed arguments before handler execution; hooks receive a read-only copy.
- `workspace_root`: authorized workspace root for this run.
- `requested_at`: timestamp for audit/debug metadata.

Validation:
- `tool_call_id` must be non-empty when the call comes from an LLM response.
- `workspace_root` must be resolved before permission classification.

## Entity: ToolResultEnvelope

Shared Agent-visible result wrapper for upgraded built-in tools.

Fields:
- `schemaVersion`: integer, starts at `1`.
- `tool`: built-in tool name.
- `outcome`: `success`, `error`, `rejected`, `unsupported`, `timeout`, `background_started`, `not_executed`, or `confirmation_required`.
- `payload`: tool-specific bounded data.
- `error`: optional `ToolError`.
- `permission`: optional `PermissionDecision`.
- `limits`: optional truncation, pagination, byte, line, and cap metadata.
- `references`: optional list of `ToolOutputReference` handles.
- `warnings`: optional user-actionable warning strings.
- `verification`: optional `VerificationResult`.
- `createdAt`: ISO timestamp.

Validation:
- `schemaVersion` is required.
- `outcome != success` requires `error.code` unless the result is a background start with no failure.
- Raw binary, base64 media, full unredacted secrets, and unbounded command output are forbidden in `payload`.

## Entity: ToolError

Stable failure descriptor for LLM-visible and testable outcomes.

Fields:
- `code`: stable snake_case code.
- `message`: concise safe explanation.
- `retryable`: boolean.
- `nextAction`: optional instruction such as reread, retry with baseline, request confirmation, inspect process, or load reference.
- `details`: optional bounded structured data with no raw secret or raw blob content.

Initial error-code catalog:
- `path_not_found`
- `path_not_file`
- `path_not_directory`
- `path_outside_workspace`
- `path_hidden_or_system`
- `permission_denied`
- `confirmation_failed_closed`
- `unsupported_binary`
- `decode_failed`
- `baseline_required`
- `baseline_stale`
- `edit_target_not_found`
- `edit_target_not_unique`
- `patch_validation_failed`
- `search_pattern_invalid`
- `command_rejected`
- `command_timeout`
- `process_not_found`
- `process_unavailable_after_restart`
- `output_reference_not_found`
- `output_reference_expired`
- `compaction_failed_fallback`
- `internal_error`

## Entity: PermissionDecision

Records how the request was classified before execution.

Fields:
- `scope`: `workspace`, `external`, `system`, `hidden`, or `linked_external`.
- `risk`: `read_only`, `workspace_mutation`, `elevated`, or `denied`.
- `decision`: `allowed`, `confirmation_required`, `confirmed`, `rejected`, or `denied`.
- `summary`: safe confirmation/audit summary.
- `reason`: stable reason string.

Validation:
- External read may be `confirmation_required` or `confirmed`.
- External write, delete, patch, and execution must be `denied`.
- `summary` must not contain full file content, full replacement text, full command bodies, credentials, or raw large output.

## Entity: FileContentWindow

Bounded text read result.

Fields:
- `path`: normalized display path.
- `fileType`: `text`, `binary`, `media`, `unsupported`, or `missing`.
- `encoding`: detected or requested encoding.
- `lineStart`: first one-based line returned.
- `lineEnd`: last one-based line returned.
- `totalLines`: total line count when available.
- `hasMoreBefore`: boolean.
- `hasMoreAfter`: boolean.
- `content`: redacted content window.
- `lineNumbers`: optional line-numbered rows.
- `baseline`: `FileBaseline`.
- `redactions`: list of redaction categories and counts.
- `repeatRead`: optional `RepeatReadObservation`.

Validation:
- Text content must respect configured line and character caps.
- Binary/media reads must not include raw bytes in `content`.

## Entity: RepeatReadObservation

Loop-prevention metadata for repeated bounded reads in one Agent run.

Fields:
- `windowKey`: hash of resolved path, line window, encoding, and content baseline.
- `seenCount`: number of times this window was requested in the current run.
- `recommendation`: safe hint, usually "request a different window or explain why rereading is intentional".

Validation:
- Repeated reads are not blocked; metadata is advisory.

## Entity: FileBaseline

Caller-provided identifier for stale mutation detection.

Fields:
- `baselineId`: stable id derived from raw-byte hash and file identity metadata.
- `sha256`: raw-byte content hash.
- `sizeBytes`: current file size.
- `modifiedAt`: filesystem modified timestamp if available.
- `observedAt`: read timestamp.
- `path`: resolved path at observation time.

Validation:
- Existing-file replace, edit, delete, and patch update/delete operations require a current baseline by default.
- New file creation may omit a baseline only when the resolved path does not already exist.
- Mutating tools compare current raw-byte hash with `sha256` when resolving `expectedBaselineId` or `expectedSha256`.
- Missing required baseline rejects with `baseline_required`; stale mismatch rejects with `baseline_stale` before mutation.

## Entity: FileMutationPlan

Validated mutation before disk write.

Fields:
- `operation`: `create`, `replace`, `edit`, or `delete`.
- `path`: resolved target path.
- `expectedBaseline`: required `FileBaseline` for existing-file replace, edit, delete, and patch update/delete; omitted only for new-file create.
- `replacements`: ordered list of replacement operations for edits.
- `preservedStyle`: detected `TextStyle`.
- `dryRunSummary`: affected line ranges and byte counts.

Validation:
- Targets must be inside workspace.
- Replacement ranges must be non-overlapping.
- Existing-file mutation without `expectedBaseline` rejects before mutation.
- Stale baselines reject before mutation.

## Entity: TextStyle

Detected style that should survive unchanged regions.

Fields:
- `encoding`: detected or selected encoding.
- `bom`: boolean.
- `newline`: `lf`, `crlf`, `cr`, or `mixed`.
- `finalNewline`: boolean.
- `leadingMarker`: optional marker such as shebang or coding cookie.

Validation:
- Style preservation is best-effort only when style is detectable.

## Entity: PatchOperation

One operation in a multi-file patch.

Fields:
- `operationId`: caller or system generated id.
- `type`: `add`, `update`, or `delete`.
- `path`: target path.
- `expectedBaseline`: required baseline for update/delete.
- `content`: bounded new content for add/update, excluded from confirmation summaries.
- `editOperations`: optional targeted replacements for update.

Validation:
- All operation paths must be inside the authorized workspace before any operation mutates disk.
- Update/delete operations without baselines reject before mutation.
- Patch validation is all-or-reject for unsafe targets; partial per-file rejections may be reported only before mutation.

## Entity: PatchSummary

Agent-visible patch result.

Fields:
- `operations`: ordered operation summaries.
- `affectedFiles`: count.
- `changedFiles`: list of path, operation type, old/new baseline ids, and verification.
- `rejected`: list of operation ids with stable error codes.

Validation:
- Summary must not include full added/replacement content.

## Entity: SearchQuery

Structured filename or content search request.

Fields:
- `root`: optional search root under workspace.
- `kind`: `files` or `content`.
- `pattern`: file glob, literal text, or regex depending on `mode`.
- `mode`: `glob`, `literal`, or `regex`.
- `includeHidden`: boolean.
- `contextLines`: content search context line count.
- `pageSize`: requested page size capped by config.
- `pageToken`: opaque continuation token.

Validation:
- Search root must be inside workspace.
- Default ignored generated/dependency directories are excluded unless explicitly included by a future safe option.

## Entity: SearchPage

Bounded search result page.

Fields:
- `matches`: file or content match summaries.
- `count`: count in this page.
- `hasMore`: boolean.
- `nextPageToken`: optional opaque token.
- `ignoredDefaults`: list of default ignore labels applied.
- `truncated`: boolean.

Validation:
- Sorting must be deterministic.
- Content matches must include file path and line numbers, with optional bounded context.

## Entity: CommandInvocation

Structured command execution request.

Fields:
- `command`: command string parsed into argv; shell control syntax is not supported.
- `cwd`: resolved working directory.
- `timeoutMs`: bounded timeout.
- `mode`: `sync` or `background`.
- `stdin`: optional bounded input.
- `risk`: permission classification.

Validation:
- `cwd` must be inside workspace.
- Launch uses argv with `shell=False`; shell hosts, inline interpreter code, and external path arguments are rejected.
- Elevated commands require existing high-risk confirmation and fail closed if confirmation is unavailable.
- External cwd or execution targets are rejected.

## Entity: ProcessRecord

In-memory record for a background command during the current sidecar process session.

Fields:
- `processId`: stable id for this sidecar session.
- `sessionEpoch`: sidecar process session id/epoch.
- `commandSummary`: safe one-line summary.
- `cwd`: workspace-relative display path.
- `status`: `running`, `completed`, `failed`, `timed_out`, `terminated`, `closed`, or `unavailable_after_restart`.
- `startedAt`: timestamp.
- `finishedAt`: optional timestamp.
- `exitCode`: optional integer.
- `recentOutput`: bounded stdout/stderr tail metadata.
- `outputReferences`: reserved for a future durable complete-log capture path; current process records expose only bounded ring-buffer tails.

Validation:
- Records are not persisted as manageable live processes.
- After sidecar restart, prior ids must resolve to `process_unavailable_after_restart` if mentioned through a durable reference path.

## Entity: ToolOutputReference

Persistently recoverable pointer to raw output or media metadata.

Fields:
- `referenceId`: stable opaque id.
- `kind`: `stdout`, `stderr`, `combined_output`, `file_snapshot`, `media`, or `tool_payload`.
- `toolName`: producing tool.
- `sessionId`: owning Agent session.
- `toolCallId`: source tool call id when available.
- `storageKey`: internal blob locator relative to the tool-output storage root, never shown as ordinary Agent text.
- `storageRootKind`: fixed value identifying the application data `tool_outputs` root.
- `sizeBytes`: raw stored size.
- `contentType`: MIME-like content type.
- `sha256`: blob hash.
- `createdAt`: timestamp.
- `expiresAt`: optional retention expiry.
- `redactionProfile`: profile used for visible preview.
- `status`: `active`, `expired`, or `deleted`.
- `ownerWorkspaceHash`: hash of the authorized workspace root, used for authorization checks without exposing the raw local path.

Validation:
- Metadata is stored in SQLite through `ToolOutputRepository`.
- Blob content is loaded only through an authorized reference-loading tool after session/workspace ownership checks.
- Ordinary visible results include `referenceId`, size, type, digest, and expiry metadata, not raw local paths or `storageKey`.
- `storageKey` and `ownerWorkspaceHash` may appear in database rows and debug-only diagnostics, but not in Agent-visible envelopes, public UI events, confirmation summaries, or ordinary logs.
- Expired or deleted references return stable errors and never reveal whether a local path exists.

## Entity: ToolOutputArtifactWrite

Transient write transaction used to create a durable `ToolOutputReference`.

Fields:
- `tempPath`: internal temporary blob path.
- `finalStorageKey`: internal final blob locator.
- `metadata`: pending `ToolOutputReference` metadata.
- `state`: `writing_blob`, `blob_finalized`, `metadata_committed`, or `failed`.
- `failureCode`: optional stable failure code for cleanup diagnostics.

Validation:
- Temporary paths are removed on failure when possible.
- The blob is atomically finalized before active metadata is committed; a metadata failure removes the finalized blob best effort.
- A failure returns one safe fallback envelope with `compaction_failed_fallback` and no active reference.

## Entity: ToolOutputAuthorization

Authorization context for loading raw-output references.

Fields:
- `referenceId`: requested reference.
- `requestingSessionId`: current Agent session.
- `requestingWorkspaceHash`: hash of the current authorized workspace root.
- `decision`: `allowed`, `denied`, `expired`, or `not_found`.
- `reason`: stable reason string.

Validation:
- Initial implementation allows owner-session/workspace scoped loading only.
- Cross-session loading is denied unless a later specification defines a broader trust boundary.

## Entity: VerificationResult

Post-mutation or post-write verification.

Fields:
- `status`: `verified`, `failed`, or `skipped`.
- `oldBaseline`: optional previous baseline id.
- `newBaseline`: optional new baseline id.
- `readback`: optional bounded readback metadata.
- `message`: concise safe status.

Validation:
- Successful mutations should include `newBaseline`.
- Verification failure must not silently mark a mutation successful without a warning.

## Relationships

- `BuiltinToolRequest` produces exactly one persisted Agent `tool` message through `ToolResultEnvelope`.
- `FileContentWindow` produces `FileBaseline`; `FileMutationPlan` consumes it.
- `PatchOperation` validates multiple `FileMutationPlan` records before any mutation.
- `CommandInvocation` may produce a session-scoped `ProcessRecord`.
- `ToolResultEnvelope.references[]` point to `ToolOutputReference` records.
- `ToolOutputReference` metadata is durable; `ProcessRecord` live control is not.
- `ToolOutputArtifactWrite` creates at most one active `ToolOutputReference`; failed writes must not leave an active metadata row.
- `ToolOutputAuthorization` gates every `load_tool_output` call before blob reads.

## State Transitions

ProcessRecord:

```text
running -> completed
running -> failed
running -> timed_out
running -> terminated
completed/failed/timed_out/terminated -> closed
any persisted mention after sidecar restart -> unavailable_after_restart
```

ToolOutputReference:

```text
creating -> active
creating -> deleted
active -> expired -> deleted
active -> deleted
```

ToolOutputArtifactWrite:

```text
writing_blob -> metadata_inserted -> finalized
writing_blob -> failed
metadata_inserted -> failed
```

File mutation:

```text
validated -> mutated -> verified
validated -> rejected
mutated -> verification_failed
```
