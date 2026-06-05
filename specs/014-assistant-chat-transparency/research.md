# Phase 0 Research: 主助理对话透明与可控

关键技术决策（多数已在前期脑暴/澄清中与用户逐项确认，此处固化）。规格无残留 `NEEDS CLARIFICATION`。

---

## R1. 深度取消的实现机制：业务层 ContextVar 运行上下文

- **Decision**: 新建 `src/business/agents/run_context.py`，持有一个 `ContextVar[{root_session_id, cancel_event}]` 与一张 `session_id → threading.Event` 表。`AssistantRuntime` 在 **worker 线程入口**（`_run_assistant` 与续跑 worker）`begin(root_session_id)` 写入 ContextVar 并登记 Event，`finally` 中 `end()` 清理。`AgentLoop.run` 在**每轮迭代开头**与 **LLM 返回后、执行工具批次前**读取 ContextVar 的 `cancel_event`，命中则 `update_session_status("suspended")` 并返回 `ResultType.CANCELLED`。停止端点按 `session_id` 在表中 `set` 该 Event。
- **Rationale**: 助理 100% 调度，子代理/专员在**同一 worker 线程内同步**跑子 loop（调用栈 `父 loop → 工具 handler → 子 loop.run`）。ContextVar 沿同线程同步调用栈自动传播——子 loop 读到的是**父助理那个 Event**，故停止一次即父子皆停（深度取消）。原语放业务层，满足分层（desktop_api 单向调用），`AgentLoop` 不 import desktop_api。
- **Alternatives rejected**:
  - 把 cancel token 作为参数层层穿过 `run_agent → loop.run → 工具 handler`：侵入面大，工具 handler 调用签名 `handler(**args)` 无上下文位可塞。
  - 硬杀线程/进程：Python 不安全，破坏数据一致性。
  - 按 workflow lineage hash 全局注册表逐轮反查父子关系：比 ContextVar 复杂、每轮有查询开销。
- **Note**: 协作式——停止在当前 LLM/原子工具步骤返回后的下一个安全节点生效；点击即时反馈由 UI 负责。非助理流程不调 `begin` → ContextVar 空 → 取消恒 False、零行为变化。
- **Critique 加固（E1/E2）**：① "同线程同步委派"是深度取消的**承重不变量**——补门卫测试断言委派同线程执行，并在代码处注释。② cancel Event 在 `end()` 清表，且每次运行配**代际 token**，使陈旧 `set` 无法误取消复用同一 session 的新一轮运行。

## R2. 取消结果类型：新增 `ResultType.CANCELLED`

- **Decision**: `config.py` 的 `ResultType` 新增 `CANCELLED`。`AgentLoop` 命中取消时置会话 `suspended` 并返回 `CANCELLED`；`orchestrator.run_agent`（assistant 路径）把 `CANCELLED` 当**正常终止**返回、不走 `_emit_agent_error`；`_run_delegated_executor` 把子 loop 的 `CANCELLED` 当"已停止/已暂停"非失败返回，并确保该委派的工具结果**先落库**（记"子代理 X 已被停止、可 continue_subagent 续跑"），再轮父 loop 退出——为"继续任务"留线索。
- **Rationale**: 代码库偏好显式结果类型；用户主动停止是**可恢复暂停**而非错误，必须与不可恢复错误（400/认证）严格区分（参见 `_is_recoverable_llm_failure` 既有约束）。
- **Alternatives rejected**: 复用 `ERROR`（语义错误、会误报失败）、复用 `PAUSED`（语义是"撞上限/LLM 失败"，与用户主动停止来源不同，混用会污染 resumable 语义）。

## R3. 过程可见：AgentLoop 逐步 blinker 事件（实时流式）

- **Decision**: `AgentLoop` 在 `ctx.save_assistant_message`（带 tool_calls 的中间消息）后与 tool 结果后 `emit("assistant_agent_step", session_id=<root>, subagent_id=<self≠root 时>, agent_type, kind∈{reasoning,tool_call,tool_result}, ...)`，文本/结果截断。仅对**带工具调用的中间步骤**与 **tool 结果**发；最终无工具调用的回复仍走既有 display-message，不重复进时间线。`session_id` 取 ContextVar 的 `root_session_id`（子代理活动也归到父会话）；`subagent_id` 为自身 session（≠root 时）供前端归类。
- **Rationale**: 用户明确选择"实时流式"以获得"放心"。同一套逐步事件**同时**服务主助理过程透明（R3）与子任务实时详情（R4）。emit 经 blinker（业务层合法），由 projector 译为 typed UI 事件。
- **Risk & mitigation**: `AgentLoop` 是所有 Agent 共用的高风险核心 → 必补行为契约测试；emit 为 best-effort（异常吞掉记日志，不影响主流程）；payload 截断控制事件量与安全。非助理 agent_type 在 projector 处被过滤，零 UI 噪声。
- **Critique 加固（E4/E5）**：仅在 ContextVar 存在（可观测运行）时才 emit，避免对 PM/Programmer/Trial 白发被丢弃的事件；单回合活动事件设上限/合并防极端长回合刷爆；载荷**显式走 009 payload safety allowlist 脱敏**（不仅截断），防工具入参/结果夹带敏感数据外泄。
- **Alternatives rejected**: 回合结束后回放（不碰 AgentLoop、风险低，但等待期间主助理纯思考段不可见，"放心"打折）；用户已否决。

## R4. 子任务可观测：生命周期事件 + 逐步事件 + 权威列表

- **Decision**:
  - 卡片壳与状态：`orchestrator` 委派点（`_run_delegated_executor`）`emit("assistant_subagent_started|finished|paused", session_id=<parent>, subagent_id, label, task, status, last_output?)` → projector → `assistant.subagent`（scope=父会话）。
  - 卡片内嵌套时间线：复用 R3 的 `assistant_agent_step`（子代理 session 的步骤，经 ContextVar 路由到父会话 + subagentId 归类）。
  - 重连/重开会话：`GET /api/assistant/sessions/{id}/subagents` 由 `WorkflowTransitionRepository` + `SessionRepository` 重建**权威列表**；`GET …/{sessionId}/transcript` 由 `MessageRepository` 重建完整过程（含工具）。
- **Rationale**: 实时事件给当下反馈，权威端点兜底缺口/历史（符合 009 "缺上下文走权威快照"）。卡片双击拉 transcript 即可看历史子任务过程。
- **Alternatives rejected**: 仅靠实时事件（断连/重开会话即丢失，违反 009 兜底原则）。

## R5. "继续任务" = 唤醒主助理续跑（守 100% 调度）

- **Decision**: 暂停态子任务卡片的"继续任务"**复用助理消息派发路径**：带 `subagent_id` 的续跑指令（+ 可选用户补充消息）唤醒主助理；主助理 LLM 看到已落库的"子代理已暂停"线索调既有 `continue_subagent` 续跑；结果走主助理正常回复 + 实时活动时间线。**不新增**绕过主助理的"直连子代理"续跑端点。
- **Rationale**: 用户明确"本质是唤醒主助理再续跑子代理"；守住"100% 调度"约束；`continue_subagent` 已具备 `instruction` 追加、归属校验、`status==active` 拒绝并发；结果天然经主助理回到对话。
- **Alternatives rejected**: 直连子代理续跑端点（绕过主助理，违反 100% 调度，且需额外把结果再注回主助理才能呈现）。

## R6. 排队：前端驱动的单条状态机

- **Decision**: 前端驱动，单条 `queuedMessage`，**整框三态**：`idle`（正常发送）/ `editing`（编辑中，不外发）/ `queued`（已提交，待发）。running 时输入即排队；**回车或失焦**提交（`editing→queued`），**双击**返回编辑（`queued→editing`）；编辑态绝不外发。回合**离开 running**（成功 / 失败 / 等待回答）时自动派发已提交排队消息（含"等待回答"情形，作为对反问的回应——见澄清）；**停止**则退回普通草稿、不自动派发。排队消息**按会话各存一份、跨会话切换保留**（不持久化到后端）。后端 `dispatch_message` 既有 `accepted=False` 作并发竞态安全网（撞到则静默重排）。
- **Rationale**: 全部来自前期脑暴+澄清的逐项确认。前端驱动符合"排队是用户盯着会话时的临时意图"；显式 `editing/queued` 两态解决"编辑中误发"。
- **Alternatives rejected**: 多句队列（过期指令堆积）；覆盖+重敲（丢字）；划线留痕（被原地编辑取代）；两输入框（打架、丢字）；后端排队（关窗仍跑、反直觉、与取消交互复杂）。

## R7. 输入门控键：`progress.status === 'running'`

- **Decision**: 输入可用性由助理真实运行态 `progress.status` 驱动，而非一次 POST 的瞬时 `sending`。`running` 门控；`waiting_for_user` 视为非忙、输入可用。
- **Rationale**: `sending` 只覆盖发送请求那一瞬，POST 返回即解禁，不代表 agent 仍在跑（根因）。
- **Alternatives rejected**: 沿用 `sending`（无法挡住运行期）；`progress!=idle` 一刀切（会误锁 `waiting_for_user`，用户无法回答反问）。

## R8. 活动时间线：默认折叠、限高内滚、历史可重建

- **Decision**: 每回合内嵌**默认折叠、不受控**的 `<details>` 时间线（运行中头部带转圈+"正在处理"，但不自动展开）；正文**限高 + 内部滚动**（复用 `.me-scroll` 风格）；最终回复正常显示且不重复。历史会话的过程由既有已存中间消息重建（无需额外保存实时事件流）。
- **Rationale**: 用户明确要默认折叠、不自动撑开、限高加小滚动条。中间 assistant/tool 消息本就落库，历史重建可行、零新增存储。
- **Alternatives rejected**: `open={running}` 受控（每步强制撑开、用户收不住）；不限高（页面被长过程撑爆）。

## R9. 进度状态新增取值 `cancelled`

- **Decision**: `assistant.progress` 新增 `cancelled` 取值（Registry payload 是 **key** 白名单、不约束 status 取值，故不改 key allowlist）；`AssistantRuntime` 在 `CANCELLED` 时 flush 增量 display 消息 + 发 `assistant.progress {status:"cancelled"}`；前端 TS `AssistantProgress["status"]` 联合类型加 `"cancelled"`，composer 视其为非 running（解锁、不自动派发排队）。
- **Rationale**: 显式停止态，前端据此解锁输入并明确"已停止"，与自动派发逻辑区分。
- **Alternatives rejected**: 复用 `idle`（丢失"被停止"语义）、复用 `failed`（误报错误）。
