# Phase 1 Data Model: 自我改进提案（B 阶段）

## 新增表 `improvement_proposals`（`migrate_to_v21` 建表；`migrate_to_v22` 加 `assistant_tasks.workspace_root`；`migrate_to_v23` 收紧 `result_tests_passed` 三态 CHECK）

一行 = 一条可执行改进提案。来源于某条执行复盘的一个 `worth_changing` finding。

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | String(50) | PK | 提案 id（`prop_*`） |
| `source_review_id` | String(50) | NOT NULL, FK→`execution_reviews.id`（逻辑外键） | 来源复盘记录 |
| `finding_index` | Integer | NOT NULL | finding 在该复盘 `findings_json` 中的序号 |
| `status` | String(20) | NOT NULL, default `pending_review` | 生命周期，见状态机 |
| `severity` | String(10) | nullable | 快照自 finding（high/med/low） |
| `finding_type` | String(20) | nullable | 快照自 finding（效率/健壮性） |
| `dedup_key` | String(200) | nullable, INDEX | 跨复盘同类去重键（如 `finding_type` + 归一化 `what` 的稳定散列），用于 FR-001a 去重/冷却 |
| `what` | Text | nullable | 问题描述快照 |
| `evidence` | Text | nullable | 证据快照 |
| `suggestion` | Text | nullable | 审查员建议快照 |
| `user_supplement` | Text | nullable | 用户批准时补料文本 |
| `graph_id` | String(50) | nullable | 实施任务图 id（批准后写入） |
| `worktree_path` | String(500) | nullable | 隔离工作区路径（批准后写入） |
| `branch_name` | String(200) | nullable | 实施分支名（批准后写入） |
| `result_tests_passed` | Integer | nullable | 回报：测试是否通过（1/0/NULL=未跑/未知） |
| `result_summary` | Text | nullable | 回报：安全摘要（不含 provider 原始错误） |
| `error` | Text | nullable | 失败安全原因（脱敏） |
| `created_at` | String(50) | NOT NULL | 生成时间 |
| `decided_at` | String(50) | nullable | 用户批准/拒绝时间 |
| `completed_at` | String(50) | nullable | 实施终态时间 |

**索引 / 约束**：
- `UNIQUE(source_review_id, finding_index)` —— 保证 D1 幂等，同一 finding 不重复生成提案。
- `INDEX(status)` —— 轮询 `in_progress` / 列表展示按状态过滤。
- `INDEX(dedup_key)` —— 跨复盘去重（FR-001a）：生成前查同 `dedup_key` 是否已有未终态或最近失败（`pending_review`/`approved`/`in_progress`/`failed`）或冷却窗口内的提案（含 `failed` 以防刚失败的同类在冷却窗口内立即重提，对齐 `DEDUP_BLOCKING_STATUSES`），命中则**不新建**（合并/抑制），避免同类低效反复刷屏。**advisory 软保证（非原子）**：`create()` 内是 read-then-write，两个并发提案（不同 review、同 `dedup_key`）理论上可同时通过判定并双双落库（`UNIQUE(source_review_id, finding_index)` 不挡不同 review）；复盘串行生成下实际触发概率低，最坏只是 UI 多一条待审，由用户用"拒绝"过滤。需要硬保证时另行加应用级锁。
- **串行化（FR-018）**：同一时刻至多一条提案处于 `in_progress`；桥接踢图前检查无其它 `in_progress` 提案，否则排队，降低执行容量争用与跨提案合并冲突。

**快照而非引用 finding 的理由**：findings 存在 A 的 `execution_reviews.findings_json` blob 内，无法稳定单条索引/查询；把展示所需字段在生成时快照进提案行，使提案可独立查询/展示/状态流转，且不依赖 A 的内部 JSON 结构（A 只读不动）。

## 状态机

```
                 ┌──────────────┐
   生成(D1) ───▶ │ pending_review│
                 └──────┬───────┘
              reject │        │ approve(+supplement)
                     ▼        ▼
                ┌────────┐  ┌──────────┐
                │rejected│  │ approved │  （写 user_supplement；触发桥接 D4/D6）
                └────────┘  └────┬─────┘
                                 │ 桥接建 worktree+graph 成功
                                 ▼
                           ┌────────────┐
                           │ in_progress│  （写 graph_id/worktree_path/branch_name）
                           └─────┬──────┘
                  图终态:全成功+测试过 │   │ 图终态:失败/测试不过 或 建图失败
                                    ▼   ▼
                              ┌──────┐ ┌────────┐
                              │ done │ │ failed │
                              └──────┘ └────────┘
```

**合法流转**（其余一律拒绝）：
- `pending_review → approved`（用户批准，可带 `user_supplement`）
- `pending_review → rejected`（用户拒绝）
- `approved → in_progress`（桥接成功建 worktree + 图）
- `approved → failed`（桥接建 worktree/图失败，写安全 error）
- `in_progress → done`（图全成功且测试通过，写 result_*）
- `in_progress → failed`（图失败或测试不过，写 result_*/error）
- `failed → rejected`（用户对已失败提案显式弃用，触发 worktree 清理 D8）

**终态**：`done`、`rejected`。`failed` 可被 `reject` 收尾（清理）。

## 并发与一致性

- 状态流转用**条件 UPDATE + rowcount CAS**（`UPDATE ... WHERE id=? AND status=?`），避免重复批准/重复踢图丢更新（沿用项目 CAS 约定，不用 `BEGIN IMMEDIATE`）。
- 重复 `approve` 同一提案：CAS 命不中（已非 `pending_review`）→ 幂等忽略，不重复建 worktree/图。
- 跨进程重启恢复：扫到仍 `in_progress` 的提案，由 D3 轮询继续读图状态回报；扫到 `approved` 但无 `graph_id` 的（桥接中途崩）→ 由兜底重新触发桥接或标 failed（实现期定）。

## 与既有实体关系

- `execution_reviews`（A，只读）1 —— N `improvement_proposals`（一条复盘的多个 worth_changing finding 各成一条提案）。
- `improvement_proposals` 1 —— 0..1 任务图（`graph_id` 指向 `assistant_tasks` 图，批准后建立）。
- 不改任何既有表结构。

## Repository（`ImprovementProposalRepository`）核心方法

- `create(...)`（幂等，撞 UNIQUE 静默跳过或返回既有；生成前按 `dedup_key` 查同类未终态/冷却内提案，命中则抑制不新建 —— FR-001a）
- `has_in_progress()`（串行化闸门，FR-018：存在 `in_progress` 提案时新批准的排队不踢图）
- `list_recent(limit)` / `list_by_status(status)`（UI 列表 + 轮询）
- `get_by_id(id)`
- `approve(id, supplement)` —— CAS `pending_review → approved`
- `reject(id)` —— CAS `pending_review|failed → rejected`
- `mark_in_progress(id, graph_id, worktree_path, branch_name)` —— CAS `approved → in_progress`
- `mark_done(id, summary)` —— CAS `in_progress → done`，固定写入 `result_tests_passed=true`
- `mark_failed(id, error, tests_passed?, summary?)` —— CAS from `in_progress`/`approved`；只有确定性测试失败写 `tests_passed=false`，建图/调度/未知结果保持 `null`
