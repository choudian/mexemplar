# Tool Contract: `ask_user_question`

**作用域**：仅主助理（Assistant）。PM / Programmer / Trial / specialist / subagent 不暴露。
**类别**：`requires_exclusive_call=True`、`is_interrupting=False`、`has_side_effects=True`、`is_concurrency_safe=False`。
**行为**：handler 阻塞等待用户决策（默认 5 分钟），返回 `str` 结果后 AgentLoop 在同一 loop 内继续。

## Schema（function-calling）

```jsonc
{
  "name": "ask_user_question",
  "description": "在关键决策无法可靠推断时，向用户提出 1-4 道结构化问题（每题 2-4 个选项，单选或多选，始终可填\"其他\"）。仅用于关键岔路口；关联问题一次问齐；不得询问或展示任何密钥/令牌等敏感信息。取消或超时后不得在同一回合重复追问或基于猜测继续执行。",
  "parameters": {
    "type": "object",
    "properties": {
      "questions": {
        "type": "array",
        "minItems": 1, "maxItems": 4,
        "items": {
          "type": "object",
          "properties": {
            "question": { "type": "string", "description": "完整问题文本" },
            "header":   { "type": "string", "description": "短标题（建议 ≤12 字符）" },
            "multiSelect": { "type": "boolean", "description": "true 为多选，默认 false 单选" },
            "options": {
              "type": "array", "minItems": 2, "maxItems": 4,
              "items": {
                "type": "object",
                "properties": {
                  "label":       { "type": "string" },
                  "description": { "type": "string" },
                  "preview":     { "type": "string", "description": "纯文本预览，前端不渲染 HTML/Markdown" }
                },
                "required": ["label"]
              }
            }
          },
          "required": ["question", "header", "options"]
        }
      }
    },
    "required": ["questions"]
  }
}
```

## 输入校验（失败返回 `error_json`，不创建 pending）

| 规则 | 违反返回 |
|------|----------|
| `questions` 1–4 个 | `error_json("问题数量必须为 1-4 个")` |
| 每题 `options` 2–4 个 | `error_json("每题选项必须为 2-4 个")` |
| `question`/`header`/`label` 非空 | `error_json("问题文本/标题/选项标签不能为空")` |
| 批次内 `question` 不重复 | `error_json("同一批次问题文本不得重复")` |
| 同题 `label` 不重复 | `error_json("同一问题选项标签不得重复")` |

校验通过后：后端生成 `questionId=q{i+1}`、`optionId=q{i+1}o{j+1}`，忽略模型 ID。

## 输出（tool result string，JSON）

```jsonc
{ "status": "answered",
  "answers": [ { "question": "...", "selectedLabels": ["..."], "otherText": null } ] }
```

| status | 触发 | answers |
|--------|------|---------|
| `answered` | 用户提交有效答案 | 非空 |
| `cancelled` | 用户"暂不回答" | `[]` |
| `timeout` | 5 分钟无操作 | `[]` |
| `stopped` | 用户停止当前回合 | `[]` |
| `shutdown` | 应用关闭 | `[]` |
| `unavailable` | clarification signal 未注册 | `[]` |

## AgentLoop 配对规则

- **solo**：正常阻塞执行，结果 `_persist_tool_result` 写入，loop 继续。
- **与其他工具同批**（`batch_size>1` 且本工具在批内）：批内**所有** call 写 `invalid_model_output`，零执行，loop 继续（提示模型单独调用）。
