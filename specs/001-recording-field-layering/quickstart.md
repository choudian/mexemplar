# Quickstart: 录制数据大字段按需读取

## Preconditions

- The implementation from this plan has been applied.
- You have a recording whose `network_requests.response_body`, `actions.dom_tree_snapshot`, `sibling_snapshots.siblings`, or **any other text column** holds a value `>= threshold_chars` (default `1000`). Any text column can trigger a placeholder; continuation examples below use tables covered by built-in `StableLocatorRule`.

## 1. Confirm `describe_data` exposes large-field hints

Inspect a source table that contains text columns and verify that `describe_data` advertises both the follow-up tool and the required locator fields based on current schema, not on a maintained hint list.

Expected outcome:
- A text column such as `response_body`, `dom_tree_snapshot`, or `siblings` includes `large_field: true`
- `read_via` is `read_field_chunk`
- `locator_fields` lists the stable ID column needed for continuation

## 2. Query a large field with its locator present

Example `query_data` SQL:

```sql
SELECT request_id, response_body
FROM network_requests
WHERE recording_id = 'rec'
ORDER BY request_id DESC
LIMIT 1
```

Expected outcome:
- `response_body` is returned as a structured placeholder object
- `locator.table = "network_requests"`
- `locator.id_field = "request_id"`
- `read_hint = "read_field_chunk"`

## 3. Read the first chunk

Use the placeholder's `locator` plus its `field` value (omitting `length` lets the server pick `max_chunk_chars`, default `1000`):

```json
{
  "locator": {
    "table": "network_requests",
    "id_field": "request_id",
    "id_value": 42
  },
  "field": "response_body",
  "offset": 0
}
```

Expected outcome:
- `error` is `null`
- The response contains raw `content`
- `returned_length <= max_chunk_chars` (default 1000)
- `has_more` and `next_offset` indicate whether another call is needed

## 4. Continue paging

Call `read_field_chunk` again with `offset = next_offset`.

Expected outcome:
- The next slice does not repeat the previous slice
- Repeated calls eventually return `has_more = false`
- An EOF request returns the empty-success shape defined in the contract (`content = ""`, `returned_length = 0`, `has_more = false`, `next_offset = null`, `error = null`)
- A failure (e.g. record deleted between calls) returns the same shape with a non-null `error: {code, message}`

## 5. Verify blocked continuation

Run a query that omits the stable locator field:

```sql
SELECT response_body
FROM network_requests
WHERE recording_id = 'rec'
ORDER BY request_id DESC
LIMIT 1
```

Expected outcome:
- The field still becomes a placeholder
- `locator` is `null`
- `read_blocked_reason` is a stable enum such as `missing_locator_field`
- `read_blocked_message`, when present, explains that the stable locator field must be included in a follow-up query

## 6. Run targeted tests

Suggested verification commands:

```powershell
uv run python -m pytest tests/recording/test_recording_data_large_fields.py tests/recording/filtering/test_query_projection_analyzer.py -q
```

```powershell
uv run python -m pytest tests/recording/test_query_data_sanitization.py tests/recording/test_recording_data_tools_noise_filtering.py -q
```

## 7. Measure `SC-003`

Use an in-process benchmark around the `query_data` placeholder-delivery path on a recording row that contains one `1.2MB` text field.

Acceptance method:
- Warm the process, DuckDB connection, and SQL parsing path first
- Measure only the incremental time from "raw result rows already fetched" to "placeholder objects built and tool result structured"
- Exclude GUI startup, process startup, human interaction, and any `read_field_chunk` calls
- Acceptance target: added latency `<= 200ms`
