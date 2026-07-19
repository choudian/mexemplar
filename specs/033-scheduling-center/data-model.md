# Data Model: Scheduling Center（调度中心）

**Phase 1 产出**。定义 033 的实体、字段、状态机与 v30/v31 migration。字段接入点证据来自调查（migration 体系见 `src/data/migrations.py`、ORM 见 `models_sqlite.py`、Repository 范本见 `improvement_proposal_repository.py`）。

> **时间戳惯例**：所有数据库 `*_at` 列存 UTC naive ISO8601 TEXT（项目
> `utc_now_naive()`）。`schedule_payload` 保留用户的调度意图：无 offset 的
> `run_at`、`time_of_day` / `weekdays` 是用户本地时区语义（见 research.md R2），
> 计算出的 `next_fire_at` 才转 UTC。
> **主键前缀**：`scheduled_task_id` 用 `sch_`、`run_id` 用 `schr_`（`generate_id("sch")` / `generate_id("schr")`，`base_repository.py:38`）。
> **外键策略**：**一律不建 FK**——遵循 `discussion_session_id` 先例（`models_sqlite.py:1333`：会话可被用户删除，FK 会挡 delete，绑定死亡由业务层惰性自愈重建）。

---

## 实体关系

```
user_todos (todo_id, 不碰) ◄──外部引用── scheduled_tasks.source_ref (source_type='todo')
                                            │
                                            │ 1
                                            │
                                            │ N
scheduled_tasks ────────────────── scheduled_task_runs ──► sessions (session_id, source='scheduled')
(定时任务主表, 软删)                    (每次触发账目, append-only)     (复用既有表, 加 source 列)
```

---

## 实体 1：`scheduled_tasks`（定时任务主表）

**ORM**：`ScheduledTask`（`src/data/models_sqlite.py`，新增）；**Repository**：`ScheduledTaskRepository`（仿 `UserTodoRepository` + CAS `next_fire_at`）；**建表 migration**：v30 仿 v18/v21。

| 字段 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `scheduled_task_id` | TEXT | PK，`sch_<16hex>` | 主键 |
| `source_type` | TEXT | NOT NULL，`CHECK IN ('direct','todo')` | 指令来源：direct=直接文本 / todo=引用待办 |
| `source_ref` | TEXT | NOT NULL | direct 时为指令文本；todo 时为 `todo_id`（外部引用，不建 FK） |
| `title` | TEXT | NOT NULL，长度 ≤120 | 展示标题 |
| `instruction` | TEXT | NOT NULL，长度 ≤4000 | 用户在确认卡核定后的实际执行指令；todo 来源与 `source_ref=todo_id` 分开保存，避免编辑内容丢失 |
| `schedule_kind` | TEXT | NOT NULL，`CHECK IN ('one_shot','recurring')` | 触发类型。**`source_type='todo'` 时强制 `one_shot`**（门卫） |
| `schedule_payload` | TEXT | NOT NULL（JSON） | 调度参数（见下「payload schema」） |
| `status` | TEXT | NOT NULL DEFAULT `'active'`，`CHECK IN ('active','paused','completed','expired')` | 任务状态（见状态机） |
| `unattended_auto_approve` | INTEGER | NOT NULL DEFAULT `0` | **per-task 免确认（CC-005 受控破例）**；只能经确认卡勾选或详情页开关写入，**不得经工具参数写入**（门卫） |
| `executor_hint` | TEXT | NULL | advisory 专员倾向（第一批可裁/留空） |
| `next_fire_at` | TEXT | NULL（UTC ISO） | 下次触发时刻；`active ∧ one_shot/recurring` 时非空，`paused/completed/expired` 时可空 |
| `last_fired_at` | TEXT | NULL（UTC ISO） | 上次触发时刻 |
| `is_deleted` | INTEGER | NOT NULL DEFAULT `0` | 软删标记（0/1）；删除 = 置 1，历史 runs 保留 |
| `created_at` | TEXT | NOT NULL | |
| `updated_at` | TEXT | NOT NULL | |

**索引**：`idx_scheduled_tasks_fire` ON `(next_fire_at)` WHERE `status='active' AND is_deleted=0`（调度扫描主索引）；`idx_scheduled_tasks_source_todo` ON `(source_ref)` WHERE `source_type='todo'`（待办悬空反查）。

**payload schema（`schedule_payload` JSON）**：
```jsonc
// one_shot
{ "run_at": "<本地 naive ISO 或带 offset 的 ISO>", "tz": "<可选 IANA 名，如 Asia/Shanghai>" }
// recurring — 每隔 N
{ "interval_seconds": 3600 }
// recurring — 每天某时
{ "kind": "daily", "time_of_day": "09:00", "tz": "Asia/Shanghai" }
// recurring — 每周某天某时
{ "kind": "weekly", "weekdays": [1,3,5], "time_of_day": "08:00", "tz": "Asia/Shanghai" }
// recurring — 工作日
{ "kind": "weekdays", "time_of_day": "09:00", "tz": "Asia/Shanghai" }
```
`tz` 作意图记录与展示（「每天 9:00」），计算 `next_fire_at` 时用 `zoneinfo`
（research.md R2）。无 offset 的 `run_at` 缺省按桌面系统本地时区解释；带 offset
时直接按 offset 转 UTC，避免把“本地 17:00”误排成 UTC 17:00。

**状态机（`status`）**：
```
              用户暂停                      用户启用
   active ◄────────────── paused ──────────────► active
     │                       │
     │ one_shot 触发后        │ paused 期间过点（one_shot）
     ▼                       ▼
  completed               expired
     │                       │
     └─────── 用户软删（is_deleted=1，保留行）──────┘
```
- `active ⇄ paused`：用户操作（行内暂停/启用），CAS 条件 UPDATE。
- `active → completed`：one_shot 成功触发一次后（recurring 不主动 completed，持续滚动）。
- `active/paused → expired`：todo 悬空（待办被删/手动完成，D6/FR-016）；或 paused 期间过点的 one_shot（D8）。
- 软删（`is_deleted=1`）与 `status` 正交，保留历史可追溯。

---

## 实体 2：`scheduled_task_runs`（执行账目，append-only）

**ORM**：`ScheduledTaskRun`；**Repository**：`ScheduledTaskRunRepository`（复用
`src/data/scheduling_types.py` 的 `RunStatus` + 合法转移表，在最终 mutation 边界执行
条件 CAS）；**建表 migration**：v30；终态事件投递确认列：v31。

| 字段 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `run_id` | TEXT | PK，`schr_<16hex>` | 主键 |
| `scheduled_task_id` | TEXT | NOT NULL（不建 FK） | 关联任务，悬空时业务层惰性处理 |
| `session_id` | TEXT | NOT NULL（不建 FK，`ast_` 前缀） | 非 skipped 时关联真实 scheduled 会话；skipped 未启动会话，只能经 `create_skipped()` 建账并内部存 run-specific `ast_skipped_<run_id>` 占位，公开 REST `sessionId` 固定投影为 `null` |
| `started_at` | TEXT | NOT NULL（UTC ISO） | 触发时刻 |
| `finished_at` | TEXT | NULL（UTC ISO） | 置终态时刻 |
| `status` | TEXT | NOT NULL DEFAULT `'running'`，`CHECK IN ('running','succeeded','failed','waiting_user','skipped')` | run 状态（见状态机） |
| `summary` | TEXT | NULL | 完成时刻该会话最后一条 assistant 展示消息的确定性截取（advisory，不跑 LLM 生成，§7.3） |
| `failure_reason` | TEXT | NULL | failed 时的安全失败投影（不含敏感诊断） |
| `terminal_event_delivered_at` | TEXT | NULL（UTC ISO） | v31 持久投递确认；终态先提交，`scheduler_run_terminal` 成功投影后再写入；NULL 由启动恢复与每轮 worker tick 有界重试 |
| `terminal_event_version` | INTEGER | NOT NULL DEFAULT `0` | v31 单调事件代次；每次进入 succeeded / failed / waiting_user 时递增，投递确认必须匹配该代次 |
| `created_at` | TEXT | NOT NULL | |

**创建原子性**：非 skipped 触发由 `ScheduledTaskRunRepository.try_create_active_with_session()`
在同一 SQLite 事务写入 `sessions` 与 `scheduled_task_runs`；任一写入失败则两者均不落库。
因此新 run 提交时即满足“关联真实 scheduled 会话”，不会出现先有 run、后建 session 的
phantom 窗口。接管路径仅为旧版本遗留 phantom/空会话提供惰性自愈，并把原任务指令作为
可编辑草稿返回，既不伪造历史消息也不自动重跑。

**索引**：`idx_runs_task_started` ON `(scheduled_task_id, started_at DESC)`（历史列表）；
`idx_runs_session` ON `(session_id)`（真实会话反查 run；skipped 占位不提供导航）；`uq_runs_active_per_task` UNIQUE ON
`(scheduled_task_id) WHERE status IN ('running','waiting_user')`（FR-011 数据库硬门卫：
同一任务同时最多占用一个 active-run 槽；业务预读只作快速路径，真正的并发 first-wins
由该 partial unique index 决定）。
v31 另建 `idx_runs_terminal_event_pending`，只扫描
`succeeded|failed|waiting_user` 且尚未确认投递的终态事实。

**状态机（`status`，CAS 推进）**：
```
   running ──会话静默 ∧ all_completed──► succeeded
       │
       ├──会话静默 ∧ 含失败──────────► failed
       │
       ├──主助理需补充信息──────────► waiting_user ──用户接管后继续──► running
       │                                  └──等待态被停止/明确失败────► failed
       │
       └──明确 runtime 失败/停止──────► failed

   新触发 ──发现该 task 的 active-run 槽已占用──► skipped（不创建 scheduled 会话）
```
- `succeeded`：会话静默且图内执行节点全部完成后由 `RunCompletionMonitor` 置。
- `failed`：主助理返回明确失败 / 取消 / 停止时直接置；或会话静默但图含失败 /
  取消节点时由 monitor 置。只保存安全失败投影。
- `waiting_user`：主助理返回需补充信息时由 monitor 原子写入并单次通知；用户从历史
  接管后可回 `running`，直至静默再置终态。等待本身**不标失败、不悬空**。
- `skipped`：触发时检测到同任务上次未静默，或数据库 active-run 唯一槽并发冲突；
  本次不启动会话、经独立 `create_skipped()` 直接创建终态账目；真实 `running` run
  不允许转成 skipped。
- 终态（succeeded/failed/skipped）不可逆；`waiting_user → running|failed`。
- `succeeded` / `failed` / `waiting_user` 的业务状态提交与 UI 通知投影分离：每次状态
  转换清空 `terminal_event_delivered_at`，进入可投递状态时递增
  `terminal_event_version`，事件成功后按 `(run_id, version)` CAS 确认；旧事件即使在
  并发续跑/再终止后才返回，也不能确认掉新代次。失败保留 NULL，启动和 worker tick
  重试。该机制为跨进程 at-least-once；极窄的“已发布、未确认即退出”窗口允许重复提醒，
  但不能永久丢失。

---

## 实体 3：`sessions` 表加列（既有表，v30）

**ORM**：`Session`（`models_sqlite.py:120-185`，`:132` 后追加）；**migration**：v30 仿 v29 `_add_column_if_missing`。

| 新字段 | 类型 | 约束 / 默认 | 说明 |
|---|---|---|---|
| `source` | TEXT | NOT NULL DEFAULT `'user'`；`SessionRepository` closed-enum 门卫 | 会话来源；聊天屏列表 `exclude_sources=['scheduled']`（FR-021） |
| `scheduled_task_id` | TEXT | NULL | 关联触发它的定时任务（不建 FK） |
| `is_scheduled` | INTEGER | NOT NULL DEFAULT `0` | bool；Segment opt-out 单点判定（`segment_service.seal_segment` early-return） |

**Backfill**：既有 sessions 行 `source='user'`、`is_scheduled=0`（migration 内 `UPDATE sessions SET source='user' WHERE source IS NULL` 或靠 DEFAULT）。

> 关系门卫：`SessionRepository.create` 强制 `source='scheduled'` ⇔
> `scheduled_task_id` 非空且 `is_scheduled=1`；`source='user'` ⇔
> `scheduled_task_id IS NULL` 且 `is_scheduled=0`。`ChatService` 分别提供 user/scheduled
> 构造语义并派生 bool，调用方不能独立漂移三个字段。数据库 v30 因 SQLite 增列兼容性
> 未补跨列 CHECK，Repository 是最终持久化门卫。

---

## 待办悬空处理（FR-016 / CC-001）

`source_type='todo'` 的任务，worker 到点与 `fire_now` 都在触发前校验引用的 `todo_id` 仍存在且未完成：
- 待办被删除 / 被用户手动标记 `done` → 任务 CAS 置 `status='expired'`，`updated_at` 更新，记日志（原因可入 `schedule_payload.note` 或单独字段，tasks 阶段定）。
- 正常触发使用确认卡已编辑并持久化的 `instruction`；仅兼容早期草稿行时才从当前待办 title + description 兜底。
- 待读取异常时本轮不触发、保留任务供下轮重试；不得把数据库故障误判为待办已删除。
- **不写 `user_todos` 表**（门卫 `test_todo_table_untouched.py`）。

---

## CAS 与软删约定（Constitution II + memory `project_cas_conditional_update_convention`）

- 所有状态推进（`status` 转移、`next_fire_at` 滚动、run 状态机、软删）**必须**走条件 UPDATE + `rowcount` 校验（仿 `improvement_proposal_repository.py:360-390`）；task/run 状态 CAS 还必须在 Repository 最终边界与 `scheduling_types.py` 合法转移表求交，**不得**信任调用方传入的源状态，**不得** read-modify-write。
- `ensure_immediate_transaction()` 是 no-op（023 遗留），CAS 原子性靠 rowcount + DB
  约束，**不**恢复 `BEGIN IMMEDIATE`；run 创建先尝试占用
  `uq_runs_active_per_task`，唯一冲突不得先创建第二个 session。
- 软删：`UPDATE scheduled_tasks SET is_deleted=1 WHERE scheduled_task_id=? AND is_deleted=0`；历史 runs 不删。

---

## v30 Migration 草案

文件 `src/data/migrations.py`，注册 `_MIGRATIONS` 末尾追加 `(30, migrate_to_v30)`：

```python
def migrate_to_v30(engine):
    """v30: scheduling center — scheduled_tasks, scheduled_task_runs, sessions.source/scheduled_task_id/is_scheduled."""
    with engine.begin() as conn:
        # 1) 两张新表（仿 v18/v21：CREATE TABLE IF NOT EXISTS + 内联 CHECK + 独立 CREATE INDEX）
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                scheduled_task_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL CHECK (source_type IN ('direct','todo')),
                source_ref TEXT NOT NULL,
                title TEXT NOT NULL,
                instruction TEXT NOT NULL,
                schedule_kind TEXT NOT NULL CHECK (schedule_kind IN ('one_shot','recurring')),
                schedule_payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed','expired')),
                unattended_auto_approve INTEGER NOT NULL DEFAULT 0,
                executor_hint TEXT,
                next_fire_at TEXT,
                last_fired_at TEXT,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_fire ON scheduled_tasks(next_fire_at) WHERE status='active' AND is_deleted=0"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_source_todo ON scheduled_tasks(source_ref) WHERE source_type='todo' AND is_deleted=0"))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS scheduled_task_runs (
                run_id TEXT PRIMARY KEY,
                scheduled_task_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','succeeded','failed','waiting_user','skipped')),
                summary TEXT,
                failure_reason TEXT,
                created_at TEXT NOT NULL
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_task_started ON scheduled_task_runs(scheduled_task_id, started_at DESC)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_runs_session ON scheduled_task_runs(session_id)"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_active_per_task ON scheduled_task_runs(scheduled_task_id) WHERE status IN ('running','waiting_user')"))

        # 2) sessions 加三列（仿 v29 _add_column_if_missing，幂等）
        _add_column_if_missing(conn, "sessions", "source", "TEXT NOT NULL DEFAULT 'user'")
        _add_column_if_missing(conn, "sessions", "scheduled_task_id", "TEXT")
        _add_column_if_missing(conn, "sessions", "is_scheduled", "INTEGER NOT NULL DEFAULT 0")

        # 3) 推进版本号
        conn.execute(text("UPDATE schema_version SET version = 30"))
        conn.commit()
```

> ORM 同步：`models_sqlite.py` 的 `Session` 加 3 列 + 新增 `ScheduledTask` / `ScheduledTaskRun` 类（文件头注释 `:5` 要求 ORM 与 migration 同步）。`is_scheduled` 用 `Integer` 映射 bool（仿既有 `is_active` 惯例）。

## v31 Migration：终态事件持久投递确认

v31 在 `scheduled_task_runs` 上幂等新增 `terminal_event_delivered_at DATETIME`、
`terminal_event_version INTEGER NOT NULL DEFAULT 0` 与
`idx_runs_terminal_event_pending` partial index，并把 `schema_version` 推进到 31。
不新增业务实体；确认时间 + 单调代次记录 `scheduler_run_terminal` 的投影确认，既解决
业务终态已提交后 projector / event queue 暂时失败导致通知永久丢失，也防止旧事件 ack
吞掉并发产生的新终态通知。
