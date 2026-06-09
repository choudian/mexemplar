# Contract: Agent Foundational Built-in Tools

This contract defines the upgraded Agent-facing built-in tool surface. The implementation may stage tool families, but each migrated family must switch its affected call sites fully to these request/result shapes.

## Common Result Envelope

Every upgraded built-in returns a JSON string matching `tool-result-envelope.schema.json`.

Required top-level fields:
- `schemaVersion`: `1`
- `tool`: tool name
- `outcome`: stable outcome string
- `payload`: bounded tool-specific object
- `createdAt`: ISO timestamp

Common optional fields:
- `error`: stable `code`, safe `message`, `retryable`, and `nextAction`
- `permission`: scope/risk/decision metadata
- `limits`: pagination/truncation/cap metadata
- `references`: persistent raw-output references
- `warnings`: safe warning strings
- `verification`: post-write or post-execution verification metadata

Common outcome values:
- `success`
- `error`
- `rejected`
- `unsupported`
- `timeout`
- `background_started`
- `not_executed`
- `confirmation_required`

## Payload Safety Validators

The common JSON schema validates only the envelope shape. Each upgraded tool family must also validate its payload before it becomes Agent-visible:

- `read_file`: content window must be bounded and redacted; binary/media payloads must contain metadata only.
- `write_file` / `edit_file` / `apply_patch`: summaries must not contain full written content or full replacement text.
- `exec`: visible stdout/stderr must respect configured caps and attach raw-output references for oversized completed output.
- Process log tools: visible logs must respect the configured ring-buffer and response caps; they do not promise a durable complete-stream reference.
- `load_tool_output`: returned raw windows must be bounded, redacted, and authorized.

Validation failures return one safe fallback envelope with `compaction_failed_fallback` or `internal_error`; they must not create an additional tool result.

## High-Risk Confirmation Summaries

Confirmation summaries must be specific enough for a user decision but safe enough for logs/UI:

- Outside-workspace read: `Read outside workspace: <redacted display path>; reason: exceptional inspection`.
- File replace/edit: `Mutate workspace file: <relative path>; operation: replace|edit; baseline: <baseline id prefix>`.
- Command execution: `Run elevated command in workspace: <first redacted command line>`.

Summaries must not include full file contents, full replacement text, complete multi-line command bodies, credentials, raw large output, runtime tokens, local database paths, or raw artifact storage paths.

## Tool: `read_file`

Purpose: Inspect a bounded text window from a file, or safely report unsupported binary/media files.

Request:

```json
{
  "path": "src/business/agents/agent_loop.py",
  "startLine": 1,
  "maxLines": 200,
  "encoding": "utf-8",
  "includeLineNumbers": true
}
```

Response payload on text success:

```json
{
  "path": "src/business/agents/agent_loop.py",
  "fileType": "text",
  "encoding": "utf-8",
  "lineStart": 1,
  "lineEnd": 200,
  "totalLines": 1050,
  "hasMoreBefore": false,
  "hasMoreAfter": true,
  "content": "bounded and redacted text",
  "baseline": {
    "baselineId": "base_...",
    "sha256": "...",
    "sizeBytes": 12345
  },
  "redactions": []
}
```

Errors:
- `path_not_found`
- `path_not_file`
- `path_outside_workspace`
- `path_hidden_or_system`
- `unsupported_binary`
- `decode_failed`

Permission:
- Workspace read: allowed.
- Outside-workspace read: high-risk confirmation required; fail closed when confirmation is unavailable.

## Tool: `write_file`

Purpose: Create a new text file or replace an existing text file inside the authorized workspace. New file creation may omit a baseline. Existing file replacement requires a current baseline.

Request:

```json
{
  "path": "docs/example.md",
  "content": "# Example\n",
  "expectedBaselineId": "base_...",
  "encoding": "utf-8"
}
```

Rules:
- If `path` does not exist, `expectedBaselineId` may be omitted.
- If `path` exists, `expectedBaselineId` is required and must match the current raw-byte baseline.
- No force replace mode is part of the MVP contract.
- The visible result summarizes changed regions and verification only; it must not echo full `content`.

Response payload on success:

```json
{
  "path": "docs/example.md",
  "bytesWritten": 10,
  "created": false,
  "changeSummary": {
    "operation": "replace",
    "changedRegions": [{"lineStart": 1, "lineEnd": 1}]
  }
}
```

Verification:

```json
{
  "status": "verified",
  "oldBaseline": "base_previous",
  "newBaseline": "base_..."
}
```

Errors:
- `path_outside_workspace`
- `path_hidden_or_system`
- `permission_denied`
- `confirmation_failed_closed`
- `baseline_required`
- `baseline_stale`
- `internal_error`

Permission:
- Workspace mutation: allowed or confirmed according to configured risk rules.
- Outside-workspace write: rejected before mutation.

## Tool: `edit_file`

Purpose: Apply targeted replacements to an existing text file inside the workspace.

Request:

```json
{
  "path": "src/example.py",
  "expectedBaselineId": "base_...",
  "replacements": [
    {
      "oldText": "return False",
      "newText": "return True",
      "replaceAll": false
    }
  ]
}
```

Rules:
- `expectedBaselineId` is required and must match the current raw-byte baseline.
- Replacements must be non-overlapping after resolution.
- `replaceAll: false` requires exactly one match for `oldText`.
- The implementation preserves detectable newline, BOM, final newline, and leading marker style.

Errors:
- `path_not_found`
- `path_not_file`
- `path_outside_workspace`
- `baseline_required`
- `baseline_stale`
- `edit_target_not_found`
- `edit_target_not_unique`
- `permission_denied`

## Tool: `apply_patch`

Purpose: Validate and apply a coherent multi-file add/update/delete patch inside the workspace.

Request:

```json
{
  "operations": [
    {
      "operationId": "op1",
      "type": "add",
      "path": "src/new_file.py",
      "content": "print('ok')\n"
    },
    {
      "operationId": "op2",
      "type": "update",
      "path": "src/existing.py",
      "expectedBaselineId": "base_...",
      "replacements": [
        {"oldText": "old", "newText": "new", "replaceAll": false}
      ]
    }
  ]
}
```

Rules:
- All operation targets are resolved and authorized before any mutation.
- If any operation targets outside the workspace, the patch is rejected before mutation.
- `add` operations must target paths that do not already exist unless a future explicit replace mode is specified.
- `update` and `delete` operations require `expectedBaselineId`.
- Result reports operation type, affected path, old/new baseline, verification, and rejected operation codes.

Errors:
- `patch_validation_failed`
- `path_outside_workspace`
- `baseline_required`
- `baseline_stale`
- `edit_target_not_found`
- `edit_target_not_unique`

## Tool: `search_files`

Purpose: Return a deterministic bounded list of file paths matching a name/glob query.

Request:

```json
{
  "root": ".",
  "pattern": "*.py",
  "pageSize": 100,
  "pageToken": null,
  "includeHidden": false
}
```

Response payload:

```json
{
  "matches": [
    {"path": "src/business/agents/agent_loop.py", "type": "file", "sizeBytes": 40000}
  ],
  "count": 1,
  "hasMore": false,
  "nextPageToken": null,
  "ignoredDefaults": [".git", "node_modules", "__pycache__", "dist", "build"]
}
```

Errors:
- `path_not_directory`
- `path_outside_workspace`
- `search_pattern_invalid`

## Tool: `list_dir`

Purpose: Return a deterministic, bounded directory listing without exposing an absolute workspace path.

Rules:
- Workspace directories are listed with workspace-relative display paths.
- Hidden entries are omitted unless explicitly requested.
- Symlink entries are identified without following them to inspect external targets.
- Results are capped at 1000 entries and report truncation in `limits`.
- Outside-workspace listing follows the same exceptional high-risk confirmation policy as other read-only access.

Errors:
- `path_not_found`
- `path_not_directory`
- `path_outside_workspace`
- `path_hidden_or_system`
- `confirmation_failed_closed`

## Tool: `search_content`

Purpose: Search text content with grouped matches, line numbers, optional bounded context, and continuation metadata.

Request:

```json
{
  "root": ".",
  "pattern": "ToolDefinition",
  "mode": "literal",
  "includeGlobs": ["*.py"],
  "contextLines": 2,
  "pageSize": 50,
  "pageToken": null
}
```

Response payload:

```json
{
  "files": [
    {
      "path": "src/business/agents/config.py",
      "matches": [
        {
          "line": 65,
          "text": "class ToolDefinition:",
          "before": [],
          "after": []
        }
      ]
    }
  ],
  "matchCount": 1,
  "hasMore": false,
  "nextPageToken": null
}
```

Rules:
- Generated/dependency directories are excluded by default.
- Binary/media files are skipped and counted in metadata, not rendered.
- Secret-like values in context lines are redacted.

Errors:
- `path_not_directory`
- `path_outside_workspace`
- `search_pattern_invalid`

## Tool: `exec`

Purpose: Run a command in the authorized workspace with bounded synchronous output or start it as a managed background process.

Request:

```json
{
  "command": "uv run pytest tests/business/agents/test_builtin_file_tools.py",
  "cwd": ".",
  "timeoutMs": 120000,
  "mode": "sync"
}
```

Synchronous success payload:

```json
{
  "status": "completed",
  "exitCode": 0,
  "stdout": "bounded stdout",
  "stderr": "",
  "durationMs": 1234
}
```

Background start payload:

```json
{
  "processId": "proc_...",
  "status": "running",
  "commandSummary": "uv run python -m server",
  "logTail": ""
}
```

Rules:
- `cwd` must resolve inside workspace.
- Commands are parsed into argv and launched without a shell.
- Shell control syntax, shell hosts, inline interpreter code, explicit external executables, and path-like arguments outside the workspace are rejected before launch. The current Python runtime executable is the narrow exception used to run workspace scripts.
- Elevated commands require existing high-risk confirmation.
- Large output is compacted and accompanied by persistent `references`.
- Timeouts return `timeout` and keep raw output reference when output exists.

Errors:
- `path_outside_workspace`
- `command_rejected`
- `confirmation_failed_closed`
- `command_timeout`
- `internal_error`

## Process Lifecycle Tools

All process lifecycle tools are valid only in the current sidecar process session.

### `process_list`

Request:

```json
{"status": "running"}
```

Returns bounded process summaries.

### `process_poll`

Request:

```json
{"processId": "proc_..."}
```

Returns current status, exit code when finished, and recent log metadata.

### `process_logs`

Request:

```json
{"processId": "proc_...", "stream": "combined", "tailChars": 4000}
```

Returns only the bounded current-session ring-buffer tail. This endpoint does not retain or reference a complete process log stream.

### `process_wait`

Request:

```json
{"processId": "proc_...", "timeoutMs": 30000}
```

Waits for completion up to the timeout.

### `process_stop`

Request:

```json
{"processId": "proc_...", "force": false}
```

Stops the process and returns termination status.

### `process_send_input`

Request:

```json
{"processId": "proc_...", "text": "q\n"}
```

Sends bounded stdin when the process was started with input enabled.

### `process_close`

Request:

```json
{"processId": "proc_..."}
```

Closes the in-memory record after completion or termination.

Process errors:
- `process_not_found`
- `process_unavailable_after_restart`
- `process_limit_reached`
- `process_start_failed`
- `process_stop_failed`
- `process_input_failed`
- `permission_denied`
- `internal_error`

## Tool: `load_tool_output`

Purpose: Load a bounded window from a persistent raw-output reference.

Request:

```json
{
  "referenceId": "out_...",
  "offset": 0,
  "maxBytes": 64000,
  "renderAs": "text"
}
```

Response payload:

```json
{
  "referenceId": "out_...",
  "kind": "combined_output",
  "offset": 0,
  "bytesReturned": 1200,
  "hasMore": false,
  "content": "bounded and redacted raw output window"
}
```

Rules:
- The tool enforces authorization for the owning session/workspace context.
- Initial implementation allows owner-session/workspace scoped loading only; cross-session loading is denied unless a later specification broadens the trust boundary.
- Media/binary references return metadata unless a future authorized media path is explicitly added.
- Expired references return a stable error and no blob content.
- Responses must not expose raw blob paths, internal storage keys, local database paths, or unredacted secret-like values.

Errors:
- `output_reference_not_found`
- `output_reference_expired`
- `permission_denied`
- `unsupported_binary`
