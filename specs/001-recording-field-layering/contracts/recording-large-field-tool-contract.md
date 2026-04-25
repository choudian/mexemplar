# Recording Large-Field Tool Contract

## Scope

This contract defines the observable behavior added by the feature for `describe_data`, `query_data`, and the new `read_field_chunk` tool.

## 1. `describe_data` large-field metadata

For text fields surfaced by `describe_data(..., tables=[...])` in tables covered by a built-in `StableLocatorRule`, field-detail entries must keep the existing human-readable `warning` and add machine-readable continuation hints derived from current schema plus stable-locator metadata. These hints are not driven by a configurable field allow-list. Text fields in tables not covered by `StableLocatorRule` must not advertise continuation hints, but they can still be placeholdered by `query_data` with `locator = null` when they reach the threshold.

### Field detail additions

| Field | Type | Meaning |
|-------|------|---------|
| `large_field` | `bool` | `true` when the field participates in placeholder delivery and chunk reading through a stable locator rule |
| `read_via` | `str` | Fixed value `read_field_chunk` |
| `locator_fields` | `list[str]` | Stable ID columns the agent should include in `query_data` results to enable continuation |

### Example

```json
{
  "name": "response_body",
  "type": "TEXT",
  "description": "响应体",
  "warning": "⚠️ 大字段，可能几 KB ~ 几百 KB，按需查询",
  "large_field": true,
  "read_via": "read_field_chunk",
  "locator_fields": ["request_id"]
}
```

## 2. `query_data` placeholder contract

### Trigger rules

- Placeholder replacement applies to **any** result cell whose value is a non-null text string with `len(value) >= threshold_chars` (default `1000`). There is no allow-list gate; the prior `_MAX_QUERY_CELL_CHARS = 12000` blanket truncation is removed and replaced by this universal placeholder mechanism.
- Continuation via `read_field_chunk` is enabled only when the output column is a direct selection of an existing source-table text column (or a simple alias of one), the source table is covered by a built-in `StableLocatorRule`, **and** the same result row exposes that rule's stable ID column via direct selection or simple alias. Otherwise the placeholder still emits, but with `locator = null` and a structured `read_blocked_reason`.
- Function calls, concatenations, aggregates, casts, and other computed expressions still trigger placeholder replacement when the result reaches the threshold, but they always have `locator = null` because their lineage cannot be traced back to a single source record.
- Values below the configured threshold are returned unchanged.
- Once a value reaches the configured threshold, placeholder replacement still applies even if returning the raw value might produce a shorter JSON payload for that single result.

Supported continuation example:

```sql
SELECT nr.request_id, nr.response_body AS body, a.action_type
FROM network_requests nr
JOIN actions a ON a.recording_id = nr.recording_id
WHERE nr.request_id = 42
```

This remains eligible because `response_body` is still a direct large-field selection and the stable locator field `request_id` is present in the result with an unambiguous source-record mapping.

Unsupported continuation examples:

```sql
SELECT recording_id, COUNT(*)
FROM network_requests
GROUP BY recording_id
```

```sql
SELECT response_body || '' AS body
FROM network_requests
WHERE request_id = 42
```

These do not support continuation because the output is aggregated or computed rather than a direct source-field selection that can be traced back as-is.

If a join result includes same-name locator columns or otherwise requires heuristic inference to decide which source record owns the continuation target, continuation must be rejected as unsupported instead of guessed.

### Placeholder object

| Field | Type | Rule |
|-------|------|------|
| `__large_field__` | `bool` | Always `true` |
| `field` | `str` | Unqualified source field name when derivable from direct projection; otherwise the result-column name (e.g. for computed columns) |
| `size_chars` | `int` | Character count of the raw source value (Python `len()` of the unicode string) |
| `preview` | `str` | Controlled preview prefix, length `<= preview_chars` (default `1000`) |
| `locator` | `object \| null` | `null` when continuation is unavailable |
| `read_hint` | `str` | Always `read_field_chunk` |
| `read_blocked_reason` | `str` | Required when `locator` is `null`. Stable enumerated values: `missing_locator_field`, `computed_or_aggregated_column`, `ambiguous_locator_source`, `unsupported_source_table` |
| `read_blocked_message` | `str \| null` | Optional when `locator` is `null`. Human-readable explanation; not used for stable branching |

Non-text result values do not trigger placeholders; attempts to chunk-read a non-text source field use the `read_field_chunk.error.code` path.

### Readable example

```json
{
  "__large_field__": true,
  "field": "response_body",
  "size_chars": 128734,
  "preview": "<!doctype html><html><head><title>Example</title>...",
  "locator": {
    "table": "network_requests",
    "id_field": "request_id",
    "id_value": 42
  },
  "read_hint": "read_field_chunk"
}
```

### Blocked example

```json
{
  "__large_field__": true,
  "field": "response_body",
  "size_chars": 128734,
  "preview": "<!doctype html><html><head><title>Example</title>...",
  "locator": null,
  "read_hint": "read_field_chunk",
  "read_blocked_reason": "missing_locator_field",
  "read_blocked_message": "当前结果缺少继续读取所需的稳定定位字段 request_id，请补查直接列。"
}
```

## 3. `read_field_chunk` request contract

### Request shape

```json
{
  "locator": {
    "table": "network_requests",
    "id_field": "request_id",
    "id_value": 42
  },
  "field": "response_body",
  "offset": 0,
  "length": 1000
}
```

`length` is **optional**; omit it (or pass `null`) to default to `max_chunk_chars` (default `1000`).

### Validation rules

- `locator.table` must exist in the recording DuckDB schema; `field` must be an existing **text** column of that table.
- `locator.table` must be covered by a built-in `StableLocatorRule`; otherwise return `error.code = "unsupported_continuation"`.
- `locator.id_field` must match the stable identifier declared by that table's `StableLocatorRule`.
- For `locator.table == "network_requests"`: read goes through the existing filtered SQL rewrite path; if the record is filtered out, return `error.code = "record_unavailable"`. Other `StableLocatorRule`-covered source tables may use parameterized direct DuckDB reads, but only the single record selected by `id_field = id_value`.
- `offset` is zero-based and cannot be negative (`error.code = "invalid_offset"` otherwise).
- When provided, `length` must be positive (`error.code = "invalid_length"` otherwise). Effective return length = `min(length or max_chunk_chars, max_chunk_chars)`.
- Validation runs against current schema, built-in `StableLocatorRule`, and runtime config at call time. Runtime config only affects threshold / preview / chunk budgets; it does not maintain a field allow-list. Previously issued `locator`s remain valid as long as the underlying record/column still exists, the source table remains covered by `StableLocatorRule`, the field is still text-readable, and the `network_requests` filter boundary still allows access when applicable.

## 4. `read_field_chunk` response contract (unified shape)

The response always has the same fixed fields; the `error` field discriminates success from failure.

| Field | Type | Rule |
|-------|------|------|
| `content` | `str` | Raw text slice returned for this window. `""` on failure or EOF |
| `field` | `str` | Echoed source field |
| `locator` | `object \| null` | Echoed validated locator; `null` if validation failed before locator was confirmed |
| `offset` | `int` | Starting offset used for the slice |
| `returned_length` | `int` | Actual returned length in characters. `0` on failure or EOF |
| `total_length` | `int \| null` | Full raw value length in characters. `null` if not computable (e.g. record not found) |
| `has_more` | `bool` | Whether more content remains. `false` on failure or EOF |
| `next_offset` | `int \| null` | Next suggested offset; `null` on failure or EOF |
| `error` | `{code: str, message: str} \| null` | `null` for success; non-null structured error otherwise |

### Partial-read example (success)

```json
{
  "content": "<!doctype html><html>...",
  "field": "response_body",
  "locator": {
    "table": "network_requests",
    "id_field": "request_id",
    "id_value": 42
  },
  "offset": 0,
  "returned_length": 1000,
  "total_length": 128734,
  "has_more": true,
  "next_offset": 1000,
  "error": null
}
```

### End-of-field example (success, EOF)

```json
{
  "content": "",
  "field": "response_body",
  "locator": {
    "table": "network_requests",
    "id_field": "request_id",
    "id_value": 42
  },
  "offset": 128734,
  "returned_length": 0,
  "total_length": 128734,
  "has_more": false,
  "next_offset": null,
  "error": null
}
```

### Failure example

```json
{
  "content": "",
  "field": "response_body",
  "locator": null,
  "offset": 0,
  "returned_length": 0,
  "total_length": null,
  "has_more": false,
  "next_offset": null,
  "error": {
    "code": "record_unavailable",
    "message": "network_requests record request_id=42 not found or filtered out."
  }
}
```

## 5. Error code enumeration

`error.code` is a stable string drawn from the following enumeration. Every code is also emitted as a structured log key for `SC-006` observability.

| `error.code` | Trigger |
|--------------|---------|
| `invalid_offset` | `offset < 0` |
| `invalid_length` | `length <= 0` when explicitly provided |
| `unknown_table` | `locator.table` not in DuckDB schema |
| `field_not_found` | `field` not a column of `locator.table` |
| `non_text_field` | `field` exists but is not a text column |
| `unknown_id_field` | `locator.id_field` does not match the stable identifier declared by `StableLocatorRule` for `locator.table` |
| `record_unavailable` | Record not found, deleted, or filtered out (covers `network_requests` filter exclusions) |
| `unsupported_continuation` | Locator references a computed/aggregated/ambiguous source the validator refuses |
| `internal_error` | Unexpected exception (full traceback in logs only) |

`query_data` itself continues to use the existing tool-level error envelope (`{"error": "..."}`) for **its own** failures (e.g. SQL parse error). Per-cell large-field placeholders only use the structured shape defined in Section 2.
