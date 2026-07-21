# Implementation Plan: 调度任务常驻会话复用

**Branch**: `prepare-github` | **Date**: 2026-07-20 | **Spec**: [spec.md](spec.md)

## Summary

将 `ScheduledTask` 的 current session 做成长生命周期资源，将 `ScheduledTaskRun` 保持为一次
触发的执行单元。SQLite v32 增加绑定与消息窗口字段；`SessionLauncher` 通过 runtime
reservation 和数据层原子启动事务复用/首绑 session；完成监视改为 run-owned mutation；
父侧回流按 graph 隔离；调度中心增加手动 reset。

## Technical Context

| 项 | 内容 |
|---|---|
| 语言 | Python 3.11+ / React 18 + TypeScript |
| 存储 | SQLite v32；不涉及 DuckDB |
| 业务模块 | `src/business/scheduling/`，有限修改 `task_collaboration` 回流接缝 |
| Adapter | FastAPI router、AssistantRuntime、typed frontend client/store/screen |
| 新事件/配置/secret | 均无 |

## Constitution Check

| 原则 | 结论 |
|---|---|
| 分层 | 通过。启动/重置语义在 scheduling；runtime 只提供预约/worker adapter；SQL 只在 Repository/migration。 |
| 数据 | 通过。v32 有回填、幂等、downgrade 测试；首次绑定+session+run 同事务。 |
| 配置/secret | 通过。无新增配置或 secret。 |
| 可验证 | 通过。Repository、launcher、monitor、runtime/reentry、REST、前端均按行为测试覆盖。 |
| 规格驱动 | 通过。034 明确替代 033 两处冲突并同步活文档。 |

## 关键设计

### 1. 数据所有权

- `scheduled_tasks.session_id`：当前常驻 session，唯一可空。
- `scheduled_task_runs.baseline_message_sequence`：本 run 开始前最大消息序号。
- `scheduled_task_runs.trigger_message_sequence`：本 run 首条 scheduled user 消息预留序号。
- 数据库增加 active-per-session、task-session、session-trigger 唯一索引。

水位线是查询窗口，不是 worker 身份。终态 mutation 的唯一键是 `run_id`。

### 2. 深模块接口

数据层把复杂事务收口为两个接口：

- `try_create_active_for_bound_session(...)`
- `try_create_active_with_new_bound_session(...)`

调用方只提供候选 session、baseline/trigger 和 started_at；实现内部验证 task/session 关系、
唯一槽、绑定 CAS 和事务提交。

runtime 把启动竞态收口为三个接口：

- `reserve_scheduled_session(session_id, reservation_id) -> bool`
- `dispatch_reserved_message(..., reservation_id, scheduled_run_id) -> bool`
- `release_scheduled_session_reservation(...)`

普通 dispatch/retry/reentry 与 reservation 共用同一把 worker lock。

### 3. Run 归属

- 自动触发从 Launcher 显式把 `run_id` 传入 runtime worker。
- waiting_user takeover 后的用户消息，只允许解析“该 session 唯一 active run”一次并将
  `run_id` 固定进 worker；后续 waiting/failed/evaluate 不再反查 session。
- graph 事件读取 graph root 的 `user_message_sequence`，映射到最大
  `baseline < sequence` 的 run；历史/错误图不会写当前 run。

### 4. Graph 与回流

- graph 查询限定 `user_message_sequence > baseline`。
- 同窗口若出现 `user_message_sequence IS NULL` 的 root，返回 unknown。
- `ParentReentrySink` 队列改为 `(session_id, graph_id)`；runtime worker 只 drain/re-enqueue
  指定 graph，tail-kick 选择仍 pending 的 graph。
- `GraphScheduler` 先把 graph-complete 放入回流 sink，再 emit scheduling observer。

### 5. Reset 与授权

- `SchedulerService.reset_session()` 在统一 trigger guard 内校验 task 无 active run，再调用
  注入的 runtime busy guard，最后 CAS 清绑定。
- API 返回当前 task typed snapshot；busy 映射 409。
- unattended helper 除来源和 task id 外，再验证 `task.session_id == session_id`。
- 旧 session 不改来源、不删除，仍隐藏于普通聊天列表。

## 迁移策略

v32 在表存在时加列和索引；按每个 task 最新、关系合法且 session 状态可复用的 run 回填
`scheduled_tasks.session_id`。遇到不合法/冲突历史保持 NULL，下一次 launch 惰性创建。
历史 run 的 trigger 保持 NULL，避免伪造归属。reserved dispatch 若在 trigger 消息落库前失败，
会原子终结该 run 并清空它的 trigger 预留槽；若消息已经落库则保留序号作为审计归属。

## 验证策略

按纵向 TDD：

1. migration/Repository 原子首绑与复用；
2. Launcher 连续触发与 busy skip；
3. monitor 旧消息/旧图/NULL 图隔离；
4. runtime run-id 终态与 graph-scoped reentry；
5. reset REST、授权门卫和前端操作；
6. 专项测试 → Black/Flake8 → frontend lint/build/test → Python 全量测试。

## 活文档

同步 `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`、根/`src`/
`src/business/scheduling`/`frontend` 的三份 AI 入口镜像，以及 033 活跃描述中仍写“每次新建”
的当前真相段落。历史规格保留原文，由 034 的替代条款解释演进。
