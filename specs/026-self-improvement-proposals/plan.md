# Implementation Plan: 自我改进提案 — 半自动执行复盘改造闭环（B 阶段）

**Branch**: `026-self-improvement-proposals` | **Date**: 2026-06-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/026-self-improvement-proposals/spec.md`

## Summary

在已完成的 A 阶段（执行复盘·只读报告制）之上加一层「人审批 + 机器实施」：把复盘 findings 里 `worth_changing` 的项落成可审批的**改进提案**；用户在 BrainScreen 复盘视图里批准（带补料文本）或拒绝；批准后由**提案→任务桥接 service** 创建一个独立 git worktree + 程序化建任务图（复用 `TaskCollaborationService.build_task_graph` + `get_graph_scheduler().start_graph`），让规划专员拆解、执行体在隔离 worktree 内**真改源码并跑测试**，完成后把"分支名 + 测试通过与否 + 安全摘要"回写提案。安全网是 git：执行体爆炸半径焊死在「只改源码」、合并保持用户手动、随时可删分支/弃 worktree 干净回滚。整条闭环停在 B（人批准、人合并），不引入机器自批自改（C）。

技术路线已由脑暴阶段定型并经读代码核实：A 真接线（`f50ce7a`）、任务协作执行内核可被后台程序化驱动（`GraphScheduler` 进程级单例 + `start_graph` 幂等踢图 + dispatcher 自有线程池 + `requires_confirmation` 暂停）。

## Technical Context

**Language/Version**: Python 3.12（后端 sidecar / 业务 / 数据层）+ TypeScript + React 18（frontend）
**Primary Dependencies**: FastAPI sidecar、SQLAlchemy + SQLite、blinker、自研 AgentLoop、`src/business/task_collaboration`（GraphScheduler / TaskDispatcher / TaskCollaborationService）、`src/business/self_improvement`（A 阶段执行复盘）、git worktree（隔离执行）、Vitest / React Testing Library（前端）
**Storage**: SQLite —— 新增 `improvement_proposals` 表（`migrate_to_v21`）；git worktrees 作为「一提案一隔离工作区」的运行时隔离机制（非持久数据，路径/分支名引用存提案行）
**Testing**: pytest（`tests/business/`、`tests/data/`、`tests/desktop_api/`、`tests/guardrails/`、`tests/integration/`）+ frontend Vitest/RTL
**Target Platform**: Windows 桌面（Tauri 2 shell + Python sidecar）
**Project Type**: desktop-app（前后端分离：frontend React + src-tauri Rust 壳 + Python sidecar）
**Performance Goals**: 非延迟敏感。提案生成挂在复盘 worker 写回后旁路，开销可忽略；自动实施受任务图既有 task budget 约束，异步后台推进，不阻塞 UI/对话。
**Constraints**: 执行体改动 100% 限制在 git 跟踪源码且位于隔离 worktree（fail-closed）；用户批准前零副作用；合并手动、生效需重启；A 阶段只读不动；不数据化提示词/工具进 DB；停在 B。
**Scale/Scope**: 单用户、未发布、无外部消费者；不预留兼容双发。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. 分层边界与事件协调 | 是否保持 `UI → business → execution → data` 方向，跨模块通知走 blinker，面向前端事件走 UI Event Registry？ | **PASS**。触达层：UI（BrainScreen 复盘视图扩展、brainStore、API client）→ desktop_api（提案 typed API + 注册新公开 UI 事件）→ business（提案生成旁路 + 桥接 service + 执行体 source-only 约束）→ data（新表 + Repository）。后端跨模块通知用 blinker；面向前端的提案状态事件先在 `src/desktop_api/ui_events.py` 注册再消费，缺口走 `backend.resync_required`。桥接的"踢图"复用既有 `get_graph_scheduler()`，不新增编排路径。监听器不承担长任务（实施异步在 dispatcher 线程池）。 |
| II. 数据边界与持久化纪律 | SQLite/DuckDB 职责清晰、Repository 边界保留、迁移有兼容方案？ | **PASS**。仅触 SQLite；新增 `improvement_proposals` 表 + `migrate_to_v21`（v20 之后单调递增，向后兼容只新增表）；数据访问全经新 `ImprovementProposalRepository`，业务层不裸写 SQL；读写并发用条件 UPDATE + rowcount CAS（沿用项目约定）。不触 DuckDB / `network_requests`。A 的 `execution_reviews` 只读引用。 |
| III. 统一配置与密钥安全 | 配置/密钥是否全走 UnifiedConfigManager，DTO/UI 遮罩、日志脱敏？ | **PASS**。新增开关/参数（如 `self_improvement.proposals.enabled`、并发上限）走 `get_unified_config()` 三处同步；无新增 secret 字段；实施失败的 provider 原始错误不入安全失败摘要（只暴露安全投影），不进普通日志/DTO/UI。复用 A 既有独立审查员模型配置，不新增凭据解析路径。 |
| IV. 可验证交付 | 是否覆盖确定性逻辑 + 架构接线冒烟/门卫测试？ | **PASS**。单元：提案生成幂等 + 跨复盘去重、状态机流转、Repository CAS。集成：批准→桥接建图→调度推进→回报闭环（命门回归 SC-006，mock executor/LLM 确定性测接线）。门卫：FR-014 三条爆炸半径（文件 source-only / exec 仅测试型 / 禁改自我改进核心+启动路径，均 fail-closed）、A 只读不被改（回归）、拒绝/失败无残留。前端：复盘视图提案交互单测。**前置门**：执行体 workspace→worktree 重定向 spike（见下「实施排序」）必须先过。 |
| V. 活文档与规格驱动交付 | 是否标明要更新的活文档，过程材料留 `docs/local/`？ | **PASS**。本特性走 spec-kit（spec/plan/tasks）。完成时更新活文档：`docs/ARCHITECTURE.md`（新增自我改进提案层 + 桥接）、`docs/PROJECT_CONSTRAINTS.md`（执行体 source-only 例外边界）、`src/AGENTS.md`/`CLAUDE.md`/`GEMINI.md`（模块约束 + Recent Changes）。脑暴实录已在 `docs/local/todo/`。 |

**结论：5 项全 PASS，无违例。** Complexity Tracking 留空。

## Project Structure

### Documentation (this feature)

```text
specs/026-self-improvement-proposals/
├── plan.md              # 本文件
├── research.md          # Phase 0：关键设计决策（session 归属、回报机制、隔离实现等）
├── data-model.md        # Phase 1：improvement_proposals 表 + 状态机
├── quickstart.md        # Phase 1：端到端验证脚本
├── contracts/           # Phase 1：typed API + UI 事件 + 内部桥接契约
│   ├── api.md
│   └── events.md
├── checklists/
│   └── requirements.md  # spec 质量检查（已通过）
└── tasks.md             # Phase 2（/speckit-tasks 生成，非本命令产出）
```

### Source Code (repository root)

```text
frontend/
└── src/
    ├── api/
    │   └── executionReview.ts        # 扩展：提案列表 / 批准+补料 / 拒绝 client
    ├── screens/BrainScreen/
    │   └── BrainScreen.tsx           # 扩展：复盘视图内提案列表 + 批准/补料/拒绝交互
    └── state/
        └── brainStore.ts             # 扩展：提案状态 + 事件消费

src/
├── business/
│   └── self_improvement/
│       ├── proposal_service.py       # 新增：提案生成（从 worth_changing findings 幂等落库）+ 审批/拒绝业务
│       ├── proposal_bridge.py        # 新增：批准 → 建 worktree → build_task_graph → start_graph → 回报
│       ├── proposal_workspace.py     # 新增：git worktree 生命周期（建/弃）+ source-only 边界辅助
│       └── (execution_review_*.py)   # A 阶段既有，只读引用，不改
├── desktop_api/
│   ├── routers/
│   │   └── execution_reviews.py      # 扩展：新增提案 GET / approve / reject 端点（或新 proposals.py 路由）
│   └── ui_events.py                  # 扩展：注册提案公开 UI 事件 type + payload allowlist
└── data/
    ├── migrations.py                 # 新增 migrate_to_v21（improvement_proposals 表）
    ├── models_sqlite.py              # 新增 ImprovementProposal model
    └── repos/
        └── improvement_proposal_repository.py  # 新增 Repository（状态机 CAS）

tests/
├── business/self_improvement/
│   ├── test_proposal_service.py            # 提案生成幂等 + 状态机
│   ├── test_proposal_bridge.py             # 批准→建图→踢图→回报（mock scheduler）
│   └── test_proposal_workspace.py          # worktree 建/弃 + source-only 边界
├── data/
│   ├── test_improvement_proposal_migration.py
│   └── test_improvement_proposal_repository.py
├── desktop_api/
│   └── test_proposals_endpoint.py          # typed API + 事件
├── guardrails/
│   └── test_proposal_guardrails.py         # FR-014 三门卫(文件 source-only / exec 仅测试型 / 禁改自我改进核心+启动路径) + A 只读回归 + 拒绝无残留
└── integration/
    └── test_proposal_closed_loop.py        # 端到端：复盘→提案→批准→实施→回报（命门回归 SC-006；mock executor/LLM，确定性测接线+状态机，不测改码质量）

frontend/tests/unit/
└── proposal-review.test.tsx                # 复盘视图提案交互
```

**Structure Decision**: 提案能力整体收进既有 `src/business/self_improvement/`（A 阶段已在此）作为新的「实施层」，与 A 的「报告层」同包但职责分离；UI 复用 BrainScreen 执行复盘视图不开新主屏；执行复用 `src/business/task_collaboration` 内核，不新建平行流水线。新表 + Repository 进 `src/data`。

## 实施排序与门禁（critique 后纳入）

> 来源：`critiques/critique-20260628-160133.md`（E1/E2/X1/X2 等）。tasks 生成时按此排序。

1. **门禁 T0（最先做，E1/X2）**：执行体 workspace 重定向到指定 git worktree 的**可行性 spike + 冒烟测试**。读 `builtin_general_tools` workspace 解析与 `run_context` 后确定注入点；跑通"执行体在 worktree 内改文件、worktree 外 fail-closed"。**此门不过，US2 桥接不启动**——因为整套隔离/回滚安全模型依赖它。
2. **US1 先行（可与 T0 并行，X2）**：提案生成（含跨复盘去重 FR-001a）+ 数据层 + 审批/补料/拒绝 API + BrainScreen 交互 + 待审通知（FR-020）。US1 与桥接解耦，可独立交付并用真实数据验证提案质量。
3. **US2 桥接（T0 过后）**：worktree 生命周期 + `build_task_graph`/`start_graph` 桥接 + 串行化（FR-018）+ 轮询回报（D3）+ 调度器未装配兜底（D6）。
4. **FR-014 三门卫与 US3 安全保证**：随 US2 同步落地（文件 / exec / 禁改核心），并补 worktree 回收（FR-019）。
5. **闭环回归（SC-006）**：mock executor/LLM 的端到端接线测试收尾。

## Complexity Tracking

> 无 Constitution 违例，无需填写。

## Phase 0 / Phase 1 产物

- Phase 0 决策见 [research.md](./research.md)（session 归属与回报机制、worktree 隔离实现、执行体 source-only 强制点、提案生成挂载点、调度器未装配兜底）。
- Phase 1 设计见 [data-model.md](./data-model.md)、[contracts/api.md](./contracts/api.md)、[contracts/events.md](./contracts/events.md)、[quickstart.md](./quickstart.md)。
