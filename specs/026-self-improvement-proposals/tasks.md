---
description: "Task list — 自我改进提案（B 阶段）"
---

# Tasks: 自我改进提案 — 半自动执行复盘改造闭环（B 阶段）

**Input**: `specs/026-self-improvement-proposals/`（spec.md / plan.md / research.md / data-model.md / contracts/）
**Tests**: 含测试任务 —— spec CC-008 与 constitution IV 明确要求静默失败/编排/Repository/恢复路径补行为契约 + 门卫测试。
**Organization**: 按 user story 分组（US1=提案+审批；US2=桥接自动实施；US3=隔离与安全保证）。排序遵循 plan「实施排序与门禁」：数据层 foundational → US1 先行 → US2 以 T0 spike 为门 → US3 → 收尾。

## Format: `[ID] [P?] [Story] Description with file path`
- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: US1/US2/US3（Setup/Foundational/Polish 无标签）

---

## Phase 1: Setup

- [x] T001 在 `src/data/unified_config.py` 增加 `self_improvement.proposals.*` 配置 getter（`enabled`、`worktree_retention_max`、`dedup_cooldown_hours`（A3 去重冷却窗口默认 24h）等），并在 `config.example.json` 补本地默认值；走 `UnifiedConfigManager` 三处同步，不硬编码（CC-003）。

## Phase 2: Foundational（阻塞 US1 + US2，先完成）

- [x] T002 在 `src/data/migrations.py` 新增 `migrate_to_v21`：建 `improvement_proposals` 表（字段见 data-model.md），含 `UNIQUE(source_review_id, finding_index)`、`INDEX(status)`、`INDEX(dedup_key)`；注册进 `_MIGRATIONS` 并把 schema 版本推到 21（当前 v20）。
- [x] T003 [P] 在 `src/data/models_sqlite.py` 新增 `ImprovementProposal` ORM model（与 v21 表对齐，含 `dedup_key` / `user_supplement` / `graph_id` / `worktree_path` / `branch_name` / 结果回报列）。
- [x] T004 新建 `src/data/repos/improvement_proposal_repository.py`：`create`（幂等：撞 UNIQUE 跳过 + 按 `dedup_key` 抑制同类未终态/冷却内提案）、`list_recent` / `list_by_status`、`get_by_id`、`approve` / `reject` / `mark_in_progress` / `mark_done` / `mark_failed`（全部条件 UPDATE + rowcount CAS）、`has_in_progress`（串行化闸门 FR-018）；在 `src/data/repos/__init__.py` 导出。
- [x] T005 [P] `tests/data/test_improvement_proposal_migration.py`：v20→v21 升级、表/索引/唯一约束存在、幂等重跑。
- [x] T006 [P] `tests/data/test_improvement_proposal_repository.py`：CAS 状态机合法/非法流转、create 幂等 + dedup 抑制、`has_in_progress` 串行闸门、并发重复 approve 不双触发。

**Checkpoint**: 数据层就绪，US1 与 US2 可在其上展开。

---

## Phase 3: User Story 1 — 看见可执行的改进提案并人工把关 (P1) 🎯 MVP

**Goal**: 复盘 `worth_changing` finding → 提案 → BrainScreen 审批+补料/拒绝。**不依赖 US2 桥接，可独立交付与验证。**
**Independent Test**: 构造含 `worth_changing` 的复盘 → 断言提案出现、状态正确；批准（带补料）/拒绝流转持久化、刷新不丢；同复盘重处理不重复、跨复盘同类不刷屏。

- [x] T007 [US1] 新建 `src/business/self_improvement/proposal_service.py`：`generate_from_review(review)` 从 `worth_changing=true` findings 生成 `pending_review` 提案（快照 what/evidence/suggestion/severity/finding_type，算 `dedup_key`），幂等 + 跨复盘去重（FR-001/FR-001a）。
- [x] T008 [US1] 在 `src/business/brain/background_worker.py` 的 `_run_execution_review` 复盘写回后**旁路调用** `ProposalService.generate_from_review`（不改 A 的只读语义，仅新增生成）。
- [x] T009 [US1] 在 `proposal_service.py` 增 `approve(id, supplement)` / `reject(id)` 业务方法（经 Repository CAS；approve 仅落 `approved` 不在此处建 worktree/图 —— FR-008 审批前零副作用）。
- [x] T010 [P] [US1] `tests/business/self_improvement/test_proposal_service.py`：生成幂等、dedup 抑制、approve/reject 状态流转、审批前零副作用。
- [x] T011 [US1] 在 `src/desktop_api/ui_events.py` 注册公开事件 `improvement_proposal.changed` + payload allowlist（contracts/events.md）；缺口走 `backend.resync_required`。
- [x] T012 [US1] 新建 `src/desktop_api/routers/proposals.py`：`GET /api/improvement-proposals`、`POST /{id}/approve`、`POST /{id}/reject`（contracts/api.md），只回安全投影；在 `src/desktop_api/app.py` 挂载路由。
- [x] T013 [P] [US1] `tests/desktop_api/test_proposals_endpoint.py`：列表/批准/拒绝 typed 契约 + 事件发出 + 安全投影（不泄漏原始错误/secret）。
- [x] T014 [US1] 在 `frontend/src/api/executionReview.ts`（或新建 `proposals.ts`）加提案 client：list / approve(+supplement) / reject。
- [x] T015 [US1] 在 `frontend/src/state/brainStore.ts` 加提案状态分片，按 `improvement_proposal.changed` type 消费、缺口走 resync。
- [x] T016 [US1] 在 `frontend/src/screens/BrainScreen/BrainScreen.tsx` 执行复盘视图内加：提案列表 + 批准（含补料文本框）+ 拒绝交互，以及存在 `pending_review` 时的待审提示（FR-020）。
- [x] T017 [P] [US1] `frontend/tests/unit/proposal-review.test.tsx`：提案展示、批准+补料、拒绝交互。

**Checkpoint**: US1 独立可用 —— 提案可见、可审批、可拒绝、不刷屏。MVP 达成。

---

## Phase 4: User Story 2 — 批准后机器自动改源码并回报 (P2)

**Goal**: 批准 → worktree + 任务图 → 规划/执行/测试节点协作改源码并回报。
**⚠️ 前置门 T0**：T018 spike 不过，本阶段其余任务不启动（plan 实施排序 #1）。
**Independent Test**: 批准一条提案 → 隔离 worktree + 分支产生、提案 in_progress→done/failed，结果（分支名+测试通过与否+摘要）回写、除批准外零人工介入。

- [x] T018 [US2] **🚧 T0 GATE** workspace 重定向可行性 spike：读 `src/business/agents/tools/builtin_general_tools.py` workspace 解析 + `run_context`，确认执行体工作目录能被指向指定 worktree；落 `tests/business/self_improvement/test_proposal_workspace.py` 冒烟（worktree 内可改、worktree 外 fail-closed）。**不通则停下与用户复议隔离方案。**
- [x] T019 [US2] 新建 `src/business/self_improvement/proposal_workspace.py`：git worktree 生命周期（建 `.worktrees/improvement/<id>` + 分支 `improvement/<id>` from HEAD；弃用清理），路径/分支回填提案行。
- [x] T020 [US2] 新建 `src/business/self_improvement/proposal_bridge.py`：approve 后 → 串行闸门 `has_in_progress` 检查 → 建 worktree → `TaskCollaborationService.build_task_graph`（规划/执行/测试节点均复用 task collaboration 调度；规划节点只给读/搜能力，执行与测试节点给限定 worktree 的源码修改/测试能力，session=`self_improvement:<proposalId>`）→ `get_graph_scheduler().start_graph()`；scheduler 为 None 时兜底（D6，不静默丢）；CAS `approved→in_progress` 回填 graph_id/worktree/branch。
  - **(U1) 把提案问题/建议 + `user_supplement` 注入实施任务图节点输入**（FR-006：补料 MUST 传递给实施）。
  - **(A1) 任务图含一个确定性「跑测试」节点**，其结果以结构化形式（如该节点 attempt result_ref 的固定字段）落到可被 T021 确定性读取的位置——"测试通过与否"不靠 LLM 复述。
- [x] T021 [US2] 轮询回报 job：扫 `in_progress` 提案读其 graph snapshot，终态 → 确定性读取「分支名 + 测试通过与否（来自 T020 的结构化测试节点结果，A1）+ 安全摘要」写回并 `mark_done`/`mark_failed`（D3）；**宿主钉死在 task_collaboration 后台 worker（A2）**，跨重启可恢复。
- [x] T022 [P] [US2] `tests/business/self_improvement/test_proposal_bridge.py`：mock scheduler/build_task_graph，断言 建图→踢图→CAS→回报 接线、串行闸门、scheduler-None 兜底。
- [x] T023 [US2] 把 `POST /{id}/approve` 接到桥接异步触发（API 立即返回 approved，后续状态走事件）。

**Checkpoint**: 批准即自动产出隔离的、跑过测试的分支并回报；命门闭环打通。

---

## Phase 5: User Story 3 — 隔离与可回滚的安全保证 (P3)

**Goal**: 把 FR-014 三条爆炸半径焊死并以门卫证伪；worktree 可清理、可回滚。
**Independent Test**: 门卫断言执行体改非源码/网络破坏 exec/自我改进核心均 fail-closed；拒绝后无残留；删分支/弃 worktree 干净回滚；运行中应用不被扰动。

- [x] T024 [US3] FR-014(a)：确保执行体 workspace base = 该提案 worktree，复用 015 workspace policy 使 worktree 外文件/DB 写 fail-closed（在 `proposal_bridge.py`/执行体装配处落实）。
- [x] T025 [US3] FR-014(b)：限制实施任务图内 `exec` 仅 worktree 内测试型用途，阻断网络/破坏型 exec（在执行体能力装配/hook 处约束）。
- [x] T026 [US3] FR-014(c)：禁止执行体修改自我改进子系统自身文件（`src/business/self_improvement/`、proposal_*、审查员、`task_collaboration` 调度内核）与应用启动核心路径；以路径拒绝清单/校验落实。
- [x] T027 [US3] worktree 回收（FR-019）：保留上限 / 显式清理入口；`reject`（含对 failed 提案）触发 worktree 清理（D8）。
- [x] T028 [P] [US3] `tests/guardrails/test_proposal_guardrails.py`：FR-014 三门卫各一断言（文件 / exec / 禁改核心）+ A 阶段只读不被改（回归 SC-005）+ 拒绝/失败无残留 + 运行中文件不被扰动 + **闭环全程不自动合并/重启（FR-015 负向断言：桥接与回报路径绝不触发 merge / 应用重启）**。

**Checkpoint**: 安全模型可证伪，敢放手让机器改源码。

---

## Phase 6: Polish & Cross-Cutting

- [x] T029 `tests/integration/test_proposal_closed_loop.py`：端到端 复盘→提案→批准→实施→回报（命门回归 SC-006），mock executor/LLM 确定性测接线+状态机，不测改码质量。
- [x] T030 [P] 更新 `docs/ARCHITECTURE.md`：新增自我改进提案层 + 提案→任务桥接的运行结构。
- [x] T031 [P] 更新 `docs/PROJECT_CONSTRAINTS.md`：执行体「只改源码 + exec 仅测试型 + 禁改自我改进/启动核心」例外边界与 worktree 隔离约束。
- [x] T032 [P] 同步更新 `src/AGENTS.md` / `src/CLAUDE.md` / `src/GEMINI.md`（模块约束 + Recent Changes 026），保持三镜像同内容。
- [x] T033 跑 `uv run black src/ tests/`、`uv run flake8 src/ tests/`、相关 `uv run pytest tests/{data,business/self_improvement,desktop_api,guardrails,integration}`、frontend `npm run lint && npm run test`；按 quickstart.md 四条路径手验。
  - 2026-06-30 验证：`black`、`flake8`、相关后端 pytest（937 passed）、frontend lint、frontend Vitest（315 passed）均通过；quickstart 四路径由 `test_proposal_service.py` / `test_proposal_bridge.py` / `test_proposal_workspace.py` / `test_proposal_guardrails.py` / `test_execution_reviews_endpoint.py` / `test_proposal_closed_loop.py` / `proposal-review.test.tsx` 覆盖核对。

---

## Dependencies & 执行顺序

- **Setup(T001) → Foundational(T002–T006) → 其余全部**。
- **US1(T007–T017)** 仅依赖 Foundational，**不依赖 US2 的 T018 spike** —— 可作为 MVP 独立交付。
- **US2** 以 **T018(T0 GATE)** 为硬前置：T018 不过，T019–T023 不启动。US2 依赖 Foundational + US1 的 approve 业务（T009）。
- **US3(T024–T028)** 依赖 US2 的桥接/worktree（T019/T020）。
- **Polish(T029–T033)** 最后；T029 依赖 US2 闭环，T030–T032 可并行。

## Parallel 机会

- Foundational：T003 / T005 / T006 可并行（model 与两组测试不同文件）。
- US1：T010 / T013 / T017（三层测试）可并行；T014/T015/T016 前端串行（同屏/同 store）。
- US2：T022 可与 T021 并行（测试 vs 回报实现，不同文件）。
- Polish：T030 / T031 / T032 文档类可并行。

## Implementation Strategy

- **MVP = US1**：先交付"提案可见 + 审批/补料/拒绝 + 不刷屏 + 待审提示"，用真实数据验证提案质量是否值得自动改（critique X2/Q3）。
- **再上 US2**：务必先过 T018 spike（隔离地基），通过后建桥接；US3 安全门卫随 US2 同步。
- **全程**：改静默失败/编排/Repository/恢复路径必须带行为/门卫测试（CC-008）；自我改造的爆炸半径靠门卫硬保证，不靠 LLM 自觉。
