# Feature Specification: Parallel Tool Execution

## Goal

Reduce AgentLoop latency when one model response contains multiple independent,
read-only tool calls, without weakening side-effect ordering, failure cascade,
tool-call/result pairing, or interrupting-tool semantics.

## User Stories

### US1 - Independent reads finish together

When the model emits multiple explicitly concurrency-safe tool calls in one
response, the AgentLoop executes the contiguous calls concurrently and persists
their governed results in the original model-provided order.

### US2 - Side effects remain ordered

Tools that are not explicitly concurrency-safe execute serially. A failing
side-effect tool continues to produce `not_executed` results for all later calls.

### US3 - Read failures stay isolated

A failed concurrency-safe tool does not cancel sibling calls in the same
parallel partition and does not prevent later serial partitions from running.

## Functional Requirements

- **FR-001** `ToolDefinition` MUST expose `is_concurrency_safe: bool = False`.
- **FR-002** Only explicitly reviewed tools MAY set the flag to `True`.
- **FR-003** AgentLoop MUST partition ordinary calls into contiguous safe
  partitions and single-call serial partitions while preserving input order.
- **FR-004** Parallel partitions MUST use at most four worker threads.
- **FR-005** Handler execution and output governance MUST run in the worker so
  semantic-summary latency can overlap.
- **FR-006** `ContextManager.save_tool_result` and activity emission MUST remain
  on the caller thread and occur in original call order.
- **FR-007** A failure inside a parallel partition MUST be persisted normally
  and MUST NOT establish the serial failure cascade.
- **FR-008** Unknown tools, interrupting tools, single-tool batches, and
  side-effect failure cascade MUST retain existing behavior.
- **FR-009** Mutable discovery tools, methodology load counters, process tools,
  user-defined tools, and write/exec/delegation tools MUST remain serial unless
  separately proven safe.

## Success Criteria

- Two safe calls overlap during both handler and governance execution.
- Mixed `[safe, safe, unsafe, safe]` calls execute as three ordered partitions.
- Result messages remain paired and ordered exactly as the assistant tool calls.
- Existing multi-tool, hook, cancellation, and output-governance tests pass.

