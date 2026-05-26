# Data Model: Desktop UX, Debug Inspector, and Grand Tour Acceptance

## Storage Impact

本 feature **不新增持久化业务表或 migration**。

- Composer 折叠状态是 React 内存状态，不进入 SQLite、DuckDB 或浏览器持久化。
- `debug.trace.enabled` 是 sidecar 当前进程的 runtime-only arm，由 authenticated debug control facade 通过 unified config runtime set 管理；sidecar 启动默认关闭，不写持久配置。
- LLM trace、debug-only handoff/result detail 与 trace correlation 是 sidecar 当前 tracing epoch 内按记录数和 bytes 有界的状态，禁写数据库、普通日志、SSE replay、HTTP/WebView cache、URL 和前端持久化 store；disable、clear、restart 或离开 debug route 时销毁。
- Agent Flow 读取现有 SQLite `workflow_transitions`、`sessions` 与必要的已有 payload；其原有生命周期不因 debug 功能改变。现有 Assistant delegation 未持久保存的 raw task/result 只能来自临时诊断捕获。
- Real Grand Tour 仅在临时 `EXEMPLAR_DATA_DIR` 内生成 SQLite/DuckDB/配置与录制产物；main/vision/background/settings validation/skill-composition/compression/embedding/redactor 所需 credential 仅经不会触发 plaintext fallback/migration/write/delete 的注入式只读 provider 解析，或在场景启动前明确跳过对应路径。

## Raw Diagnostic Lifecycle Matrix

| Diagnostic data | Source of truth | Retention | Excluded sinks |
|-----------------|-----------------|-----------|----------------|
| Text/model/tool trace detail | Unified model invocation observation boundary | Current enabled epoch, count/byte bounded | SQLite, DuckDB, ordinary logs, public SSE |
| Vision trace detail | Same boundary | Text blocks and media metadata only; no restorable bytes/data URLs | Same exclusions plus raw media buffer |
| Existing transition facts | Existing repository data | Existing business retention lifecycle | Not erased by debug clear |
| Assistant delegated task/result detail | Delegation boundary while tracing enabled | Current enabled epoch, count/byte bounded | Durable transition payload, logs, public SSE |
| Reference expansion body | Existing reference loader, on demand | Returned response only, response-size bounded or chunked; not automatically inserted into buffer | Logs, public SSE, HTTP/WebView cache, frontend persisted state |

既有产品事件内容不属于新增 diagnostic sink：`assistant.message.content` 可继续承载正常用户可见回复；不得新增进入 public SSE 的是 prompt trace、raw handoff/media/correlation 等诊断专属内容。Embedding/vectorization calls 不生成 `LLMTraceRecord`，但其 credential/callsite 必须出现在 redaction、real-tour provider 或静态 allowlist inventory 中。

## Composer Presentation State

### `LongPastePresentationState` (frontend-only)

| Field | Type | Rules |
|-------|------|-------|
| `collapsed` | `boolean` | 仅由 qualifying paste 或用户“收起/展开”操作改变；初始 `false` |
| `qualified` | `boolean` | 最近草稿是否曾由 qualifying paste 进入长内容呈现状态；发送/清空/切换草稿归属后复位 |
| `previewLineLimit` | `number` | 初始为 `6`；展示值，不修改 draft |
| `characterThreshold` | `number` | 初始为 `1200`；用于超长单行兜底 |

### Existing `draft`

`draft: string` 继续由对应屏幕/store 持有，是唯一待发送文本事实源。Paste handler 必须按：

```text
result = draft[0:selectionStart] + clipboardText + draft[selectionEnd:]
```

构造新值；不得规范化换行、截断空白或把 preview 文本发送给后端。

### State Transitions

| From | Trigger | To | Draft effect |
|------|---------|----|--------------|
| normal | qualifying text paste | collapsed | 精确保留插入后的完整文本 |
| collapsed | 展开 | expanded | 无变化 |
| expanded | 收起 | collapsed | 无变化 |
| collapsed/expanded | 清空 | normal | 设为空串 |
| collapsed/expanded | send accepted | normal | 由既有发送流程清空 |
| normal | manual typing exceeds thresholds | normal | 仅更新文本，不自动折叠 |

## Debug Runtime Models

### `TraceArmState` (runtime-only unified config + business facade)

| Field | Type | Rules |
|-------|------|-------|
| `enabled` | `boolean` | sidecar 启动固定为 `false`；仅 authenticated debug control facade 以 `persist="runtime"` 设置 |
| `warning_acknowledged` | `boolean` | arm request 必须显式携带确认；未确认不可启用 |
| `armed_at` | ISO datetime \| null | 当前进程成功 arm 后生成，仅用于安全状态显示 |
| `capture_status` | `disabled \| armed` | control API / app-shell banner 可读取，不含 raw detail |
| `retention_epoch` | internal string \| null | enable 新建、disable/clear 失效；不得作为普通公共事件 payload |

`GET/PUT /api/debug/control` 是唯一产品可触达的控制合同。Data endpoint 在 disabled 时 fail closed，但 control endpoint 仍可在通过 sidecar auth 后返回警示与安全状态。App shell 在 `armed` 状态显示持续 stop 操作；restart 不继承此状态。

### `TraceCaptureContext` (process-local contextvar)

| Field | Type | Description |
|-------|------|-------------|
| `source` | `str` | `agent_loop`, `llm_review`, `distillation`, `prediction`, `compression`, `vision`, `composition`, `unknown` |
| `agent_type` | `str \| null` | `assistant`, `pm`, `programmer`, `trial`, `ephemeral_subagent`, `specialist` 等 |
| `session_id` | `str \| null` | 发起模型调用的业务 session |
| `workflow_id` | `str \| null` | Teaching 或 delegated work correlation id |
| `iteration` | `int \| null` | AgentLoop 轮次 |
| `transition_id` | `str \| null` | 当前可知的 transition；不可知时由 workflow/session 关联补齐 |
| `work_unit_id` | `str \| null` | brain segment 等非 workflow 工作单元 |

上下文必须使用 token/reset 形式的 scope，嵌套调用和异常退出后恢复原值。凡模型调用跨 `threading.Thread`、executor 或后台 worker 边界，入口必须显式传播或重新设置 `TraceCaptureContext`；只有确实无法恢复来源时才使用 `unknown`。

### `LLMTraceRecord` (bounded process-local)

| Field | Type | Rules |
|-------|------|-------|
| `trace_id` | `str` | 新建不可预测 id |
| `retention_epoch` | `str` | 捕获开始时所在 tracing epoch；epoch 失效后不得完成写入 |
| `created_at` | ISO datetime | 捕获时生成 |
| `completed_at` | ISO datetime \| null | 成功或失败终结时间 |
| `method` | `chat \| chat_with_tools \| multimodal` | unified observation boundary method; embedding/vectorization calls are out of trace-record scope |
| `source` / `agent_type` | `str` / nullable | 从 context 投影；缺失显示 `unknown` |
| `session_id` / `workflow_id` / `work_unit_id` | nullable strings | 筛选及流转关联元数据 |
| `iteration` | nullable int | 调用序号上下文 |
| `input_messages` | JSON list | 实际提交 textual content 的 redacted copy；媒体 block 的 raw data URL 不保留 |
| `input_media` | JSON list | 媒体安全元数据，如 type/media_type/byte_count/count；不可含可还原 bytes |
| `input_tools` | JSON list \| null | tool-enabled 调用的 redacted schema copy |
| `output_content` | string \| null | redacted provider output |
| `output_tool_calls` | JSON list | redacted tool call output |
| `outcome` | `succeeded \| failed \| cancelled` | 不吞掉失败记录 |
| `error_summary` | string \| null | 仅安全类型/摘要，不返回 secret 或完整 stack |
| `linked_transition_ids` | string list | 当前进程 correlation index 派生，不持久化 |
| `retained_bytes` | int | 此记录占用的 retained diagnostic bytes |
| `detail_availability` | `full_text \| media_metadata_only \| oversized_omitted \| diagnostic_unavailable` | 被预算或诊断旁路故障限制时显式说明缺失详情 |

### `TraceBuffer`

| Property | Rule |
|----------|------|
| Lifetime | 单个 enabled tracing epoch；disable、clear 或进程退出后 purge trace、ephemeral flow detail 与 correlation |
| Epoch transition | 由 control facade 通过 runtime-only unified config arm 驱动：warning-confirmed enable 创建新 epoch；disable 原子失效并清空；旧 epoch 的 mid-flight completion 丢弃，不得写回；restart 初始 disabled |
| Record capacity | `debug.trace.max_records`, 初始默认 `200`，非法值回退默认；最旧先淘汰 |
| Byte capacity | `debug.trace.max_record_bytes` 初始 `1048576` 与 `debug.trace.max_total_bytes` 初始 `16777216`；聚合超限先淘汰最旧记录/详情 |
| Oversized behavior | 不能在单记录预算内保留的 raw textual/tool detail 改为 `oversized_omitted` 安全记录，不静默丢失；媒体一律仅元数据 |
| Mutation | capture/clear/enable-disable 必须线程安全且与 epoch 校验原子协作 |
| Read gate | 每次读取重新检查 `debug.trace.enabled` |
| Redaction | 存入前与响应前都替换已由实际模型工厂注册的主模型、vision、embedding credential、runtime token 和其它应用控制 authorization material；不得为脱敏调用 migration-capable getter |
| Failure isolation | capture/redaction/correlation/buffer 旁路失败不得中断或替换 provider request/result/error；能安全表示时只记录 `diagnostic_unavailable` |

### `DebugClientState` (frontend-only)

| Property | Rule |
|----------|------|
| Storage | Raw trace detail、flow detail、reference body 只能保存在当前 DebugScreen 的内存 state 中 |
| Prohibited sinks | localStorage、sessionStorage、persisted Zustand、URL/query/hash、普通 nav state 和 Playwright default artifacts |
| Purge triggers | `DELETE /api/debug/traces` 成功、control disabled、sidecar auth 失效、离开 `/debug` route、窗口刷新或 sidecar restart |
| HTTP cache | Raw debug endpoints 必须返回 `Cache-Control: no-store`，客户端不得依赖浏览器/WebView cache 恢复 raw detail |

### `ObservationFailureIsolation`

| Failure point | Required business behavior | Diagnostic behavior |
|---------------|----------------------------|---------------------|
| Pre-call context/capture/redaction fails | 仍执行原 provider 调用一次 | 安全记录 unavailable 状态或完全跳过 detail |
| Provider succeeds, post-call capture/correlation/buffer fails | 原样返回 provider 成功结果 | 安全记录 unavailable 状态或跳过 |
| Provider fails and diagnostic handling also fails | 保留原 provider failure 语义 | 日志仅含安全类型/status，不含请求正文或 secret |

### `TraceGroupView`

由查询结果动态构造，不持久化：

| Field | Description |
|-------|-------------|
| `group_key` | `source + session/workflow/work_unit` 的稳定显示键 |
| `source` | 调用来源 |
| `agent_type` | 可用时提供 |
| `session_id` / `workflow_id` / `work_unit_id` | 可用关联 |
| `trace_count` / `last_created_at` | 定位最近链路所需摘要 |
| `retained_bytes` / `omitted_count` | 让开发者理解当前诊断预算与详情缺失 |

## Agent Flow View Models

### Existing Authority: `WorkflowTransition`

已存在字段：

| Field | Meaning |
|-------|---------|
| `transition_id` | transition identity |
| `workflow_id` | Teaching 或 assistant delegated workflow correlation |
| `event_type` | `requirement_confirmed`, `review_failed`, `trial_failed`, `triage_completed`, `tool_saved`, `assistant_delegation_started`, `assistant_delegation_completed`, `assistant_delegation_failed` 等 |
| `from_session_id` / `to_session_id` | 来源与目标 session |
| `payload` | 已有业务交接/结果 JSON，按诊断合同脱敏返回；并不保证含 Assistant delegated task/result text |
| `created_at` | 权威排序时间 |

### `DebugOnlyFlowDetail` (bounded process-local)

| Field | Rules |
|-------|-------|
| `transition_id` / `workflow_id` | 关联现有 authoritative transition/workflow |
| `retention_epoch` | 仅当前 enabled epoch 可读取 |
| `detail_type` | `delegated_task \| delegated_result \| diagnostic_error` |
| `content` | 委派边界捕获并脱敏的文本；不写回 transition |
| `retained_bytes` / `detail_availability` | 与 `TraceBuffer` 共用总预算和 omission 语义 |
| `provenance` | 固定为 `ephemeral_debug_capture` |

### `AgentFlowTransitionView`

| Field | Source / Rule |
|-------|---------------|
| `transition_id`, `workflow_id`, `event_type`, `created_at` | existing transition |
| `from_session`, `to_session` | existing session 元数据投影为 agent type / id |
| `status` | event type 的稳定 UI 分类：`handoff`, `retry`, `failure`, `completion`, `publication`, `waiting` |
| `reason` | existing payload 中可安全呈现的原因；无值明确为 `null` |
| `detail` | 已有 payload 的 redacted diagnostic view，或当前 epoch 可用的 `DebugOnlyFlowDetail`；不通过公共 SSE 发送 |
| `detail_provenance` | `persisted_transition \| ephemeral_debug_capture \| unavailable`，UI 必须显示区别 |
| `detail_availability` | `full_text \| oversized_omitted \| unavailable`；临时详情受共享聚合预算省略时 UI 必须明确展示 |
| `trace_ids` | 当前进程内 correlation；可为空 |
| `link_status` | `linked` 或 `unlinked`；无 trace 时 transition 仍必须返回 |

### `TraceCorrelationIndex` (process-local)

| Key | Value | Rule |
|-----|-------|------|
| `(retention_epoch, workflow_id, session_id)` and optional active transition scope | `trace_id[]` / `DebugOnlyFlowDetail[]` | 只为当前 epoch 捕获内容建索引；不写回 transition |

## Reference Expansion

### `ExpandedReferenceView`

| Field | Rules |
|-------|------|
| `reference_id` | 请求的 existing message/summary reference id |
| `content` | 通过现有 reference semantics 获取并按同一 redactor 处理后的原文 |
| `available` | 不存在/已失效时 API 返回明确 not-found 错误而非空成功 |
| `truncated` | 超过单响应预算时为 `true`，UI 必须显示内容被限制 |
| `next_chunk` | 若采用 chunking，则提供下一段读取 token；否则为 `null` |

访问前置条件为当前 sidecar 鉴权成功且 `debug.trace.enabled = true`。该读取按需求是进程范围诊断能力，不限制 reference 必须出现于当前选中 trace。单次 response 受 `debug.reference.max_response_bytes` 或等价实现配置约束；实现可以选择截断、分块或返回明确 too-large diagnostic，但不得无界返回。

## Grand Tour Runtime Model

### `RealGrandTourRun` (test-owned ephemeral state)

| Field | Rules |
|-------|------|
| `run_id` | 单次人工执行 identity |
| `data_dir` | 新建临时 `EXEMPLAR_DATA_DIR`，运行结束清理 |
| `sidecar_port` / `session_token` | 每次随机生成；仅测试进程与被测前端持有 |
| `credential_mode` | `read_existing_keyring_only`；任何 write/delete 都是测试失败 |
| `credential_provider_scope` | `main`, `vision`, `background`, `settings_validation`, `skill_composition`, `compression`, `embedding`, `redactor` 均由同一注入式 side-effect-free provider 覆盖，或在场景进入前显式跳过未覆盖路径 |
| `credential_mutation_count` | 必须保持 `0`；由可跨 sidecar 观测的 audit guard 统计迁移写入、保存和删除尝试 |
| `non_secret_settings_snapshot` | 允许列表方式复制到隔离配置/SQLite，不复制 secret |
| `live_journey_id` | 固定安全脚本 identity；对应预先准备的非敏感目标窗口/页面 |
| `recording_consent_confirmed_at` | 当前桌面/浏览器采集前必须存在 |
| `scenario_results` | 每个场景独立结果、最后可见 workflow status、cleanup result |
| `recording_cleanup_status` | success/failure/timeout/cancel 任一出口都必须确认停止 |
| `elapsed_budget_minutes` / `paid_call_budget` | 初始分别为 `20` / `30`；超限必须停止付费调用和录制并失败 |
| `budget_usage` | 报告实际 elapsed time 与 paid-call count，不暴露请求正文 |
| `report_path` | 本地 Playwright output 下的非敏感 summary JSON 路径；默认不提交版本控制 |
| `commit_sha` | 被验收的代码 identity；连续通过证据必须一致 |

### `RealGrandTourSummaryReport` (non-sensitive test artifact)

| Field | Rule |
|-------|------|
| `runId`, `commitSha`, `liveJourneyId` | 关联一次运行、被测版本和固定脚本 |
| `scenarios` | 仅含 outcome、last observable status、elapsed/paid-call usage、cleanup status |
| `credentialMutationCount` | 必须为 `0` |
| Forbidden content | raw prompt/response、trace/handoff detail、截图/录制正文、token/credential、临时数据路径正文 |

报告写入 `frontend/test-results/real-grand-tour/<run_id>/summary.json` 或等价 Playwright local output；不作为持久业务数据，也不默认提交仓库。发布/PR 可引用同一 `commitSha`/`liveJourneyId` 的三次安全摘要结果。

## Configuration Keys

| Key | Default | Persistence | UI Exposure |
|-----|---------|-------------|-------------|
| `debug.trace.enabled` | `false` | unified configuration runtime only; sidecar restart resets | 仅隐藏 debug control / armed banner；不在普通 Settings 页面展示 |
| `debug.trace.max_records` | `200` | unified configuration | 本 feature 不在普通 Settings 页面展示 |
| `debug.trace.max_record_bytes` | `1048576` | unified configuration | 本 feature 不在普通 Settings 页面展示 |
| `debug.trace.max_total_bytes` | `16777216` | unified configuration | 本 feature 不在普通 Settings 页面展示 |
| `debug.reference.max_response_bytes` | `1048576` | unified configuration | 本 feature 不在普通 Settings 页面展示 |

这些 debug 配置不是秘密；sidecar runtime token 与 API key 都不是新增配置项，也绝不因诊断能力进入明文配置或普通日志。上述默认值必须通过统一配置默认/schema/accessor 提供，非法值回退到安全默认，不得只在调用模块中硬编码。
