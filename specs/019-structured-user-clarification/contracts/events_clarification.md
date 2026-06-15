# Event Contract: Clarification UI Events

注册在 `src/desktop_api/ui_events.py` 的 `UI_EVENT_REGISTRY`，类别 `interactive`，scope = `sessionId`。前端只消费已注册 type。

## `assistant.clarification_requested`

工具发起澄清时发出。

```jsonc
{
  "type": "assistant.clarification_requested",
  "scope": { "sessionId": "sess_1" },
  "payload": {
    "requestId": "clr_ab12cd34ef56",
    "sessionId": "sess_1",
    "questions": [
      { "questionId": "q1", "question": "选择执行方式？", "header": "执行方式",
        "multiSelect": false,
        "options": [
          { "optionId": "q1o1", "label": "按顺序执行", "description": "稳", "preview": null }
        ] }
    ],
    "expiresAt": "2026-06-15T08:05:00Z",
    "status": "pending"
  }
}
```

- `payload_keys`: `{requestId, sessionId, questions, expiresAt, status}`
- `required_payload_keys`: `{requestId, sessionId, questions, status}`
- `payload_enum_values`: `status ∈ {pending}`
- `required_scope_keys`: `{sessionId}`
- `questions` 嵌套结构经 `unsafe_public_ui_event_value_reason` **递归扫描**：命中密钥/traceback/本地 DB 路径等禁用值即拒绝发出（secret 防护）。不标记 `unredacted`。

## `assistant.clarification_resolved`

请求进入任一终态时发出。**绝不含用户答案**。

```jsonc
{
  "type": "assistant.clarification_resolved",
  "scope": { "sessionId": "sess_1" },
  "payload": { "requestId": "clr_ab12cd34ef56", "sessionId": "sess_1", "status": "answered" }
}
```

- `payload_keys`: `{requestId, sessionId, status}`
- `required_payload_keys`: `{requestId, sessionId, status}`
- `payload_enum_values`: `status ∈ {answered, cancelled, timeout, stopped, shutdown}`
- `required_scope_keys`: `{sessionId}`

## 生命周期与恢复

| 事件源 | requested | resolved |
|--------|-----------|----------|
| 工具发起 | ✅ | — |
| 用户提交/取消 | — | ✅（answered/cancelled） |
| 5 分钟超时 | — | ✅（timeout） |
| 停止当前回合 | — | ✅（stopped） |
| 应用关闭 | — | ✅（shutdown） |
| 普通 SSE 断线 | 不触发任何结算；重连经 replay 或 `GET pending` 恢复 | |

## 前端消费规则

- `requested` → upsert 当前会话 `pendingClarification`（非当前会话忽略展示，但状态可缓存）。
- `resolved` → 清理对应 `requestId` 的 pending + 草稿（以权威事件为准，不靠本地猜测）。
- `backend.resync_required` / 会话打开 → 调 `GET pending` 拉权威快照。
