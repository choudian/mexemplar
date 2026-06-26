# Tasks: 024 Task Graph Scheduling（复杂任务"先分解，再按图执行"纠偏）

**Input**: Design documents from `/specs/024-task-graph-scheduling/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/, quickstart.md

**Tests**: 本特性测试**必需**（constitution IV 可验证交付 + CLAUDE.md 硬规则 6 改静默失败路径必补测试 + spec §8 测试策略）。每个 user story 阶段测试任务前置（TDD：先写测试、确认 FAIL 再实现）。

**Organization**: 按 user story 组织（US1 复杂分解按图执行 / US2 简单走快通道 / US3 高风险暂停确认 / US4 失败先自愈 / US5 进度可见+取消），每 story 可独立实现与测试。

**基线**：worktree commit `06053db`（023 已落地）。所有 023 接口契约见 research.md §2。不碰 orchestrator.py 死代码（`_build_*`），工具装配落 tool_registry.py。

## Constitution-Driven Minimums

- ✅ Repository/migration 任务：migration v17（`requires_confirmation` + `role_kind`）— Phase 1。
- ⬜ DuckDB 边界：本特性不涉及录制数据，无 DuckDB 任务。
- ✅ 配置任务：复杂度阈值 + planner 注册走 `UnifiedConfigManager`（默认值/模板/脱敏）— Phase 1。
- ✅ 接线冒烟 + 门卫测试：复杂必落库为 DAG、planner 不拿执行器工具、dependency 边写入、简单任务不建图 — Phase 2/3/4。
- ✅ 活文档更新：`docs/ARCHITECTURE.md`、根 `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`、`docs/FEATURES.md` — Phase 8。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属 user story（US1~US5）；Setup/Foundational/Polish 阶段无 story 标签
- 描述含确切文件路径

## Project Paths

- **Python source**: `src/`（business, desktop_api, data, execution, recording, utils）
- **Frontend source**: `frontend/src/`
- **Python tests**: `tests/`（guardrails, integration, business, data）
- **Frontend tests**: `frontend/tests/unit/`、`frontend/tests/e2e/`
- **Runner**: `uv run pytest tests/`；`uv run black src/ tests/`；`uv run flake8 src/ tests/`；前端 `npm run lint`/`npm run test`

---

## Phase 1: Setup（数据脚手架）

**Purpose**: migration v17 + ORM + 配置键，为所有 story 提供数据基础。

- [x] T001 Add migration v17: `assistant_tasks.requires_confirmation INTEGER NOT NULL DEFAULT 0` and `brain_specialists.role_kind TEXT NOT NULL DEFAULT 'executor'` in `src/data/migrations.py`
- [x] T002 [P] Add `requires_confirmation` to `AssistantTask` ORM and `role_kind` to specialist ORM in `src/data/models_sqlite.py`
- [x] T003 [P] Add unified config keys for complexity thresholds and planner specialist registration (defaults in config.json, app_settings override, masked/redaction N/A — non-secret) in `src/data/unified_config.py`

**Checkpoint**: v17 可 `alembic upgrade head`，两列默认值兼容现有数据。

---

## Phase 2: Foundational（阻塞原语，所有 story 复用）

**Purpose**: 多 story 共享的底层原语。**⚠️ CRITICAL**：未完成前 user story 不可开工。

- [x] T004 [P] Implement `_assert_dependencies_satisfied(graph_id, task_id)` ready-check (all `edge_type='dependency'`+`propagation='blocking'` predecessors must be `completed`) in `src/data/repos/assistant_task_repository.py`
- [x] T005 [P] Implement `TaskCollaborationService.build_task_graph(session_id, nodes, dependencies)` atomic entry (reuse `_atomic`; create root + node tasks with `requires_confirmation`/`capability_scope`; add `edge_type='dependency', propagation='blocking'` edges via `add_edge` which reuses `_assert_no_cycle`; respect `get_assistant_tasks_graph_max_tasks()`) in `src/business/task_collaboration/service.py`
- [x] T006 [P] Extend `build_reentry_briefing(entries, *, snapshot=None)` with text-segment helpers (next-step suggestions / self-heal action list / todo overview); keep pure function, no IO in `src/business/task_collaboration/reentry_briefing.py`
- [x] T007 Wire `assistant_runtime._run_assistant_reentry` to load graph snapshot after drain and pass to `build_reentry_briefing` (depends T006) in `src/desktop_api/assistant_runtime.py`
- [x] T008 [P] Add complexity-classification + decomposition-decision section to assistant prompt (between `### 任务分类` and `### 100% 调度规则`): route simple→fast delegation, medium→build_task_graph, above-threshold→delegate_to_specialist(planner) in `src/business/agents/prompts/assistant_prompt.py`
- [x] T009 [P] Expand `todo_update` tool description (when to use ≥3 sub-steps, three-state flow, completion red-line) and soften `_SUBAGENT_WORK_RULES` rules 2/3 (no longer discourage planning) in `src/business/agents/tools/assistant_tools.py` and `src/business/orchestration/agent/orchestrator.py`
- [x] T010 [P] Add `requiresConfirmation` projection to task graph snapshot DTO + frontend type (read path, consumes existing `assistant.task_graph.changed` event, 0 new event) in `src/desktop_api/schemas.py` and `frontend/src/api/assistantTasks.ts`

**Checkpoint**: 共享原语就位，user story 可并行开工。

---

## Phase 3: User Story 1 — 复杂任务分解成有序图并按序执行 (Priority: P1) 🎯 MVP

**Goal**: 复杂任务经主助理自拆（中等）或规划专员（超阈值）产出带 dependency 边的 DAG，由确定性 scheduler 按依赖自动推进、全图完成后汇报。
**Independent Test**: 给一个多步跨领域复杂任务，观察执行前产出多节点+依赖边的图，节点按依赖顺序完成、无依赖节点并行、全图完成后主助理汇报。

### Tests for User Story 1（TDD：先写、确认 FAIL）

- [x] T011 [P] [US1] Architecture guard: complex task (above-threshold trigger) MUST persist as DAG with dependency edges and be scheduler-driven; reject one-shot delegation regression in `tests/guardrails/test_task_graph_scheduling_guard.py`
- [x] T012 [P] [US1] Scheduler unit tests: ready-activation order (serial chain, parallel fan-out, mixed), cycle reject (reuse), ready-check rejects out-of-order in `tests/business/task_collaboration/test_graph_scheduler.py`
- [x] T013 [P] [US1] Planner specialist guard: planner tool set excludes executor tools (`todo_update`/`ask_parent`); planner gets `build_task_graph` variant in `tests/guardrails/test_planner_specialist_tools.py`

### Implementation for User Story 1

- [x] T014 [US1] Implement DAG scheduler core `GraphScheduler` (`start_graph`, `advance` loop with ready-scan + `_assert_dependencies_satisfied` + capacity=1 dispatch via `start_attempt_async`, `on_attempt_outcome`, `on_executor_recovered`, full-graph-complete notification) in `src/business/task_collaboration/graph_scheduler.py`
- [x] T015 [US1] Wire scheduler triggers: `start_graph` from build_task_graph handler; `on_attempt_outcome` hook in dispatcher `_record_attempt_outcome`; `on_adjudication_decided` in adjudication; `on_executor_recovered` in background_worker `_fence_expired_attempts` in `src/business/task_collaboration/dispatcher.py`, `src/business/task_collaboration/adjudication.py`, `src/business/task_collaboration/background_worker.py`
- [x] T016 [US1] Implement `build_task_graph` + `mutate_task_graph` assistant tools (schema + handler factory per 023 pattern; call service methods; return graphId/nodeTaskIds) in `src/business/agents/tools/assistant_tools.py`
- [x] T017 [US1] Assemble `build_task_graph` + `mutate_task_graph` into `tool_registry.build_assistant_tools()` static_tools list in `src/business/orchestration/agent/tool_registry.py`
- [x] T018 [US1] Add planner `role_kind` branching in `build_delegated_executor_tools`: planner specialist gets `build_task_graph` (read-only planning variant), NOT executor tools (`todo_update`/`ask_parent`/specialist-subagent-tools) in `src/business/orchestration/agent/tool_registry.py`
- [x] T019 [US1] Add planner specialist recruitment/registration path (`role_kind='planner'`; first version supports config/manual registration to avoid signal-threshold cold start) in `src/business/brain/specialist_service.py`
- [x] T020 [US1] Verify `delegate_to_specialist(specialist_name=<planner>)` above-threshold path end-to-end (planner produces graph via build_task_graph, returns graphId, main assistant triggers scheduler) — wiring check + prompt guidance already in T008 in `src/business/agents/tools/assistant_tools.py`
- [x] T021 [US1] Integration E2E: medium self-decompose + above-threshold planner path → schedule in dependency order → parallel independent nodes → full completion reports to user in `tests/integration/test_task_graph_e2e.py`

**Checkpoint**: US1 独立可测——复杂任务分解、按序调度、全图完成。

---

## Phase 4: User Story 2 — 简单任务走快速通道、不建图 (Priority: P1)

**Goal**: 1-2 步单领域简单任务继续走现有快速委派，不建图，无回归。
**Independent Test**: 给一个简单任务，观察直接 `delegate_to_subagent/specialist`、不产出任务图、行为/延迟与改造前一致。

### Tests for User Story 2

- [x] T022 [P] [US2] Regression guard: simple task (1-2 steps, single domain) uses fast delegation, builds no graph; existing durable-accepted/recovery/concurrency paths not degraded in `tests/guardrails/test_task_graph_scheduling_guard.py`

### Implementation for User Story 2

- [x] T023 [US2] Tune complexity-classification prompt so simple tasks are not over-routed to build_task_graph; verify fast-delegation path unchanged in `src/business/agents/prompts/assistant_prompt.py`

**Checkpoint**: US2 守住——简单任务零回归。

---

## Phase 5: User Story 3 — 高风险步骤执行前暂停等待确认 (Priority: P2)

**Goal**: `requires_confirmation=1` 节点在依赖前置完成后，scheduler 暂停、不 dispatch，建 pending adjudication 回流主助理裁定；放行后才执行。
**Independent Test**: 含高风险节点的图，该节点前置完成后暂停上浮，未放行前 100% 不执行；放行后继续。

### Tests for User Story 3

- [x] T024 [P] [US3] Integration test: requires_confirmation node pauses before dispatch; never executes without adjudication accepted; accepted→dispatch resumes; suspendReason reuses `waiting_user` (DEC-G) in `tests/integration/test_task_graph_confirmation.py`

### Implementation for User Story 3

- [x] T025 [US3] Scheduler: before dispatching `requires_confirmation=1` node, skip dispatch, create pending adjudication (`kind=needs_confirmation`) + notify via reentry (DEC-D) in `src/business/task_collaboration/graph_scheduler.py`
- [x] T026 [US3] Add `needs_review` reentry_type in dispatcher `_paused_reentry_payload` + matching briefing segment in `src/business/task_collaboration/dispatcher.py` and `src/business/task_collaboration/reentry_briefing.py`
- [x] T027 [US3] Wire confirmation adjudication: `decide(accepted)` → `on_adjudication_decided` → scheduler dispatches the node; `returned`/`abandoned` handled per data-model §3 in `src/business/task_collaboration/adjudication.py`

**Checkpoint**: US3 独立可测——高风险节点裁定前绝不执行。

---

## Phase 6: User Story 4 — 节点失败先自愈，兜不住再升级 (Priority: P2)

**Goal**: 节点失败时回流 briefing 附自愈动作清单；主助理优先自愈（重试/换执行器/调输入/跳过/改图），兜不住才 `ask_user_question` 升级。
**Independent Test**: 制造节点失败，观察回流附自愈清单，可恢复场景多数自愈不升级用户。

### Tests for User Story 4

- [x] T028 [P] [US4] Integration test: node failure (stuck/failed_input) offers self-heal actions; self-heals without escalation when recoverable; escalates via ask_user_question only when unrecoverable in `tests/integration/test_task_graph_self_heal.py`

### Implementation for User Story 4

- [x] T029 [US4] Add `healingActions` (deterministic candidate set by failure class) + `safeRecoveryHint` (safe projection, no provider error leak) to failure entry payload in `src/business/task_collaboration/dispatcher.py`
- [x] T030 [US4] Render self-heal action list segment in briefing from failure entry `healingActions` in `src/business/task_collaboration/reentry_briefing.py`
- [x] T031 [US4] Implement `mutate_task_graph` (add_node/skip_node/add_dependency/remove_dependency; reuse `_assert_no_cycle`; bump graph_version; skip-node downstream rule per data-model §3) as service method + tool handler in `src/business/task_collaboration/service.py` and `src/business/agents/tools/assistant_tools.py`
- [x] T032 [US4] Add self-heal decision guidance to assistant prompt (retry/swap/adjust→decide returned; replan/skip→mutate_task_graph; give up→decide abandoned; stuck→ask_user_question) in `src/business/agents/prompts/assistant_prompt.py`

**Checkpoint**: US4 独立可测——失败优先自愈。

---

## Phase 7: User Story 5 — 中途可见进度、能取消/改主意 (Priority: P3)

**Goal**: 节点 todo 概览回流主助理；用户按需在 TaskGraphPanel 节点展开看 todo（默认界面不展示）；取消顺图传播、改主意走 cancel+重分解。
**Independent Test**: 图运行中取消→顺图停止无孤儿；改主意→取消旧图重分解；TaskGraphPanel 展开节点看 todo、默认不展示。

### Tests for User Story 5

- [x] T033 [P] [US5] Integration test: cancel propagates through graph (in-flight retracted, unstarted cancelled, no orphan); redirect = cancel old graph + re-decompose (reuses 023 `cancel_graph` + 3-layer cancel keys) in `tests/integration/test_task_graph_cancel.py`
- [x] T034 [P] [US5] Frontend unit: todo on-demand visible via TaskGraphPanel node expand (reuses `todosByTaskId` + `GET /tasks/{id}/todos`); hidden in default task UI in `frontend/tests/unit/task-graph-todo-visibility.test.tsx`

### Implementation for User Story 5

- [x] T035 [US5] Render todo overview segment in briefing (aggregate per-node todo status from snapshot via `TaskTodoService.list_todos`, read-only) in `src/business/task_collaboration/reentry_briefing.py`
- [x] T036 [P] [US5] Frontend: TaskGraphPanel node-expand todo (reuse `assistantTaskStore.todosByTaskId` + existing todo API/event; default hidden, expand on user action; 0 change to 014 SubagentCard/Drawer per DEC-E) in `frontend/src/screens/assistant/TaskGraphPanel.tsx`
- [x] T037 [US5] Verify cancel/redirect via existing `cancel_graph` + three-layer cancel keys (graph/task/attempt) — wiring confirmation, no new infra in `src/business/task_collaboration/service.py`

**Checkpoint**: 全部 story 独立可用。

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 跨 story 收口与活文档同步。

- [x] T038 [P] Update active doc: task_collaboration runtime overview + DAG scheduling in `docs/ARCHITECTURE.md`
- [x] T039 [P] Update AI entry mirrors (Recent Changes + active feature 024) in `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, and feature list in `docs/FEATURES.md`
- [x] T040 [P] Add spec FR-012 wording footnote (DEC-E: todo visibility mechanism = TaskGraphPanel node-expand, not 014 SubagentDrawer; intent unchanged) in `specs/024-task-graph-scheduling/spec.md`
- [x] T041 Full E2E integration: decompose → schedule → needs-confirmation adjudicate → failure self-heal → cancel/redirect in `tests/integration/test_task_graph_full_e2e.py`
- [x] T042 Run `uv run black src/ tests/`, `uv run flake8 src/ tests/`, `uv run pytest tests/` green; frontend `npm run lint`, `npm run test` green; run quickstart.md validation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始。blocks all.
- **Foundational (Phase 2)**: 依赖 Phase 1（T002 ORM 列供 T005/T010 用）；**blocks 所有 user story**。
- **User Stories (Phase 3-7)**: 均依赖 Phase 2。
- **Polish (Phase 8)**: 依赖所有目标 story 完成。

### User Story Dependencies

- **US1 (P1)**: 依赖 Phase 2；无其他 story 依赖。**MVP**。
- **US2 (P1)**: 依赖 Phase 2（T008 prompt 路由）；与 US1 独立（守门卫性质）。
- **US3 (P2)**: 依赖 US1（scheduler 必须存在才能在派发前暂停）+ Phase 2（briefing）。
- **US4 (P2)**: 依赖 US1（scheduler/attempt outcome）+ Phase 2（briefing、mutate 原语）。
- **US5 (P3)**: 依赖 US1（图存在）+ Phase 2（briefing todo 段）；取消复用 023，与 US3/US4 独立。

### Story 完成顺序

```
Phase1 Setup → Phase2 Foundational → US1 (MVP)
                                   → US2 (guard，可与 US1 并行)
                          US1 done → US3 ┐
                                   → US4 ├ 可并行（各在 US1 scheduler 上叠加）
                                   → US5 ┘
                        all stories → Phase8 Polish
```

### Within Each User Story

- 测试先写、确认 FAIL，再实现。
- Repository/数据 → service → 工具/orchestration → 接线 → 集成测试。
- scheduler/确定逻辑配单测；架构切换配门卫+冒烟测试。

### Parallel Opportunities

- Phase 1：T002/T003 [P]（不同文件）。
- Phase 2：T004/T005/T006/T008/T009/T010 [P]（不同文件）；T007 依赖 T006。
- US1：T011/T012/T013 测试 [P] 并行；T016→T017→T018 装配链顺序。
- US1 完成后：US3/US4/US5 可并行（不同关注：确认暂停 / 自愈 / 可见性+取消）。
- US5 前端（T036）可与 US3/US4 后端并行。

---

## Parallel Example: User Story 1

```bash
# 并行写 US1 测试（先 FAIL）：
Task: "T011 guard: complex→DAG+scheduler in tests/guardrails/test_task_graph_scheduling_guard.py"
Task: "T012 scheduler unit in tests/business/task_collaboration/test_graph_scheduler.py"
Task: "T013 planner tools guard in tests/guardrails/test_planner_specialist_tools.py"

# 顺序实现（不同文件，但 T017 依赖 T016，T015 依赖 T014）：
Task: "T014 GraphScheduler core in src/business/task_collaboration/graph_scheduler.py"
Task: "T016 build_task_graph + mutate_task_graph tools in assistant_tools.py"
Task: "T017 assemble tools in tool_registry.py"
```

---

## Implementation Strategy

### MVP First（仅 US1）

1. Phase 1 Setup（migration v17 + ORM + config）
2. Phase 2 Foundational（共享原语）
3. Phase 3 US1（scheduler + build_task_graph + planner + 接线 + 测试）
4. **STOP and VALIDATE**：独立测 US1（复杂任务分解→按序调度→全图完成）
5. 可演示

### Incremental Delivery

1. Setup + Foundational → 引擎就位
2. +US1 → 独立测 → MVP
3. +US2 → 守简单任务零回归
4. +US3 → 高风险暂停确认
5. +US4 → 失败自愈
6. +US5 → 进度可见+取消
7. Phase 8 Polish → 活文档 + 全链路 E2E + lint/test green

### Parallel Team Strategy

1. 团队共同完成 Setup + Foundational
2. Foundational 完成后：US1 优先（MVP，单人推进装配链）
3. US1 完成后：US3/US4/US5 三人并行

---

## Notes

- [P] = 不同文件、无未完成依赖。
- [Story] 标签映射到 spec.md 的 user story。
- 每个 story 独立可完成、可测试。
- 测试先写、确认 FAIL 再实现（constitution IV）。
- 每个任务或逻辑组后提交。
- 在 checkpoint 处独立验证 story。
- 避免：模糊任务、同文件冲突、破坏独立性的跨 story 依赖。
- 待定项（见 plan.md 末尾）：planner 冷启动招募机制、skip 节点下游策略、suspendReason 精确化、graph_version 批量优化——在对应任务实现时定。
