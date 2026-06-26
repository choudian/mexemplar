# Data Model: 024 Task Graph Scheduling

**Branch**: `024-task-graph-scheduling` | **Date**: 2026-06-24
**Principle**: 最大化复用 023 schema，最小化新增列；新增项仅 `requires_confirmation`（task）与 `role_kind`（specialist），走 migration v17。

---

## 1. 实体总览

| 实体 | 来源 | 024 改动 |
|---|---|---|
| **任务图 (Task Graph / DAG)** | 023 `graph_id` 聚合 | 无 schema 改动；激活 dependency 边语义 |
| **任务节点 (Task Node)** | 023 `assistant_tasks` | +`requires_confirmation` 列 |
| **依赖边 (Dependency Edge)** | 023 `assistant_task_edges`（`edge_type='dependency'` 闲置枚举） | 新增写入路径（无 schema 改动） |
| **TaskAttempt** | 023 `assistant_task_attempts` | 无改动（lease/fence/capacity=1 复用） |
| **裁定 (Adjudication)** | 023 `assistant_task_adjudications` | 复用三态决策；+needs_confirmation 触发路径（无 enum 改动，用 kind/reentry_type 标记） |
| **规划专员 (Planning Specialist)** | 023 brain specialist | +`role_kind` 列 |
| **DAG 调度器 (DAG Scheduler)** | **新增** runtime 组件 | 不持久化（确定性推进器，消费 task/edge 表） |
| **节点 Todo** | 023 `assistant_todos` | 无改动（行为引导，非 schema） |
| **回流包 (Reentry Briefing)** | 023 纯文本 briefing | 无 schema 改动（文本段扩展） |

---

## 2. Schema 变更（migration v17）

### 2.1 `assistant_tasks.requires_confirmation`
```sql
ALTER TABLE assistant_tasks ADD COLUMN requires_confirmation INTEGER NOT NULL DEFAULT 0;
-- 0 = 普通节点，1 = 高风险/不可逆节点（scheduler 派发前需主助理裁定放行）
```
- **为什么新列**：无现成列可复用（`capability_scope` 是 tool whitelist；`suspend_reason` 撞 CHECK）。详见 research.md DEC-A。
- **读取方**：DAG scheduler（派发前判定是否走裁定暂停路径）。
- **写入方**：`build_task_graph`（分解者标注）；graph mutation（改图时调整）。
- **快照投影**：`TaskGraphSnapshot` 节点 DTO 增 `requiresConfirmation`（read 路径，`desktop_api/schemas.py` + 前端 `assistantTasks.ts` 类型）。

### 2.2 specialist `role_kind`
```sql
ALTER TABLE brain_specialists ADD COLUMN role_kind TEXT NOT NULL DEFAULT 'executor';
-- 'executor'（默认，现有专员）| 'planner'（规划专员，只规划不执行）
```
- **为什么**：tool_registry 按角色分支装配工具（planner 拿 `build_task_graph` 规划变体，不拿 todo_update/ask_parent/执行器工具）。详见 research.md DEC-B。
- **兼容**：默认 `'executor'`，现有专员不受影响。
- **招募**：复用 `brain/specialist_service.py`；首版提供配置/手动注册一个 planner 专员（避免信号阈值冷启动），后续接累计信号。

### 2.3 不改动项（明确边界）
- `assistant_task_edges`：`edge_type='dependency'` + `propagation='blocking'` 已在 CHECK 内，**无 migration**，仅激活写入路径。
- `assistant_task_attempts`：lease/fence/capacity=1 结构不动。
- `assistant_task_adjudications`：决策枚举 `accepted/returned/abandoned` 不扩；needs_confirmation 用 `kind`/reentry_type 标记，不改 enum。
- 事件契约：`suspendReason` 首版纯复用 `waiting_user`，**0 事件改动**（DEC-G）。

---

## 3. 任务节点状态机（scheduler 驱动）

复用 023 `TaskStatus`：`pending_dispatch → running → {completed | failed | suspended | cancelled}`。

```
[建图] build_task_graph
   │  N 节点 + M dependency 边，原子落库（_atomic）
   │  所有节点初始 pending_dispatch；requires_confirmation 标记就位
   ▼
[scheduler 循环] graph_scheduler.py（确定性，非 LLM）
   │
   ├─ 1. 扫就绪节点：status=pending_dispatch 且 所有 dependency 前置=completed
   │     〔就绪硬校验 _assert_dependencies_satisfied 兜底，前置没全完成→派不出〕
   │
   ├─ 2. requires_confirmation=1 ?
   │     ├─ 是 → 建 pending adjudication(needs_confirmation) → 回流主助理裁定
   │     │        〔不 dispatch；DEC-D〕
   │     │        ├─ accepted  → 标记放行 → 进步骤 3
   │     │        ├─ returned → 调整后放行 / 改图
   │     │        └─ abandoned→ 节点取消（下游按规则处理）
   │     └─ 否 → 进步骤 3
   │
   ├─ 3. dispatcher.start_attempt_async(node) → running（capacity=1，复用 023）
   │     〔executor 异常/lease 过期 → attempt fenced → 节点回 pending_dispatch → 重入步骤1〕
   │
   ├─ 4. attempt 完成 → parent reentry 回流 → adjudication pending
   │     ├─ delivered=done    → 主助理 decide(accepted) → completed → 重扫激活下游
   │     ├─ delivered=stuck/failed_input → 自愈（DEC-C）：
   │     │     briefing 附「重试/换执行器/调输入/跳过/改图/放弃」清单
   │     │     ├─ returned(重试/调输入/换执行器) → 回 pending_dispatch
   │     │     ├─ 改图 → graph mutation → 重扫
   │     │     ├─ abandoned → failed → 下游按规则取消/跳过
   │     │     └─ 兜不住 → ask_user_question 升级用户
   │     └─ 全图 completed → 主助理向用户汇报
   │
   └─ 暂停条件：需确认节点(步骤2) / 失败(步骤4) / 用户取消
```

### 关键转换规则
- **就绪（ready）**：`status=pending_dispatch` AND 所有 `dependency` 前置节点 `status=completed`。`propagation=blocking` 的边参与就绪判定；`none` 的边不参与（可并行）。
- **跳过（skip）**：自愈决策「跳过」时，节点置一终态（复用 `cancelled` 或新增语义标记，tasks 阶段定），下游就绪判定按「该前置视为已完成」或「取消下游」二选一（默认：可容忍跳过→视为完成推进下游；不可容忍→取消下游子图）。
- **改图（replan）**：graph mutation 工具（add/skip node、add/remove dependency edge），落 `graph_version` 变更可追溯；复用 `_assert_no_cycle`。
- **取消传播**：复用 023 `cancel_graph`（`_bulk_transition` + `expected_graph_version` 围栏）+ 三层 cancel key。

---

## 4. 校验规则

| 规则 | 位置 | 状态 |
|---|---|---|
| **无环**（dependency 边不成环） | `assistant_task_repository._assert_no_cycle`（add_edge 内） | 023 已有，复用 |
| **就绪硬校验**（前置未完成派不出） | 新建 `_assert_dependencies_satisfied`（Repository 层） | **新建**（借鉴 claude-code claim） |
| **capacity=1**（一执行器一 active attempt） | v16 partial unique index + `start_attempt` 双守卫 | 023 已有，复用 |
| **委派深度封顶** | `_MAX_DELEGATION_DEPTH=2`（`create_child_task`） | 023 已有；planner 不向下委派执行，图节点不触发深度递增 |
| **graph 预算** | `get_assistant_tasks_graph_max_tasks()` | 023 已有，`build_task_graph` 复用 |
| **归属校验** | adjudication/todo 的 session_id/executor 归属 | 023 已有，复用 |

---

## 5. 复杂度路由（LLM 软判定，CC-006/CC-008）

主助理在首轮推理分类（prompt 新段引导），**软判定**，落库层门卫兜底：

| 路由 | 判定 | 执行 |
|---|---|---|
| 简单 | 1-2 步、单领域、无跨执行器依赖 | 现有快速委派（`delegate_to_subagent/specialist`），不建图 |
| 中等 | 多步有清晰依赖、单/弱跨领域 | 主助理调 `build_task_graph` 自拆 → 触发 scheduler |
| 超阈值 | ≥3 步且跨 ≥2 领域；或自评规划不清；或不可逆外部动作且有依赖 | 主助理 `delegate_to_specialist(planner)` → 规划专员 `build_task_graph` → 主助理触发 scheduler |

**硬保证**（门卫测试，落库层校验）：命中超阈值规则（门卫测试用确定性触发条件）的任务必须落库为带 dependency 边的 DAG 且由 scheduler 驱动；planner specialist 工具集不含执行器工具。复杂度分类本身是 LLM 软判定，门卫只守「落库形态」不守「分类一定正确」。

---

## 6. 工具层变更摘要（详 contracts/）

| 工具 | 变更 | 持有者 |
|---|---|---|
| `build_task_graph` | **新增**：输入节点列表+依赖+需确认标记，原子建图，返回 graphId+nodeTaskIds | 主助理 + 规划专员（planner 变体） |
| `mutate_task_graph` | **新增**（自愈「改图」用）：add/skip node、add/remove dependency edge | 主助理（自愈决策） |
| `todo_update` | **扩 description**：引导节点内 ≥3 步主动分解 todo、三态流转、完成判定红线 | 执行器（专员/子agent） |
| `decide_task_adjudication` | 复用（accepted/returned/abandoned），无 schema 改动 | 主助理 |
| `delegate_to_specialist` | 复用（超阈值委派 planner） | 主助理 |
| `ask_user_question` | 复用（自愈兜不住升级） | 主助理 |

---

## 7. 回流包扩展（DEC-H，纯文本段）

`build_reentry_briefing(entries, snapshot)` 在现有 result/question 段基础上追加：
- **下一步建议段**（确定性，由 snapshot 计算）：就绪可派节点清单 / 是否有待裁定（needs_confirmation/failure）节点 / 是否全图完成（完成则提示向用户汇报）。
- **自愈动作清单段**（失败 entry 携带）：重试/换执行器/调输入/跳过/改图/放弃。
- **节点 todo 概览段**（snapshot 聚合）：各进行中节点的 todo 进度（供主助理裁定节点结果）。

briefing 保持纯函数可单测；snapshot 由 `assistant_runtime._run_assistant_reentry` drain 后查一次传入。
