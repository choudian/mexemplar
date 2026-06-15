# API Contract: Clarifications

挂在既有 assistant router（`/api/assistant`），与 `confirmations/{request_id}/decision` 同级但独立。鉴权沿用 sidecar runtime token（`X-Mexemplar-Session`）。

## GET `/api/assistant/sessions/{sessionId}/clarifications/pending`

返回该会话当前 pending 澄清快照（重连 / 会话打开 / resync 兜底）。

**200 响应**：

```jsonc
{
  "clarification": {              // 无 pending 时为 null
    "requestId": "clr_ab12cd34ef56",
    "sessionId": "sess_1",
    "questions": [
      { "questionId": "q1", "question": "选择执行方式？", "header": "执行方式",
        "multiSelect": false,
        "options": [
          { "optionId": "q1o1", "label": "按顺序执行", "description": "稳", "preview": null },
          { "optionId": "q1o2", "label": "并行执行", "description": null, "preview": null }
        ] }
    ],
    "expiresAt": "2026-06-15T08:05:00Z",
    "status": "pending"
  }
}
```

- 快照**不含**任何用户答案或草稿（草稿是前端内存态）。
- 会话不存在或无 pending → `clarification: null`（不 404，便于前端统一处理）。

## POST `/api/assistant/sessions/{sessionId}/clarifications/{requestId}/decision`

提交或取消一组澄清。

**请求体**：

```jsonc
{
  "decision": "submit",          // submit | cancel
  "answers": [                   // cancel 时 [] 或省略
    { "questionId": "q1", "selectedOptionIds": ["q1o1"], "otherText": null }
  ]
}
```

**200 响应**：

```jsonc
{ "requestId": "clr_ab12cd34ef56", "status": "answered", "accepted": true }
```

| 情形 | accepted | status | HTTP |
|------|----------|--------|------|
| 有效 submit（首个决策） | true | `answered` | 200 |
| 有效 cancel（首个决策） | true | `cancelled` | 200 |
| 请求不属于该会话 | — | — | 404（不泄漏存在性） |
| 已结算 / 过期 / 重复提交 | false | 当前终态 | 200（幂等） |
| 校验失败（缺答/单选多选/otherText 超长） | — | — | 422（不结算，前端保留卡片） |

**决策校验**（对标 data-model.md）：
- 单选题：恰好一个 `selectedOptionId` 或一段非空 `otherText`（二选一）。
- 多选题：选项与 `otherText` 可组合，但不可全空。
- 每题必须有答案；`otherText` ≤ 1000 字符。
- `selectedOptionIds` 必须是该题合法 `optionId`。

## 错误映射

- 业务校验异常 → 422 + 用户向友好消息（不含 provider/stack/内部 ID）。
- 归属失败 → 404「clarification not found」。
- 其他异常 → 500 `{"error": "internal_error"}`。
