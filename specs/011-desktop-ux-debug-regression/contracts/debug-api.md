# Contract: Local Debug Inspector API

## Boundary

所有端点挂在现有 FastAPI sidecar 下，统一前缀 `/api/debug`。前端隐藏诊断入口为直接访问 route `/debug`，不得出现在普通导航或 NavRail 数据源中。该 API 分为 control 端点和 raw data 端点：

- 所有请求首先受现有 `X-Mexemplar-Session` middleware 保护；无效 token 返回现有 `401 desktop_api_unauthorized`。
- 通过 session 鉴权后，`/api/debug/control` 即使 tracing 未武装也可返回安全状态和警示文案，但不返回 raw 内容。
- 通过 session 鉴权后，若 `debug.trace.enabled` 未武装，所有 `/api/debug/traces*`、`/api/debug/flows*` 与 `/api/debug/references/*` raw data 端点返回 `404` 与 `debug_disabled`。
- Debug 页面不得列入普通 `NavRail`；它仅供直接访问 `/debug` 进入。
- API 只调用 `DebugInspectorService`；router 不直接读取 Repository、keyring、config 文件或 reference 存储。
- Debug raw detail 不投影到 `/api/events` 公共事件流；既有用户可见产品输出（如 `assistant.message.content`）不属于新增 debug raw detail。
- 所有受支持的 text/tool/vision LLM 请求（包含 vision/multimodal helper）必须经过统一 observation boundary；受支持路径不得以 direct provider invoke 绕开 trace gate。Embedding/vectorization calls are out of trace-record scope for this feature, but their credentials and callsites must be registered in the redaction/real-tour inventory or an explicit allowlist.
- Observation boundary 必须 fail isolated：capture、redaction、correlation 或 buffer 写入异常不得改变底层 provider 请求、返回值或原 provider 失败语义。
- ordinary application logs 不构成诊断输出渠道，不得记录 raw prompt/response/tool arguments/handoff text 或 secret/token。
- 所有返回 raw trace、flow detail 或 reference content 的响应必须设置防缓存响应头，至少包含 `Cache-Control: no-store`；前端不得把 raw debug 内容放入 URL、query/hash、localStorage、sessionStorage、persisted Zustand 或其它可跨 clear/disable/restart 保留的存储。

## Trace Control

- `debug.trace.enabled` 是当前 sidecar 进程内的 runtime-only unified-config arm，默认 `false`，不得由普通 Settings 页面或持久配置保存启用状态。
- Hidden DebugScreen 在未武装时只显示警示、状态和启用控件；启用动作必须带有 warning acknowledgement。警示文案至少说明 raw 用户/模型文本可能被保留、开发者自行输入的秘密不会被启发式清除、stop/clear/restart 会销毁当前 epoch、armed 期间应用壳保持可见停止入口。
- 启用成功创建新的 epoch；禁用、清空或 sidecar 重启必须使当前 epoch 失效并 purge trace、ephemeral flow detail 与 correlation。
- App shell 必须在 armed 状态持续显示 trace-active indicator 和 stop action；stop action 调用同一 control facade 禁用 tracing。
- Control state 可进入前端 UI state，但不得进入公共 SSE replay 或普通 Settings persistence。

## Redaction And Lifetime

- 实际 textual user/model 内容可显示，但在写入 trace buffer 前和返回 DTO 前均必须替换主模型、vision、embedding credential、sidecar runtime token 及应用控制的 authorization material。Trace buffer 不得保存 pre-redaction payload；retained byte accounting 以 redacted retained payload 为准。
- Redactor 的 secret inventory 来自实际模型/runtime factory 注册的 credential/token snapshot；不得为脱敏调用会触发 plaintext fallback 或 keyring migration 的普通 getter。运行期间注册新模型客户端或 credential 轮换时，新旧已注册 sentinel 都必须继续被屏蔽，且注册过程不得调用有迁移副作用的 getter。
- Multimodal trace 只能返回文本 block 与媒体安全元数据（如类型、数量、字节数）；不得保存或返回 restorable image bytes、base64 data URL 或等价原始媒体内容。
- 页面必须在 arm 前展示“不要在 traced 对话粘贴自行管理的敏感内容”的警示，armed 期间页面和应用壳均必须保持明确的捕获中状态。
- `LLMTraceRecord`、ephemeral flow detail 与 trace correlation 在当前 enabled tracing epoch 中按记录数、单条 bytes 与聚合 bytes 有界保存；`DELETE /api/debug/traces`、关闭 trace 或重启后不可再次读取。
- Trace 从 enabled 变为 disabled 时必须先原子失效当前 epoch，使旧 epoch 不可读不可写，再 best-effort purge ephemeral 内容；随后重新开启产生空的新 epoch。旧 epoch 中仍在执行的调用完成时不得写入新缓存。若 purge/cleanup 抛错，API 可返回安全错误或 disabled 状态，但旧 raw 数据仍不可读取。
- 超出单条保留预算的请求必须返回带 `detailAvailability: "oversized_omitted"` 的安全记录而非静默消失；诊断旁路故障可返回 `detailAvailability: "diagnostic_unavailable"`；聚合预算超限按最旧优先淘汰。
- 现有 `workflow_transitions` 的业务事实可按原生命周期读取，但返回 payload 仍经过脱敏并标记 `persisted_transition`；仅为查看 Assistant delegated task/result 新捕获的详情必须标记 `ephemeral_debug_capture` 且不得写入 durable raw diagnostic/correlation。
- 前端 DebugScreen 只能将 raw detail 保存在当前页面内存状态中；disable、clear、离开 `/debug` 或 sidecar auth 失效时必须清除本地 raw detail cache。

## Endpoints

### `GET /api/debug/control`

返回当前 sidecar 的安全 control 状态，不包含 raw trace detail。

Response:

```json
{
  "enabled": false,
  "armedAt": null,
  "retentionEpoch": null,
  "warning": "调试记录可能包含原始用户文本，请勿在 traced 对话中输入自行管理的秘密。",
  "limits": {
    "maxRecords": 200,
    "maxRecordBytes": 1048576,
    "maxTotalBytes": 16777216
  }
}
```

### `PUT /api/debug/control`

Request:

```json
{
  "enabled": true,
  "warningAcknowledged": true
}
```

Rules:

- `enabled=true` requires `warningAcknowledged=true`; otherwise return `422 debug_warning_required`.
- `enabled=true` creates an empty new epoch if currently disabled; repeated enable returns current armed state without exposing raw data.
- `enabled=false` first invalidates the current epoch for reads/writes, then best-effort purges trace, ephemeral flow detail and correlation; cleanup failure must not make old data readable.
- Both transitions must go through `UnifiedConfigManager.set("debug.trace.enabled", value, persist="runtime")` or an equivalent runtime-only unified-config facade so observers and purge semantics are testable.

Response uses the same shape as `GET /api/debug/control`.

### `GET /api/debug/traces`

Query:

| Name | Type | Meaning |
|------|------|---------|
| `source` | string optional | 来源过滤 |
| `agentType` | string optional | agent 类型过滤 |
| `sessionId` | string optional | session 过滤 |
| `workflowId` | string optional | workflow/delegation 过滤 |
| `limit` | integer, `1..200` | 默认 `50` |

Response:

```json
{
  "items": [
    {
      "traceId": "trace_a1",
      "method": "chat_with_tools",
      "source": "agent_loop",
      "agentType": "assistant",
      "sessionId": "ast_1",
      "workflowId": null,
      "workUnitId": null,
      "iteration": 3,
      "outcome": "succeeded",
      "detailAvailability": "full_text",
      "retainedBytes": 812,
      "createdAt": "2026-05-24T10:00:00Z",
      "completedAt": "2026-05-24T10:00:01Z",
      "summary": "tool_calls: delegate_to_subagent",
      "linkedTransitionIds": []
    }
  ],
  "retainedBytes": 812,
  "omittedCount": 0,
  "warning": "调试记录可能包含原始用户文本，请勿在 traced 对话中输入自行管理的秘密。"
}
```

列表返回定位所需摘要，不必重复完整 raw messages。

### `GET /api/debug/traces/{trace_id}`

Response:

```json
{
  "traceId": "trace_a1",
  "method": "chat_with_tools",
  "source": "agent_loop",
  "agentType": "assistant",
  "sessionId": "ast_1",
  "workflowId": "delegate_ast_1_001",
  "iteration": 3,
  "inputMessages": [{ "role": "user", "content": "..." }],
  "inputMedia": [],
  "inputTools": [{ "type": "function", "function": { "name": "delegate_to_subagent" } }],
  "outputContent": null,
  "outputToolCalls": [{ "name": "delegate_to_subagent", "args": { "task_description": "..." } }],
  "outcome": "succeeded",
  "errorSummary": null,
  "detailAvailability": "full_text",
  "retainedBytes": 812,
  "linkedTransitionIds": ["trans_1"],
  "createdAt": "2026-05-24T10:00:00Z",
  "completedAt": "2026-05-24T10:00:01Z"
}
```

Unknown source 必须返回 `"source": "unknown"`，不能静默过滤。视觉记录使用 `"method": "multimodal"` 和 `inputMedia` 元数据；预算不足的详情使用 `"detailAvailability": "oversized_omitted"` 并保留来源、结果/失败状态和安全摘要；诊断旁路失败使用 `"detailAvailability": "diagnostic_unavailable"` 且不得替换原模型结果。

### `DELETE /api/debug/traces`

清空本进程当前 epoch 捕获的 trace、ephemeral flow detail 与 debug-only correlation。该操作必须先使当前 epoch 对读写失效，再执行 best-effort cleanup；cleanup 异常不能让旧 raw 数据重新可见。该操作不删除或修改现有 persisted `workflow_transitions`。

Response: `204 No Content`

### `GET /api/debug/flows`

Query:

| Name | Type | Meaning |
|------|------|---------|
| `workflowId` | string optional | 精确筛选 Teaching/delegation flow |
| `sessionId` | string optional | 关联 session 筛选 |
| `limit` | integer, `1..100` | 最近 flow 摘要数量 |

Response:

```json
{
  "items": [
    {
      "workflowId": "wf_1",
      "transitionCount": 4,
      "lastEventType": "tool_saved",
      "lastCreatedAt": "2026-05-24T10:01:00Z",
      "linkedTraceCount": 3
    }
  ]
}
```

### `GET /api/debug/flows/{workflow_id}`

按 `created_at` 正序返回已有权威 transitions，并在当前 enabled epoch 可用时附上 trace link 与 ephemeral detail：

```json
{
  "workflowId": "wf_1",
  "transitions": [
    {
      "transitionId": "trans_1",
      "eventType": "requirement_confirmed",
      "status": "handoff",
      "fromSession": { "sessionId": "pm_1", "agentType": "pm" },
      "toSession": { "sessionId": "prog_1", "agentType": "programmer" },
      "reason": null,
      "detail": { "requirements": { "goal": "..." } },
      "detailProvenance": "persisted_transition",
      "detailAvailability": "full_text",
      "traceIds": ["trace_1"],
      "linkStatus": "linked",
      "createdAt": "2026-05-24T10:00:00Z"
    }
  ]
}
```

无关联 trace 的真实 transition 必须保留并标识 `"linkStatus": "unlinked"`。Assistant delegation 的 task/result 仅在当前 epoch 捕获成功时以 `"detailProvenance": "ephemeral_debug_capture"` 显示；该临时 detail 与 trace records 共用聚合 bytes 预算，超限时必须返回 `"detailAvailability": "oversized_omitted"` 而非展示空内容为完整结果。若无临时详情则保留 transition 并使用 `"detailProvenance": "unavailable"` 与 `"detailAvailability": "unavailable"`，不能假定持久 payload 含原文。

### `GET /api/debug/references/{reference_id}`

在同一 trace/auth gate 下读取任意当前仍可寻址的 existing reference，并返回脱敏原文。该端点必须受响应预算控制：默认一次最多返回实现配置的 reference bytes/characters，超过时返回截断标记或 chunk token，不得无界返回大型 reference。

```json
{
  "referenceId": "msg_123",
  "content": "...",
  "truncated": false,
  "nextChunk": null
}
```

Reference 不要求来自选中 trace；不存在或不可加载返回 `404 reference_not_found`。分块读取若实现为后续端点，仍必须使用同一 auth/trace/no-store/redaction 边界。

## Stable Errors

| HTTP | Code | Condition |
|------|------|-----------|
| `401` | `desktop_api_unauthorized` | 当前 sidecar token 不匹配 |
| `404` | `debug_disabled` | 调试开关关闭 |
| `404` | `trace_not_found` | 当前进程无该 trace 或已清空 |
| `404` | `reference_not_found` | reference 不存在/已不可寻址 |
| `422` | `debug_warning_required` | 尝试启用 trace 但未确认敏感内容警示 |
| `422` | `debug_query_invalid` | 查询参数不合法 |
| `413` | `reference_too_large` | 实现选择拒绝而非分块/截断返回超大 reference |

## Required Verification

- Disabled 状态不捕获、不读取 raw data、不显示隐藏页面 raw 内容；control API 只返回安全状态和 warning。
- Arm 必须要求 warning acknowledgement，且警示文案覆盖 raw 文本保留、自行输入秘密不启发式清除、stop/clear/restart 销毁 epoch、armed indicator 持续可见；armed 时 AppShell 显示持续 stop 控件；stop 后旧 epoch 立即不可读且重启后默认 disabled。
- `capture -> disable -> re-enable` 返回空的 ephemeral state；在 disable 前启动、disable 后完成的调用不回填记录。
- 主模型、vision、embedding credential 与 runtime token sentinel 字面值不会出现在 trace detail、flow detail、reference response、失败 response 或 captured ordinary logs；credential snapshot 轮换后新旧 sentinel 均不泄漏。
- Vision 调用进入 trace coverage，且 trace DTO/日志中没有 image data URL/base64/raw bytes；oversized request 提供明确 omission 标记并遵守 aggregate byte budget。
- Embedding/vectorization calls 不要求产生 trace records；但 embedding credential getter/client callsites 必须被 redaction/real-tour inventory 或静态 allowlist 覆盖。
- Observation failure injection：pre-call capture/redaction failure、post-call buffer failure 与 provider failure+diagnostic failure 均不改变原业务结果或原 provider failure 语义；disable/clear cleanup failure 后旧 epoch 仍不可读不可写。
- `ui_events.py` registry 与 ordinary SSE payload 不新增 diagnostic-only raw prompt/trace/handoff/media/correlation 字段；既有 `assistant.message.content` 继续作为用户可见产品消息存在。
- 现有 LLM/delegation 日志被移除或改为安全摘要；正常路径和 provider/vision/delegation 异常路径的日志捕获均验证无 raw prompt/response/tool args/handoff detail/secret。
- Raw debug endpoints 返回 `Cache-Control: no-store`；frontend storage scan 验证 raw prompt/trace/reference/handoff 内容未进入 URL、localStorage、sessionStorage 或 persisted stores；disable/clear/route leave 后本地 raw state 被 purge。
- Reference expansion 的超大响应路径返回明确 truncation/chunking/too-large diagnostic，并且不突破响应预算。
- 进程重启、clear 或 disable 后 raw trace/ephemeral detail 不可读取；已有业务 transition 可按既有生命周期显示并标记 provenance。
