# Research: 统一任务模型 + 多范式协作

## Decision 1: Task 图是新的业务事实源

**Decision**: 新增 Assistant Task 图仓库作为任务/委派/子任务的权威事实；`workflow_transitions` 继续作为 Debug Inspector 和历史审计线索，不再作为 UI 子任务列表或恢复语义的主来源。  
**Rationale**: 现有 `build_subagent_list()` 依赖 transition + child session 现场重建，无法表达依赖边、父侧裁定、看板租约、会议通道、Todo 和 crash-fenced attempt。  
**Alternatives considered**: 扩展 `workflow_transitions.payload`；会把业务状态塞进审计日志，难以建立约束、索引和恢复事务。

## Decision 2: Task 与 TaskAttempt 分离

**Decision**: `assistant_tasks` 表示持久工作项；`assistant_task_attempts` 表示一次易朽运行，带 lease、heartbeat、checkpoint 和 fence token。  
**Rationale**: spec 要求崩溃后不留永久 running、不盲目从头重跑、迟到结果幂等拒绝。工作项和运行实例分离才能围栏旧 attempt 并保留可裁定 Task。  
**Alternatives considered**: 在 Task 行直接记录运行字段；会让重试/续跑历史和迟到结果围栏混在一起。

## Decision 3: 父侧裁定不是 Task 状态

**Decision**: Task 只保存执行者侧六态；待裁定进入独立 `assistant_task_adjudications`。父侧 agent 默认自动裁定，用户只在顶层失败、高危确认、澄清上冒或主动介入时参与。  
**Rationale**: 这保持执行者状态机封闭，也避免"等待裁定"和"挂起"混淆。  
**Alternatives considered**: 把 `awaiting_adjudication` 放入 Task status；违背 spec 的六态边界，并让执行者误以为自己仍持有任务。

## Decision 4: 异步委派以 accepted + task_id 返回

**Decision**: 委派工具返回 `accepted=true`、`taskId`、`graphId`、`assignment`，父 agent 停在等待回流/裁定的 parking 点；结果回流事件唤醒父侧重入。  
**Rationale**: 现有同步子 loop 阻塞父 agent，无法实现跨执行者真并行。accepted 契约仍保持 function-calling 配对完整。  
**Alternatives considered**: 后台线程直接写回 parent messages；会绕过 AgentLoop 配对、活动事件和失败恢复边界。

## Decision 5: 容量=1 用 DB-backed executor lease 表达

**Decision**: 每个 executor 同时最多一个 active attempt；领取任务时用 Repository 条件更新/事务写入 claim，释放在 attempt 终态或 lease 超时恢复中完成。  
**Rationale**: 单进程内锁无法覆盖 crash/restart；共享 SQLAlchemy Session 也不能跨线程复用。DB 条件写入能测试并发双认领为 0。  
**Alternatives considered**: 仅用 Python `threading.Lock`；重启后会丢占用事实。

## Decision 6: 看板认领复用 assignment-null Task

**Decision**: 看板任务是 `assignee_type/id` 为空且满足依赖的 Task；认领写入 assignee、claim lease 和 task version。拒绝者记录在 claim history 中。  
**Rationale**: spec 要求点名委派与开放认领统一为同一机制。  
**Alternatives considered**: 独立 board item 再生成 task；会产生两个生命周期和取消传播来源。

## Decision 7: 停止作用于当前用户请求的 task graph

**Decision**: `stop` 绑定当前 user message / root request graph，向该 graph 的所有 active attempts 发出 cooperative stop，并把范围内 Task 挂起为 `user_stop`；不影响其他会话或其他请求。  
**Rationale**: 这匹配澄清结果和现有 runId 防迟到旧停止误停新回合的思路。  
**Alternatives considered**: session-wide stop；会误停同会话中不相关的后台任务或后续请求。

## Decision 8: 用户待答仍不持久化

**Decision**: agent-to-agent question route 可以持久化；最终上冒到用户的 pending card 和答案继续只存在进程内。失效后 Task 挂起为 `waiting_user`，用户可交互时重新发起澄清。  
**Rationale**: 保留 019 的 secret/answer 安全边界，同时满足本 feature 的任务可恢复需求。  
**Alternatives considered**: 新增用户待答表；违反现有澄清约束并扩大敏感数据面。

## Decision 9: 会议通道是受监督消息管道

**Decision**: 会议只允许两名执行者交换消息，保存通道和消息；不代理工具调用、不扩授权。通道有轮次/时长预算，必须产出 conclusion，超限或互等关闭并回父侧裁定。  
**Rationale**: 解决传话成本，但不破坏能力授权和拓扑封顶。  
**Alternatives considered**: 让会议参与者共享工具池；会产生隐式扩权。

## Decision 10: Todo 是私有 checklist，不进 task graph

**Decision**: Todo 按 Task + executor scoped 保存，状态词使用 `todo/doing/done/skipped`，不参与依赖、委派或裁定。  
**Rationale**: 用户需要可见进度，但不能把模型自管步骤误当成对外任务承诺。  
**Alternatives considered**: 把 Todo 条目建成 child Task；会引入不必要裁定和取消传播。

## Decision 11: Public UI event + snapshot 双轨

**Decision**: 新增 task/board/meeting/todo UI event type 只传 allowlist 投影；任意重连缺口仍通过 `backend.resync_required` 拉取 task graph/board/meeting/todo 权威快照。  
**Rationale**: event stream 是通知通道，不是长期事实。该模式与 009 event layer 一致。  
**Alternatives considered**: 在前端从事件日志重建全部状态；会在 replay 缺口和重启时丢失业务事实。

## Decision 12: 性能验收用受控执行器

**Decision**: 并行缩短、事件延迟和 snapshot 延迟用 fake executor / fake clock / local SQLite 测试量化；真实 LLM 场景只做 smoke。  
**Rationale**: LLM/provider 延迟不稳定，不能作为确定性验收门槛。  
**Alternatives considered**: 直接用真实模型测耗时；成本高且波动大。

## Decision 13: v15/v16 cutover 不做双写

**Decision**: v15 migration 引入 task collaboration schema，v16 migration 增加 active TaskAttempt 的数据库级约束，并选择 clean-start guard 或 backfill 其中一种切换方式；统一派发开启后，UI/API 的任务事实只读新仓库和 snapshot，`workflow_transitions` 只保留 debug/audit breadcrumb。  
**Rationale**: 双写会制造两个权威来源，尤其在 crash recovery、迟到结果和停止/取消排序上难以证明一致。  
**Alternatives considered**: 同时从 legacy transition 和新 Task 表派生 UI；会保留当前 bug 的根因并扩大迁移测试矩阵。

## Decision 14: Main Assistant 是协调者，不是执行器

**Decision**: Main Assistant 可以拥有和协调 root graph，但 user-work `TaskAttempt.executor_type` 只能是 `ephemeral_subagent` 或 `specialist`。  
**Rationale**: 项目约束要求办公助理 100% 调度；让 Main Assistant 作为执行器会把协调、派发和实际工作重新混在一起。  
**Alternatives considered**: 支持 `executor_type=assistant` 并用代码分支限制；边界不清且容易在后续工具接入时绕过调度。

## Decision 15: 副作用前先写 Operation 记录

**Decision**: 每个有外部副作用或不可安全重复的步骤，在执行前必须写入 `AssistantTaskOperation` 的 stable `operation_key`，成功后再写 completion marker。  
**Rationale**: checkpoint 字符串不足以证明副作用是否已经发生；恢复必须能区分可重试、已完成和 unsafe-to-retry。  
**Alternatives considered**: 只依赖 executor 自报 checkpoint；模型或进程崩溃时缺少可审计的确定性恢复依据。

## Decision 16: Agent-to-agent question route 持久化

**Decision**: `ask_parent` 创建持久 `AssistantTaskQuestion` 路由，覆盖 clarification、resource_request 和 capability_request；只有上冒到用户的 pending card 与原始答案继续不持久化。  
**Rationale**: 子代理向父代理提问是任务图恢复语义的一部分，必须能跨重启保留；用户答案仍遵守既有隐私边界。  
**Alternatives considered**: 仅在内存中保存 agent-to-agent question；重启后会丢失阻塞原因并导致任务无法解释地挂起。

## Decision 17: 分阶段门禁先于完整 UI

**Decision**: P1/P2 先完成 durable graph、state machine、cutover、idempotency、stop/cancel 和 failure bridge 的 MVP 门禁；P3/P4 的会议、看板、Todo 和完整 UI 只能在门禁通过后进入。  
**Rationale**: 该 feature 跨数据、业务、API、事件和前端，若一次性生成大批任务，最容易把高风险恢复语义埋在后置 UI 工作中。  
**Alternatives considered**: 按界面模块一次性交付；演示快但会让 crash recovery、调度边界和回滚策略缺测试。

## Decision 18: MVP 默认 clean-start cutover

**Decision**: v15/v16 MVP 默认使用 clean-start guard；backfill 仅在实现前显式选择时启用。  
**Rationale**: 项目是单用户未发布 feature branch，clean-start 能避免把旧 `workflow_transitions` 语义误解释成新的 Task 图事实，也最容易用门卫测试证明没有双权威来源。  
**Alternatives considered**: 默认 backfill；能保留更多历史状态，但需要为旧子会话、缺 checkpoint、暂停/失败映射维护更复杂的兼容矩阵。

## Decision 19: Task artifacts 跟随 session 可见性软隐藏

**Decision**: Task、meeting、Todo、adjudication 等协作 artifact 跟随 Assistant session archive/delete 的普通可见性软隐藏；task collaboration service 不新增物理删除路径。  
**Rationale**: 这些 artifact 可能含用户数据，但同时承担恢复、审计和调试语义；跟随 session 可见性可避免普通 UI 泄漏，并避免业务服务绕过既有数据保留边界。  
**Alternatives considered**: Task service 自行物理删除；会破坏可追溯性并增加与 session/brain 删除规则冲突的风险。
