# Data Model: 录制数据大字段按需读取

## Entities

### 1. LargeFieldConfig

Runtime configuration loaded through unified config (namespace `recording.large_field.*`).

| Field | Type | Notes |
|-------|------|-------|
| `threshold_chars` | `int` | Trigger threshold; any text result-cell with `len(value) >= threshold_chars` becomes a placeholder. Default: `1000` |
| `preview_chars` | `int` | Maximum preview prefix included in the placeholder. Default: `1000` |
| `max_chunk_chars` | `int` | Maximum `content` characters returned by one `read_field_chunk` call (also the default when the caller omits `length`). Default: `1000` |

Validation rules:
- `threshold_chars`, `preview_chars`, and `max_chunk_chars` must all be positive integers.
- No mandated ordering between `preview_chars` and `threshold_chars`; aligning at `1000 / 1000 / 1000` is the default but `preview_chars > threshold_chars` is permitted (preview will simply equal the full value when the field is just over threshold).

### 2. StableLocatorRule

Built-in metadata that maps a source table to the stable locator fields used by `describe_data` and `read_field_chunk`. **Not a field allow-list** for `query_data` placeholder replacement.

| Field | Type | Notes |
|-------|------|-------|
| `table` | `str` | Source table name. v1 built-in rules MUST include `network_requests`, `actions`, and `sibling_snapshots` |
| `recommended_id_field` | `str` | Stable locator column for one rule: `request_id` for `network_requests`, `action_id` for `actions`, `snapshot_id` for `sibling_snapshots` |
| `describe_locator_fields` | `list[str]` | Fields `describe_data` should surface as required for continuation. v1 usually contains the single `recommended_id_field`; the list shape keeps the contract extensible |

Relationships:
- `describe_data` inspects current DuckDB schema and, for text columns in a table covered by a `StableLocatorRule`, must expose machine-readable `large_field` / `read_via` / `locator_fields` hints.
- Text columns in tables not covered by a `StableLocatorRule` must not be advertised as continuation-capable by `describe_data`; they can still produce `query_data` placeholders with `locator = null` when they reach `threshold_chars`.
- Placeholder replacement is **not** restricted to named fields: any text result cell can produce a placeholder. Continuation is narrower: it is available only when SQL projection lineage points to a table covered by `StableLocatorRule` and the same row carries that rule's stable ID field.

### 3. ProjectionBinding

Internal analysis result produced from the SQL AST.

| Field | Type | Notes |
|-------|------|-------|
| `output_name` | `str` | Result-column name after aliasing |
| `source_table` | `str \| None` | Canonical source table if the expression is a direct column |
| `source_field` | `str \| None` | Canonical source column if the expression is a direct column |
| `is_direct_column` | `bool` | `true` for direct column selection or simple alias only |

Validation rules:
- Computed expressions, aggregates, concatenations, and function calls must produce `is_direct_column = false`.
- Any non-null text result value can trigger placeholder replacement when it reaches `threshold_chars`; a direct binding is only required for locator extraction and continuation.

### 4. LargeFieldLocator

Structured pointer that lets `read_field_chunk` re-read one raw source value.

| Field | Type | Notes |
|-------|------|-------|
| `table` | `str` | Source table name covered by a built-in `StableLocatorRule` |
| `id_field` | `str` | Stable key column declared by that table's `StableLocatorRule` |
| `id_value` | `int \| str` | JSON scalar identifier copied from the query result row |

Validation rules:
- `table` must exist in the recording DuckDB schema and be covered by a built-in `StableLocatorRule`.
- `id_field` must match the stable identifier declared by the `StableLocatorRule` for `table`. Non-rule columns are rejected even if they look unique.
- `id_value` must be present and non-null in the same result row for readable placeholders.
- `locator = null` is the only allowed blocked state (paired with `read_blocked_reason`).

### 5. LargeFieldPlaceholder

Structured value returned by `query_data` instead of raw content.

| Field | Type | Notes |
|-------|------|-------|
| `__large_field__` | `bool` | Literal sentinel, always `true` |
| `field` | `str` | Unqualified source field name when derivable; otherwise the result-column name (e.g. for computed columns) |
| `size_chars` | `int` | Character count of the raw stored value (Python `len()` of the unicode string) |
| `preview` | `str` | Controlled raw prefix preview, length `<= preview_chars` |
| `locator` | `LargeFieldLocator \| null` | Continuation pointer when available |
| `read_hint` | `str` | Literal `read_field_chunk` |
| `read_blocked_reason` | `str \| null` | Stable enum value; present only when `locator` is `null` |
| `read_blocked_message` | `str \| null` | Optional human-readable explanation; present only when `locator` is `null` |

Validation rules:
- Emitted whenever a result cell is a non-null text value with `len(value) >= threshold_chars`. **No allow-list gate**.
- `locator` is populated only when (a) `ProjectionBinding.is_direct_column` is true, (b) the source `(table, field)` exists in DuckDB schema as a text column, (c) `table` is covered by a built-in `StableLocatorRule`, AND (d) a same-row direct projection of that rule's stable ID column is available with a non-null scalar value.
- `read_blocked_reason` is required whenever `locator` is `null`. Allowed placeholder-blocking values include but are not limited to: `missing_locator_field`, `computed_or_aggregated_column`, `ambiguous_locator_source`, `unsupported_source_table`.
- Non-text result values do not trigger placeholders; attempts to chunk-read a non-text source field use the `read_field_chunk.error.code` path.
- `read_blocked_message` is optional and carries the human-readable explanation; agents and tests should rely on `read_blocked_reason` for stable branching.

### 6. ChunkReadRequest

Input payload for `read_field_chunk`.

| Field | Type | Notes |
|-------|------|-------|
| `locator` | `LargeFieldLocator` | Required structured pointer |
| `field` | `str` | Unqualified source field name |
| `offset` | `int` | Character offset, zero-based |
| `length` | `int \| null` | **Optional**. Requested character length before server-side capping. Omitted/null → defaults to `max_chunk_chars` |

Validation rules:
- `offset >= 0` (else `error.code = "invalid_offset"`)
- `length > 0` when provided (else `error.code = "invalid_length"`)
- `locator.table` must exist in DuckDB schema (else `error.code = "unknown_table"`) and be covered by a built-in `StableLocatorRule` (else `error.code = "unsupported_continuation"`)
- `field` must exist as a text column of `locator.table` in DuckDB schema (else `error.code = "field_not_found"` or `"non_text_field"`)
- For `locator.table == "network_requests"`: read must go through the filtered SQL rewrite path (not raw DuckDB). If the record is filtered out, return `error.code = "record_unavailable"`.
- Effective return length is `min(length or max_chunk_chars, max_chunk_chars)`.

### 7. ChunkReadResponse

Unified response payload from `read_field_chunk`. Same shape for success and failure; the `error` field discriminates.

| Field | Type | Notes |
|-------|------|-------|
| `content` | `str` | Raw text slice returned for this window. `""` on failure or EOF |
| `field` | `str` | Echoed source field name |
| `locator` | `LargeFieldLocator \| null` | Echoed validated locator; `null` if validation failed before locator was confirmed |
| `offset` | `int` | Starting offset used for the slice |
| `returned_length` | `int` | Actual character count returned. `0` on failure or EOF |
| `total_length` | `int \| null` | Full raw value length in characters. `null` if not computable (e.g. record not found) |
| `has_more` | `bool` | Whether more content remains. `false` on failure or EOF |
| `next_offset` | `int \| null` | Next suggested offset; `null` on failure or EOF |
| `error` | `{code: str, message: str} \| null` | `null` for success; non-null structured error otherwise |

Validation rules:
- `error == null`:
  - `returned_length = len(content)`
  - If `offset >= total_length`: `content = ""`, `returned_length = 0`, `has_more = false`, `next_offset = null`
  - If `has_more = true`: `next_offset = offset + returned_length`
- `error != null`:
  - `content = ""`, `returned_length = 0`, `has_more = false`, `next_offset = null`
  - `total_length` is filled if known; else `null`
  - `code` is one of the enumerated stable identifiers below

### 8. ChunkReadError codes (enumeration)

| `error.code` | Trigger |
|--------------|---------|
| `invalid_offset` | `offset < 0` |
| `invalid_length` | `length <= 0` when explicitly provided |
| `unknown_table` | `locator.table` not in DuckDB schema |
| `field_not_found` | `field` not a column of `locator.table` |
| `non_text_field` | `field` exists but is not a text column |
| `unknown_id_field` | `locator.id_field` not a stable identifier of `locator.table` |
| `record_unavailable` | Record not found, deleted, or filtered out (also covers `network_requests` filter exclusions) |
| `unsupported_continuation` | Locator references a computed/aggregated/ambiguous source the validator refuses |
| `internal_error` | Unexpected exception (logged with traceback) |

## Relationships

- `LargeFieldConfig` controls threshold / preview / chunk-size tunables only.
- `ProjectionBinding` may resolve one source-table text column and, when the table is covered by `StableLocatorRule`, one matching stable ID binding per result row.
- `StableLocatorRule` provides the table-level locator metadata reused by `describe_data` hints and `read_field_chunk` validation.
- `LargeFieldPlaceholder` references zero or one `LargeFieldLocator`.
- `ChunkReadRequest` targets exactly one source-table text column.
- `ChunkReadResponse` is the paged continuation of one `LargeFieldPlaceholder`.

## State Transitions

### Query cell delivery

1. Raw value below threshold -> pass through unchanged.
2. Raw value at or above threshold + locator available -> readable placeholder.
3. Raw value at or above threshold + locator unavailable -> blocked placeholder with `read_blocked_reason`.

### Chunk reading lifecycle

1. First slice: `offset = 0`, returns initial content window.
2. Middle slice: `offset = next_offset`, returns another window with `has_more = true`.
3. Final slice: returns remaining content with `has_more = false`.
4. EOF request: returns empty-success shape.
5. Invalid locator, deleted record, or unsupported field: returns an error payload instead of a success object.
