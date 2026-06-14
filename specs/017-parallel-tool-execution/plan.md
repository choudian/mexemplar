# Implementation Plan: Parallel Tool Execution

## Technical Context

- Runtime: Python 3.11+, synchronous `AgentLoop`
- Concurrency primitive: `concurrent.futures.ThreadPoolExecutor`
- Primary files:
  - `src/business/agents/config.py`
  - `src/business/agents/agent_loop.py`
  - `src/business/agents/tools/builtin_general_tools.py`
  - `src/business/agents/tools/dynamic_tool_manager.py`
- Verification:
  - `tests/integration/test_agent_loop_parallel_tools.py`
  - existing AgentLoop, hook, cancellation, and built-in tool suites

## Design

1. Add a conservative opt-in flag to `ToolDefinition`.
2. Partition only contiguous ordinary calls whose definitions are marked safe.
3. Run handler, hooks, and result governance in worker threads with a copied
   `contextvars` context.
4. Collect worker results and persist them on the caller thread in original
   order. This keeps SQLite message writes and activity sequence allocation
   deterministic.
5. Keep unknown and non-safe tools on the existing serial path.
6. Mark only reviewed immutable/read-only tools safe. `get_tool_detail` remains
   serial because it mutates activation state; `load_skill_methodology` remains
   serial because it increments a persisted load counter.

## Constitution Check

- Layers: business-only change; no dependency inversion.
- Events: no new public or blinker event.
- Storage: no schema change; message persistence remains serial.
- Configuration/secrets: no new configuration or credential path.
- Tests: adds deterministic concurrency, ordering, and failure tests.
- Documentation: update architecture, constraints, and backend AI mirrors.

