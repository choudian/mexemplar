# Quickstart: AgentLoop 多工具调用结果配对修复

## Prerequisites

- Work inside `D:\develop\code\Exemplar\.worktrees\003-fix-agentloop-tool-calls`
- Use the project test environment with pytest available
- Keep validation focused on AgentLoop and message persistence; no real LLM key is required

## Validation Flow

### 1. Ordinary multi-tool success

Create or run a test where one mocked model response returns two ordinary tool calls and the next model response returns completion text.

Expected:
- both handlers are invoked once, in list order
- the assistant message stores both tool calls
- two tool result messages are persisted with matching `tool_call_id`
- the next LLM call receives no unmatched tool calls

### 2. Ordinary multi-tool failure cascade

Create or run a test where the second of three ordinary tool calls returns a standardized error structure.

Expected:
- first handler runs and saves success
- second handler runs and saves error
- third handler does not run
- third tool call receives a `not_executed` result with `{"error": "not_executed", "upstream_tool_call_id": "<call_2_id>", ...}`
- next LLM call can proceed with complete message pairing

### 3. Plain-text "error" is not failure

Create or run a test where the first ordinary tool returns plain text containing `error`, but not a standardized error structure.

Expected:
- subsequent ordinary tools still run
- the plain text result is saved as a normal tool result

### 4. Mixed interrupt-tool response (invalid output)

Create or run a test where one response includes an interrupting tool plus another ordinary tool.

Expected:
- no tool handler runs
- the assistant response is persisted
- every tool call receives an `invalid_model_output` result: `{"error": "invalid_model_output", ...}`
- the next model turn asks the model to regenerate a legal tool call

### 5. Multi-interrupt response (invalid output)

Create or run a test where one response includes two interrupting tools (e.g., two `talk_to_user`).

Expected:
- no tool handler runs
- the assistant response is persisted
- every tool call receives an `invalid_model_output` result
- the next model turn asks the model to regenerate a legal tool call

### 6. Solo interrupt handler exception

Create or run a test where a solo interrupting tool handler raises an exception.

Expected:
- a `handler_exception` error result is saved: `{"error": "handler_exception", "tool_name": "...", ...}`
- the loop continues (does not terminate with `AgentResult`)
- the model sees the error and can replan

### 7. Handler contract violation (interrupting returns str)

Create or run a test where a solo interrupting tool (`is_interrupting=True`) handler returns `str` instead of `ToolSignal`.

Expected:
- a `handler_contract_violation` error result is saved: `{"error": "handler_contract_violation", ...}`
- the loop continues
- the model sees the error and can replan

### 8. Handler contract violation (ordinary returns ToolSignal)

Create or run a test where an ordinary tool (`is_interrupting=False`) in a multi-call batch returns `ToolSignal` instead of `str`.

Expected:
- a `handler_contract_violation` error result is saved for that call
- later calls in the batch receive `not_executed` results
- no later handler runs
- the loop continues

### 9. Recovery with partial results

Create or run a test where a session already has an assistant message with three tool calls and only the first tool result.

Expected:
- recovery skips the first call
- recovery resumes from the second call
- already completed calls are not repeated

### 10. Recovery with missing handler

Create or run a test where the next missing recovered call no longer has a registered handler.

Expected:
- the missing call receives a `{"error": "unknown_tool", ...}` result
- later calls receive `not_executed` results
- no later handler runs

### 11. Single-tool regression

Create or run existing single-tool integration tests (`test_v2_full_flow.py`, `test_assistant_new_session.py`).

Expected:
- all existing tests pass with no regression
- single ordinary tool, single interrupting tool, and text-only paths are unchanged

## Suggested Targeted Command

```powershell
uv run pytest tests/integration/test_agent_loop_multi_tool_calls.py tests/integration/test_v2_full_flow.py tests/integration/test_assistant_new_session.py
```

If `uv` or the local environment is unavailable, run the same pytest targets with the available project interpreter and record the blocker in the implementation summary.
