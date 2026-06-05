# Contract: HTTP Endpoints（sidecar bridge）

新增端点位于 `src/desktop_api/routers/assistant.py`，经 `AssistantRuntime` / 业务 facade 调用业务层；不直接访问 Repository 之外的存储。所有请求带 `X-Mexemplar-Session` runtime token（既有约定）。前端 typed client 在 `frontend/src/api/assistant.ts`。

---

## 1. 停止当前回合

```
POST /api/assistant/sessions/{sessionId}/stop
```

- **Request**: 可选 body `{ "runId": string }`；前端收到 `assistant.progress{status:"running", runId}` 后回传，后端只取消同一代运行。无 body 兼容旧客户端与早停竞态。
- **Response**: `{ "accepted": boolean }`
  - `accepted=true`：已对该会话发出取消信号（协作式，在下一安全节点生效）
  - `accepted=false`：该会话当前无运行中的回合
- **行为**: `AssistantRuntime.cancel_session(sessionId, runId?)` → 在取消注册表中按会话与可选运行代际 `set` Event。深度穿透由 ContextVar 在子 loop 生效。
- **前端**: `stopAssistantRun(sessionId, runId?)`；点击即时置忙，等待 `assistant.progress {status:"cancelled"}` 解锁。

## 2. 列出会话的子任务（权威列表）

```
GET /api/assistant/sessions/{sessionId}/subagents
```

- **Response**: `{ "items": Subagent[] }`，`Subagent = { subagentId, label, task, status, lastOutput? }`
  - `status ∈ {running, done, suspended, failed}`
- **行为**: 由 `WorkflowTransitionRepository`（委派流转）+ `SessionRepository`（子会话状态）重建；用于重连/重开会话兜底与卡片渲染。`lastOutput` 等文本字段 MUST 与实时事件一致走 009 payload safety allowlist 脱敏（不仅截断）。
- **前端**: `listSubagents(sessionId)`；收到 `backend.resync_required` 或打开会话时调用。

## 3. 取子任务/会话的过程时间线（含工具）

```
GET /api/assistant/sessions/{sessionId}/transcript?subagentId={id?}
```

- **Query**: `subagentId` 可选——给定则取该子任务自身过程，否则取主助理过程
- **Response**: `{ "steps": ActivityStep[] }`，`ActivityStep = { kind, toolName?, text, seq }`
  - `kind ∈ {reasoning, tool_call, tool_result}`
- **行为**: 由 `MessageRepository` 的中间 assistant（含 `tool_calls`）与 tool 结果消息重建；文本截断、不暴露内部术语，且 MUST 与实时事件一致**显式走 009 payload safety allowlist 脱敏**（不仅截断）。已被压缩/概要化、中间步骤不全的回合，重建结果 MUST 带"已压缩/步骤不全"标志供前端按规整概要渲染（不补充持久化）。
- **前端**: `getSubagentTranscript(sessionId, subagentId)`；双击卡片或展开历史回合时拉取。

---

## "继续任务" 不新增端点

"继续任务"复用既有助理消息派发：`POST /api/assistant/sessions/{sessionId}/messages`。body MUST 结构化携带目标子任务，避免只靠自然语言文本解析：

```json
{
  "content": "请继续把刚才暂停的子任务做完。补充说明：再补一句",
  "continueSubagent": {
    "subagentId": "sess_child_1",
    "supplemental": "再补一句"
  }
}
```

由主助理调既有 `continue_subagent` 续跑（守 100% 调度）。后端在派发前校验 `subagentId` 归属当前对话且状态为 suspended；派发后校验该子任务确实产生新的续跑/完成/暂停/失败流转，若主助理没有实际续跑该子任务，MUST 发出明确兜底提示而非静默无反应。

## 错误与约束

- 4xx 错误 MUST 翻译为用户可懂文案（前端层），不回传 stack trace / 内部 ID。
- 端点 MUST 经业务 facade；router 不直连 Repository 以外存储。
- token 不进日志、不作为 UI 文案。
