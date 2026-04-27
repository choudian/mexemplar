# Tasks: 高危操作确认 Toast 化（Auth Toast）

**Input**: Design documents from `/specs/004-auth-toast/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/auth-confirmation-ui.md](./contracts/auth-confirmation-ui.md), [quickstart.md](./quickstart.md)

**Tests**: Included because the specification defines independent tests and measurable outcomes, and the constitution requires coverage for UI/Worker wiring and silent failure risks.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare empty modules and test files without changing runtime behavior.

- [X] T001 Create `src/ui/widgets/auth_toast.py` with an empty `AuthToastSurface` placeholder class and module docstring
- [X] T002 [P] Create `tests/test_auth_toast_confirmation.py` with pytest imports and an autouse fixture that resets confirmation state via `src/business/agents/tools/builtin_general_tools.py`
- [X] T003 [P] Create `tests/ui/test_auth_toast_surface.py` with Qt offscreen setup and imports for `src/ui/widgets/auth_toast.py`
- [X] T004 [P] Create `tests/ui/test_chat_widget_auth_toggle.py` with Qt offscreen setup and imports for `src/ui/widgets/chat_widget.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared confirmation metadata and logging primitives that all stories depend on.

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T005 Extend `set_confirm_result` in `src/business/agents/tools/builtin_general_tools.py` with a backward-compatible optional `source` parameter
- [X] T006 Define confirmation decision/source constants and a reset helper for tests in `src/business/agents/tools/builtin_general_tools.py`
- [X] T007 Implement sanitized summary helper functions for `write_file`, `edit_file`, and `exec` arguments in `src/business/agents/tools/builtin_general_tools.py`
- [X] T008 Implement a structured confirmation decision logging helper in `src/business/agents/tools/builtin_general_tools.py`
- [X] T009 [P] Add object names and public constants for auth toast buttons/states in `src/ui/widgets/auth_toast.py`

**Checkpoint**: Foundation ready. User story implementation can now begin.

---

## Phase 3: User Story 1 - 单次确认改为非阻塞浮层 (Priority: P1) - MVP

**Goal**: Assistant 高危工具确认显示为非阻塞右下角浮层，支持"同意"、"拒绝"和超时拒绝，不影响普通 Toast 或主窗口交互。

**Independent Test**: 启动应用或 Qt offscreen 测试，触发 `write_file` 确认；确认浮层出现且主窗口仍可交互，主窗口交互响应延迟保持在 100ms 内，且"同意/拒绝/超时"分别返回正确 Worker 结果并满足 UI/Worker 超时收敛差值 <= 1s。

### Tests for User Story 1

> Write these tests first and verify they fail before implementation.

- [X] T010 [P] [US1] Add tests for sanitized summaries, accept/reject result handling, timeout logging, and backward-compatible `set_confirm_result` in `tests/test_auth_toast_confirmation.py`
- [X] T011 [P] [US1] Add UI tests for `AuthToastSurface` buttons, no close button, single terminal signal, and timeout rejection in `tests/ui/test_auth_toast_surface.py`
- [X] T012 [US1] Add AgentHandlerMixin tests for 5-Worker FIFO/no-loss confirmation queue handling, ordinary Toast coexistence, main-window interaction responsiveness <= 100ms, and UI/Worker timeout convergence <= 1s in `tests/ui/test_agent_handler_mixin.py`

### Implementation for User Story 1

- [X] T013 [US1] Add typed pending confirmation metadata and `request_id` lifecycle handling in `src/business/agents/tools/builtin_general_tools.py`
- [X] T014 [US1] Update `write_file_pre_hook`, `edit_file_pre_hook`, and `exec_pre_hook` to call typed confirmation helpers with sanitized summaries in `src/business/agents/tools/builtin_general_tools.py`
- [X] T015 [US1] Implement the non-modal `AuthToastSurface` widget with "全部允许" / "同意" / "拒绝" buttons and timeout timer in `src/ui/widgets/auth_toast.py`
- [X] T016 [US1] Replace `AgentHandlerMixin._on_confirm_action_requested` with a non-blocking auth confirmation queue in `src/ui/mixins/agent_handler_mixin.py`
- [X] T017 [US1] Add active auth toast state and resize repositioning alongside ordinary `_active_toast` in `src/ui/main_window.py`
- [X] T018 [US1] Add auth toast QSS rules without changing ordinary Toast rules in `src/ui/resources/styles.qss`
- [X] T019 [US1] Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/business/agents/tools/builtin_general_tools.py`, `src/ui/widgets/auth_toast.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, and `src/ui/resources/styles.qss`

**Checkpoint**: User Story 1 is fully functional and testable independently.

---

## Phase 4: User Story 2 - 会话级"全部允许"快捷通道 (Priority: P2)

**Goal**: 用户点击确认浮层的"全部允许"后，当前会话内 Assistant 的 `write_file` / `edit_file` / `exec` 后续高危请求自动放行；新对话自动复位。

**Independent Test**: 同一会话连续触发 10 次 `write_file`，首次点击"全部允许"后后续 9 次请求不弹浮层且直接放行；新建对话后首个高危请求重新弹浮层。

### Tests for User Story 2

> Write these tests first and verify they fail before implementation.

- [X] T020 [US2] Add business tests for auto-approve enable/disable, auto-approved decision logging, and new-chat reset state in `tests/test_auth_toast_confirmation.py`
- [X] T021 [US2] Add UI tests for "全部允许" auto-approving active/queued requests across 10 consecutive high-risk requests and new-chat settling prior-session active/queued requests in `tests/ui/test_agent_handler_mixin.py`

### Implementation for User Story 2

- [X] T022 [US2] Implement `set_auto_approve_enabled`, `is_auto_approve_enabled`, `reset_auto_approve`, and auto-approved bypass in `src/business/agents/tools/builtin_general_tools.py`
- [X] T023 [US2] Wire the `allow_all` auth toast decision to enable auto-approve and drain queued requests in `src/ui/mixins/agent_handler_mixin.py`
- [X] T024 [US2] Reset auto-approve and settle/clear visible or queued prior-session confirmation requests from the new-chat flow in `src/ui/main_window.py` and `src/ui/widgets/chat_widget.py`
- [X] T025 [US2] Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/business/agents/tools/builtin_general_tools.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, and `src/ui/widgets/chat_widget.py`

**Checkpoint**: User Stories 1 and 2 both work independently.

---

## Phase 5: User Story 3 - 顶栏 Toggle 与浮层状态双向同步 (Priority: P3)

**Goal**: 对话窗口顶栏提供"免确认" Toggle，与浮层"全部允许"共享同一会话级状态，任一入口变化后另一个入口同步显示。

**Independent Test**: 顶栏开启 Toggle 后触发 `write_file` 不弹浮层并直接放行；若开启前已有已显示或排队请求，则这些请求立即自动放行；关闭后重新弹浮层；点击浮层"全部允许"后顶栏 Toggle 在同帧或下一帧内显示开启。

### Tests for User Story 3

> Write these tests first and verify they fail before implementation.

- [X] T026 [P] [US3] Add ChatWidget tests for top "免确认" Toggle default-off, state-change signal, visible enabled-state cue, new-chat reset/off-state contract, and same-frame-or-next-frame state reflection contract in `tests/ui/test_chat_widget_auth_toggle.py`
- [X] T027 [US3] Add integration-style UI tests for Toggle auto-approve, Toggle-on draining active/queued requests, Toggle-off re-enables auth toast, and allow-all syncing Toggle state within the same frame or next frame in `tests/ui/test_agent_handler_mixin.py`

### Implementation for User Story 3

- [X] T028 [US3] Add a conversation header with a checkable "免确认" Toggle and reset API in `src/ui/widgets/chat_widget.py`
- [X] T029 [US3] Connect ChatWidget Toggle changes to business auto-approve state, drain active/queued confirmation requests on Toggle-on, and sync Toggle after "全部允许" with same-frame-or-next-frame semantics in `src/ui/main_window.py` and `src/ui/mixins/agent_handler_mixin.py`
- [X] T030 [US3] Add visible enabled-state styling and warning copy for the "免确认" Toggle in `src/ui/resources/styles.qss`
- [X] T031 [US3] Run `uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py tests/test_auth_toast_confirmation.py -q` and fix failures in `src/ui/widgets/chat_widget.py`, `src/ui/main_window.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/resources/styles.qss`, and `src/business/agents/tools/builtin_general_tools.py`

**Checkpoint**: All user stories are independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Regression coverage, documentation, and final validation across all stories.

- [X] T032 [P] Add or update guard assertions that Assistant confirmation wiring no longer imports or calls `QMessageBox.question` in `tests/ui/test_agent_handler_mixin.py`
- [X] T033 Add regression coverage proving `IntentConfirmationUI` and `ToolExecutionDialog` behavior is unchanged in `tests/test_skill_composition_regressions.py` and `tests/ui/test_agent_handler_mixin.py`
- [X] T034 [P] Update current code reality for Assistant high-risk confirmation behavior in `AGENTS.md`
- [X] T035 [P] Update active development constraints for sanitized confirmation logging and non-persistent auto-approve scope in `docs/PROJECT_CONSTRAINTS.md`
- [X] T036 Validate the manual flow in `specs/004-auth-toast/quickstart.md` against `src/ui/main_window.py`, `src/ui/widgets/chat_widget.py`, and `src/ui/widgets/auth_toast.py`
- [X] T037 Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_chat_widget_auth_toggle.py tests/test_hook_protocol.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/` and `tests/`
- [ ] T038 Run `uv run black --check src tests` and `uv run flake8 src tests`, then fix formatting/lint issues in `src/` and `tests/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies; can start immediately.
- **Foundational (Phase 2)**: Depends on Setup completion; blocks all user stories.
- **User Story 1 (Phase 3)**: Depends on Foundational; delivers MVP.
- **User Story 2 (Phase 4)**: Depends on Foundational and uses the US1 auth toast decision surface for "全部允许".
- **User Story 3 (Phase 5)**: Depends on Foundational and integrates with US2 auto-approve state.
- **Polish (Phase 6)**: Depends on all selected user stories being complete.

### User Story Dependencies

- **US1 (P1)**: Required MVP; no dependency on US2/US3.
- **US2 (P2)**: Builds on the US1 auth toast decision surface; can be validated independently after US1.
- **US3 (P3)**: Builds on the US2 auto-approve state; can be validated independently after US2.

### Within Each User Story

- Tests first; verify they fail before implementation.
- Business confirmation helpers before UI integration.
- Widget implementation before MainWindow/mixin integration.
- Story-specific validation before moving to the next priority.

### Parallel Opportunities

- T002, T003, and T004 can run in parallel after T001.
- T009 can run in parallel with T005-T008 if it only touches `src/ui/widgets/auth_toast.py` constants.
- T010 and T011 can run in parallel; T012 touches an existing mixin test file and should be sequenced with other edits to that file.
- T026 can run in parallel with T027 only if no one else is editing `tests/ui/test_agent_handler_mixin.py`.
- T032 and T033 should be sequenced because both touch `tests/ui/test_agent_handler_mixin.py`; T034 and T035 can run in parallel with either of them because they update different documentation files.

---

## Parallel Example: User Story 1

```text
Task: "Add tests for sanitized summaries, accept/reject result handling, timeout logging, and backward-compatible set_confirm_result in tests/test_auth_toast_confirmation.py"
Task: "Add UI tests for AuthToastSurface buttons, no close button, single terminal signal, and timeout rejection in tests/ui/test_auth_toast_surface.py"
```

---

## Parallel Example: User Story 3

```text
Task: "Add ChatWidget tests for top 免确认 Toggle default-off, state-change signal, and new-chat reset in tests/ui/test_chat_widget_auth_toggle.py"
Task: "Add visible enabled-state styling and warning copy for the 免确认 Toggle in src/ui/resources/styles.qss"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 for US1.
3. Stop and validate `write_file` single-request confirm, reject, and timeout behavior.
4. Run the US1 targeted test command in T019.

### Incremental Delivery

1. Deliver US1: non-blocking auth toast for one request.
2. Deliver US2: session-level "全部允许" and new-chat reset.
3. Deliver US3: top Toggle and bidirectional state sync.
4. Run cross-story regression and docs tasks.

### Validation Gate Before Implementation Handoff

After generating these tasks, run `/speckit.analyze` before `/speckit.implement` to catch cross-artifact gaps.

---

## Notes

- `[P]` means different files and no dependency on incomplete tasks.
- `[US1]`, `[US2]`, and `[US3]` map directly to the user stories in `spec.md`.
- Keep `IntentConfirmationUI` and `ToolExecutionDialog` behavior out of scope except for regression guards.
- Do not add SQLite/DuckDB migrations or unified config keys for this feature.
