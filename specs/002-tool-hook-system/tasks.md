# Tasks: 工具执行 Pre/Post Hook 系统

**Input**: Design documents from `specs/002-tool-hook-system/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/tool-hook-protocol.md`, `quickstart.md`

**Tests**: 本 feature 明确要求协议测试、迁移回归测试、静态 guard 与链路烟测；测试任务必须先写，预期先失败再实现。

**Organization**: Tasks are grouped by user story so each story can be implemented and tested independently after the foundational protocol model exists.

## Constitution-Driven Minimums

- No SQLite/DuckDB schema, Repository, migration, UI, config, keyring, or blinker event tasks are required.
- All implementation stays in business-layer Agent runtime files under `src/business/agents/`.
- Add wiring smoke tests and guard tests because the AgentLoop batch/solo-interrupt tool execution path is being extended.
- Update active docs in `docs/ARCHITECTURE.md` and `docs/PROJECT_CONSTRAINTS.md` after behavior is implemented.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the files that all story phases will extend.

- [X] T001 Create `tests/test_hook_protocol.py` with shared pytest fixtures for fake tool definitions, fake tool calls, and AgentLoop tool-execution assertions
- [X] T002 [P] Create `src/business/agents/hook_models.py` as the hook protocol module scaffold with public export placeholders

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define the shared hook protocol and public Agent configuration surface before any story implementation.

**Critical**: No user story work can be completed until this phase is done.

- [X] T003 Implement `ToolCallContext`, `PreHookResult`, `PostHookResult`, `PreHook`, `PostHook`, recursive read-only args freezing, internal `ToolExecutionDefinition`, and internal `ToolExecutionOutcome` in `src/business/agents/hook_models.py`
- [X] T004 Extend `ToolDefinition` with optional `pre_hook`/`post_hook` while preserving existing `is_interrupting`, extend `AgentConfig` with `global_pre_hooks`/`global_post_hooks`, and update `__all__` in `src/business/agents/config.py`

**Checkpoint**: Protocol types and config fields are importable without changing existing tool behavior.

---

## Phase 3: User Story 1 - 工具执行管线支持统一的 Pre/Post 拦截 (Priority: P1) MVP

**Goal**: A `ToolDefinition` can define tool-level pre/post hooks; no-hook tools remain transparent; hook errors, handler errors, `ToolSignal`, recursive read-only args, and callable tool refresh follow the contract.

**Independent Test**: `tests/test_hook_protocol.py` can construct synthetic tools and execute AgentLoop's tool path without relying on any migrated real tool.

### Tests for User Story 1

- [X] T005 [US1] Add no-hook transparency, `PreHookResult(error=...)` standardized error-structure short-circuit, and `PostHookResult(result=...)` rewrite tests in `tests/test_hook_protocol.py`
- [X] T006 [US1] Add recursive `ToolCallContext.args` top-level and nested mutation tests plus pre-hook exception skips post-hook test in `tests/test_hook_protocol.py`
- [X] T007 [US1] Add ordinary handler exception reaches post-hook, `ToolSignal` bypasses post-hook, handler/`is_interrupting` contract violation, and ordinary-batch failure-status cascade tests in `tests/test_hook_protocol.py`
- [X] T008 [US1] Add callable tool factory same-name handler/hook/`is_interrupting` replacement smoke test in `tests/test_hook_protocol.py`
- [X] T009 [US1] Add tool-level no-op hook overhead smoke test for tool pre + tool post against no-hook baseline in `tests/test_hook_protocol.py`

### Implementation for User Story 1

- [X] T010 [US1] Integrate hook-aware per-call execution into `AgentLoop._execute_tool_batch()` and `_execute_solo_interrupt()` through `_execute_tool_call()`, including context construction, `PreHookResult(error=...)` standardized error result construction, handler exception conversion, hook exception logging, reliable failure status, and final result selection in `src/business/agents/agent_loop.py`
- [X] T011 [US1] Update callable-tools rebuild logic so schemas can remain name-cached while handler/pre_hook/post_hook execution mappings and `_current_tool_defs` classification metadata refresh every iteration in `src/business/agents/agent_loop.py`
- [X] T012 [US1] Keep injected `load_reference` and `talk_to_user` available for existing batch classification/solo-interrupt behavior but excluded from tool-level and AgentConfig global hook execution in `src/business/agents/agent_loop.py`
- [X] T013 [US1] Run focused P1 validation with `uv run python -m pytest tests/test_hook_protocol.py -q` for `tests/test_hook_protocol.py`

**Checkpoint**: P1 is independently usable: synthetic tools can be intercepted, no-hook tools behave as before, callable dynamic tool changes take effect next iteration, 003 multi-tool batch semantics are preserved, and `ToolSignal` control flow is untouched.

---

## Phase 4: User Story 2 - 把分散在 handler 内的门卫式安全校验迁移到 pre_hook (Priority: P2)

**Goal**: Existing rejection/confirmation/rate-limit/security gates move out of handlers and into pre-hooks for builtin general tools, recording data tools, and trial tools without changing allowed behavior.

**Independent Test**: The migrated real tools reject before handler execution; handlers retain only execution preparation and result conversion; parser-based SQL behavior still allows harmless comments and semicolons inside string literals.

### Tests for User Story 2

- [X] T014 [US2] Add builtin general tool migration tests for `read_file`, `write_file`, `edit_file`, `list_dir`, and `exec` rejected paths and handler-skip assertions in `tests/test_hook_protocol.py`
- [X] T015 [US2] Add recording tool migration tests for `query_data` parser/filter rejection, harmless comment/string-semicolon allowance, and `analyze_image` 6-action rejection in `tests/test_hook_protocol.py`
- [X] T016 [US2] Add trial `run_command` per-`AgentLoop.run()` 6th-call rejection and handler-skip tests in `tests/test_hook_protocol.py`
- [X] T017 [US2] Add static source guard tests proving migrated gate checks are gone from handler bodies while `edit_file` `old_text` uniqueness remains in `tests/test_hook_protocol.py`
- [X] T018 [US2] Add non-migration guard tests proving `programmer_tools.syntax_check`, `recording_data_tools.execute_code`, `tool_executor`, and `dynamic_tool_manager` boundaries remain outside hook migration in `tests/test_hook_protocol.py`

### Implementation for User Story 2

- [X] T019 [US2] Implement and attach pre-hooks for `read_file`, `write_file`, `edit_file`, `list_dir`, and `exec`, reusing `_ask_user_confirm` and removing migrated gate checks from handlers in `src/business/agents/tools/builtin_general_tools.py`
- [X] T020 [P] [US2] Implement and attach `query_data` and `analyze_image` pre-hooks, reusing `rewrite(sql)`/filter policy and preserving handler execution preparation in `src/business/agents/tools/recording_data_tools.py`
- [X] T021 [P] [US2] Move `run_command` attempt counting into a per-run pre-hook closure and leave `_run_command_handler()` execution-only in `src/business/agents/tools/trial_tools.py`
- [X] T022 [US2] Run migrated-tool validation with `uv run python -m pytest tests/test_hook_protocol.py -q` for `tests/test_hook_protocol.py`

**Checkpoint**: P2 can be validated without P3: migrated tools reject through pre-hooks, handlers no longer contain the moved gate logic, and existing parser/filter behavior is preserved.

---

## Phase 5: User Story 3 - 全局 Hook 用于跨工具的日志/审计/限流 (Priority: P3)

**Goal**: `AgentConfig.global_pre_hooks` and `AgentConfig.global_post_hooks` apply to all `ToolDefinition` tools in that config instance, after tool-level pre-hooks and after tool-level post-hooks, without affecting injected built-ins.

**Independent Test**: Two synthetic tools share the same global hooks; hook order is tool pre -> global pre -> handler -> tool post -> global post; tool-level pre error prevents global hooks.

### Tests for User Story 3

- [X] T023 [US3] Add global pre/post ordering tests across two `ToolDefinition` tools in `tests/test_hook_protocol.py`
- [X] T024 [US3] Add global hook scope, short-circuit, invalid mixed-batch no-hook, and context field tests for `tool_name`, `args`, `session_id`, `agent_type`, and `iteration` in `tests/test_hook_protocol.py`
- [X] T025 [US3] Add full-chain overhead budget and global pre-hook mounting-cost verification tests for SC-002 and SC-005 in `tests/test_hook_protocol.py`

### Implementation for User Story 3

- [X] T026 [US3] Wire `AgentConfig.global_pre_hooks` and `AgentConfig.global_post_hooks` into the AgentLoop hook order and short-circuit rules in `src/business/agents/agent_loop.py`
- [X] T027 [US3] Run global-hook validation with `uv run python -m pytest tests/test_hook_protocol.py -q` for `tests/test_hook_protocol.py`

**Checkpoint**: P3 is independently demonstrable on synthetic tools and does not require audit/logging example hook files.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, static scans, and regression validation after all selected stories are complete.

- [X] T028 [P] Update AgentLoop runtime structure and hook execution semantics in `docs/ARCHITECTURE.md`
- [X] T029 [P] Document hook boundaries, no args/result pipeline, migrated gate ownership, and non-migrated exceptions in `docs/PROJECT_CONSTRAINTS.md`
- [X] T030 Run focused protocol suite with `uv run python -m pytest tests/test_hook_protocol.py -q` for `tests/test_hook_protocol.py`
- [X] T031 Run recording guard/regression suite with `uv run python -m pytest tests/recording/test_recording_data_tools_noise_filtering.py tests/recording/filtering/test_recording_tools_no_sqlglot.py -q` for `tests/recording/test_recording_data_tools_noise_filtering.py` and `tests/recording/filtering/test_recording_tools_no_sqlglot.py`
- [X] T032 Run Agent runtime smoke suite with `uv run python -m pytest tests/integration/test_agent_loop_multi_tool_calls.py tests/integration/test_assistant_new_session.py -q` for `tests/integration/test_agent_loop_multi_tool_calls.py` and `tests/integration/test_assistant_new_session.py`
- [X] T033 Run stale-semantics scan `rg -n "PreHookResult.*args|ToolCallContext.*result|只读浅拷贝|pipeline|流水线|改参" src tests` for `src/` and `tests/`
- [X] T034 Run syntax validation with `uv run python -m py_compile src/business/agents/hook_models.py src/business/agents/config.py src/business/agents/agent_loop.py src/business/agents/tools/builtin_general_tools.py src/business/agents/tools/recording_data_tools.py src/business/agents/tools/trial_tools.py` for the changed `src/business/agents/` files
- [ ] T035 Run formatting check with `uv run black --check src tests` for `src/` and `tests/`
- [ ] T036 Run lint check with `uv run flake8 src tests` for `src/` and `tests/`
- [ ] T037 Run final regression command `uv run python -m pytest tests -q` for `tests/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Phase 1 and blocks every user story.
- **User Story 1 (Phase 3)**: Depends on Phase 2; this is the MVP.
- **User Story 2 (Phase 4)**: Depends on Phase 2 and practically depends on US1 hook execution being available for real tools.
- **User Story 3 (Phase 5)**: Depends on Phase 2 and can be implemented after US1's execution path exists.
- **Polish (Phase 6)**: Depends on the selected user stories being complete.

### User Story Dependencies

- **US1 (P1)**: No story dependency after foundational protocol work.
- **US2 (P2)**: Uses the US1 hook execution path; can be tested independently through migrated real-tool paths once US1 is complete.
- **US3 (P3)**: Uses the US1 hook execution path; independent from US2 migrations.

### Parallel Opportunities

- T001 and T002 can run in parallel because they touch different files.
- After T003/T004 and US1 batch-compatible execution-path work, T019, T020, and T021 can be split by tool module; T020 and T021 are explicitly parallelizable.
- T028 and T029 can run in parallel after behavior is implemented because they touch different docs.
- US2 and US3 can proceed in parallel after US1 if separate owners avoid conflicts in `src/business/agents/agent_loop.py` and coordinate on `tests/test_hook_protocol.py`.

---

## Parallel Example: User Story 2

```text
Task: "Implement and attach query_data and analyze_image pre-hooks in src/business/agents/tools/recording_data_tools.py"
Task: "Move run_command attempt counting into a per-run pre-hook closure in src/business/agents/tools/trial_tools.py"
```

## Parallel Example: Polish

```text
Task: "Update AgentLoop runtime structure and hook execution semantics in docs/ARCHITECTURE.md"
Task: "Document hook boundaries and migrated gate ownership in docs/PROJECT_CONSTRAINTS.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 (US1).
3. Stop and validate `tests/test_hook_protocol.py` against synthetic tools before touching existing real-tool handlers.

### Incremental Delivery

1. Deliver US1 protocol and AgentLoop execution path.
2. Deliver US2 real-tool gate migrations and static handler cleanup guards.
3. Deliver US3 AgentConfig global hook behavior.
4. Update active docs and run the quickstart validation commands.

### Notes

- Do not reintroduce `PreHookResult.args`, `ToolCallContext.result`, confirmation callbacks on `ToolCallContext`, or args/result pipeline semantics.
- Preserve 003 multi-tool semantics: invalid mixed interrupt batches run no hooks/handlers, hook rejection or handler failure in ordinary batches cascades `not_executed`, and `is_interrupting` contract violations remain standardized errors.
- Keep `programmer_tools.syntax_check`, `recording_data_tools.execute_code` sandboxing, `tool_executor` venv isolation, and `dynamic_tool_manager` tool discovery rules outside hook migration.
- Keep `edit_file` `old_text` existence/uniqueness validation in the handler.
- Keep `query_data` parser/filter behavior based on `rewrite(sql)`; do not add raw-text bans for harmless comments or semicolons inside string literals.
