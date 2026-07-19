# Contract: Public UI Events（UI Event Registry）

**注册位置** `src/desktop_api/ui_events.py`：type 常量加进 `:62-92`，`UiEventDefinition` 加进 `UI_EVENT_REGISTRY`，category ∈ `notification` / `interactive`。**emit 走 blinker→`ui_event_projector`→`publish_draft_nowait`**（不直接 `event_queue.publish_nowait`）。前端镜像 `frontend/src/api/uiEventTypes.ts`（type 常量 + handler domain + payload enums）+ `uiEventParser.ts` mapper + `AppShell.dispatchUiEvent` case + resync 分支。

> 会话关联事件（完成、需接管、确认卡）scope 用 `sessionId`（既有 key）；新增 scope 键须同步
> `_scope_from_payload`。`scheduled_task.changed` 不关联单一会话，是无 scope 的全局列表刷新事件。

## 1. `scheduled_task.completed`（notification）

run 静默且全成功时发。前端 → Toast（success tone）+ 桌面通知 + 历史刷新。

```jsonc
{
  "taskId": "sch_xxx",
  "taskTitle": "查竞品价格",
  "runId": "schr_xxx",
  "sessionId": "ast_xxx",
  "outcome": "succeeded",            // enum: succeeded | failed（合并到本事件，按 outcome 分流）
  "summary": "<最后一条 assistant 展示消息的确定性截取，advisory>",
  "failureReason": null              // outcome=failed 时填安全投影
}
```
`required_payload_keys = {taskId, runId, sessionId, outcome}`；`outcome` enum `{succeeded, failed}`；`unredacted_payload_keys = {taskTitle, summary}`（这些是用户可见安全文本）。

## 2. `scheduled_task.needs_takeover`（notification）

run 落 `waiting_for_user`（D10）时发。前端 → Toast（warning tone）+ 桌面通知 + 历史醒目标注。

```jsonc
{
  "taskId": "sch_xxx",
  "taskTitle": "...",
  "runId": "schr_xxx",
  "sessionId": "ast_xxx",
  "reason": "needs_user_input"       // enum: needs_user_input | failed_takeover
}
```
`required = {taskId, runId, sessionId, reason}`。

## 3. `scheduled_task.changed`（notification）

任务列表变更（创建/暂停/启用/删除/触发滚动）。前端 `scheduledStore` 刷新列表（防抖 `createDebouncedRefresh(300)`）。

```jsonc
{
  "taskId": "sch_xxx",
  "changeType": "created"             // enum: created | paused | resumed | deleted | fired | status_changed
}
```
`required = {taskId, changeType}`。`deleted` 时前端移除行（软删）。

## 4. `scheduling.confirmation_requested`（interactive）

主助理创建定时任务后弹确认卡（D12）。复用 019 `ClarificationCard` 视觉，**但经独立 manager + 独立事件**（不复用 `assistant.clarification_*`，见 `confirmation-and-unattended.md`）。

```jsonc
{
  "requestId": "scf_<hex12>",         // scheduling confirmation 前缀
  "sessionId": "ast_xxx",             // 触发创建的主助理会话（用户正在对话的那个）
  "draft": {
    "title": "查竞品价格",
    "scheduleDescription": "每天 早上 09:00",   // 人话，核对用
    "instruction": "<任务指令原文>",
    "scheduleKind": "recurring",
    "sourceType": "direct"
  },
  "unattendedAutoApprove": false,      // 默认不勾，附风险说明；卡片承载勾选
  "expiresAt": "<ISO>"                 // 后端算（now + 超时），first-decision-wins
}
```
`required = {requestId, sessionId, draft, expiresAt}`；`draft` 内各 key 必填；status enum `{pending}`（对齐 019 风格）。**payload 不携带已解析的 `next_fire_at` 明文**（防泄露内部计算细节，前端展示用 `scheduleDescription`）。

## 5. `scheduling.confirmation_resolved`（interactive）

确认卡结算。前端移除卡片。

```jsonc
{
  "requestId": "scf_xxx",
  "sessionId": "ast_xxx",
  "status": "confirmed"               // enum: confirmed | cancelled | timeout | stopped | shutdown
}
```
`required = {requestId, sessionId, status}`；**不带答案详情**（对齐 019 `clarification_resolved` 风格，防泄漏）。`timeout/stopped/cancelled` = fail-closed 不创建（FR-006）。

## 6. 完成判定的内部触发（非公开 UI 事件）

最终选择分立的 `scheduled_task.completed` / `scheduled_task.needs_takeover`，不注册
`scheduling.notification`。`RunCompletionMonitor` 的判定由两条内部路径触发：

- `AssistantRuntime` 在主助理普通回合 / reentry 回合退出 worker 注册表后直接调用
  `evaluate_session()`；返回需补充信息或明确失败时分别调用 `mark_waiting_user()` /
  `mark_failed()`。
- `task_collaboration.graph_scheduler` 在执行节点首次全终态时 emit 内部
  `graph_scheduler_terminal(graph_id, session_id, all_terminal, all_completed)`；
  monitor 还监听内部子任务完成 / root failure 活动事件，用同一静默门卫重评。
  “首次”只约束这条新增 observer event；不得用其进程内 claim 门控既有 root 收口或
  父侧 reentry。状态写入或 reentry sink 瞬时失败时，后续推进必须仍可重试。

任一路径都必须满足「无活跃 worker ∧ 无未消费回流 ∧ 图全终态」；图查询失败是未知，
fail-closed 延后重试，不能当作“无图且成功”。

run 业务终态先通过 Repository CAS 提交，随后投影 `scheduler_run_terminal`。v31 用
`terminal_event_delivered_at` 持久确认，并用单调 `terminal_event_version` 绑定每次进入
succeeded / failed / waiting_user 的事件代次；ack 必须同时匹配 run + version，旧投影不能
确认掉并发续跑后产生的新终态。emit / projector / event queue 任一异常都保留 NULL，
`RunCompletionMonitor.connect()` 与每轮 `SchedulerWorker` tick 有界补投。交付语义是
at-least-once；若公开事件已发布而确认写入前进程退出，重启补投可能产生重复提醒，但
不得为了追求 exactly-once 而先确认后发布并重新引入永久丢失窗口。

## 复用既有事件（不新增）

- `assistant.progress`：scheduled 会话仍正常发布当前主助理回合进度，但
  `RunCompletionMonitor` **不订阅公开 UI 事件**；业务终态以本契约 §6 的内部调用 /
  blinker 路径为准。
- `assistant.message`：scheduled 会话的 assistant 回复正常走此事件（`source='scheduled'` 的会话由调度中心历史消费，聊天屏按 source 排除）。

## Resync

`scheduledStore` 收到事件 payload 缺字段 → `markNeedsResync()` + 重拉
`GET /api/scheduled-tasks`（仿 `assistantTaskStore`）。列表与 pending 确认卡刷新都会在
保留旧快照、设置 `lastError + needsResync` 后向 AppShell 传播失败；AppShell 对整组
scheduling 权威快照统一做最多 3 次有界重试，任一部分仍失败就保持事件增量阻塞并把
backend 标为 degraded，不能把部分成功误当成已恢复。`backend.resync_required` 兜底。
