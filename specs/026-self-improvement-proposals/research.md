# Phase 0 Research: 自我改进提案（B 阶段）

> 已亲自读代码核实的事实见 spec「背景」节，不在此重复。本文件只记需要拍板的设计决策。
> 标 ⚠️ 的是「方向已定、精确接线点留实现期确认」的项，按项目 verify-before-claiming 纪律如实标注。

## D1. 提案生成挂载点

- **Decision**: 在 brain 后台 worker 的 `_run_execution_review` job 把复盘写回 `execution_reviews` 后，**顺带**用一段确定性逻辑从该复盘的 `worth_changing=true` findings 生成 `pending_review` 提案行（调用新 `ProposalService`）。A 的审查员逻辑、表、advisory 语义不动。
- **Rationale**: 复用已存在且已接线的触发线（A 的 worker），不新增 background job、不新增触发钩子；生成与复盘落库在同一处发生，时序自然。符合「复用不推翻」。
- **Alternatives considered**:
  - 单独再起一个轮询 worker 扫已完成复盘 → 多一条后台线、多一处时序不一致风险，否决。
  - 在 desktop API 读取复盘时惰性生成 → 把写副作用塞进只读 GET，破坏分层与幂等，否决。
- **幂等**: 提案唯一性按 `(source_review_id, finding_index)` 约束；worker 重复处理同一复盘不重复生成。

## D2. 实施任务图的 session 归属

- **Decision**: 后台发起的实施任务图使用**专用合成 session 命名空间** `self_improvement:<proposalId>`，不复用任何真实对话 session。
- **Rationale**: 任务图全图完成会经 `GraphScheduler._notify_graph_complete` → 进程级 `reentry_sink`（主助理的）回流。若借用真实 chat session，会把"自我改造完成"当成对话 briefing 注入聊天，污染用户对话。专用 session 让回报走提案而非聊天。
- **Alternatives considered**: 借用触发复盘的原 chat session → 会向该会话注入无关 briefing，否决。

## D3. 完成回报机制（写回提案）

- **Decision**: 采用**轮询式回报**——新增一个轻量 job（挂在 task_collaboration 后台 worker 或 brain worker）周期扫描 `in_progress` 提案，读其关联 graph 的快照；图到终态（全 completed / 含失败）时把「分支名 + 测试通过与否 + 安全摘要」写回提案并置 `done|failed`。
- **Rationale**: `GraphScheduler` 的完成通知硬接到单例 `reentry_sink`（主助理），不便为后台图分流；轮询式写回与提案状态机解耦、可跨进程重启恢复（重启后扫到仍 `in_progress` 的提案继续等），符合「恢复逻辑要可验证」。轮询仅针对 `in_progress` 提案，量极小。
- **Alternatives considered**:
  - 扩展 `reentry_sink` 按 session 前缀分流到提案回写 → 侵入任务协作内核、耦合度高，否决（保持内核不动）。
  - 桥接同步阻塞等图完成 → 违反「委派不阻塞」与监听器快速返回原则，否决。
- ⚠️ **测试通过与否的判定来源**：实施任务图里「跑测试」由执行体节点完成，其结果需以**确定性**形式落到可读位置（候选：作为一个测试节点的 attempt result_ref / 安全摘要）。精确"测试结果如何结构化回流"在实现期随任务图节点设计确认；回报本身只做确定性读取，不靠 LLM 复述。

## D4. worktree 隔离与执行体 workspace 指向

- **Decision**: 桥接在 `build_task_graph` 前创建 git worktree（位置 `.worktrees/improvement/<proposalId>`，分支 `improvement/<proposalId>`，从当前 HEAD）；实施任务图节点携带该 worktree 路径，执行体的工作目录解析到该 worktree。提案记录 worktree 路径 + 分支名。
- **Rationale**: worktree 是项目既有惯例（spec-kit 每个 feature 都开 worktree），独立目录共享 git 历史 → programmer 改的文件与正在跑的 sidecar 文件物理隔离；回滚 = 删分支/弃 worktree。
- ⚠️ **精确接线点留实现期确认**：执行体（delegated executor / programmer）当前 workspace ≈ 项目根；把它指向特定 worktree 的注入点（候选：`capability_scope` 携带 workspace 根 / 专用 `run_context` workspace / builtin tools workspace policy 的 base 覆盖）需在实现期读 `builtin_general_tools` workspace 解析 + `run_context` 后确定。这是本特性最大的接线不确定点，tasks 阶段应优先打通并补冒烟测试。
- **Alternatives considered**:
  - 在主工作树上开分支改 → 扰动正在运行的 sidecar 文件、与用户自己的 git 操作打架，否决（脑暴已定）。
  - 临时 clone 整库 → 比 worktree 重得多、丢共享对象，否决。

## D5. 执行体「只改源码」爆炸半径强制

- **Decision**: 双层强制——(1) 执行体 workspace 焊死在 worktree 根，015 既有契约对 workspace 外的写/删/patch/exec 已 fail-closed，DB/外部资源天然在 workspace 外 → 自动挡住；(2) 新增 guardrail 门卫测试断言：执行体对 worktree 外路径、对 DB 文件、对外部副作用的修改尝试被拒绝。
- **Rationale**: 复用 015 已有的 workspace fail-closed 边界，不另造安全机制；门卫测试把「只改源码」从软约束变成可证伪硬保证（符合 IV 与项目「硬保证靠门卫不靠 LLM」纪律）。
- **Alternatives considered**: 仅靠 prompt 要求执行体别碰非源码 → LLM 软约束，不可靠，否决。
- ⚠️ 「git 跟踪源码 only」中"未跟踪新文件是否允许"按默认允许（新增源码文件是合理改法），但仍限定在 worktree 内；最终以门卫测试覆盖的边界为准。

## D6. 调度器单例未装配兜底

- **Decision**: 桥接调用 `get_graph_scheduler()`；非 None 直接 `start_graph`；为 None 时不静默丢——把提案留在 `approved`（或 `in_progress` 标记待踢），由 D3 的轮询 job 在调度器可用后补踢一次。
- **Rationale**: B 触发在「任务完成之后」，此时 orchestrator 必已创建、调度器经 `assistant_runtime._ensure_task_scheduler_for_orchestrator` eager 装配（已核实），None 极罕见；兜底保证罕见竞态下不丢任务、不崩溃（符合静默失败纪律）。
- **Alternatives considered**: None 时直接报错失败 → 把罕见竞态变成用户可见失败，体验差，否决。

## D7. 审批前零副作用（advisory 直到人点头）

- **Decision**: 提案生成只写 DB（`pending_review`），不创建 worktree、不建图、不调任何执行体；只有用户显式 `approve` 才触发 D4/D6 的实施路径。`reject` 只改状态。
- **Rationale**: 落实 spec FR-008/CC-007；审查员与提案产出本质 advisory，人是唯一触发实施的闸门。
- **Alternatives considered**: 高分提案自动实施 → 那是 C 阶段，超范围，否决。

## D8. 失败/拒绝的 worktree 清理策略

- **Decision**: 实施失败/测试不过 → 提案 `failed`，worktree **保留**供用户检视 diff；用户 `reject`（含对已 failed 提案的弃用）→ 删 worktree、清残留。成功 `done` 的 worktree 也保留，等用户手动合并后由用户/清理命令回收。
- **Rationale**: 失败时保留现场利于排查（贴合调试需要）；拒绝是明确「不要了」信号才清理。合并与最终回收保持用户手动（FR-015）。
- **Alternatives considered**: 失败即删 worktree → 丢失排查现场，否决。
