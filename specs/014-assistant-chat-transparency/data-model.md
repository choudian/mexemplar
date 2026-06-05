# Phase 1 Data Model: 主助理对话透明与可控

本特性**不新增任何持久化存储**（无 SQLite 表/迁移、不触 DuckDB）。下列为**运行时/前端 UI 实体**与**状态机**；历史过程由既有 `MessageRepository` / `WorkflowTransitionRepository` / `SessionRepository` 只读重建。

---

## 1. 运行状态 / Progress（前端 + `assistant.progress` 事件）

| 取值 | 含义 | 输入门控 | 排队自动派发 |
|------|------|----------|--------------|
| `idle` | 空闲 | 可输入、可发送 | — |
| `running` | 正在处理 | **门控**（不可发新消息；输入即排队）| 否 |
| `waiting_for_user` | 助理反问、等回答 | 可输入、可发送 | **是**（离开 running） |
| `succeeded` | 回合完成 | 可输入、可发送 | **是**（离开 running） |
| `failed` | 回合失败 | 可输入、可发送 | **否**（排队退回草稿）|
| `cancelled` | 用户已停止（**新增**）| 可输入、可发送 | **否**（排队已退回草稿） |

- 状态转移：`idle/cancelled/succeeded/failed/waiting_for_user --发送--> running`；`running --完成--> succeeded`；`running --反问--> waiting_for_user`；`running --停止--> cancelled`；`running --出错--> failed`。
- 由后端 `assistant.progress` 事件驱动（payload: `status`, `headline`, 可选 `message`/`question`）。

## 2. 回合 / Turn（前端展示单元）

| 字段 | 说明 |
|------|------|
| `id` | 回合标识 |
| `user` | 用户消息（纯文本展示）|
| `steps[]` | 主助理活动步骤（`subagentId == null`）|
| `subagents[]` | 本回合派出的子任务 |
| `reply?` | 最终回复（SafeMarkdown 正常展示，不进时间线）|
| `status` | 该回合状态（running/succeeded/failed/cancelled）|

## 3. 活动步骤 / Activity Step（`assistant.activity` 事件 + 时间线项）

| 字段 | 说明 |
|------|------|
| `id` / `seq` | 标识与排序（用于主步骤与子任务卡片按序交织）|
| `kind` | `reasoning` / `tool_call` / `tool_result` |
| `toolName?` | 工具名（kind=tool_call/result 时）|
| `text` | 可读文本（已截断；不暴露内部术语）|
| `subagentId?` | 归属：`null`=主助理；非空=某子任务（前端据此归类到卡片）|

- 仅由**带工具调用的中间步骤**与 **tool 结果**产生；最终回复不在此列。`kind=reasoning` 为**随该带工具调用中间消息一同落库的推理文本**（故历史可由 `MessageRepository` 重建），不单独 emit 不落库的纯推理步骤——保证实时时间线与历史回看口径一致（E4）。

## 4. 子任务 / Subagent Task（`assistant.subagent` 事件 + 卡片，权威态走 `GET …/subagents`）

| 字段 | 说明 |
|------|------|
| `subagentId` | 子任务标识（= 子会话 id）|
| `label` | 展示名（如"子助手 · 资料检索"）|
| `task` | 任务描述 |
| `status` | `running` / `done` / `suspended` / `failed` |
| `output?` | 产出摘要 |
| `steps[]` | 自身过程（Activity Step，含工具）——双击详情/transcript 提供 |

- 状态转移：`running --完成--> done`；`running --用户停止--> suspended`；`running --错误--> failed`；`suspended --继续任务--> running`（经主助理）。
- 归属：仅属于发起它的父会话；归属校验复用既有 `_resolve_subagent_session`。

## 5. 排队消息 / Queued Message（前端临时状态，按会话）

| 字段 | 说明 |
|------|------|
| `text` | 待发文本 |
| `state` | `editing`（编辑中，不外发）/ `queued`（已提交，待发）|
| 归属 | 按 `sessionId` 各存一份；跨会话切换保留；不持久化到后端，关闭应用即丢 |

- 状态机：`(running 时输入) → editing --回车/失焦--> queued --双击--> editing`；`queued --回合离开 running--> 自动派发`；`任意 --停止--> 退回普通草稿（清 state）`。
- 不变量：每会话最多一条；编辑态绝不自动外发。

## 6. 取消注册表 / Cancellation Registry（后端业务层，进程内内存）

| 元素 | 说明 |
|------|------|
| ContextVar | 持 `{root_session_id, cancel_event}`；worker 线程入口 `begin` 设置、`end` 清理；同步子 loop 自动继承 |
| `session_id → threading.Event` 表 | 停止端点按会话查找并 `set`；`AgentLoop` 经 ContextVar 读取并在安全节点检查 |

- 纯内存、会话级；不写配置/keyring/SQLite/DuckDB（符合"免确认/会话级状态"同类纪律）。

---

### 后端只读数据来源（无写入新结构）

- `MessageRepository`：中间 assistant 消息（含 `tool_calls`）与 tool 结果 → 重建主助理/子任务过程时间线（历史与 transcript）。
- `WorkflowTransitionRepository`：`assistant_delegation_started/completed/failed/paused` 流转 → 重建子任务权威列表与状态。
- `SessionRepository`：子会话状态（active/suspended/...）→ 子任务状态与"继续任务"可用性判定。
