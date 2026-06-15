# Phase 1 Data Model: 结构化多选澄清

> 全部为**内存态**结构（sidecar 进程内），无任何 SQLite/DuckDB 持久化、无迁移。重启即失效。

## 后端内存实体（`clarification_manager.py`）

### PendingClarification

一次澄清请求的权威内存记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `request_id` | str | 后端生成（`clr_<uuid12>`），全局唯一 |
| `session_id` | str | 归属 Assistant 会话（取 `run_context.get_current().root_session_id`） |
| `questions` | list[NormalizedQuestion] | 后端规范化后的问题（含稳定 ID） |
| `created_at` | float | `time.monotonic()`，用于超时与 `expiresAt` 计算 |
| `event` | threading.Event | worker 阻塞/唤醒原语 |
| `status` | str | `pending`→终态之一 |
| `answers` | list[ResolvedAnswer] \| None | 仅 `answered` 时有值 |

**status 状态机**（单向，first-decision-wins；任一终态 set event 一次）：

```
pending ──submit──▶ answered
        ──cancel──▶ cancelled
        ──timeout─▶ timeout      (event.wait 超时)
        ──stop────▶ stopped      (用户停止当前回合)
        ──shutdown▶ shutdown     (应用关闭)
（signal 未注册时 handler 直接返回 unavailable，不创建 pending）
```

不变量：
- 同一 `session_id` 同时最多一个非终态 `PendingClarification`（Assumption / 单 pending）。
- 进入终态后 `event` 必被 set；重复决策因 `event.is_set()` 守门被幂等忽略。

### NormalizedQuestion

| 字段 | 类型 | 约束 |
|------|------|------|
| `question_id` | str | 后端生成 `q{i+1}` |
| `question` | str | 必填，非空；批次内不得重复 |
| `header` | str | 必填，短标题（建议 ≤ 12 字符，仅校验非空） |
| `multi_select` | bool | 默认 false |
| `options` | list[NormalizedOption] | 2–4 个 |

### NormalizedOption

| 字段 | 类型 | 约束 |
|------|------|------|
| `option_id` | str | 后端生成 `q{i+1}o{j+1}` |
| `label` | str | 必填，非空；同题内不得重复 |
| `description` | str \| None | 可选说明 |
| `preview` | str \| None | 可选**纯文本**预览（前端不渲染 HTML/Markdown） |

### ResolvedAnswer（结果侧，进入 tool result / 不进事件）

| 字段 | 类型 | 说明 |
|------|------|------|
| `question` | str | 原问题文本（便于模型理解） |
| `selected_labels` | list[str] | 用户所选选项标签（单选至多 1 个；可为空当仅填"其他"） |
| `other_text` | str \| None | "其他"自由输入（≤ 1000 字符） |

## 工具输入契约（模型 → `ask_user_question`）

```jsonc
{
  "questions": [
    {
      "question": "选择执行方式？",          // 必填
      "header": "执行方式",                   // 必填
      "multiSelect": false,                   // 可选，默认 false
      "options": [                            // 2–4 个
        { "label": "按顺序执行",
          "description": "稳，逐步可控",       // 可选
          "preview": "step1 → step2" }        // 可选纯文本
      ]
    }
  ]
}
```

**输入校验（handler 内，失败返回 `error_json`，不创建 pending）**：
- `questions` 长度 1–4；每题 `options` 长度 2–4。
- `question` / `header` / 每个 `label` 必填非空。
- 批次内 `question` 文本不得重复；同题内 `label` 不得重复。
- 模型若提供 ID 一律忽略，由后端重新生成。

## 工具输出契约（`ask_user_question` → tool result，进入上下文）

```jsonc
{
  "status": "answered",         // answered|cancelled|timeout|stopped|shutdown|unavailable
  "answers": [                  // 仅 answered 时非空
    { "question": "选择执行方式？",
      "selectedLabels": ["按顺序执行"],
      "otherText": null }
  ]
}
```

## 决策提交契约（API → manager）

```jsonc
{
  "decision": "submit",         // submit|cancel
  "answers": [                  // cancel 时为空
    { "questionId": "q1",
      "selectedOptionIds": ["q1o1"],   // 单选至多 1；可为空当仅填 otherText
      "otherText": null }              // ≤ 1000 字符
  ]
}
```

**决策校验**：
- 会话归属：`request_id` 必属于 `session_id`，否则拒绝。
- 已结算请求（含过期/重复）→ 幂等拒绝，不改终态。
- `submit` 时每题必须有答案：单选题恰好一个 `selectedOptionId` **或**一段 `otherText`（二选一，不可空）；多选题可组合选项与 `otherText`，但不可全空。
- `otherText` ≤ 1000 字符。
- 校验失败 → 返回错误且**不结算**（前端保留卡片可重试）。

## 公开事件 payload（详见 contracts/events_clarification.md）

- `assistant.clarification_requested`：`requestId / sessionId / questions(含选项, 不含答案) / expiresAt / status=pending`
- `assistant.clarification_resolved`：`requestId / sessionId / status(终态)`，**不含任何用户答案**

## 前端内存状态（`assistantStore`，按 session）

| 字段 | 类型 | 说明 |
|------|------|------|
| `pendingClarification` | by sessionId → ClarificationRequestDTO \| null | 当前会话待答卡片 |
| `clarificationDrafts` | by sessionId → { [questionId]: { optionIds:Set, otherText:string } } | 未提交草稿，切换会话保留 |
| `clarificationSubmitting` | by sessionId → bool | 提交期间禁用全部控件 |

resolved 事件 / 提交成功 → 清理该 request 的 pending 与草稿。
