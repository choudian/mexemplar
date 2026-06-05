# 主助理对话：透明与可控 — 设计文档

> 状态：设计稿（待评审）
> 日期：2026-06-03
> 适用：`frontend/`（AI Assistant 主屏）+ `src/`（desktop_api、business agents/orchestration）

---

# 第一部分 · 业务理解（面向用户）

## 一句话

把现在"黑盒"的主助理，变成**看得见、停得下、接得上**的透明助理——让用户在等待时心里有数、随时能干预、被打断的活儿还能接着干。

## 解决的核心问题

今天用户面对助理时有三个不安：

1. **看不见**：助理在干嘛全不知道，派出去的子任务、它自己的思考，全是黑盒，只能干等。
2. **停不下**：它跑起来就只能等它跑完，想喊停没办法；而且跑着的时候还能往里发消息，体验混乱。
3. **接不上**：万一被打断，那件做了一半的活儿就没了，得从头来。

## 六个用户场景（已与用户确认）

**① 它在忙的时候，别让我误操作**
助理正在处理任务时，输入框进入"它在忙"的状态——不会再不小心发消息把它打断或重复唤醒。

**② 我想停，随时能停**
正在跑的任务旁有"停止"。点一下当前活儿就停——**包括它派出去正在跑的子任务也一起停**，不会"主的停了、子的还在偷偷跑"。

**③ 它忙的时候，我可以先把下一句想好**
它还在忙，你就能先把下一条消息写好、点发送，它不会立刻发，而是**停在那当"排队的下一条"**，助理一空就自动发出。
**只排一句**，而且这条**随时能接着改**——改措辞、往后追加都行，**不用重敲**。比如排了"帮我查 A"又想加 B，补一句"和 B"就行，"帮我查 A"不用重打。要取消就删掉它。
**就一个输入处**：排队那条始终在输入框这一个地方，没有"另一个空框"。想换成完全不同的下一条，就在这框里改掉它——旧内容一直看得见，不会偷偷丢；不存在"已排一条、又在别处敲了一条"的打架情况。
（不做"覆盖逼你重敲"，也不做划线留痕——直接原地改这一条就够了。）
如果你中途点了停止，排队那条会**回到输入框**，让你重新决定。

**④ 我能看见它派出去的子任务在干嘛**
助理把活儿分给"子助手"时，对话里冒出一张**卡片**（带动效），让你一眼知道"这有个子任务在跑"。**双击展开**能看这个子助手具体做了什么、用了哪些工具。

**⑤ 我能看见主助理自己的思考过程**
主助理怎么想的、调了什么、中间拿到什么结果，也显示在对话里——**默认折叠**，想看就展开，不想看就收着。整个过程对你透明，你就放心了。
（思考过程**实时**显示，等待时就能边跑边看。）

**⑥ 被打断/暂停的活儿，能接着干**
被你停下来的子任务，会以"已暂停"留在那张卡片上。你随时可以点**"继续任务"**让它接着做；有补充想说的写上一起带过去。
本质上是"重新唤醒主助理、让它把刚才那件事接着做完"。

## 整体脉络

**看得见（④⑤）→ 停得下（①②③）→ 接得上（⑥）**，把助理变得透明可控。

## 不做什么（非目标）

- 不做"排多句"队列（确认只排一句）。
- 不做硬杀进程式的瞬时中断；停止是"停在当前这一步之后"（详见技术部分）。
- 不在用户绕过主助理直接操纵子代理；"继续任务"始终经主助理（守住"100% 调度"）。
- 本期不暴露后端调优参数到设置界面。

---

# 第二部分 · 实现设计（技术，供开发参考）

## 现状根因

- 前端发送按钮只在 `sending`（一次 POST 的瞬间）禁用，POST 一返回就解禁；它**不代表 agent 还在跑**。真正的运行态在 `progress.status`（`idle/running/waiting_for_user/succeeded/failed`），由 `assistant.progress` 事件驱动。
- 后端 `AssistantRuntime.dispatch_message` 已对"同会话并发唤醒"返回 `accepted=False`（安全网），但前端没据此做输入门控。
- 子代理（`delegate_to_subagent` / `delegate_to_specialist` / `continue_subagent`）在**同一 worker 线程内同步**跑子 loop（调用栈 `父 loop → 工具 handler → 子 loop.run`，不开新线程）；子代理/专员工具池**不含**委派工具，故委派深度天然有界。
- 子代理活动、主助理中间步骤当前都不进 UI：`get_display_messages_after` 只挑最终回复。
- 业务层（`agent_loop.py`/`orchestrator.py`）**不得** import `desktop_api`；面向前端的事件须走 blinker → `ui_event_projector` → UI Event Registry（typed envelope）。
- `AssistantRuntime._run_assistant` 在 worker 线程内同步调 `run_agent(ASSISTANT) → loop.run`，是设置线程级上下文的正确位置。

## 统一原语：Agent 运行上下文（ContextVar）

新建业务层 `src/business/agents/run_context.py`：一个 `ContextVar` 持有当前运行的 `{root_session_id, cancel_event}`，外加按 `session_id` 注册 `threading.Event` 的表（供 stop 端点按会话查找并 `set`）。

- 在 worker 线程入口（`_run_assistant`、Phase C 续跑 worker）`begin(root_session_id)`：建 Event、登记、写 ContextVar；`finally` 里 `end()` 清理。
- 同线程同步调用栈里的所有嵌套子 loop **自动继承**该 ContextVar。
- `AgentLoop` 读它做两件事：
  1. **取消**：迭代边界 + LLM 返回后执行工具批次前，检查 `cancel_event` → 命中则 `update_session_status("suspended")` 并返回 `ResultType.CANCELLED`。父 loop 与正在跑的子 loop 各自在下一边界退出 → 深度穿透停止。
  2. **活动路由**：emit 每步事件时用 `root_session_id` 定 scope（子代理活动也落到父助理会话），并把自身 `session_id`（≠root 时）作为 `subagent_id` 供前端归类。
- 非助理流程（PM/programmer/trial）不调 `begin` → ContextVar 为空 → 取消恒 False、活动在 projector 按 `agent_type` 过滤 → **零行为变化**。

> 仍是协作式取消：纯对话回合秒停；若卡在一次 LLM 调用或单个原子工具执行内，等那一步返回后立即停（Python 线程下唯一安全做法）。

## Phase A — 输入门控 + 停止 + 排队

**前端**
- `MessageComposer` 改按 `progress.status==='running'` 决定：文本框可编辑、主按钮变"停止"、回车/点发送=入队。`waiting_for_user` 视为非 running（必须可输入以回答助理）。
- **单一输入处（one-slot）**：composer 只有一个文本输入区，**不**渲染"独立排队 chip + 另一个空框"。running 时点发送 → 当前内容置为 `queuedMessage`（armed）、输入区保持显示该文本并标注"排队中·助理空了自动发"；在同一输入区继续改写/追加即**实时更新同一条** `queuedMessage`（不新增第二条、不覆盖丢字）。只有一条生效待发；"取消排队"清空它；停止时它退回普通草稿态。
- `assistantStore` 新增：`queuedMessage: string|null`（armed 的下一条，running 时与 composer 文本同步）、`submitDraft()`（running→arm/更新排队 / 否则立即发送）、`stopRun()`、`cancelQueued()`。
  - `progress` 从 `running` → `{idle/succeeded/failed/waiting_for_user}` 时，若有 armed `queuedMessage` 则**自动派发**（派发时机/输入焦点的细节留给实现）。
  - `stopRun()`：先 `draft = queuedMessage ?? draft; queuedMessage = null`，再调 stop API；因此 `cancelled` 转换**不**触发自动派发（队列已空，排队消息退回草稿）。
  - 撞后端 `accepted=false` 时**静默重新入队**等下次自动派发（不再弹"上一条仍在处理"）。
- `api/assistant.ts` 加 `stopAssistantRun(sessionId)`。
- `AssistantProgress["status"]` 联合类型加 `"cancelled"`。

**后端**
- `ResultType` 新增 `CANCELLED`。
- `AgentLoop.run`：两处取消检查（见统一原语）。
- `orchestrator.run_agent`（assistant 路径）：`CANCELLED` 当正常终止返回，不当错误；`_run_delegated_executor` 把子 loop 的 `CANCELLED` 当"已停止/已暂停"非失败返回，并确保该委派的**工具结果先落库**（记"子代理 X 已被停止、可续跑"），再轮父 loop 退出 → 为 Phase C 留线索。
- `AssistantRuntime`：`_run_assistant` 套 `begin/end`；新增 `cancel_session(session_id)`；`CANCELLED` 时 flush 增量 display 消息 + 发 `assistant.progress {status:"cancelled"}`。
- 端点 `POST /api/assistant/sessions/{id}/stop` → `runtime.cancel_session`。

## Phase B — 实时活动时间线 + 子代理卡片（统一）

**后端**
- `AgentLoop` 每步 `emit("assistant_agent_step", session_id=root_session_id, subagent_id?, agent_type, kind, ...)`：
  - `kind ∈ {reasoning, tool_call, tool_result}`；文本/结果截断（沿用 `_safe_text` 上限）。
  - 仅对**带 tool_calls 的中间 assistant 消息**和 **tool 结果**发；最终无工具调用的回复仍走现有 display-message，不重复。
- `orchestrator` 委派点（`_run_delegated_executor`）补 `emit("assistant_subagent_*", session_id=parent_session_id, subagent_id, label, task, status, last_output?)`（生命周期：started/finished/paused）。
- `ui_event_projector` 加分支：
  - `assistant_agent_step` → `assistant.activity`（scope=父会话；payload 含 `subagentId/kind/toolName/text/...`）；`agent_type` 不属于 {assistant, ephemeral_subagent, specialist} 时返回空。
  - `assistant_subagent_*` → `assistant.subagent`（scope=父会话；卡片壳 + 状态）。
- UI Event Registry 注册 `assistant.activity`、`assistant.subagent` 及其 payload/scope allowlist。
- 端点：`GET /api/assistant/sessions/{id}/subagents`（权威列表，重连兜底）、`GET /api/assistant/sessions/{sessionId}/transcript`（从落库消息重建活动时间线，含工具，用于历史/重连回填）。

**前端**
- store 累积 `activity[]` 与 `subagents[]`（按 `subagentId` 归类；`subagentId==null` 进主时间线）。
- `AssistantScreen`：每回合内嵌**默认折叠**的活动时间线；子代理渲染为卡片（运行动效），**双击展开**看该子代理自己的嵌套时间线。
- 收到 `backend.resync_required` 或打开历史会话时，走 transcript/subagents 端点拉权威快照。

## Phase C — 「继续任务」（唤醒主助理续跑，守 100% 调度）

- 暂停态子代理卡片上"继续任务"按钮 + 可选补充消息框。
- 动作 = **复用助理消息派发路径**，带 `subagent_id` 的续跑指令唤醒主助理（可附用户补充消息）；主助理 LLM 看到已落库的"子代理 X 已暂停"线索 + 指令，自己调 `continue_subagent` 续跑；结果走正常回复 + 实时活动时间线。
- 不新增"直连子代理"续跑端点（守住 100% 调度）；`continue_subagent` 已具备 `instruction` 追加、归属校验、`status==active` 拒绝并发。
- 续跑同样经 worker + `begin/end`，故可再次被停止。`status==active` 时前端"继续任务"按钮禁用。

## 契约与接口新增汇总

- UI 事件：`assistant.activity`（新）、`assistant.subagent`（新）、`assistant.progress` 增 `cancelled` 取值。
- 端点：`POST .../{id}/stop`、`GET .../{id}/subagents`、`GET .../{sessionId}/transcript`。
- 结果类型：`ResultType.CANCELLED`（新）。

## 测试策略（按硬规则补行为契约测试）

- **A**：loop 取消（迭代边界 / 工具批次前各一例）、深度取消父子链（父委派子、stop 后父子都返回 CANCELLED）、`runtime.cancel_session`、stop 端点、`CANCELLED` 不被当错误、composer 各态、store 自动派发、停止退回草稿、`accepted=false` 静默重排。
- **B**：`AgentLoop` 逐步 emit（root 路由 + subagentId 归类 + 非助理零 emit）、projector 映射、`assistant.activity`/`assistant.subagent` 契约、`subagents`/`transcript` 端点、前端时间线折叠 + 卡片双击 + scope=父会话过滤。
- **C**：resume 注入指令唤醒助理、补充消息追加、`active` 禁用、归属校验。

## 风险与缓解

- **改 `AgentLoop`（B 的实时 emit）属高风险区**：被所有 Agent 类型共用 → 必补完整行为契约测试；emit 失败不得影响主流程（best-effort，异常吞掉记日志）。
- **事件量**：长回合逐步事件较多 → payload 截断 + 仅对中间步骤发；最终回复不重复进时间线。
- **协作式取消的延迟**：等待当前 LLM/原子工具返回 → 文档化为预期行为，UI 上"停止"点击即给反馈（按钮置忙）。
- **透明视图暴露工具细节**：用户明确要看（含工具）→ 详情视图按可读方式渲染工具名/参数/结果，避免裸内部 JSON。

## 分期交付

A → B → C（C 依赖 B 的可见性与 A 的暂停态）。三者共用"运行上下文"原语与活动事件，可分批实现、分批评审，但同属一个特性。
