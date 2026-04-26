# Contract: AgentLoop Multi-Tool-Call Handling

## Scope

This contract defines AgentLoop behavior when one model response contains tool calls. It covers ordinary tools, interrupting tools, failure handling, handler contract validation, and recovery from incomplete message history.

## Inputs

### LLM Response

```json
{
  "content": "",
  "tool_calls": [
    {"id": "call_1", "name": "tool_a", "args": {}},
    {"id": "call_2", "name": "tool_b", "args": {}}
  ]
}
```

Rules:
- `tool_calls` order is authoritative.
- `content` may be empty.
- More than one tool call is valid input even when the client requested serial tool use.

### Tool Registry

AgentLoop receives a current mapping from tool name to `ToolDefinition`. The mapping may be static for PM/Programmer/Trial agents or rebuilt each iteration for assistant dynamic tools.

### Tool Classification

Before executing any handler, AgentLoop must classify each tool call by looking up its name in the active tool registry and reading `ToolDefinition.is_interrupting`. A call whose name is not in the registry is classified as `unknown` and treated as ordinary for batching purposes (it will fail on execution).

Classification rules:
- `is_interrupting=True` → kind `interrupting`
- `is_interrupting=False` → kind `ordinary`
- name not in registry → kind `unknown`

This classification is the **sole** input to mixed-batch validation. Hard-coded tool-name lists and post-execution `isinstance(ToolSignal)` checks are not permitted as classification mechanisms.

## Outputs

### Persisted Assistant Message

AgentLoop saves the assistant response with the full ordered `tool_calls` list.

### Persisted Tool Result Messages

For every saved tool call, AgentLoop must eventually save one matching tool result message:

```json
{
  "role": "tool",
  "tool_call_id": "call_1",
  "tool_name": "tool_a",
  "content": "..."
}
```

### Standardized Error Content

AgentLoop-emitted results for failures, not-executed calls, and invalid-output rejections must use this JSON structure:

```json
{
  "error": "<canonical_code>",
  "message": "<human-readable explanation>",
  "tool_name": "<optional>",
  "upstream_tool_call_id": "<optional, for not_executed>",
  "code": "<optional diagnostic>"
}
```

Canonical `error` codes emitted by AgentLoop:
- `"unknown_tool"` — tool name not in registry
- `"handler_exception"` — handler raised an exception
- `"handler_contract_violation"` — handler return type disagrees with `is_interrupting`
- `"not_executed"` — skipped because an earlier call in the batch failed
- `"invalid_model_output"` — batch rejected because interrupting and non-interrupting tools were mixed, or multiple interrupting tools appeared

## Behavior Rules

### Batch Classification

After persisting the assistant message, classify the batch:

1. **Ordinary batch**: all calls are `ordinary` or `unknown`, batch size ≥ 1. Execute via Ordinary Multi-Tool Batch rules.
2. **Solo interrupting batch**: batch size == 1 and the single call is `interrupting`. Execute via Solo Interrupting Tool rules.
3. **Invalid-output batch**: batch size > 1 and at least one call is `interrupting` (includes interrupt + ordinary, interrupt + interrupt, and mixed-subtype combinations). Execute via Invalid Output rules.

### Ordinary Multi-Tool Batch

1. Save the full assistant response.
2. Execute ordinary tools in original order.
3. After each successful execution, validate handler return type:
   - If `is_interrupting=False` and handler returned `str`: save success result → next call.
   - If `is_interrupting=False` but handler returned `ToolSignal`: contract violation (see below).
4. If a reliable failure occurs, save the failing tool's error result using standardized error content.
5. For every later tool call in the same batch, save a `not_executed` result and do not run its handler.
6. Continue to the next LLM turn only after every tool call in the batch has a paired result.

Reliable failures are limited to:
- unknown tool → `{"error": "unknown_tool", ...}`
- handler exception → `{"error": "handler_exception", ...}`
- standardized error structure returned by handler (top-level JSON with `error` field or `success: false`)
- handler contract violation → `{"error": "handler_contract_violation", ...}`

Plain text keywords are not failure signals.

### Solo Interrupting Tool

If the batch contains exactly one interrupting tool (batch size == 1):
1. Execute the handler.
2. Validate return type:
   - If handler returned `ToolSignal` (consistent with `is_interrupting=True`):
     - Save the tool result using `ToolSignal.display_text` (or `"[工具执行失败，已提交分诊处理]"` if `save_result=False`).
     - Return `AgentResult` with the appropriate `ResultType`.
   - If handler returned `str` (contract violation — `is_interrupting=True` but got `str`):
     - Save `{"error": "handler_contract_violation", ...}`.
     - **Continue the loop** — do not terminate with `AgentResult`. Let the model replan.
   - If handler raised an exception:
     - Save `{"error": "handler_exception", ...}`.
     - **Continue the loop** — do not terminate with `AgentResult`. Let the model replan.

Pause/complete semantics fire only on successful `ToolSignal` return.

### Invalid Output Batch

If the batch contains more than one tool call and at least one is interrupting:
- save the assistant response
- run no handlers
- save `{"error": "invalid_model_output", ...}` for every tool call in the batch
- continue to the next LLM turn so the model can regenerate a legal call

This applies to all mixed combinations: interrupt + ordinary, interrupt + interrupt, and mixed subtypes.

### Handler Contract Consistency

AgentLoop enforces strong consistency between `ToolDefinition.is_interrupting` and handler return type at execution time:

| `is_interrupting` | Handler returns | Outcome |
|---|---|---|
| `True` | `ToolSignal` | Normal interrupt path |
| `True` | `str` | Contract violation → error result, continue loop |
| `True` | raises exception | `handler_exception` error result, continue loop |
| `False` | `str` | Normal ordinary path |
| `False` | `ToolSignal` | Contract violation → error result, cascade `not_executed` for later calls |
| `False` | raises exception | `handler_exception` error result, cascade `not_executed` for later calls |

### Recovery

Before the next LLM request, AgentLoop must ensure persisted active history has no unmatched assistant tool calls.

Recovery rules:
- detect incomplete batches by comparing assistant `tool_calls` with following tool results by `tool_call_id`
- re-derive `kind` for each call from the **current** tool registry (may differ from original classification)
- never repeat calls that already have results
- resume missing calls in original order
- if a missing tool no longer has a handler, save a `{"error": "unknown_tool", ...}` result for it and `not_executed` results for later calls

## Acceptance Checks

- A batch with two successful ordinary tools yields two handler invocations and two tool results in order.
- A batch with success, standardized error, later ordinary call yields two real invocations and one `not_executed` result.
- A mixed ordinary + interrupting batch (batch size > 1) yields zero handler invocations and one `invalid_model_output` result per tool call.
- A batch with two interrupting tools yields zero handler invocations and one `invalid_model_output` result per tool call.
- A solo interrupting tool whose handler raises an exception yields one `handler_exception` error result and the loop continues (no `AgentResult` returned).
- A solo interrupting tool whose handler returns `str` (contract violation) yields one `handler_contract_violation` error result and the loop continues.
- An ordinary tool declared `is_interrupting=False` that returns `ToolSignal` (contract violation) yields one `handler_contract_violation` error result, later calls receive `not_executed` results, no later handler runs.
- A recovery run with the first result already saved does not re-run the first tool.
- A plain text result containing `error` does not stop later ordinary tools.

## Structured Logging

AgentLoop must emit the following log entries at `logger.info` level during multi-tool batch processing:

### Batch Start

```
agent_loop.batch.start batch_size=<int> call_names=<list[str]>
```

Logged once per batch, before classification.

### Per-Call Result

```
agent_loop.batch.call_result position=<int> tool_name=<str> outcome=<success|failure|not_executed|invalid_model_output|contract_violation> error_code=<str|None>
```

Logged once per tool call in the batch.

### Batch Summary

```
agent_loop.batch.complete batch_size=<int> successes=<int> failures=<int> not_executed=<int> cascade_triggered=<bool>
```

Logged once per batch, after all results are written.

### Recovery

```
agent_loop.recovery.start pending_count=<int> already_paired=<int> to_resume=<int>
agent_loop.recovery.call_result position=<int> tool_name=<str> outcome=<success|failure|not_executed> error_code=<str|None>
```

Logged during session recovery when pending tool calls are detected.
