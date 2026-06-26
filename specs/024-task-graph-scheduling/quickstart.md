# Quickstart: 024 Task Graph Scheduling

**Branch**: `024-task-graph-scheduling` | **Date**: 2026-06-24
本文档描述如何开发与验证 024。前提：023 分层越权重构核心批次已稳定（CC-007），024 只消费 023 稳定接口。

---

## 1. 环境准备

```powershell
# 在 worktree 内
cd E:\code\Exemplar\.worktrees\024-task-graph-scheduling
uv sync                                   # Python 依赖
uv run alembic upgrade head               # 应用 migration v17（requires_confirmation + role_kind）
cd frontend; pnpm install; cd ..          # 前端依赖
```

启动桌面应用（Tauri shell，正常开发路径，不走 legacy PyQt 入口）：
```powershell
# 分别起 sidecar 与前端（具体脚本以 src-tauri/AGENTS.md 为准）
```

---

## 2. 端到端手动验证（AI Assistant 主屏）

### 2.1 简单任务（回归，不建图）
- 输入：「把这段会议纪要里的待办列出来」
- 预期：主助理直接 `delegate_to_subagent/specialist`，**不**产出任务图，行为与改造前一致（SC-005）。

### 2.2 中等任务（主助理自拆建图）
- 输入：「整理这三场会议的纪要，合并成一份周报草稿」
- 预期：
  - 主助理首轮分类为「中等」，调 `build_task_graph`。
  - Debug Inspector 或 TaskGraphPanel 出现一张多节点 + dependency 边的图。
  - scheduler 按依赖推进：纪要整理节点先完成 → 周报合并节点就绪 → 完成。
  - 全图完成 → 主助理向用户汇报最终周报（SC-001）。

### 2.3 超阈值任务（规划专员建图）
- 输入：「整理本周三场会议纪要、生成周报、并发送给团队，再据此更新项目看板」（≥3 领域、含对外发送）
- 预期：
  - 主助理识别超阈值，`delegate_to_specialist(planner)`。
  - 规划专员产出带 dependency 边 + 需确认标记（发送邮件节点 needsConfirmation=true）的图。
  - scheduler 推进；到「发送周报邮件」节点时**暂停**，回流让主助理裁定（SC-002）。
  - 主助理放行 → 发送节点执行。

### 2.4 高风险节点暂停裁定（SC-002）
- 在 2.3 中，发送节点前置完成后：
- 预期：scheduler 不 dispatch，建 pending adjudication(needs_confirmation)，主助理回流收到「节点 X 即将执行、需确认」；**未放行前绝不执行**（100%）。

### 2.5 节点失败自愈（SC-003）
- 制造一个节点失败（如某工具临时不可用）：
- 预期：回流 briefing 附「重试/换执行器/调输入/跳过/改图/放弃」清单；主助理优先自愈（如 returned 重试），多数情况不升级用户。

### 2.6 节点 todo 按需可见（SC-006，DEC-E）
- 任一进行中的图节点：在 TaskGraphPanel **展开该节点** → 看到 executor 的 todo 子步骤进度（todo/doing/done）。
- 预期：默认任务界面**不展示** todo；展开后经 `GET /tasks/{taskId}/todos` + `assistant.todo.changed` 实时更新。

### 2.7 中途取消/改主意（SC-004）
- 图运行中点「停止/取消」：取消顺图传播，运行中执行回收、未开始节点转 cancelled，无孤儿执行。
- 改主意（「改成只发周报不发看板」）：旧图取消 + 重新分解。

---

## 3. 自动化测试（constitution IV）

```powershell
# 架构门卫 + 链路 + 回归（单文件/分批跑，规避 023 teardown flaky）
uv run pytest tests/guardrails/test_task_graph_scheduling_guard.py -q
uv run pytest tests/business/task_collaboration/test_graph_scheduler.py -q
uv run pytest tests/integration/test_task_graph_e2e.py -q
uv run pytest tests/guardrails/test_planner_specialist_tools.py -q
# 前端 todo 可见性单测
cd frontend; pnpm test -- todo-visibility
```

测试矩阵见 `data-model.md §3-4`、`contracts/graph-scheduler.md §5`、`research.md §5`。

---

## 4. 关键观测点（Debug Inspector，隐藏路由 `/debug`）

- **Agent Flow**：主助理复杂度判定 → build_task_graph / delegate_to_specialist(planner) → scheduler 推进 → 裁定/自愈。
- **Task Graph snapshot**：节点状态、dependency 边、requires_confirmation、adjudication。
- **reentry briefing 文本**：确认含「下一步建议 / 自愈清单 / todo 概览」三段（DEC-H）。

> 诊断 raw 数据仅驻留有界进程内 epoch（011 约束），不持久化、不外泄。

---

## 5. 不做的事（非目标，防过度工程）

- 不强制简单任务建图。
- 不做前端图的可视化编辑（仅消费）。
- 不改 UI 事件契约与前端投影方式（首版 suspendReason 纯复用 waiting_user）。
- 不重写 023 持久化/恢复/并发安全。
