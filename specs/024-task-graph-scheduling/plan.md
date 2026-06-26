# Implementation Plan: 024 Task Graph Scheduling（复杂任务"先分解，再按图执行"纠偏）

**Branch**: `024-task-graph-scheduling` | **Date**: 2026-06-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/024-task-graph-scheduling/spec.md`；设计草案 `docs/superpowers/specs/2026-06-24-task-graph-scheduling-design.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

对 023-unified-task-collaboration 落地后执行模型偏离的纠偏：复杂任务从"一把委派 / 边想边派"改为"**识别复杂度 → 分解成带依赖的 DAG → 确定性调度器按依赖自动推进 → 遇高风险节点或失败时停下让主助理裁定**"。

技术路径（4 个并行调研代理已锁定 023 接口契约）：
- **激活** 023 闲置的 `edge_type='dependency'` 边 + 新建确定性 `graph_scheduler.py`（复用 `dispatcher.start_attempt_async` 派发内核、`_assert_no_cycle` 无环校验、capacity=1、lease/fence 恢复）。
- **新增** `build_task_graph` / `mutate_task_graph` 工具 + 主助理 prompt 复杂度判定段；`requires_confirmation` 列（高风险节点裁定暂停）；`role_kind` 列 + tool_registry 分支（规划专员只规划不执行）。
- **扩展** `reentry_briefing` 文本段（下一步建议 / 自愈动作清单 / todo 概览，DEC-H）；扩 `todo_update` description 引导节点内分解。
- **0 新增**公开 UI 事件 type / desktop API（CC-004 成立）；todo 按需可见走 TaskGraphPanel 节点展开（DEC-E）。

所有 Technical Context 未知项已在 [research.md](./research.md) 解析（DEC-A~H），无残留 NEEDS CLARIFICATION。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）、React 18 + TypeScript/Vite、Rust stable、FastAPI sidecar
**Primary Dependencies**: LangChain、blinker、自研 AgentLoop、023 task_collaboration 基础设施（dispatcher / parent_reentry_sink / adjudication / todos / atomic UoW）、brain specialist 招募
**Storage**: SQLite（`assistant_tasks` +`requires_confirmation`、`brain_specialists` +`role_kind`，Alembic migration v17）；不涉及 DuckDB
**Testing**: pytest（`tests/guardrails`、`tests/integration`、`tests/business`）+ Vitest（`frontend/tests/unit`）；多文件同 process 规避 023 teardown flaky，单文件/分批跑
**Target Platform**: Windows desktop（Tauri shell，正常开发路径）
**Project Type**: desktop-app（AI 办公助理）
**Performance Goals**: scheduler 推进为确定性本地计算，延迟相对 LLM 调用可忽略；capacity=1 保证一执行器一节点
**Constraints**: 助理 100% 调度不执行；capacity=1；0 新公开 UI 事件；复用 023 持久化/恢复/并发安全（CC-001）；硬保证由落库层门卫承担，LLM 软判定不当作保证（CC-006/008）
**Scale/Scope**: 单用户、未发布、无外部消费者（不预留 deprecation 双发兼容）

> 无 NEEDS CLARIFICATION。复杂度阈值、配置键、needs-confirmation 承载、规划专员形态、自愈机制、todo 可见性机制、suspendReason、graph_version 递增、briefing 扩展方式——全部见 [research.md](./research.md) DEC-A~H。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | 结论 |
|-----------|---------------|------|
| I. 分层边界与事件协调 | 保持 `UI→business→execution→data`？跨模块通知走 blinker？ | **PASS**。新 `GraphScheduler` 在 business 层（`task_collaboration/`），调 dispatcher/service/reentry_sink 均 business 内。受影响层：business（agents / orchestration / task_collaboration / brain-specialist）、data（migration v17 + repos）。**0 新公开 UI 事件 type**（DEC-G，复用现有 7 个 task 事件）。受控例外（继承自 023）：dispatcher→parent_reentry_sink→assistant_runtime 为直接 callback（非 blinker），已有 constitution I 注释说明"事件只通知不调度"，024 沿用不改。 |
| II. 数据边界与持久化 | SQLite/DuckDB 职责明确？Repository 边界保留？ | **PASS**。业务数据走 SQLite + Repository（`build_task_graph` 用 `_atomic` + `add_edge`/`create_task`，业务层无裸 SQL）。migration v17 带兼容默认（`requires_confirmation` DEFAULT 0、`role_kind` DEFAULT 'executor'），现有数据不受影响。不涉及 DuckDB / network_requests。 |
| III. 统一配置与密钥 | 配置/密钥走 UnifiedConfigManager？脱敏？ | **PASS**。复杂度阈值等运行时可调项经 `UnifiedConfigManager` 读写（新键如 `agent_tasks.complexity.*` 带 config.json 默认值 + app_settings 覆盖）。无新密钥。自愈 `safeRecoveryHint` 遵循 023 安全投影（不泄漏 provider 原始错误）。 |
| IV. 可验证交付 | 确定性逻辑有单测？架构切换有冒烟/门卫测试？ | **PASS**。确定性逻辑（scheduler 推进、就绪硬校验、无环、briefing 拼装）配单测；架构切换（scheduler 新路径、planner 工具分支、dependency 边激活）配冒烟 + 门卫测试（"复杂必落库为 DAG 且由 scheduler 驱动"、"planner 不拿执行器工具"、"dependency 边无写入回归"）。LLM 软行为（复杂度分类、分解质量、自愈选择）走集成测试 + 软约束文档（CC-008）。测试矩阵见 research.md §5 / data-model.md / contracts/graph-scheduler.md §5。 |
| V. 活文档与规格驱动 | 活文档识别更新？过程材料限 docs/local/？ | **PASS**。spec/plan/tasks/research/data-model/contracts 在 `specs/024-task-graph-scheduling/`（spec-kit 管理）。待更新活文档：`docs/ARCHITECTURE.md`（task_collaboration 运行时总览补 DAG 调度）、`CLAUDE.md`/`AGENTS.md`/`GEMINI.md`（Recent Changes + Active feature 024，AI 入口同内容镜像）、`docs/FEATURES.md`。设计草案源文档 `docs/superpowers/specs/...` 为输入参考。 |

**初评**：5/5 PASS，无 gate 失败。

**设计后复评（Phase 1 完成后）**：data-model.md / contracts/ / research.md 落地后再次核对——
- I：scheduler/reentry/briefing 全在 business 层，0 新事件 ✅
- II：仅 +2 列、Repository 边界守得住 ✅
- III：配置走 UnifiedConfigManager、无密钥、脱敏 ✅
- IV：门卫 + 单测 + 集成测试矩阵齐全 ✅
- V：活文档更新点已列 ✅
**复评结论**：5/5 PASS，无需例外。

## Project Structure

### Documentation (this feature)

```text
specs/024-task-graph-scheduling/
├── plan.md              # 本文件
├── spec.md              # /speckit-specify 产出
├── research.md          # Phase 0：决策固化 + 023 接口契约 + 借鉴机制适配 + 设计偏差
├── data-model.md        # Phase 1：实体/schema 变更/状态机/校验
├── quickstart.md        # Phase 1：端到端开发与验证流程
├── contracts/
│   ├── agent-tools.md       # build_task_graph / mutate_task_graph / todo_update 契约
│   ├── graph-scheduler.md   # DAG scheduler 接口 + 就绪硬校验 + 暂停/恢复/取消
│   └── reentry-briefing.md  # briefing 文本段扩展
├── checklists/
│   └── requirements.md  # spec 质量校验清单
└── tasks.md             # /speckit-tasks 产出（本命令不创建）
```

### Source Code (repository root)

```text
src/
├── business/
│   ├── agents/
│   │   ├── prompts/assistant_prompt.py        # +「复杂度判定与任务分解」段（任务分类与100%调度之间）
│   │   └── tools/assistant_tools.py           # +build_task_graph / +mutate_task_graph；扩 todo_update description
│   ├── orchestration/agent/
│   │   ├── tool_registry.py                   # +build_task_graph 装配；+planner role_kind 分支（规划者拿 build_task_graph，不拿执行器工具）
│   │   └── orchestrator.py                    # 弱化 _SUBAGENT_WORK_RULES 第2/3条；不碰死代码 _build_* 方法
│   ├── task_collaboration/
│   │   ├── graph_scheduler.py                 # 【新增】DAG 调度器（确定性推进、就绪硬校验、暂停/恢复/取消复用）
│   │   ├── service.py                         # +build_task_graph 原子入口（_atomic 批量建 task+dependency 边）
│   │   ├── reentry_briefing.py                # +snapshot 参数；+下一步建议/自愈清单/todo 概览 文本段
│   │   ├── dispatcher.py                      # 失败 entry +healingActions/safeRecoveryHint；paused payload +needs_review reentry_type
│   │   └── adjudication.py                    # 复用 decide（三态）；needs_confirmation 触发路径
│   └── brain/specialist_service.py            # +planner role_kind 招募/注册路径
├── data/
│   ├── migrations.py                          # +v17：assistant_tasks.requires_confirmation；brain_specialists.role_kind
│   ├── models_sqlite.py                       # +两列 ORM
│   └── repos/assistant_task_repository.py     # +_assert_dependencies_satisfied（就绪硬校验）
├── desktop_api/
│   ├── assistant_runtime.py                   # _run_assistant_reentry drain 后查 snapshot 传入 build_reentry_briefing
│   ├── routers/assistant_tasks.py             # 复用 12 endpoint（0 新 API）；snapshot DTO +requiresConfirmation
│   ├── schemas.py                             # +requiresConfirmation 投影
│   └── ui_events.py                           # 0 改动（suspendReason 纯复用 waiting_user，DEC-G）
└── frontend/
    └── src/
        ├── screens/assistant/                 # TaskGraphPanel +节点展开看 todo（复用 todosByTaskId，0 改 014）
        ├── state/assistantTaskStore.ts        # 节点 requiresConfirmation 投影（消费既有 task_graph.changed 事件）
        └── api/assistantTasks.ts              # DTO +requiresConfirmation 类型

tests/
├── guardrails/                                 # 架构门卫：复杂必落库为 DAG、planner 不拿执行器工具、dependency 边无写入回归
├── business/task_collaboration/                # graph_scheduler 单测
├── integration/                                # 端到端：分解→调度→裁定→自愈→取消
└── frontend/tests/unit/                        # todo 可见性单测
```

**Structure Decision**: 复用 023 `task_collaboration/` 模块，新增 `graph_scheduler.py`（确定性调度器）为唯一新业务组件；建图逻辑作为 `service.py` 的 `build_task_graph` 方法（复用 `_atomic` UoW），不另起 service 类。工具落 `assistant_tools.py` + `tool_registry.py`（不碰 orchestrator 死代码）。数据层仅 +2 列（migration v17）。desktop_api/frontend 0 新事件 / 0 新 API，仅补 DTO 投影与 TaskGraphPanel 节点展开。

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

无 Constitution 违规，本表为空。5 项 gate 初评 + 设计后复评均 PASS。

---

## 待确认 / 后续阶段提示（供 /speckit-tasks 与评审参考）

1. **规划专员招募冷启动**（DEC-B）：首版用配置/手动注册一个 planner 专员（避免依赖信号阈值冷启动），后续接 brain 累计信号自动招募。具体注册机制在 tasks 阶段定。
2. **「跳过」节点下游处理**（data-model §3）：默认可容忍跳过→视为完成推进下游；不可容忍→取消下游子图。二选一在 tasks 阶段定（建议可配置）。
3. **suspendReason 精确化**（DEC-G）：首版纯复用 `waiting_user`；若评审认为需区分高风险待裁定与普通等用户，再扩 enum 加 `waiting_confirmation`（payload enum 扩展，非新事件 type，合规）。
4. **graph_version 批量优化**（DEC-F）：首版接受 per-edge 递增；若 cancel 围栏语义受影响再优化为批量入口一次性 +1。
5. **spec FR-012 措辞消解**（DEC-E）：todo 可见性机制从「014 SubagentDrawer」落实为「TaskGraphPanel 节点展开」——tasks 阶段在 spec Event/Architecture Impact 处补一行注脚说明机制修正（意图不变）。
