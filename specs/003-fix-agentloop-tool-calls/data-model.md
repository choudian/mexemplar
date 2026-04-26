# Data Model: AgentLoop 多工具调用结果配对修复

## Entity 1: ToolCallBatch

Represents one assistant message that contains one or more tool calls.

Fields:
- `assistant_message_id`: persisted message identifier for the assistant response
- `session_id`: Agent session owning the response
- `content`: assistant text content, possibly empty
- `tool_calls`: ordered list of `ToolCallEntry`
- `status`: derived runtime state, one of `complete`, `incomplete`, `invalid_output`

Validation rules:
- Every `ToolCallEntry.id` must be unique within the batch.
- A batch is `complete` only when every tool call has a matching `ToolResultEntry`.
- A batch is `invalid_output` when it contains more than one tool call and at least one is interrupting (this includes interrupt + ordinary, interrupt + interrupt, and mixed-subtype combinations). No handlers may run for an `invalid_output` batch. A valid interrupting batch has exactly one tool call that is interrupting.
- Each `ToolCallEntry.kind` is derived from `ToolDefinition.is_interrupting` before any handler runs (see Entity 2).

## Entity 2: ToolCallEntry

Represents one tool call requested by the model.

Fields:
- `id`: provider-generated tool call ID
- `name`: requested tool name
- `args`: tool arguments
- `position`: zero-based position within the batch
- `kind`: derived value, one of `ordinary`, `interrupting`, `unknown`. Derivation rule: look up `name` in the active tool registry; if `ToolDefinition.is_interrupting=True` the kind is `interrupting`, otherwise `ordinary`. Names not registered in the current tool registry are `unknown`.

Validation rules:
- `name` is required for execution.
- `args` defaults to an empty object when absent.
- Original order must be preserved during execution and recovery.
- `kind` MUST be derived before any handler runs; the derivation is the sole input to mixed-batch validation. Hard-coded name lists or post-execution `isinstance(ToolSignal)` checks are not permitted as the classification mechanism.

## Entity 3: ToolResultEntry

Represents the persisted result paired to one tool call.

Fields:
- `tool_call_id`: ID of the matching `ToolCallEntry`
- `tool_name`: tool name used for diagnostics
- `content`: persisted result text
- `result_kind`: derived value, one of `success`, `error`, `not_executed`, `invalid_model_output`

Validation rules:
- Exactly one result should exist for each executed or intentionally skipped tool call.
- `not_executed` and `invalid_model_output` results MUST be a top-level JSON object whose `error` field carries the canonical code (`"not_executed"` or `"invalid_model_output"`) and whose `message` field carries a human-readable explanation. Optional diagnostic fields: `upstream_tool_call_id`, `code`, `tool_name`. Plain text or alternative schemas are not permitted.
- `error` results produced by AgentLoop on behalf of failing tools (handler exceptions, unknown tools, handler contract violations) MUST also use the standardized error structure; canonical `error` codes are `"handler_exception"`, `"unknown_tool"`, `"handler_contract_violation"`. Tool-authored failures may use any code provided the structure conforms to Entity 5.

## Entity 4: PendingToolCall

Represents a tool call that appears in a persisted assistant batch but does not yet have a matching result.

Fields:
- `assistant_message_id`
- `tool_call_id`
- `name`
- `args`
- `position`
- `previous_results`: matching results already present before this position

Validation rules:
- Recovery must select pending calls from the earliest incomplete batch that could block provider message validation.
- Completed tool calls must not be repeated.
- If the pending tool has no available handler, it is treated as a failure and later pending calls receive `not_executed` results.

## Entity 5: StandardizedErrorStructure

Represents a tool result shape that AgentLoop can reliably classify as failure or that AgentLoop itself emits on behalf of an unrun call.

Fields:
- `error`: stable error code (string). Canonical AgentLoop-emitted codes: `"unknown_tool"`, `"handler_exception"`, `"handler_contract_violation"`, `"not_executed"`, `"invalid_model_output"`. Tools may emit any other code so long as the structure conforms.
- `message`: human-readable detail (string). Required when AgentLoop emits the structure; recommended otherwise.
- `code`: optional stable diagnostic code (e.g., HTTP-style or tool-specific identifier).
- `tool_name`: optional, set by AgentLoop when emitting on behalf of a call to aid diagnostics.
- `upstream_tool_call_id`: optional, used in `not_executed` results to point at the failing predecessor.
- A top-level `success: false` field is also accepted as a failure marker for tool-authored results (alternative to `error`).

Validation rules:
- A tool result is classified as failure if and only if it is a top-level JSON object containing an `error` field or `success: false`. Plain text containing "error" / "错误" remains ordinary text.
- `unknown_tool`, `handler_exception`, and `handler_contract_violation` failures are emitted by AgentLoop itself; `not_executed` and `invalid_model_output` are also AgentLoop-emitted.
- Tool-returned failures must be structurally recognizable; keyword matching in plain text is forbidden.

## State Transitions

```text
assistant response received
  -> classify all calls by name -> ToolDefinition.is_interrupting (Decision 7)
  -> batch persisted
  -> if no tool calls: text/completion path
  -> if batch size > 1 and any call is interrupting: invalid_output (Decision 2)
       save invalid_model_output result for every call -> next LLM turn
  -> if batch size == 1 and call is interrupting (solo interrupt):
       execute handler
       -> success (ToolSignal returned): save result -> return AgentResult
       -> handler exception (Decision 10): save handler_exception error -> continue loop
       -> contract violation (Decision 9): save handler_contract_violation error -> continue loop
  -> if ordinary batch (all calls ordinary or unknown):
       execute call N
       -> success: save success result -> N+1
       -> handler exception: save handler_exception error -> save not_executed for later calls -> next LLM turn
       -> unknown tool: save unknown_tool error -> save not_executed for later calls -> next LLM turn
       -> standardized error structure: save error result -> save not_executed for later calls -> next LLM turn
       -> contract violation (is_interrupting=False but returned ToolSignal): save handler_contract_violation error -> save not_executed for later calls -> next LLM turn

recovery start
  -> find incomplete batch
  -> classify calls (re-derive kind from current tool registry)
  -> skip already paired calls
  -> resume first missing call
  -> if missing call has no handler: save unknown_tool error -> save not_executed for later calls -> next LLM turn
  -> apply ordinary failure / missing handler policy
```

## Compatibility Notes

- Existing single-tool sessions remain a one-entry `ToolCallBatch`.
- No database migration is required if current message records continue storing assistant `tool_calls` and tool `tool_call_id`.
- Archived/compressed messages must not be expanded solely for this feature unless they can still be sent to the provider; recovery should operate on active context messages that affect the next LLM request.
