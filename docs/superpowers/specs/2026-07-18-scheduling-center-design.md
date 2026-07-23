# 调度中心（Scheduling Center）设计文档

- **日期**：2026-07-18
- **状态**：设计稿（已评审——2026-07-18 全仓核实 + 4 项产品决议已并入，见 §17）
- **范围**：第一批（最小闭环 + 待办接入）
- **说明**：本稿是 brainstorming 阶段的设计共识，评审决议并入后可转 speckit 正式 spec（建议编号 033）。

---

## 1. 背景与问题

### 1.1 用户诉求
做一个"**定时 / 周期唤醒 agent 执行任务、做完通知用户**"的能力。典型场景：

- 周期任务：「每天 9 点查一下竞品价格」
- 一次性定时：「明天下午 3 点整理本周会议纪要」
- 立即触发：「这条待办，现在就帮我做」

用户最初的表述是"改造现有定时功能、从待办栏接任务自动做"，经澄清后明确：**这是一个通用的"定时唤醒 agent"能力，待办只是触发源之一，不是待办的增强**。

### 1.2 现状（已核实）
全仓盘点 + git 全历史（含所有分支/worktree/含 gitignored）确认：**Exemplar 目前没有任何用户态定时 / 周期 / 提醒功能。**

- 三个后台 worker（大脑维护 5min、任务协作恢复 30s、工具 bug 队列 5s）都是**内部维护型**，不接用户任务。
- 无 cron / APScheduler、无 `scheduled_at` / `due_at` / `recurrence` 字段、无定时 UI 屏、无定时 spec。
- 用户记忆中的"做过 cron 工具"来自 `d95ed1b`（2026-03-28）`builtin_general_tools.py` 第 13 行注释「cron...在后续 Step 实现」——**规划过，从未落地**。`docs/design/hermes-agent-reference.md:43` 也把 `cronjob_tools` 列为"Hermes 有、Exemplar 没有"。
- spec 025（待办栏）明确把"截止日期 / 提醒 / 重复任务"列为 Out Of Scope。

**结论：这是从零新建一个能力，不是改造现有功能。**

### 1.3 类比
类似 Java 的 **XXL-Job**：调度中心（决定何时触发）+ 执行器（实际怎么跑）分离。本设计沿用这套"调度 vs 执行分离"的结构。

---

## 2. 核心定位（一句话）

> **调度中心 = 现有任务调度（task_collaboration）的升级版**，在原有"派 agent 执行 + DAG 推进 + 通信 + 故障恢复"基础上，加三样东西：
> 1. **三种触发方式**（立即 / 一次性定时 / 周期）
> 2. **执行记录**（用户可看的历史）
> 3. **完成通知**（Toast + 桌面通知）

**不是另起炉灶的新系统，是给现有任务调度加"触发器 + 记账 + 通知"**，让它从"只能即时干"升级成"能定时 / 周期 / 立即干，还记着账、跑完喊你"。

---

## 3. 职责分工（业务）

这是整个设计的地基：**动脑子的事和机械执行的事分开。**

| 角色 | 业务职责 | 技术对应 | 动脑子？ |
|---|---|---|---|
| **主助理** | 接待 + 总协调：听懂用户、决定派不派活、派啥活 | `AssistantRuntime` 主助理 | 是 |
| **规划专员（plan agent）** | 把复杂任务拆成步骤图（DAG）、定工序 | task_collaboration 的 planner | 是 |
| **调度中心** | 到点触发 + 开主助理 session + 通知 + 记账 | 新 `scheduling` 模块 | **否（机械）** |
| **施工流程** | 派活后执行的系统机制（推进 / 通信 / 恢复） | task_collaboration（**不改**） | 否（机制） |
| **执行体** | 真正干活 | ephemeral_subagent / specialist | 执行时是 |

**分工原则：**
- 理解意图、拆活、决定派谁 → **主助理 / plan agent**（AI）
- 到点启动、记账、通知 → **调度中心**（机械）
- 派活后怎么推进执行、怎么通信、怎么恢复 → **施工流程**（现有 task_collaboration，不动）

> 一句话：调度中心**不拆活、不决定派谁、不干预执行内容**，它只负责"到点把任务点燃 + 跑完喊你 + 记一笔"。

---

## 4. 架构总览

```
触发源
├─ 对话（用户说话）→ 主助理接待 → 派活               〔现有，source=user，不动〕
└─ 调度中心（任务指令已明确，按时机触发）
   ├─ fire_now     立即（动作：事件唤醒任意任务马上跑一次）
   ├─ one_shot     一次性定时（到点跑一次）
   └─ recurring    周期（每天 / 每周 / 每隔 N）
        ↓ 新建主助理 session（source=scheduled，关联 scheduled_task_id）
        ↓ 投递：任务指令 + 「无人值守、自主干完别等用户」提示
   主助理 session（复用现有，全权处理）
   → 判复杂度 → 简单：派一个执行体 / 复杂：plan agent 拆 DAG + 多执行体协作
   → 通信（ask_parent 向上问 / meeting channel 横向协作 / adjudication 验收）
   → 回流
        ↓
   完成通知（Toast + 桌面通知）+ 记历史（调度中心历史列表）
```

**关键：调度中心触发后不是自己派执行体，而是开一个主助理 session 让主助理全权处理。** task_collaboration 一行不改。

---

## 5. 关键设计决策

### D1：调度中心 = task_collaboration 升级，非新系统
执行 / 通知底座已齐全（durable 执行、lease 恢复、裁定回流、UI Event Registry），复用最充分、风险最小。

### D2：定时 / 立即触发 = 新建主助理 session（**核心简化**）
触发后不直接派执行体，而是**开一个主助理 session**，把任务指令当一条消息投给它，主助理像处理用户消息一样全权处理。

**理由：**
- 最头疼的"派谁 / 怎么拆 / 多 agent 怎么协作"全由主助理包揽（它本来就会），调度中心完全不操心。
- 复杂任务（写代码、多 agent 协作）自动走"主助理判复杂度 + plan agent 拆 DAG + 多执行体协作"的现有路径，**和对话里处理复杂任务一模一样**。
- task_collaboration 完全不动，零回归风险。

**代价：** 每次触发都起一个完整主助理 session（跑 LLM 理解 + 拆解），比"直接派执行体"重。换来的是统一和能力完整。周期任务一般一天几次，成本可控；接受此权衡。

### D3：会话来源标记
session 加 `source` 字段：`user`（用户手动开）/ `scheduled`（定时任务触发）。`scheduled` 会话额外关联 `scheduled_task_id`。

### D4：scheduled 会话从聊天屏排除，进调度中心历史
- `scheduled` 会话**不在** AI Assistant 聊天屏的会话列表显示。
- 统一进**调度中心的历史执行**列表；点进去能看详情、**能接着跟那个会话聊**（复用现有会话 UI，不多做）。
- 聊天屏只留 `source=user` 的会话。

理由：把"用户主动对话"和"定时自动执行"在 UI 上分开，互不干扰。

**"接着聊"是第一批唯一的纠偏与重试通道**（用户确认）：任何终态的 run 都能从历史点进去继续沟通——跑失败了让主助理重试或换路子、跑成功但结果不满意让它返工、停在 `waiting_user`（D10）的补一句话让它继续。这条人工接管路径正是 §15 把"自动失败重试策略"列为非目标的底气：失败不需要系统自动重跑，用户看到通知后进去说一句即可，且此时人在场、高危确认恢复正常交互语义。

### D5：通信完全复用现有
子 agent 协作 / 通信走现有三条通道，调度中心提供通道但不干预内容：
- 向上问：`ask_parent` / question route（送主助理，必要时转用户）
- 横向协作：meeting channel（受监督纯消息会议）
- 完成验收：adjudication（父侧裁定）

### D6：待办接入不改 todo 表，且只能是一次性任务
待办作为触发源之一：`scheduled_task` 的 `source_ref` 引用 `todo_id`（**外部引用**）。触发时取该待办的 `title + description` 作为任务指令底稿。**`user_todos` 表结构不动**——符合用户"不想加到 todo 里"的要求。

**`source_type=todo` 的任务 `schedule_kind` 恒为 `one_shot`，不支持 `recurring`（用户拍板，门卫守住）。**
理由：待办的"完成"语义天然一次性。一条待办每周被执行一次就永远无法完成，它就不再是待办、而是混进待办列表的例行工作。切掉周期后，待办列表不会被 recurring 条目污染。**需要"每周五整理纪要"这类例行工作时走对话直接建周期任务，不经待办**——待办管一次性的事，调度中心管例行的事，职责边界更清楚。

**接入方式（三点，均不触碰 `user_todos` 表）：**
- **入口复用创建路径**：待办条目上的动作（按钮 / 右键）→ 弹 D12 同一张确认卡，不新做 UI。
- **指令预填但必须可编辑**：待办标题通常极短（"整理会议纪要"），给人看够、给 AI 当指令远远不够（整理哪些会议 / 什么格式 / 存哪）。确认卡的指令框预填 `title + description` 后允许当场补全，否则从待办建的任务大概率产出偏离预期。
- **完成后不自动划掉待办**：只在待办卡片显示"上次执行：周五 17:03 成功"（前端向调度中心查，不写 todo 表）。AI 声称完成 ≠ 用户认可完成，判断权留给用户；结果页可给"标记待办完成"按钮（调既有 `/api/user-todos`），省去跳屏。

**行业参照**：主流 AI 定时能力（ChatGPT Tasks）与自动化平台（Zapier / n8n / Apple 快捷指令）**均未接入待办列表**，调度都是独立实体；待办类产品（Todoist / Things / 微软 To Do）的时间属性只用于提醒人、不替人执行。本设计据此把"从待办建任务"定位为**内容取自待办的独立一次性任务**，而非给待办加调度属性。

### D7：无人值守 fail-closed（机制承载，非仅提示）
`scheduled` session 投递时仍附"无人值守提示"（advisory，引导主助理自主干完、少触发确认类动作），但 fail-closed 由机制硬保证，分三条链路：
- **高危确认**：scheduled 会话走新增 unattended 分支——未开启免确认的任务，高危确认**立即按拒绝处理**（不白等现有 `_CONFIRM_TIMEOUT=120s` 超时，超时拒绝仅作托底），任务继续其余部分并在汇报中列出被跳过的动作；开启 per-task 免确认的走 D11。
- **结构化澄清**：`ask_user_question` 既有 300s 超时 fail-closed 托底（`clarification_manager.py`），提示引导主助理无人值守下不调用。
- **反问等待**：主助理直接反问会让 run 停在 `waiting_for_user` 终态且**该态没有任何超时机制**——不能靠提示挡，走 D10「通知接管」，不算失败也不悬空。

### D8：错过触发 = 补跑一次（misfire 策略）
桌面 app 非常驻：sidecar 只在 app 运行时活着（与 XXL-Job 常驻服务端的关键差异）。启动 / 恢复时发现 `next_fire_at < now`：**补跑一次**——错过多个周期也只补最近一次，然后滚动到下一个未来时点；one_shot 同样补跑（用户显式交代的事不丢）。例外：`paused` 期间过点的不补（暂停语义即"别跑"）——恢复时 one_shot 已过点置 `expired`，recurring 直接滚动到下一个未来时点。app 未运行时既不触发也不通知，补跑是唯一救济，需向用户说明该预期。

### D9：同任务重入 = 跳过本次（overlap 策略）
到点触发时上一次触发仍未完成（会话未静默，见 §7.4）：**本次跳过**，历史记一条 `skipped`（对应 XXL-Job 的"丢弃后续"）。已核实 runtime 跨 session 真并发、无天然串行保护，不跳过就会堆积。排队 / 并行策略留后续批次。

### D10：反问等待 = 通知用户接管
scheduled run 落 `waiting_for_user`（主助理确需用户回答才能继续）：本次 run 置 `waiting_user` 状态并发通知（Toast + 桌面通知），用户从调度中心历史点进会话接着聊（复用 D4），聊完任务继续推进。不标失败、不静默悬空。

### D11：高危动作按任务配置免确认（默认关闭，创建时用户亲手勾选）
`scheduled_tasks` 增加 `unattended_auto_approve`（默认 0）。开启后，**仅该任务触发的 scheduled 会话内**高危确认自动放行（决策来源记入既有确认审计日志）；**不触碰进程全局 `_auto_approve_enabled`**（已核实其为进程级单一标志而非会话级，动它会波及用户正在聊的会话）。未开启的任务按 D7 立即拒绝。

**开启方式必须是用户显式操作，不得由 LLM 从对话推断**（见 D12 创建确认卡 / §9 详情页开关）。这是整个功能授权面最大的一个点——授权 AI 在用户不在场时执行破坏性动作；项目高危确认一贯是 fail-closed 硬保证，不能在此退回 prompt 自觉。

**授权粒度：** 第一批粗放单档——开启即该任务所有高危动作放行（文件删除 / 命令执行 / 对外发送不再细分）。细粒度权限矩阵易做成没人看得懂的配置，留后续批次按真实需求再拆。

> **规则冲突标注（受控例外）**：现行全局硬规则要求"免确认只允许是当前进程会话级内存状态，不得写入配置、SQLite 或 DuckDB"。本决策是用户显式拍板的**受控例外**，四重限定：仅 scheduled 会话 / 仅该任务 / 默认关闭 / 只能由用户显式 UI 确认开启。转正式 spec 时必须同步在 constitution / AI 入口文档落例外条款，不得静默违反。

### D12：创建定时任务经用户确认卡落地
主助理调 `create_scheduled_task` 后**不直接落库**：先经确认卡（复用 019 非模态结构化卡片 + first-decision-wins 协议）展示解析结果，用户确认后才写入。

卡片承载三件事：
- **核对主助理的理解**：标题 / 人话时间描述（"每天 早上 9:00"）/ 指令原文——定时任务是"埋雷式"的东西，把"每天9点"听成21点要等到跑错才发现；
- **勾选 `unattended_auto_approve`**（默认不勾，附风险说明）——满足 D11 的"用户亲手勾"；
- **取消入口**：超时 / 取消 / 停止 = 不创建（fail-closed，天然安全，无需 pending 状态与清理逻辑）。

**所有定时任务创建一律弹卡**，不按"是否涉及高危"分流——那个判断本身又会退回 LLM 启发式（参照 MCP `_is_likely_write_operation` 误报漏报的既有教训）。创建频率低，统一弹卡的打扰可接受。

---

## 6. 触发模型

| 类型 | 业务场景 | 数据 / 行为 |
|---|---|---|
| `fire_now`（动作，非 kind） | 立即跑一次（待办点"立即执行"、任意任务"现在跑一次"） | 对任意任务的触发动作：事件唤醒马上跑，不改 `next_fire_at`；"纯立即"场景 = 创建 one_shot(`run_at`=now) |
| `one_shot` | 一次性定时（明天 15:00） | `next_fire_at` = 具体时刻，触发后置 `completed` |
| `recurring` | 周期（每天 / 每周 / 每隔 N） | `next_fire_at` 按规律滚动 |

> "立即"从 schedule_kind 中移除、改为动作：否则"对 recurring 任务点现在跑一次"在数据模型上无法表达（不能临时改 kind）。业务上"三种触发方式"的说法不变。

**第一批周期支持：** 每隔 N（分钟/小时）、每天某时、每周某天某时、工作日。**不引入完整 cron / rrule 解析器**（放后续批次）。

**Worker 模式：** 周期扫描 `next_fire_at ≤ now ∧ status=active` + 事件唤醒（fire_now 立即响应），仿现有 worker（`Event.wait` 超时 + 事件触发双模式，参考 `BrainBackgroundWorker`，已核实该模式属实）。

**Misfire / 重入：** 错过触发按 D8 补跑一次；上次未完成本次按 D9 跳过并记 `skipped`。

---

## 7. 数据模型（草案，字段细节留 plan 阶段）

### 7.1 新表 `scheduled_tasks`（SQLite migration v30）
| 字段 | 说明 |
|---|---|
| `scheduled_task_id`（PK，前缀 `sch_`） | 主键（与 session 表关联字段 `scheduled_task_id` 同名对齐；不再叫 trigger_id） |
| `source_type` | `direct`（直接指令文本）/ `todo`（引用待办）——只表达指令来源。注：`todo` 来源受 D6 约束，`schedule_kind` 只能是 `one_shot` |
| `source_ref` | 任务指令文本（direct）或 `todo_id`（todo） |
| `title` | 展示用标题 |
| `schedule_kind` | `one_shot` / `recurring`（immediate 不是 kind，见 §6 fire_now 动作） |
| `schedule_payload` | JSON：`run_at` / `interval_seconds` / `weekdays` / `time_of_day` |
| `status` | `active` / `paused` / `completed` / `expired`（`expired` 仅用于暂停期间过点的 one_shot，见 D8） |
| `unattended_auto_approve` | 默认 0；per-task 高危免确认（D11，受控例外） |
| `executor_hint` | 可选，倾向某专员（advisory：投递时作为提示附带，主助理参考但不强制——派谁最终仍由主助理定；第一批可裁） |
| `next_fire_at` / `last_fired_at` | 调度时机 |
| `created_at` / `updated_at` | 时间戳 |

- **删除走软删**（对齐项目惯例：brain 永不物理删除、specialist `is_active=0`），历史 runs 与关联会话保留可追溯。
- **todo 悬空处理**：引用的待办被删除、或被用户手动标记完成 → 任务**作废**（置 `expired` 并标注原因），不再触发。一次性任务的源消失即失去意义（你自己做完了就不用 AI 再做），无需 paused 后等用户改绑。触发时读不到指令同此处理。

### 7.2 session 表加字段
- `source`：`user` / `scheduled`（默认 `user`）
- `scheduled_task_id`：可空，关联触发它的定时任务

### 7.3 执行历史
每次触发记一条 `scheduled_task_runs`：`run_id, scheduled_task_id, session_id, started_at, finished_at, status, summary`。`status` 枚举：`running` / `succeeded` / `failed` / `waiting_user` / `skipped`。会话详情本身复用现有 session 消息，不重复存。`summary` 取完成时刻该会话最后一条 assistant 展示消息的确定性截取（advisory，不额外跑 LLM 生成）。

### 7.4 完成判定（run 何时置终态、通知何时发）
已核实的架构事实：**主助理一轮 run 结束 ≠ 任务完成**——委派是 durable 非阻塞（当轮即 `assistant.progress=succeeded`，持久 Task 仍在后台跑）；图终态没有单一事件；**含失败 / 取消的图 root 不收口为 completed**（只回流主助理裁定）；图终态后还有一轮回流续跑（ParentReentrySink 注入 briefing 再跑一轮，最终汇报发生在这轮）。

因此"完成"定义为 **scheduled 会话静默**：
- 该会话无活跃 run worker、无未消费回流、关联 task graph（若有）所有执行节点均为终态；
- 实现：监听 `assistant.progress` 终态 + `assistant_task_graph_changed` blinker，触发后查 graph snapshot 推导 all_terminal（与 graph_scheduler / reentry_briefing 同一套计算）。**不得只等 root=completed**（会漏失败终态）、**不得在首轮 succeeded 就报完成**（防误报）；
- 终态映射：静默且全成功 → `succeeded`（发完成通知）；静默且含失败 → `failed`（通知带原因）；run 落 `waiting_for_user` → `waiting_user`（走 D10 通知接管，不置终态，用户接管后继续推进直至静默）。

---

## 8. 组件

- **`src/business/scheduling/`（新模块）**
  - `SchedulerService`：定时任务 CRUD + 触发时机判定
  - `SchedulerWorker`：值守线程（周期扫描 + 事件唤醒）
  - `SessionLauncher`：触发后创建主助理 session（`source=scheduled` + 关联 `scheduled_task_id` + unattended 标记）+ 投递任务指令 + 无人值守提示
  - `RunCompletionMonitor`：订阅 run / graph 事件，按 §7.4 判定会话静默、写 run 终态、触发通知
- **工具（主助理创建定时任务用）**：`create_scheduled_task` / `list_scheduled_tasks` / `update_scheduled_task` / `pause_scheduled_task` / `delete_scheduled_task`
- **desktop_api**：`/api/scheduled-tasks` typed API
- **前端**：调度中心屏（管理 + 历史）
- **sidecar lifespan**：启动时拉起 `SchedulerWorker`，关闭时停（仿现有 worker 接入）

---

## 9. UI

> **实现要求**：本屏及创建确认卡的界面设计**必须先走 `frontend-design` skill**，在写第一行 UI 代码前确定视觉方向，不要按默认样式实现完再回头美化。项目视觉基调见既有设计令牌（淡薄荷青系）。

新主屏**调度中心**（路由 `/scheduled`）：
- **定时任务管理**：所有任务（周期 / 一次性 / 来自待办）统一在此列表可见，每条展示——
  - 标题、状态（运行中 / 已暂停）
  - 调度描述（人话："每天 09:00" / "每周一 08:00" / "一次性 7月19日 17:00"）+ **下次触发时刻**
  - 上次执行结果（时间 + 成功 / 失败 / 需接管；未跑过标"还没跑过"）
  - **免确认任务的醒目标记**（⚠）：`unattended_auto_approve` 开启状态必须在**列表层**一眼可见、不埋进详情页——这是"授权 AI 在无人时执行破坏性动作"的清单，需要像系统权限总览一样可随时审视与回收
  - 行内操作：暂停 / 启用 / 现在跑一次（fire_now）/ 删除
- **空态与创建引导（必需）**：面板无"新建"按钮（第一批不做表单），因此列表为空时**必须给出创建指引**（引导去 AI 助理对话创建并给出例句）；否则用户面对空白面板无从下手。这是"创建入口只走对话"的直接代价，不能省。
- **创建确认卡**（D12）：主助理创建时弹出，核对解析结果 + 勾选免确认 + 可取消
- **任务详情页开关**：`unattended_auto_approve` 事后可改（跑过之后想放开或收回），带风险说明
- **第一批不做创建 / 编辑表单**（用户确认）：创建入口走对话 + 确认卡（工具只给主助理，见 §11），UI 只做管理与开关——单入口避免口径漂移；完整编辑表单留后续批次
- **因此第一批无"修改任务"能力**：改时间 / 改指令 = 删除后重新对话创建（已知取舍，重建成本低；若实际使用中改动频繁，再把编辑表单提进后续批次）
- **历史执行**：每次触发的状态 / 时间 / 汇报；`waiting_user` 醒目标注"需要你接管"并提供进入会话入口；点进去看会话详情、能接着聊
- `scheduled` 会话不在 AI Assistant 聊天屏显示。注意：这是 session 首次引入来源区分——已核实现状聊天屏列表**没有任何来源过滤**（仅 agent_type + status，`chat_service.py`），028 提案讨论会话今天就混在聊天屏里；`source` 枚举设计留扩展位，讨论会话是否也归类留 plan 阶段决定

---

## 10. 通知

- **通知触发点**：run 置 `succeeded` / `failed`（完成通知，§7.4）与 `waiting_user`（接管通知，D10）；`skipped` 不通知只记历史
- 应用内 Toast（仿 `BrainToast`，已核实组件存在）
- 桌面系统通知：**需新装 `tauri-plugin-notification`**（capabilities 审慎授权）；app 未运行时既不触发也不通知（D8 补跑是唯一救济），需向用户说明该预期
- 经 UI Event Registry 注册新事件（如 `scheduled_task.completed` / `scheduled_task.changed`）

---

## 11. 安全 / 边界

- 主助理 100% 调度不变；调度中心不执行、不拆活、不决定派谁。
- 无人值守 fail-closed（D7）。
- 配置 / secret 走 `UnifiedConfigManager`。
- 跨模块通知走 blinker；面向前端事件必须经 UI Event Registry。
- 桌面通知插件 capabilities 审慎授权（遵循最小权限）。
- 待办接入不改 `user_todos` 表结构（门卫测试守住）。
- 创建定时任务的工具只给主助理（对话入口），调度中心本身不持有"创建"能力。
- per-task 免确认（D11）四重限定：仅 scheduled 会话 / 仅该任务 / 默认关闭 / 只能由用户显式 UI 确认开启；**不触碰进程全局 `_auto_approve_enabled`**；持久化免确认属受控例外，须随正式 spec 修订 constitution / AI 入口文档条款。
- **`unattended_auto_approve` 不得作为 `create_scheduled_task` / `update_scheduled_task` 工具参数存在**（门卫测试守住）：该字段只能经确认卡勾选或详情页开关写入，LLM 无法通过工具调用自行开启，也无法被对话话术诱导设置。
- scheduled 会话第一批**不参与 brain Segment 沉淀**：周期任务大量重复会话会污染大脑记忆与招募信号；后续批次再评估按价值选择性沉淀。

---

## 12. 命名

中文：**调度中心**。

- **理由：** 本质是统一任务触发执行的中枢（XXL-Job 式），"调度中心"承载完整平台语义（触发 + 执行 + 监控 + 通知）。
- **撞名讨论：** 现有 `graph_scheduler`（依赖推进）和"100% 调度"（dispatch）也用"调度"二字，存在词汇重叠。解法：在模块文档点明区隔——**调度中心 = 时间维度的触发中枢；`graph_scheduler` = 依赖维度的推进器**。备选名（定时中心 / 计划中心 / 自动化中心）能避撞但语义偏窄。
- 内部命名：模块 `src/business/scheduling/`；类 `SchedulerWorker` / `SchedulerService`；表 `scheduled_tasks` / `scheduled_task_runs`。

> **命名待最终确认**（见第 14 节）。

---

## 13. 测试策略

- 触发精度：fire_now 立即、one_shot 到点、recurring 周期滚动
- 周期 `next_fire_at` 计算（每天 / 每周 / 工作日 / 时区）
- **misfire（D8）**：错过补跑一次、错过多周期只补一次、paused 期间过点不补（one_shot 置 expired）
- **重入（D9）**：上次未静默本次跳过并记 `skipped`
- session 创建 + `source` 标记 + 任务投递 + 无人值守提示已注入
- **无人值守 fail-closed（D7）**：未开免确认任务的高危确认立即拒绝（不等 120s）；`waiting_for_user` 走通知接管不悬空（D10）
- **per-task 免确认范围门卫（D11）**：只影响该任务的 scheduled 会话；不改进程全局 `_auto_approve_enabled`；用户会话不受波及
- **免确认授权来源门卫（D11/D12）**：工具 schema 不含 `unattended_auto_approve` 参数；LLM 无法自行开启；未经确认卡的创建调用不落库
- **免确认授权可见性**：开启该开关的任务在列表层带醒目标记，用户可一览并随时回收
- **创建确认卡（D12）**：确认后才落库；取消 / 超时 / 停止均不创建；卡片展示的时间解析与实际 `next_fire_at` 一致
- **完成判定（§7.4）**：首轮 succeeded 不误报完成；图含失败不漏报（不依赖 root=completed）；回流续跑轮结束才置终态
- 通知（Toast + 桌面；`skipped` 不通知）
- 待办接入不改 `user_todos` 表（门卫）；**`source_type=todo` 的任务不得配 `recurring`**（门卫）；todo 删除 / 手动完成后任务作废不再触发
- 从待办创建时指令预填 `title + description` 且可编辑；执行完成不自动修改待办状态（门卫：调度路径不写 `user_todos`）
- `scheduled` 会话从聊天屏排除、进调度中心历史、能接着聊；不进 brain Segment 沉淀
- 职责边界门卫：调度中心不直接执行 / 不拆 DAG；创建工具只主助理可用

---

## 14. 待确认 / 开放问题

1. **命名最终拍板**：调度中心 vs 定时中心 / 计划中心 / 自动化中心。
2. **周期规则细节**：工作日定义、时区处理（`next_fire_at` 存 UTC 还是本地、DST）、跨日边界。
3. **桌面通知 capabilities**：`tauri-plugin-notification` 的授权范围。
4. **待办入口的 UI 形态**：待办条目上是按钮还是右键菜单（接入语义已由 D6 定完，只剩这一处交互细节）。
5. **全局并发上限**：同任务重入已由 D9 挡住；多个**不同**任务同时触发时是否需要全局 session 数上限。
6. **D11 受控例外落地**：转正式 spec 时在 constitution / AI 入口文档写"免确认持久化例外"条款的具体措辞。
7. **`source` 枚举与 028 讨论会话归类**：讨论会话是否也标记来源、聊天屏如何处理（见 §9 注）。

> 已拍板并转正文的原开放问题：无人值守高危策略（→D7/D11）、错过触发（→D8）、周期重入（→D9）、反问处置（→D10）。

---

## 15. 非目标（Out of Scope，第一批）

- 完整 cron 表达式 / rrule 解析
- 任务编排（多个定时任务串成 DAG）
- 自动失败重试策略 / 路由策略 / 分片（重试走 D4 人工接管通道：从历史点进会话接着聊）
- 定时任务的创建 / 编辑表单（创建走对话 + 确认卡；修改 = 删除重建）
- 跨设备同步
- 待办表加 `due_at` / `recurrence` 字段（**明确不改**）
- 复杂的配额计费

---

## 16. 名词对照表（业务 ↔ 技术）

| 业务比喻 | 技术对应 |
|---|---|
| 调度台 / 调度中心 | `scheduling` 模块（`SchedulerWorker` + `SessionLauncher`） |
| 接待员 / 工头（动脑子） | 主助理 + plan agent |
| 施工流程 | task_collaboration（**不改**） |
| 工人 | 执行体（ephemeral / specialist） |
| 对讲机 | meeting channel |
| 验收 | adjudication |
| 派工单 | scheduled_task |
| 工序图 | DAG（plan agent 拆出，由 task_collaboration 的 `graph_scheduler` 照着推进——调度中心不碰执行） |

---

## 17. 评审记录（2026-07-18）

**核实结论**（全仓证据核查，含两轮并行代码调查）：
- 现状盘点（§1.2）属实：`src/` 与 `frontend/src/` 全量搜索 cron / APScheduler / scheduled_at / recurrence / next_fire_at 均 0 命中；三个内部维护 worker 确认存在（brain 300s / 任务恢复 30s / 工具队列 5s）。
- migration 现止于 v29，v30 空闲；`user_todos.description` 字段存在（D6 成立）；`BrainToast` 与 `BrainBackgroundWorker` 双模式属实。
- **跨 session 真并发可行**：runtime 门控为 per-session（`_workers` 按 session_id 键，`assistant_runtime.py`），用户会话与 scheduled 会话可同时各跑各的线程——D2 无架构阻碍。
- 高危确认 120s 超时拒绝（`builtin_general_tools.py`）与 `ask_user_question` 300s 超时 fail-closed（`clarification_manager.py`）均已存在；**免确认标志 `_auto_approve_enabled` 是进程级全局而非会话级**——D11 因此必须新建 per-task 机制而非复用。
- **一轮 run 结束 ≠ 任务完成**：委派 durable 非阻塞、图终态无单一事件、含失败图 root 不收口、图终态后还有回流续跑轮——§7.4 完成判定由此推导。
- `sessions` 表无任何来源字段，聊天屏列表无来源过滤（028 讨论会话现状混入在案）——D3 的 `source` 为首次引入。

**用户拍板**（4 项产品行为语义）：
1. 无人值守高危动作 → **按任务配置免确认**（D11；未配置的立即拒绝兜底，D7）
2. 错过触发 → **补跑一次**（D8）
3. 周期重入 → **跳过本次**（D9）
4. 半路反问 → **通知用户接管**（D10）

**评审后追加修正**：初稿 D11 与"UI 不给表单"冲突——免确认开关将只能由主助理从对话推断设置，把安全授权退回 LLM 判断。用户指出"制定任务时就该让用户确定"，据此拆开「谁设置」与「何时设置」两个维度：**创建时即可定（满足用户诉求），但必须用户亲手勾（满足安全约束）**，落为 D12 创建确认卡 + 详情页事后开关 + 工具参数门卫。

**后续三项拍板**：
5. 不做创建 / 编辑表单 → 第一批无"修改任务"能力，改动 = 删除重建（§9 / §15）
6. scheduled 会话只在调度中心历史可见，失败或结果不满意从那里接着聊 → 该通道即第一批的纠偏与重试机制，故不做自动失败重试（D4 / §15）
7. 待办来源只能是一次性任务，不加周期属性 → 保住待办的"完成"语义，例行工作走对话直接建周期任务（D6）
