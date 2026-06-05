# Contract: UI Events（公开 UI 事件契约）

面向前端的事件 MUST 经 `src/desktop_api/ui_events.py` 的 **UI Event Registry** 注册，并由 `ui_event_projector.py` 从 blinker 内部事件投影为 typed envelope（含 `eventId/sequence/sessionId/causationId/type/scope/payload/createdAt`）。前端只消费注册过的 type；缺口/会话不匹配走 `backend.resync_required` 拉权威快照。

---

## 新增内部 blinker 事件（`src/utils/events.py`）

| 事件名 | 发出方 | 关键 payload |
|--------|--------|--------------|
| `assistant_agent_step` | `AgentLoop`（best-effort）| `session_id`(=root)、`subagent_id?`、`agent_type`、`kind`∈{reasoning,tool_call,tool_result}、`tool_name?`、`text`(截断)、`seq` |
| `assistant_subagent_started` | `orchestrator` 委派点 | `session_id`(=parent)、`subagent_id`、`label`、`task`、`status="running"` |
| `assistant_subagent_finished` | `orchestrator` | `session_id`、`subagent_id`、`status`∈{done,failed}、`last_output?` |
| `assistant_subagent_paused` | `orchestrator`（取消/暂停时）| `session_id`、`subagent_id`、`status="suspended"`、`reason?` |

> 投影时按 `agent_type` 过滤：仅 `assistant`/`ephemeral_subagent`/`specialist` 产生 `assistant.activity`，其余返回空（保证非助理流程零 UI 噪声）。

## 新增/变更 公开 UI 事件（Registry）

### `assistant.activity`（新）
- **scope**: `{ sessionId }`（= 父助理会话；子任务步骤亦落于此）
- **payload allowlist**: `subagentId`(可空), `kind`, `toolName`, `text`, `seq`
- **用途**: 主助理与子任务的逐步过程；前端按 `subagentId` 归类（null=主时间线，非空=对应卡片）

### `assistant.subagent`（新）
- **scope**: `{ sessionId }`（= 父助理会话）
- **payload allowlist**: `subagentId`, `label`, `task`, `status`(running|done|suspended|failed), `lastOutput`, `reason`
- **用途**: 子任务卡片壳与状态

### `assistant.progress`（变更：新增取值 / 运行代际）
- **payload**: 既有 key `status/headline/message/question` 保留；运行中事件可带 `runId`（停止请求回传，绑定当前运行代际）；`status` **新增取值 `cancelled`**
- 前端 `AssistantProgress["status"]` 联合类型同步加 `"cancelled"`，并保存可选 `runId`

---

## 约束

- payload MUST 走 009 既有 payload safety allowlist 脱敏（不仅 `_safe_text`/`_safe_short_text` 截断），防工具入参/结果夹带敏感数据；普通文案不含内部术语（过程区为受控透明例外，可原样显示工具名等）。
- `AgentLoop` MUST 仅在 ContextVar（可观测运行）存在时 emit `assistant_agent_step`，避免对 PM/Programmer/Trial 白发；单回合活动事件设上限/合并，避免极端长回合刷爆前端 store。
- 前端 MUST NOT 依据内部 blinker 事件名或未注册 payload 决策；新展示先注册 type + allowlist。
- 断连/重开会话 MUST 以 `GET …/subagents` + `GET …/transcript` 权威快照刷新，而非依赖事件回放完整性。
