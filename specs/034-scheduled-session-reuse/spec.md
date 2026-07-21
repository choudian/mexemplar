# Feature Specification: 调度任务常驻会话复用

**Feature Branch**: `prepare-github`
**Created**: 2026-07-20
**Status**: Approved for implementation
**Input**: 同一个计划任务每次执行必须复用同一个 session；用户可手动“重开一轮”更换当前 session。

## 背景

033 调度中心把一次触发等同于一个新会话。周期任务因此无法从自己的历史执行中做纵向判断。
本特性把生命周期拆成两个正交实体：

```text
ScheduledTask
  └─ current session（常驻，可手动替换）
       └─ ScheduledTaskRun 1..N（每次触发一条，独立记账）
```

会话负责连续上下文，run 负责一次执行的归属、成败和审计。消息水位线只负责持久消息查询窗口，
不能代替运行时所有权。

## 用户场景与验收

### US1：周期任务记得上一次执行（P1）

同一个计划任务连续触发两次时，第二次必须投递到第一次使用的同一个 scheduled assistant
session。该 session 的既有对话继续作为模型上下文。

**验收**：

1. 首次触发创建并绑定一个 scheduled session。
2. 首次 run 终态后再次触发，只新增 run 和消息，不新增 session。
3. 两条 run 的 `sessionId` 相同，第二次模型上下文包含第一次的持久消息。
4. 不同 scheduled task 不得共享 current session。

### US2：每次执行独立记账（P1）

复用 session 后，run N 只能由属于 run N 的 worker、消息、任务图和回流裁定。

**验收**：

1. run N-1 的成功委派证据不能让什么都没做的 run N 成功。
2. run N-1 的失败图不能让无图的 run N 失败。
3. run N 的摘要只能取本 run 消息窗口内的 assistant 文本。
4. runtime 的 waiting/failed/evaluate 终态操作携带 `run_id`；不得按“session 最近一条 run”
   猜测写入目标。
5. 图的 `user_message_sequence` 缺失时归属未知并 fail-closed，不得降级为“本 run 无图且成功”。

### US3：同一 session 不并发跑两轮（P1）

复用 session 的新一轮开始前，session 必须处于全局静默：无 assistant worker、无启动预约、
无 pending 回流、前一轮任务图已终态。检查与 worker 注册之间必须有运行时预约，阻止用户消息、
reentry 与 scheduled trigger 同时 first-win。

**验收**：

1. 用户正在该 scheduled session 中接管/对话时，到点触发记 `skipped`，不创建失败的
   `running` run。
2. pending reentry 或非终态图存在时，到点触发记 `skipped`。
3. 两个并发触发最多一个创建 active run 和启动 worker。
4. 每个 session 同时最多一个 active scheduled run。

### US4：回流不跨 run 串台（P1）

父侧回流队列必须按 `(session_id, graph_id)` 隔离。reentry worker 只 drain 自己图的条目，
图终态事件通过图根的消息序号映射到 run 窗口。

**验收**：

1. 同一 session 两张图的回流可分别 drain，不会一次取空另一张图。
2. reentry 失败重入时只回填原 graph 队列。
3. 图完成通知先进入回流通道，再发布 scheduling 观察事件，避免“已判静默后才出现回流”的竞态。

### US5：用户手动重开一轮（P2）

用户可在调度中心详情中点击“重开一轮”。没有 active run、worker、预约、pending reentry
或非终态图时，任务清除 current session 绑定；下一次触发创建并绑定新 session。旧 session
和旧 run 历史保留。

**验收**：

1. 重置成功后下一次 run 使用不同 session。
2. active/busy 时 REST 返回 409，绑定保持不变。
3. 旧 session 继续从普通聊天列表排除。
4. 旧 session 不再继承该 task 的 unattended 授权；授权只对 task 的 current session 生效。

## 功能要求

- **FR-001** `scheduled_tasks` MUST 持久化唯一的可空 `session_id`，表示 current session。
- **FR-002** `scheduled_task_runs` MUST 持久化 `baseline_message_sequence` 和
  `trigger_message_sequence`；新 active run 的 trigger 必须等于预约时的下一消息序号。
- **FR-003** 首次绑定、scheduled session 插入和 active run 插入 MUST 在同一数据库事务中提交。
- **FR-004** 存量任务迁移时 SHOULD 回填其最近一个关系合法的非 skipped scheduled session；
  无合法历史时保持空绑定并在下一次触发惰性创建。
- **FR-005** session/task、active run/task、active run/session 和
  `(session, trigger_message_sequence)` 的唯一性 MUST 由数据库索引兜底。
- **FR-006** Launcher MUST 使用 runtime reservation 完成“占 session → 原子建 run →
  预约转 worker”；任何失败必须释放预约。若失败发生在 trigger user 消息落库前，还必须在
  run 终态事务中清空预留的 `trigger_message_sequence`，使同一 session 的下一次触发可重试；
  已落库 trigger 不得清空。
- **FR-007** busy 发生在 run 创建前时 MUST 作为本次 occurrence 的 skipped 处理，不得先建
  running 再标 failed。
- **FR-008** 完成监视 MUST 以 `run_id` 为 mutation interface；session 只用于验证归属和读取窗口。
- **FR-009** 任务图查找 MUST 限定 `user_message_sequence > baseline`；本窗口存在未标序号图时
  MUST 返回 unknown/fail-closed。
- **FR-010** tool evidence 与 summary MUST 使用 `sequence > baseline` 的消息窗口。
- **FR-011** ParentReentrySink MUST 提供 graph-scoped drain/re-enqueue/pending interface。
- **FR-012** reset MUST 经过 scheduling business facade；router/UI 不得直接操作 Repository。
- **FR-013** unattended 判定 MUST 同时验证 session 是该 task 当前绑定的 session。
- **FR-014** 不新增公开 UI event、配置或 secret；继续复用 `scheduled_task.changed`
  的 `status_changed` changeType。
- **FR-015** scheduled session 继续从普通聊天列表排除，继续跳过 Brain Segment。

## 兼容与迁移

- SQLite schema 版本从 v31 升到 v32；migration 幂等并提供仅测试调用的 downgrade。
- 历史 run 的 `baseline_message_sequence=0`，`trigger_message_sequence=NULL`，保持可读；
  完成监视不得重新推进这些已终态历史行。
- takeover 的 legacy session 修复仍保留；不能因为正常路径开始复用而删除损坏数据恢复保护。
- reset 不删除、改写或转为 user session；旧 scheduled session 仅失去 current-session 授权资格。

## 明确替代 033 的约束

- 本规格替代 `specs/033-scheduling-center/spec.md` FR-002 中“每次触发新建 session”的要求。
- 为满足 run 隔离，本规格替代 033 CC-003 对
  `task_collaboration/parent_reentry_sink.py` 和 `graph_scheduler.py` 的禁改限制；改动仅限
  graph-scoped 回流和通知顺序，不改变节点推进、裁定、执行器选择或恢复决策。
- 033 的 per-task active-run、misfire、聊天屏排除、Segment opt-out 和 CC-005 受控免确认
  规则继续有效。

## 成功标准

- **SC-001** 自动化测试证明同一任务连续两次 run 使用同一 session。
- **SC-002** 自动化测试证明旧图、旧工具结果、旧 assistant 文本均不能影响新 run。
- **SC-003** 并发测试证明 task/session 两个维度都不存在双 active run 或双 worker。
- **SC-004** reset 后新 run 换 session，旧 session 无 unattended 权限且历史仍可访问。
- **SC-005** 相关 Python 测试、前端测试、类型检查、lint、格式化与全量测试通过。
