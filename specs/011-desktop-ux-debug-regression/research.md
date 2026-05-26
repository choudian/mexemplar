# Research: Desktop UX, Debug Inspector, and Grand Tour Acceptance

## Critique-Verified Baseline

- 当前 `src/business/agents/tool_helpers.py` 的视觉 helper 直接调用底层 model invoke，而不是 `LangChainLLMClient.chat()` / `chat_with_tools()`；视觉请求必须显式迁入统一观察边界才能兑现完整 trace 覆盖。
- 当前 Assistant delegation 的 persisted transition 记录状态转移与有限状态 payload，但不保存 delegated task/result 原文；这些原文只能作为 trace-enabled ephemeral detail 提供。
- 当前 LLM 与 delegation 路径存在输出 raw input/output/task 的普通日志语句；实现必须先将这些日志收敛到安全摘要，不能把日志当作旁路调试面。
- 当前统一配置的普通 credential getter 包含历史明文迁移到 keyring 的副作用分支；real-tour 必须使用单独的 side-effect-free read contract。
- 当前 `SettingsService` 的允许设置列表不包含 `debug.trace.*`，且 unified-config observer 仅在 `set()` 调用时触发；若不新增业务拥有的 control path，disable/re-enable epoch 合同没有真实用户路径。
- 当前公共 UI event 的 `assistant.message.content` 是正常回复展示合同；安全门卫必须禁止 diagnostic-only raw 数据，而不能禁止该既有产品内容。
- 当前 embedding、compression、skill composition、settings validation 等路径也会读取 credential 或创建模型客户端；real-tour 的只读 provider inventory 必须覆盖这些实际可触达 callsite，而不能只覆盖 main/vision/background 的 broad category。
- 当前 raw debug 响应若没有 `Cache-Control: no-store` 与 frontend memory-only 约束，WebView cache、URL 或 persisted store 可能绕过 clear/disable/restart 语义。

## Decision 1: 长粘贴状态由共享前端 hook 管理

**Decision**: 在 `frontend/src/hooks/useLongPasteCollapse.ts` 提供共享交互状态，Assistant `MessageComposer` 与 Teaching `ChatComposer` 使用同一规则。判定基于一次文本 paste 插入后的完整 draft；产品阈值采用“超过 6 行或超过 1200 个字符”的初始值，覆盖超长单行。  
**Rationale**: 当前两个 composer 都是受控 textarea，draft 已由上层/store 拥有，折叠仅是短期 UI 表现。按插入后的文本判定并使用 `selectionStart` / `selectionEnd` 可保留在已有草稿中间粘贴的语义。字符兜底解决单行超长输入不折叠的边缘问题。  
**Alternatives considered**: 只按粘贴片段行数判断会漏掉短片段使现有草稿越阈值以及超长单行；把折叠状态放 Zustand 会让跨会话临时状态更容易泄漏。

## Decision 2: Debug 页面采用隐藏诊断 route，而不是普通导航条目

**Decision**: 将可被 `NavRail` 遍历的普通 `routes` 与诊断 route 解析分开，`/debug` 只在直接访问且后端 trace gate 可用时渲染。  
**Rationale**: 现有 `frontend/src/app/routes.tsx` 同时是屏幕定义和导航数据源，直接添加 route 会自然显示在主导航中，违反“不暴露正常用户入口”的需求。  
**Alternatives considered**: 在 `NavRail` 中按 id 特判过滤 debug 会使敏感入口约束依赖渲染层约定，不如数据结构上分离清晰。

## Decision 3: Raw trace 由业务层诊断服务拥有，生命周期只在进程内

**Decision**: 新增 `src/business/debug/DebugInspectorService`、业务拥有的 trace control facade 和内部 epoch-scoped buffer；`desktop_api` router 只调用 facade。`debug.trace.enabled` 由 control facade 通过 unified config 的 `persist="runtime"` 改变，sidecar 启动默认关闭；隐藏页先展示警示再允许 arm，armed 时 app shell 显示停止提示。新增的 raw textual prompt/response、tool schema、失败摘要、ephemeral flow detail 与 trace correlation 不写 SQLite、DuckDB、日志、公共 SSE、HTTP/WebView cache、URL 或前端持久化 state。Buffer 同时按记录数、单记录 bytes 与聚合 bytes 限制；clear/disable/restart/离开 `/debug` 都销毁当前 epoch 或客户端 raw state。  
**Rationale**: Trace 暴露真实提示词与输出，属于受控业务诊断能力，不适合下沉为无边界通用 utility，也不应由 adapter 层持有存取规则。Epoch 防止关闭再开启时恢复旧数据，byte budget 避免大 prompt 或工具定义令桌面进程内存失控；`no-store` 与 memory-only UI state 避免浏览器/WebView 成为旁路持久化。  
**Alternatives considered**: 数据库 trace 表利于历史查询但直接违反非持久化要求；普通 logging 无鉴权、无法可靠清空且泄漏风险更高；依赖浏览器默认缓存策略无法证明 clear/disable 后 raw 内容不可恢复。

## Decision 4: 在统一 LLM 调用边界采集，并以 contextvars 关联来源

**Decision**: 在 `LangChainLLMClient` 提供统一可观测 model invocation 边界，由 `chat()`、`chat_with_tools()` 和视觉 helper 共同调用，记录实际送出的文本/工具、媒体安全元数据与实际响应或失败；实现门卫扫描受支持业务路径中任何绕开该观察入口的 direct `llm.invoke`。AgentLoop、brain worker、review/compression/vision 等调用入口使用可恢复的 context manager 设置来源、agent/session/workflow/iteration metadata；跨 thread/executor/background worker 的入口必须显式传播或重设 context。Embedding/vectorization calls 不生成 trace records，但必须出现在 credential/redaction/provider inventory 或 allowlist 中。  
**Rationale**: `llm_client.py` 可作为 provider 统一边界，但现有视觉 helper 会绕开两个 chat wrapper。把视觉也迁入可观测 invocation，并对 image blocks 仅保留类型/数量/大小而非 base64 bytes，才能同时满足覆盖率、隐私和内存约束。`contextvars` 可在并发线程/嵌套调用中避免全局可变标签串线，且不改变 LLM 行为；显式 thread propagation 关闭后台调用变成 `unknown` 的隐性缺口。Embedding 查询的输入/输出形态与 LLM prompt/response 诊断不同，本 feature 只把它纳入凭据安全与直接调用清单。  
**Alternatives considered**: 在每个业务调用点各自复制输入输出会漏调用且难以统一失败/脱敏；只在 AgentLoop 采集无法覆盖 brain、review 与 vision direct invoke；保存截图 data URL 会把短期调试面扩大为高风险媒体缓存；把 embedding 也做成 trace record 会扩大 scope 且偏离本轮 prompt/flow 调试目标。

## Decision 5: Agent Flow 读取已有 transition 权威事实，只临时补 trace link

**Decision**: Teaching 与 Assistant delegation 时间线由现有 `workflow_transitions` 和 session 元数据经业务 service 查询并投影；当前 trace 开启期间新增的 `trace_id <-> workflow/transition` 关联和 Assistant delegated task/result detail 仅放进 epoch-scoped memory buffer。UI/API 必须标记 detail 来自 `persisted_transition` 还是 `ephemeral_debug_capture`。  
**Rationale**: 基线已在 `AgentSessionStore.record_transition()` 与 orchestrator 的 `_emit_and_log()` / delegation path 中记录 `requirement_confirmed`、`review_failed`、`trial_failed`、`triage_completed`、`assistant_delegation_started/completed/failed` 等真实转移；但 Assistant delegation payload 目前没有 task/result 原文。保留 transition 作为状态真相、只临时补 raw detail，才能兼顾诊断价值与不新增长期原文历史。  
**Alternatives considered**: 根据公共 UI event 或模型文字重建流转会丢失未投影细节；为 correlation 扩表会把 debug-only enrichment 变成永久历史。

## Decision 6: Trace gate 与脱敏在采集和返回两处防守

**Decision**: 使用统一配置键 `debug.trace.enabled`（runtime-only，进程启动默认 `false`）、`debug.trace.max_records`（初始 placeholder `200`）、`debug.trace.max_record_bytes`（初始 `1048576`）、`debug.trace.max_total_bytes`（初始 `16777216`）和 `debug.reference.max_response_bytes`（初始 `1048576`）。disabled 时数据 API fail-closed，control API 仅返回安全状态/警示并可在确认后 arm；enable-to-disable transition 原子 purge 当前 epoch；enabled 时在存入 buffer 前替换当前模型客户端已经注册的主模型、vision、embedding credential、runtime token 与其它应用控制 authorization material，并在 API 返回前再次脱敏。Redactor 不为收集 secret 调用会触发迁移的 getter。现有 raw LLM/delegation log 必须删除或改为安全摘要。  
**Rationale**: 双重脱敏覆盖 trace 捕获后配置/secret 轮换的情况，同时避免已知 secret 被短暂保存在 buffer。Epoch 与 byte budget 关闭 re-enable 泄漏和资源耗尽风险；ordinary logs 若保留原文会绕开全部诊断门禁。Runtime token 不属于统一持久配置，由 sidecar 启动时以进程内注册方式提供给 redactor。  
**Alternatives considered**: 只在 UI 渲染时脱敏会让后端 buffer 保有凭据；将 token 放入配置供 redactor 读取违反 runtime token 边界。

## Decision 7: Reference expansion 通过诊断 facade 复用现有加载语义

**Decision**: Debug API 通过 `DebugInspectorService` 调用现有 reference 加载能力，允许在 trace 开启且当前 API session 已鉴权时按 reference id 读取当前可寻址内容，并对返回值执行相同 known-secret redaction。单次 response 受 `debug.reference.max_response_bytes` 或等价实现预算约束，超限时返回 truncation/chunking/too-large diagnostic。  
**Rationale**: `ContextManager.load_reference()` 已定义 message/summary 引用语义；diagnostic facade 可实施 gate 与脱敏，避免 router 直接触及 Repository。该范围符合已澄清的 process-wide 诊断边界；响应预算避免大型引用绕过 trace buffer 上限。  
**Alternatives considered**: 将 expansion 限制为当前 trace 会违背规格；直接从 router 查询 message repository 会破坏 adapter 边界；无界返回 reference 会形成内存和隐私风险。

## Decision 8: 真实 Grand Tour 是单独 opt-in 项目，不改默认 mock 回归

**Decision**: 新增独立 Playwright real-grand-tour 配置/命令，要求人工显式确认外部模型费用与当前桌面/浏览器录制隐私风险；启动随机 localhost sidecar、临时业务数据与只允许白名单非密钥配置写入的隔离目录。真实 Teaching 验收只执行文档化、无敏感内容的固定现场操作脚本，并施加 20 分钟/30 次付费请求预算。读取默认 keyring 中已存在的模型 credential 必须走注入 main/vision/background/settings validation/skill-composition/compression/embedding/redactor 的 keyring-only read-only provider，不触发明文回退、迁移、写入或删除；未覆盖路径在场景启动前跳过或作为 unmet prerequisite 失败。Skills/compositions 场景默认只做隔离数据 visibility/create/read，不触发 LLM；若改为 generation/trial 必须计入 paid-call budget 与 provider inventory。测试使用可观察 mutation attempt 的 audit guard 并要求计数为零。每次人工 run 输出仅含 commit/journey/outcome/budget/cleanup/mutation 状态的非敏感 report，Playwright trace/video/screenshot 默认关闭或经 sentinel sanitization 限制。  
**Rationale**: 当前 `grand-tour.spec.ts` 虽启动真实 sidecar，但仍靠固定停顿推进，并在设置场景写入 API key；普通 `get_ai_api_key()` 还可能执行 migration write。新边界必须阻止污染开发者凭据，同时用固定安全现场输入和预算保留真实模型验收价值与可重复性。  
**Alternatives considered**: 把真实模型加入默认 E2E 会带来费用和不稳定性；复制或写入真实密钥到临时配置不满足安全要求。

## Decision 9: Grand Tour 等待既有安全 public status/event

**Decision**: 测试侧新增 EventWatcher，按 `ui-events` 公共合同等待 `assistant.progress.status`、既有用户可见 `assistant.message.content`、`recording.progress.status` (`recording` / `stopped` / `completed` / failure/degraded)、`teaching.stage_changed.stage`、`teaching.progress.status`、`trial.progress.status/published` 与 `settings.changed` 等安全产品字段，并在失败报告记录最后观测状态；不得为验收新增或暴露 diagnostic-only raw prompt/trace/handoff/media/correlation payload。  
**Rationale**: `009-frontend-event-layer` 已提供 authenticated SSE、replay/resync 与满足录制停止、Teaching 推进和 trial 结果判断的 allowlisted payload；复用它能验证真实用户链路而不扩大诊断数据暴露面。  
**Alternatives considered**: 固定 `waitForTimeout` 容易在真实 LLM 延迟波动下误判；读取数据库绕过产品边界。

## Decision 10: 诊断观察失败必须与被观察业务隔离

**Decision**: Unified observation boundary 将 provider 调用与诊断旁路分隔：pre-call capture/redaction/context 失败时仍执行原 provider request；post-call capture/correlation/buffer 失败时仍原样返回 provider 结果；provider 本身失败时仍抛出其原错误语义，不被诊断错误替换。诊断服务可在还能安全写入时返回 `diagnostic_unavailable`/omission 元数据，普通日志只记录安全状态和异常类型。  
**Rationale**: Trace 是可选观察能力，不是业务执行前置条件；若打开调试会改变 Assistant、Teaching 或 background brain 的行为，就违反“observe, not change”约束且使真实问题更难重现。  
**Alternatives considered**: 对诊断写入采用 fail-fast 会提升诊断完整性，但会把 debug 工具变成产品可用性风险。

## Decision 11: Trace arm 由隐藏控制面显式管理

**Decision**: `/api/debug/control` 是唯一 authenticated arm/status/stop 合同；它在 disabled 状态仍可返回不含 raw 内容的安全状态与 warning。Arm 前 UI 必须展示警示并获得确认，随后 facade 以 `config.set("debug.trace.enabled", True, persist="runtime")` 创建 epoch；Stop 以同一路径设置 `False` 并 purge。App shell 在 armed 时呈现持续停止入口，restart 不继承 arm。  
**Rationale**: 当前 Settings API 不包含 debug 键，外部改配置文件也无法可靠触发 observer 和同进程 purge。显式控制面同时解决可用性、可测试性和无感敏感采集风险。  
**Alternatives considered**: 把开关加入普通 Settings 会向普通用户扩大诊断入口；依赖启动前配置文件只能验证启动状态，无法验证同进程关闭行为。

## Decision 12: Grand Tour 以非敏感报告形成版本化证据

**Decision**: 每次 manual real-tour 在 Playwright local output 下生成不提交的 summary JSON，至少包含 `commitSha`, `runId`, `liveJourneyId`, scenario outcomes, last observable state, elapsed/paid-call usage, cleanup status 与 `credentialMutationCount`，不得含 raw prompt/response、截图、录制正文或 credential。Playwright trace/video/screenshot artifacts 默认关闭；任何失败附件都必须仅包含安全 summary/status 并通过 sentinel 检查。发布说明/PR 仅引用三次同 commit/journey 的摘要状态或附件。  
**Rationale**: “连续三次成功”只有关联具体代码与固定旅程才能作为可复核的发布证据，同时 summary 能保留清理/预算/凭据不变式而不新增敏感存储。  
**Alternatives considered**: 不保存任何报告难以复查；保存完整 Playwright trace 或截图会扩大真实采集隐私面。

## Resolved Questions

- **是否需要新的 Tauri capability/window command?** 不需要；长粘贴与 debug 展示均为 React/sidecar 合同，Grand Tour 复用既有窗口/录制能力。
- **是否新增 schema migration?** 不需要；新增诊断数据不持久化，Flow 复用既有 transition 表。
- **是否向普通用户 Settings 暴露 trace switch?** 不在本 feature 暴露；它通过隐藏诊断面的 authenticated runtime-only control arm 管理，armed 期间只在应用壳显示停止提示。
- **是否需要新的公共 SSE debug event?** 不需要；debug UI 通过受控 REST 读取，Grand Tour 继续使用已有安全事件。
- **是否把视觉截图原文放入 trace?** 不放；仅捕获文本块、媒体元数据与模型结果，原始 image bytes/data URL 不进入 debug buffer 或 API。
- **embedding 是否进入 trace?** 不进入本 feature 的 `LLMTraceRecord`；embedding credential 与 callsites 仍进入 redaction、real-tour provider 和静态 allowlist inventory。
- **是否允许普通日志作为 trace 的备用查看方式?** 不允许；日志只保留安全摘要，raw 调试内容只能通过鉴权且启用 gate 的诊断合同读取。
- **raw debug API 是否可被浏览器缓存或前端持久化？** 不允许；raw endpoints 使用 no-store，DebugScreen 仅 memory state，clear/disable/离开 route 必须 purge。
- **三项交付是否必须绑定发布?** 不需要；composer、debug/flow 与 real-tour 各自有独立 completion gate，任务可按风险分 slice 验收。
- **正常 assistant 回复是否被 SSE raw-data 门卫禁止?** 不禁止；门卫仅拒绝 diagnostic-only raw 数据与秘密，既有用户可见 message content 保持产品合同。
