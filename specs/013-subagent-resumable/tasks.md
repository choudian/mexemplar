---
description: "Task list for 013-subagent-resumable"
---

# Tasks: 子代理可唤回机制（Resumable / Re-dispatchable Subagent）

**Input**: Design documents from `specs/013-subagent-resumable/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: 已请求（宪法 IV 可验证交付 + 改静默失败/恢复逻辑必须补行为契约测试）。测试任务包含在内。

> **状态说明（2026-06-03）**：**全部任务已完成**。`test_subagent_resumable.py` **15 例全过**、相关回归全过、py_compile/flake8 通过。改动已提交到 `013-subagent-resumable` 分支（commit `4b7d84f`，15 files）。

## Project Paths

- **Python source**: `src/business/agents/`、`src/business/orchestration/agent/`
- **Python tests**: `tests/business/agents/`、`tests/integration/`
- **Runner**: `uv run python -m pytest`；格式 `uv run black src/ tests/`、`uv run flake8 src/ tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 纯 business 层增量，无脚手架/依赖初始化；worktree、分支、spec 已就绪。

- [X] T001 确认 plan.md 选定结构：改动限于 `src/business/agents/` 与 `src/business/orchestration/agent/`，复用既有 session/message 持久化（无新表、无迁移、无新配置键）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有 user story 都依赖的终止语义开关、句柄与归属校验。

**⚠️ CRITICAL**: 本阶段完成前任何 user story 不能开始。

- [X] T002 在 `src/business/agents/config.py` 新增 `ResultType.PAUSED` 与 `AgentConfig.resumable_on_failure: bool = False`（默认假，保证非临时 Agent 零回归）
- [X] T003 在 `src/business/orchestration/agent/orchestrator.py` 的 ephemeral 子代理 `AgentConfig` 设 `resumable_on_failure=True`、`max_iterations=50`
- [X] T004 在 `orchestrator.py` 让所有委派返回路径回传 `subagent_id`（= executor session id），供后续 inspect/continue 句柄使用（FR-004）
- [X] T005 在 `orchestrator.py` 实现 `_resolve_subagent_session`：校验存在 + `agent_type==EPHEMERAL_SUBAGENT` + `workflow_id` 以 `dlg_{parent[:12]}_` 开头，否则 `None`（FR-008 / SC-007 的共享前提，US1 续跑与 US3 查看都依赖）

**Checkpoint**: 终止语义开关、句柄、归属校验就绪 — user story 可开始。

---

## Phase 3: User Story 1 - 迭代超限后唤回续跑 (Priority: P1) 🎯 MVP

**Goal**: 临时子代理撞迭代上限不丢工作，转可唤回暂停；主代理凭 `subagent_id` 唤回从断点续跑直至完成，可重复唤回。

**Independent Test**: 委派一个会顶到迭代上限的任务 → 返回 `paused:true`+`subagent_id`+`reason="已达迭代上限（N 轮）"`、历史保留 → `continue_subagent` 续跑完成；再撞上限仍可再唤回。

### Tests for User Story 1

- [X] T006 [P] [US1] `tests/business/agents/test_subagent_resumable.py::TestAgentLoopPause::test_iteration_limit_pauses_when_resumable`（撞上限→PAUSED+suspended）
- [X] T007 [P] [US1] `...::test_iteration_limit_default_still_max_reached`（默认 Agent 仍 MAX_ITERATIONS_REACHED，回归保护）
- [X] T008 [P] [US1] `...::TestDelegateReturnsHandle::test_delegate_paused_returns_handle` 与 `test_delegate_returns_subagent_id_on_complete`
- [X] T009 [P] [US1] `...::TestContinueSubagent::test_continue_repause_keeps_handle`（再次中断仍返回句柄，FR-009）

### Implementation for User Story 1

- [X] T010 [US1] 在 `src/business/agents/agent_loop.py` 超过 `max_iterations` 分支：当 `resumable_on_failure` 为真，`update_session_status("suspended")` 并返回 `ResultType.PAUSED`，reason=`"已达迭代上限（N 轮）"`（FR-001）
- [X] T011 [US1] 在 `orchestrator.py` `_run_delegated_executor` 对 `ResultType.PAUSED` 返回可唤回句柄（`paused/subagent_id/reason/result_type`）并记 `assistant_delegation_paused` workflow transition（FR-001 / R5）
- [X] T012 [US1] 在 `orchestrator.py` 实现 `_continue_subagent`：归属校验→拒 `active`→以 `resumable_on_failure=True` 新 loop 对既有 `subagent_id` 调 `loop.run`，用主代理当前工具池重建；完成返回 `result_text`，再暂停返回句柄（FR-006 / FR-007 / FR-009 / R4）
- [X] T013 [US1] 在 `src/business/agents/tools/assistant_tools.py` 新增 `CONTINUE_SUBAGENT_SCHEMA` + `create_continue_subagent_handler`
- [X] T014 [US1] 在 `orchestrator.py` 注册 `continue_subagent` 工具（schema + handler 接 `_continue_subagent` callback）并加入主代理工具列表

**Checkpoint**: US1 可独立验收（MVP）—零工作丢失、断点续跑、可重复唤回。

---

## Phase 4: User Story 2 - 调用失败后保活、待恢复再续 (Priority: P1)

**Goal**: 账单/网络类 LLM 调用最终失败时子代理原地冻结保活、暂停原因可区分；外部恢复后（含进程重启）凭 `subagent_id` 唤回续跑。

**Independent Test**: 制造持续 LLM 调用失败（无效凭据/断网）→ 返回 `paused:true`+调用失败类 reason、历史保留 → 恢复后唤回成功续跑。

### Tests for User Story 2

- [X] T015 [P] [US2] `...::TestAgentLoopPause::test_llm_failure_pauses_when_resumable`（重试耗尽→PAUSED 而非 ERROR）
- [X] T016 [P] [US2] `...::test_llm_failure_default_still_error`（默认 Agent 仍 ERROR，回归保护）

### Implementation for User Story 2

- [X] T017 [US2] 在 `agent_loop.py` `_call_llm_with_retry` 返回 `None`（重试耗尽）分支：当 `resumable_on_failure` 为真，`update_session_status("suspended")` 并返回 `ResultType.PAUSED`（FR-002）
- [X] T018 [US2] 暂停原因携带可区分的调用失败类标识（FR-003），主代理 prompt 据此走"等外部恢复"策略
- [X] T019 [US2] 跨进程重启唤回依赖持久化历史（`ContextManager` 经 `MessageRepository` 从 SQLite 重建，非进程内存）—复用 US1 `_continue_subagent` 路径，无需独立持久化机制（FR-007 / CC-001 / SC-003）

**Checkpoint**: US1 + US2 各自独立可用。

---

## Phase 5: User Story 3 - 诊断"任务复杂"还是"走弯路" (Priority: P2)

**Goal**: 主代理在唤回前调取子代理工作概览（轮数/工具调用次数/最后产出/状态），零额外模型调用，据此决定续跑还是新开。

**Independent Test**: 对暂停子代理 `inspect_subagent` → 返回结构化概览且 `chat_with_tools` 未被调用；据此走 continue 或重新 delegate 两条路。

### Tests for User Story 3

- [X] T020 [P] [US3] `...::TestInspectSubagent::test_inspect_returns_overview_without_llm`（含 `chat_with_tools.assert_not_called()`）与 `test_inspect_rejects_foreign_session`（FR-008）

### Implementation for User Story 3

- [X] T021 [US3] 在 `orchestrator.py` 实现 `_inspect_subagent`：归属校验后从 `MessageRepository.get_context` 机械聚合 `assistant_turns`/`tool_call_counts`/`last_output`/`status`，**不触发任何模型调用**（FR-005 / SC-004）
- [X] T022 [US3] 在 `assistant_tools.py` 新增 `INSPECT_SUBAGENT_SCHEMA` + `create_inspect_subagent_handler`；`orchestrator.py` 注册 `inspect_subagent` 工具

**Checkpoint**: US1–US3 独立可用。

---

## Phase 6: User Story 4 - 对已完成但未达标的结果返工 (Priority: P3)

**Goal**: 对已正常完成的子代理带追加指令唤回，在原有上下文基础上补齐返工，不从零重派。

**Independent Test**: 让子代理完成一个部分达标任务 → `continue_subagent(subagent_id, instruction="补齐…")` → 在原上下文继续而非重头再来。

### Tests for User Story 4

- [X] T023 [P] [US4] `...::TestContinueSubagent::test_continue_completed_with_instruction`（instruction 作为续跑输入进入既有上下文）

### Implementation for User Story 4

- [X] T024 [US4] `_continue_subagent` 接受已 `completed` 子代理（仅拒 `active`），`instruction` 经 `loop.run(user_input=instruction)` 进入既有上下文继续（FR-006）

**Checkpoint**: 全部 4 个 user story 独立可用。

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 决策层引导、保真度收尾、活文档与提交。

- [X] T025 在 `src/business/agents/prompts/assistant_prompt.py` 新增"子代理暂停（可唤回）时的处理"引导段：账单/网络等恢复后再 continue、迭代超限先 inspect 诊断、复杂则 continue/走弯路则重新 delegate、已完成未达标带 instruction 返工（FR-010）
- [X] T026 **[MEDIUM / research R3]** 收敛 `agent_loop.py` 失败分类：新增 `_is_recoverable_llm_failure`（遍历异常链匹配配额/限流/网络标记），仅可恢复失败转 PAUSED（reason 标"账单或网络"），其余不可恢复错误（400/认证/校验等）仍走 `ERROR` 置会话 `failed`；补契约测试 `test_llm_failure_nonrecoverable_still_error_when_resumable`（14 例全过）
- [X] T027 **[LOW / review L1]** `_continue_subagent` 显式处理 `NEEDS_USER_INPUT`：对已完成子代理不带 instruction 唤回时回明确提示"需带 instruction 说明要补齐/修正什么"，不再含糊失败；补测试 `test_continue_completed_without_instruction_asks_for_instruction`（含 `chat_with_tools.assert_not_called()`）
- [X] T028 [P] 更新 `src/AGENTS.md`（及同目录 `CLAUDE.md` / `GEMINI.md` 镜像）「Agent 与工具约束」：临时子代理撞迭代上限/调用失败转可唤回暂停、可恢复失败分类、新增 `inspect_subagent`/`continue_subagent`、归属校验、100% 调度不变
- [X] T029 [P] 在 `docs/ARCHITECTURE.md` Agent 编排通信小节补"临时子代理可唤回"段（PAUSED 终止、可唤回句柄、内部 transition、inspect/continue 调度、不可恢复失败仍 ERROR）
- [X] T030 运行 quickstart 验证：`uv run python -m pytest tests/business/agents/test_subagent_resumable.py -q`（13 passed）+ 回归套件（69 passed）
- [X] T031 在 `013-subagent-resumable` 分支提交 spec 全套 + 源码 + 测试 + docs（commit `4b7d84f`，15 files）。注：根/`src` 的 `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` 被 gitignore，属本地状态，不进提交

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup** → 无依赖。
- **Phase 2 Foundational** → 阻塞所有 user story（T002 配置开关、T004 句柄、T005 归属校验是公共前提）。
- **US1 (Phase 3)** → 依赖 Foundational；MVP。
- **US2 (Phase 4)** → 依赖 Foundational；与 US1 并列 P1，复用 US1 的 `_continue_subagent` 恢复路径（T019←T012）。
- **US3 (Phase 5)** → 依赖 Foundational（尤其 T005 归属校验）；独立可测。
- **US4 (Phase 6)** → 依赖 US1 的 `_continue_subagent`（T024←T012）。
- **Polish (Phase 7)** → 引导段(T025)跨故事；T026/T027 为收尾；文档/提交(T028–T031)最后。

### Within Each User Story

- 测试先于实现（本特性测试已与实现一并落地并通过）。
- agent_loop 终止语义 → orchestrator 句柄/编排 → 工具 schema/注册。

### Parallel Opportunities

- T006–T009（US1 测试）、T015–T016（US2 测试）、T020（US3 测试）、T023（US4 测试）各组 `[P]` 可并行编写。
- T028 / T029 文档任务 `[P]` 可并行（不同文件）。
- US1 与 US2 终止路径在同一 `agent_loop.run` 方法内（T010 与 T017 改相邻分支），**不宜并行编辑同一文件**。

---

## Implementation Strategy

### MVP First

1. Phase 1 Setup → Phase 2 Foundational（开关/句柄/归属校验）。
2. Phase 3 US1（迭代超限唤回续跑）→ 独立验收即 MVP。

### Incremental Delivery

US1（MVP）→ US2（失败保活，复用恢复路径）→ US3（诊断概览）→ US4（返工）；每步独立加值不破坏前者。

### 完成状态

T001–T031 全部完成并验证（15 契约 + 回归全过、py_compile/flake8 通过），已提交 `4b7d84f`。本特性可进入 `/speckit-analyze` / `/speckit-verify` 或合并流程。

---

## Notes

- [P] = 不同文件、无依赖。
- [Story] 标签映射 user story 便于追溯。
- `[X]` = 已实现并经测试验证（14 契约 + 69 回归全过、py_compile/flake8 通过）。
- T026（FR-003 / Assumptions 保真度缺口）已收敛：可恢复失败分类落地并补测。
