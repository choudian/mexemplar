# Tool Contract: `wait_for_process_event`

> Agent 工具契约。subagent / specialist 可调用;主助理(Assistant)不暴露该工具。

## Description (供 LLM 阅读)

阻塞等待一个由本会话起的后台子进程上发生新事件,或直到超时。事件是粗粒度信号——状态边界、累积输出阈值通告、长时间静默——本身**不携带** stdout / stderr 原文。需要读取实际日志请配合 `process_logs`,需要状态快照请配合 `process_poll`。

设计上替代"循环 poll":第一次调用通常不传 `sinceCursor`,服务端会返回到目前为止所有未消费事件和下一次该用的 cursor;之后每次调用都用上次响应里的 `cursor` 作为本次的 `sinceCursor`。

## Input

```jsonc
{
  "processId": "proc_xxx",       // 必填:此前 process_start 返回的进程标识
  "sinceCursor": 12,             // 可选:上次响应里的 cursor 值;首次调用省略
  "timeoutMs": 30000             // 可选:最长等待时间,默认 30000,上限 600000
}
```

### Constraints

- `processId` 不存在 / 不属于本会话 → 错误返回(见 Error 节)。
- `sinceCursor` 必须为非负整数;未传等价 0。
- `timeoutMs` 钳位到 `[1, agent_tools.process.max_timeout_ms]`(沿用 `process_wait` 上下限);默认走 `agent_tools.process.default_timeout_ms`。

### 是否 concurrency-safe

否(`is_concurrency_safe=False`)。沿用既有 `process_*` 工具组的统一约束。

## Output (success)

`success_json("wait_for_process_event", data)`,`data` schema:

```jsonc
{
  "processId": "proc_xxx",
  "events": [                              // 按 sequence 升序;空列表代表超时无事件
    {
      "sequence": 13,
      "type": "log_chunked",
      "totalChars": 8192,
      "deltaChars": 4096
    },
    {
      "sequence": 14,
      "type": "stalled",
      "idleMs": 10247
    },
    {
      "sequence": 15,
      "type": "state_changed",
      "status": "failed",
      "exitCode": 1
    }
  ],
  "cursor": 15,                            // 调用方下次的 sinceCursor
  "status": "failed",                      // 当前进程状态
  "exitCode": 1,                           // 当前 exit code,无则 null
  "cursorTooOld": false                    // since_cursor 早于队列最旧 sequence 时为 true
}
```

### Output 不变量

- `events` 按 `sequence` 严格升序;每条 sequence > `sinceCursor`。
- 当 `cursorTooOld == true`:`events` 可能为空也可能非空;无论哪种,`cursor` 字段**始终**返回,值取队列最新事件 sequence;空队列时取该进程当前 `event_sequence` 计数器值(语义即"没有任何更新的事件,在我之前发生过的所有事件你都不要")。subagent 直接用该 `cursor` 续 wait,不必切换 process_poll + process_logs 兜底。
- 超时返回(无新事件)是**成功路径**,不是错误;`events == []`,`status` + `cursor` 仍有效。

### 不可见信息

事件 payload 中**不**出现:stdout / stderr 原文、命令字符串、cwd、env、PID、secret、文件路径。

## Output (error)

`error_json("wait_for_process_event", code, message, outcome="rejected", payload={"processId": ...})`。

| code | 触发场景 |
|---|---|
| `process_missing` | `processId` 在 ProcessManager 中不存在(从未创建 / 已被 cleanup / sidecar 重启后) |
| `permission_denied` | `processId` 属于其他会话(跨会话归属校验失败);**不**泄露该进程是否存在 |
| `internal_error` | `ProcessManager.wait_for_event` 抛任何未捕获异常 → logger.warning + `error_json` 返回(沿用 `builtin_contracts.ERROR_CODES` 注册表中的通用 `internal_error`,与既有 process_stop / process_send_input 内部异常映射一致) |

错误返回**不**阻塞工具管线;失败不级联到其它工具调用。

## 行为契约

| 编号 | 行为 |
|---|---|
| B1 | 首次调用且 deque 中已有事件:**立即**返回所有事件 + 当前状态(不等 timeout) |
| B2 | deque 中无大于 sinceCursor 的事件:在 `event_condition` 上阻塞等;新事件 emit 时 notify_all 触发返回;timeout 到则返回空 events + 当前状态 |
| B3 | 调用入口处懒判定 stalled:在 lock 持有期间,若 status==running 且 `now - last_output_at ≥ stalled_threshold_ms` 且 `last_stalled_announce_output_at != last_output_at`,则先 append 一条 stalled,再判定 B1 / B2 |
| B4 | `_refresh_locked` 检测到 status 从 running 切到终态时 append `state_changed` + notify_all |
| B5 | `_start_reader.reader` 在 chunk 入队后累加 `total_output_chars` 并更新 `last_output_at`;若 `total_output_chars - last_chunk_announce ≥ chunk_threshold_chars`,append `log_chunked` + notify_all + 更新 `last_chunk_announce` |
| B6 | 环形 buffer 满后 append 旧事件被丢弃;`event_sequence` 仍单调推进;再次有 sinceCursor 落在被丢弃区段时,返回 `cursorTooOld=true` 路径 |
| B7 | timeoutMs 超出 `[1, max_timeout_ms]` 时被钳位,**不**报错 |
| B8 | sidecar 重启后旧 processId 一律走 `process_missing`(事件不持久化) |

## 与既有工具的协同

| 既有工具 | 协同关系 |
|---|---|
| `process_start` | 返回 processId;新建 record 时事件 deque + sequence 立即可用 |
| `process_poll` | 不变;subagent 可在 `wait_for_process_event` 之外随时调用,典型用于 cursorTooOld 之后的状态再确认 |
| `process_logs` | 不变;`log_chunked` 信号只告诉 subagent "有新内容可读",原文一律从 `process_logs` 取 |
| `process_wait` | 不变;`process_wait` 仍可作为"只等终态"的更狭窄场景使用;`wait_for_process_event` 更通用 |
| `process_stop` | 不变;terminate 路径也会经过 `_refresh_locked`/explicit emit,触发一条 `state_changed: terminated` |
| `process_send_input` / `process_close` | 不变,与事件机制无直接交互 |

## 安全 / 隐私

- 归属校验 100% 复用既有 `_process_for_current_session`;无新分支。
- 错误码不区分"进程不存在"与"进程属其它会话"的内部细节(`permission_denied` vs. `process_missing`,与既有 process 工具语义一致)。
- payload 不含 stdout/stderr 原文、命令字符串、cwd、secret、文件路径,因此事件流即使在调用方上下文里被序列化也不泄漏敏感信息。
- 不进 UI Event Registry;前端无可见性,亦无 SSE 暴露面。

## 演进策略

任何变更必须满足:
- 新增事件 type:必须先在 spec 增加 FR + clarify;现有 type 与 payload 字段语义不可破坏。
- 改 `cursor` 语义(例如改成时间戳):违背 R-003,需要新的 clarify 会话。
- 让主助理订阅或前端订阅:违反 FR-011 / CC-002 / 100% 调度模型,需要 constitution-level 讨论。
