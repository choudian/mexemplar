# Tasks: AgentLoop 多工具调用结果配对修复

**Input**: Design documents from `specs/003-fix-agentloop-tool-calls/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/agentloop-multi-tool-call-contract.md

**Tests**: FR-013 explicitly requires behavioral tests. Test tasks are included.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing.

## Constitution-Driven Minimums

- No SQLite schema change, no DuckDB, no new config — so no Repository/migration/config tasks.
- Shared entity change: `ToolDefinition.is_interrupting` is a foundational task touching `src/business/agents/config.py`.
- Wiring smoke tests and guard tests included in Phase 6 (Polish) per Principle IV.
- Active-document updates included in Phase 6 per Principle V.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Project Paths

- **Source**: `src/` at repository root (business, data, recording, execution, ui, utils)
- **Tests**: `tests/` at repository root (mirrors src/ structure)
- **Test runner**: `uv run pytest tests/`
- **Formatter**: `uv run black src/ tests/`
- **Linter**: `uv run flake8 src/ tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the declarative `is_interrupting` field to `ToolDefinition` and update all existing tool registrations to declare their interrupting status. This is the sole prerequisite for all three user stories.

- [X] T001 Add `is_interrupting: bool = False` field to `ToolDefinition` dataclass in `src/business/agents/config.py` (FR-014)
- [X] T002 [P] Set `is_interrupting=True` on interrupting tool `ToolDefinition`s: find all registrations of `talk_to_user`, `submit_requirement`, and any other tool whose handler returns `ToolSignal` across `src/business/agents/tools/` and `src/business/orchestration/`; add the field to each constructor call
- [X] T003 Add helper function `classify_tool_calls(tool_calls, tool_registry) -> list[tuple[ToolCallInfo, str]]` in `src/business/agents/agent_loop.py` that maps each tool call name to its kind (`ordinary` / `interrupting` / `unknown`) via `ToolDefinition.is_interrupting` lookup; returns existing `ToolCallInfo` objects augmented with a derived kind string (data-model Entity 2 `ToolCallEntry` is a documentation concept mapped to `ToolCallInfo` + kind, not a new class) (FR-014)
- [X] T004 Add constant dict `ERROR_CODES` and helper `make_error_result(error_code, message, **extra) -> str` in `src/business/agents/agent_loop.py` that returns a JSON string conforming to the StandardizedErrorStructure (Entity 5): canonical codes `"unknown_tool"`, `"handler_exception"`, `"handler_contract_violation"`, `"not_executed"`, `"invalid_model_output"` (FR-015)

**Checkpoint**: `ToolDefinition` has `is_interrupting`; tool registrations are updated; `classify_tool_calls` and `make_error_result` helpers exist and are unit-testable.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core loop refactoring — change `_process_llm_response` to return the full tool call list instead of only the first call. This unblocks all user stories.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Refactor `_process_llm_response` in `src/business/agents/agent_loop.py` to return the **full** `response.tool_calls` list (as `list[ToolCallInfo]`) instead of `response.tool_calls[0]`; update the return type annotation from `Union[AgentResult, ToolCallInfo]` to `Union[AgentResult, list[ToolCallInfo]]` (FR-001)
- [X] T006 Refactor the `run()` main loop in `src/business/agents/agent_loop.py` to iterate over the returned tool call list: after `_process_llm_response` returns a list, loop over each `ToolCallInfo` in order, calling `_execute_tool_call` + `_handle_tool_result` for each; on the success path, finish the full list before the next LLM turn; on the failure path (reliable failure per FR-005), stop executing remaining handlers and write `not_executed` results — see T013 for cascade logic (FR-002, FR-003, FR-004)
- [X] T007 Add batch-level validation in the main loop: after receiving the tool call list from `_process_llm_response`, call `classify_tool_calls` to classify all calls; if batch size > 1 and any call is `interrupting`, skip handler execution for the entire batch and write `invalid_model_output` error results for every call using `make_error_result` (FR-006, FR-007, Decision 2)
- [X] T008 Add handler contract validation in the tool execution path: after `_execute_tool_call` returns, check return type against `ToolDefinition.is_interrupting`. If `is_interrupting=False` and result is `ToolSignal`, write `handler_contract_violation` error result and cascade `not_executed` for remaining calls. If `is_interrupting=True` and result is `str`, write `handler_contract_violation` and continue loop. (FR-016, Decision 9)

**Checkpoint**: The main loop processes full tool call lists. Mixed/interrupt batch rejection works. Contract validation works. Single-tool paths still pass.

---

## Phase 3: User Story 1 — 多工具调用完整配对 (Priority: P1) 🎯 MVP

**Goal**: When the model returns multiple ordinary tool calls, AgentLoop executes them all in order and saves paired results before the next LLM request.

**Independent Test**: Mock one LLM response with two ordinary tool calls → verify both handlers fire in order, two tool results are persisted, next LLM call has no unmatched tool calls.

### Tests for User Story 1

- [X] T009 [P] [US1] Add integration test `test_ordinary_two_tool_success` in `tests/integration/test_agent_loop_multi_tool_calls.py`: mock LLM returns two ordinary tool calls, verify both handlers invoked in order, two results persisted, next LLM messages have no unmatched tool calls (SC-001)
- [X] T010 [P] [US1] Add integration test `test_ordinary_three_tool_order` in `tests/integration/test_agent_loop_multi_tool_calls.py`: mock LLM returns three ordinary tool calls, verify execution order matches model-provided order (SC-002)
- [X] T011 [P] [US1] Add integration test `test_ordinary_failure_cascade` in `tests/integration/test_agent_loop_multi_tool_calls.py`: second of three tools returns standardized error `{"error":"x"}`, verify first two invocations happen, third handler not called, third receives `not_executed` result, next LLM call accepted (SC-003)
- [X] T012 [P] [US1] Add integration test `test_plain_text_error_not_failure` in `tests/integration/test_agent_loop_multi_tool_calls.py`: first tool returns plain text `"An error occurred"` (no standardized structure), verify subsequent tools still execute normally (SC-008)
- [X] T012a [P] [US1] Add integration test `test_ordinary_unknown_tool_cascade` in `tests/integration/test_agent_loop_multi_tool_calls.py`: multi-call batch where one call references an unknown tool name, verify `unknown_tool` error result for that call, `not_executed` for later calls, no later handler runs (Edge Case 2, FR-005)

### Implementation for User Story 1

- [X] T013 [US1] Implement ordinary-tool failure cascade in the main loop in `src/business/agents/agent_loop.py`: when `_execute_tool_call` fails (unknown tool / handler exception / standardized error structure), save error result, write `not_executed` for all remaining calls in the batch, break inner loop (FR-005, Decision 3)
- [X] T014 [US1] Add structured logging in `src/business/agents/agent_loop.py` for multi-tool batch processing: log batch size, each call's name/position, failure cascade trigger, and not-executed count at `logger.info` level (FR-012)

**Checkpoint**: Ordinary multi-tool batches fully paired. Failure cascade works. Plain text "error" is not failure.

---

## Phase 4: User Story 2 — 中断型工具行为可预期 (Priority: P1)

**Goal**: Mixed interrupt/non-interrupt responses are rejected as invalid output. Solo interrupt preserves existing semantics. Handler contract violations are caught.

**Independent Test**: Mock one LLM response mixing `talk_to_user` with an ordinary tool → verify no handler runs, every call gets `invalid_model_output` result.

### Tests for User Story 2

- [X] T015 [P] [US2] Add integration test `test_mixed_interrupt_ordinary_batch` in `tests/integration/test_agent_loop_multi_tool_calls.py`: response contains one interrupting + one ordinary tool, verify zero handler invocations, every call gets `invalid_model_output` result, next LLM turn proceeds (SC-004)
- [X] T016 [P] [US2] Add integration test `test_multi_interrupt_batch` in `tests/integration/test_agent_loop_multi_tool_calls.py`: response contains two interrupting tools, verify zero handler invocations, every call gets `invalid_model_output` result (FR-006, Decision 2)
- [X] T017 [P] [US2] Add integration test `test_solo_interrupt_handler_exception` in `tests/integration/test_agent_loop_multi_tool_calls.py`: solo interrupting tool handler raises exception, verify `handler_exception` error result saved, loop continues (does not return `AgentResult`), model can replan (Decision 10)
- [X] T018 [P] [US2] Add integration test `test_handler_contract_violation_interrupt_returns_str` in `tests/integration/test_agent_loop_multi_tool_calls.py`: `is_interrupting=True` handler returns `str`, verify `handler_contract_violation` error result, loop continues (FR-016)
- [X] T019 [P] [US2] Add integration test `test_handler_contract_violation_ordinary_returns_signal` in `tests/integration/test_agent_loop_multi_tool_calls.py`: `is_interrupting=False` handler in multi-call batch returns `ToolSignal`, verify `handler_contract_violation` error result for that call, later calls get `not_executed`, no later handler runs (FR-016)

### Implementation for User Story 2

- [X] T020 [US2] Implement solo-interrupt exception handling in `src/business/agents/agent_loop.py`: wrap `_execute_tool_call` for solo interrupting calls in try/except; on exception, save `handler_exception` error result and continue loop instead of returning `AgentResult` (FR-007, Decision 10)
- [X] T021 [US2] Implement solo-interrupt contract validation in `src/business/agents/agent_loop.py`: after solo interrupt execution, if handler returned `str` (not `ToolSignal`), save `handler_contract_violation` error result and continue loop (FR-016, Decision 9)

**Checkpoint**: Mixed/interrupt batch rejection works. Solo interrupt preserves existing behavior on success. Handler exceptions and contract violations follow failure semantics.

---

## Phase 5: User Story 3 — 会话恢复不重复或遗漏工具 (Priority: P2)

**Goal**: Recovery identifies partial multi-tool results and resumes only missing calls in original order.

**Independent Test**: Seed session history with a 3-tool assistant message and only the first tool result → verify recovery executes calls 2 and 3 only.

### Tests for User Story 3

- [X] T022 [P] [US3] Add integration test `test_recovery_partial_results` in `tests/integration/test_agent_loop_multi_tool_calls.py`: session has assistant message with 3 tool calls and only first result saved; verify recovery skips first, resumes from second in order (SC-005)
- [X] T023 [P] [US3] Add integration test `test_recovery_all_complete` in `tests/integration/test_agent_loop_multi_tool_calls.py`: all tool calls already have results; verify no tool re-execution, normal next LLM request (US3 Acceptance 2)
- [X] T024 [P] [US3] Add integration test `test_recovery_missing_handler` in `tests/integration/test_agent_loop_multi_tool_calls.py`: next missing tool has no handler in current registry; verify `unknown_tool` error result for that call, `not_executed` for later calls, no later handler runs (SC-006)
- [X] T025 [P] [US3] Add integration test `test_recovery_corrupted_tool_call` in `tests/integration/test_agent_loop_multi_tool_calls.py`: persisted tool call record missing `name` or `id`; verify explicit error logged or returned, not silent skip (US3 Acceptance 4)

### Implementation for User Story 3

- [X] T026 [US3] Extend `get_pending_tool_call` → `get_pending_tool_calls` in `src/business/memory/context_manager.py` to return a list of all unpaired tool calls within the last assistant message (not just the first), preserving original order; detect unpaired calls by comparing assistant `tool_calls` list against existing tool results by `tool_call_id` (FR-008, FR-009)
- [X] T027 [US3] Update the pending-tool-call branch in `run()` in `src/business/agents/agent_loop.py` to iterate over the full pending list instead of a single `_pending_tc`: for each unpaired call, check if handler exists, execute or write error result, cascade on failure (FR-008, FR-009, FR-010)
- [X] T028 [US3] Add recovery logging in `src/business/agents/agent_loop.py`: log number of pending calls found, how many already paired, how many being resumed, and any missing-handler failures (FR-012)

**Checkpoint**: Multi-tool recovery works. No re-execution of completed calls. Missing handlers are handled gracefully.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Regression safety, documentation, and final validation.

- [X] T029 [P] Add regression test `test_single_tool_unchanged` in `tests/integration/test_agent_loop_multi_tool_calls.py`: verify existing single-tool workflows (PM, Programmer, Trial) still pass their current behavior test suite with no user-visible regression (SC-007, FR-011); also run existing test suites `test_v2_full_flow.py` and `test_assistant_new_session.py` as baseline regression check
- [X] T030 [P] Update `docs/design/agent_loop_design.md` to document the multi-tool batch processing model, batch classification rules, failure cascade, interrupt handling, and recovery behavior (Principle V)
- [X] T031 [P] Update `docs/ARCHITECTURE.md` AgentLoop section to reflect the multi-tool batch processing change (Principle V)
- [X] T032 Run full quickstart.md validation: execute all 11 test scenarios from `specs/003-fix-agentloop-tool-calls/quickstart.md` and verify pass
- [X] T033 Run `uv run black src/ tests/` and `uv run flake8 src/ tests/` — fix any formatting or linting issues introduced by this feature

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 — ordinary multi-tool batch processing
- **User Story 2 (Phase 4)**: Depends on Phase 2 — interrupt validation builds on batch classification from Phase 2
- **User Story 3 (Phase 5)**: Depends on Phase 2 and ideally Phase 3 (recovery needs the batch-processing loop to be in place)
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2 — no dependencies on other stories
- **US2 (P1)**: Can start after Phase 2 — interrupt validation is orthogonal to ordinary batch processing; can be done in parallel with US1
- **US3 (P2)**: Depends on Phase 2; benefits from US1 being complete (recovery reuses the batch loop)

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Core loop changes before tests can verify behavior
- Logging after core behavior is stable

### Parallel Opportunities

- T009–T012 (US1 tests) can run in parallel
- T015–T019 (US2 tests) can run in parallel
- T022–T025 (US3 tests) can run in parallel
- T030–T031 (docs) can run in parallel
- US1 and US2 implementation can proceed in parallel (different code paths within `agent_loop.py`)

---

## Parallel Example: User Story 1

```bash
# Launch all US1 tests together:
Task: "test_ordinary_two_tool_success in tests/integration/test_agent_loop_multi_tool_calls.py"
Task: "test_ordinary_three_tool_order in tests/integration/test_agent_loop_multi_tool_calls.py"
Task: "test_ordinary_failure_cascade in tests/integration/test_agent_loop_multi_tool_calls.py"
Task: "test_plain_text_error_not_failure in tests/integration/test_agent_loop_multi_tool_calls.py"
Task: "test_ordinary_unknown_tool_cascade in tests/integration/test_agent_loop_multi_tool_calls.py"

# Then implement:
Task: "Implement ordinary-tool failure cascade in src/business/agents/agent_loop.py"
Task: "Add structured logging in src/business/agents/agent_loop.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (add `is_interrupting` field)
2. Complete Phase 2: Foundational (refactor loop for multi-call)
3. Complete Phase 3: User Story 1 (ordinary multi-tool success + failure)
4. **STOP and VALIDATE**: Test US1 independently — this fixes the core bug
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 → Ordinary multi-tool works (MVP!)
3. Add US2 → Interrupt handling is bulletproof
4. Add US3 → Recovery handles partial results
5. Polish → Regression safe, docs updated

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- All test tasks target `tests/integration/test_agent_loop_multi_tool_calls.py`
- Core implementation is concentrated in `src/business/agents/agent_loop.py` and `src/business/agents/config.py`
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
