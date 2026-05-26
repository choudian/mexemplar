# Feature Specification: Desktop UX, Debug Inspector, and Grand Tour Acceptance

**Feature Branch**: `011-desktop-ux-debug-regression`
**Created**: 2026-05-24
**Status**: Completed
**Input**: User description: "你看一下 docs/local/todo 下的文档，这次我打算把这些都做出来。" Source notes: `todo-chat-input-collapse-long-paste.md`, `todo-debug-trace-page.md`, `todo-grand-tour-e2e-rewrite.md`.
**Scope Addition**: 2026-05-24 — Expand the local debug inspector from individual LLM trace inspection to correlated Agent Flow visibility for orchestration handoffs, retries, failures and returns.
**Critique Remediation**: 2026-05-24 — Close trace coverage, ephemeral flow-detail, runtime-only activation lifecycle, product-event boundary, observation isolation, ordinary-log, read-only credential integration, repeatable live-journey, report-evidence and resource-budget gaps before task generation.

## Clarifications

### Session 2026-05-24

- Q: Trace 中遇到用户自行输入的敏感文本时，调试真实性与脱敏边界如何取舍？ → A: 保留用户输入与模型输出原文；强制脱敏应用已知 secret 与 sidecar runtime token；调试界面明确提示开发者不要粘贴敏感内容，清空或退出即销毁 trace。
- Q: 真实 Grand Tour 覆盖设置交互时，如何保证不会污染开发者的日常配置与凭据？ → A: 非密钥设置只写入隔离测试配置；真实 keyring 凭据仅可读取用于模型调用或连接验证，Grand Tour 不得新增、替换或删除 keyring 凭据。
- Q: Trace Inspector 是否还需开发运行门禁，还是仅由统一配置的显式开关控制？ → A: 仅依赖统一配置中的显式 trace 开关；任何本地运行在开关开启并通过当前 sidecar 会话鉴权时均可访问。
- Q: Trace Inspector 的引用原文展开是否限定为当前选中 trace 所引用的内容？ → A: 不限定；trace 开关开启且请求通过当前 sidecar 会话鉴权时，可读取当前进程内任意存在的引用原文。
- Q: Grand Tour 的 Skill Teaching 场景是否允许自动采集开发者当前真实桌面或浏览器活动？ → A: 允许；手动启动的真实 Grand Tour 可录制当前真实桌面或浏览器活动以覆盖完整 Teaching 链路。

### Critique Remediation 2026-05-24

- Q: 多模态/视觉模型调用是否属于 trace 覆盖面，截图原始字节是否进入 trace detail？ → A: 所有受支持的模型调用路径（包括视觉调用）都必须可观测；trace 展示文本 prompt/结果与媒体类型、数量、尺寸等诊断元数据，不保存或返回 base64/原始图像字节。
- Q: 关闭 trace 后同一进程再次开启时，旧临时记录能否重新显示？ → A: 不能；禁用、清空或退出都销毁当前 epoch 的 trace、debug-only flow detail 与关联，引发中的旧 epoch 调用完成后不得回写。
- Q: Assistant delegation 的任务与返回原文从哪里获得？ → A: 持久化 transition 继续只作为权威状态事实；仅在 trace 已启用时，由业务层委派边界额外捕获脱敏后的进程内 task/result detail，并在 clear/disable/restart 时销毁。
- Q: 普通日志是否可以继续输出 raw prompt、tool arguments、模型回复或委派任务？ → A: 不可以；普通日志仅允许安全摘要、identity、长度与状态信息，应用控制的主模型/视觉/embedding 凭据、授权材料和 runtime token 都纳入零泄漏验证。
- Q: Real Grand Tour 如何在保留真实录制的同时可重复验收？ → A: 使用人工启动但脚本固定的安全现场旅程，只操作为验收准备的无敏感内容目标窗口/页面；每轮限制最长 20 分钟和最多 30 次付费模型请求。
- Q: Real Grand Tour 如何保证 credential 只读？ → A: 使用不会触发迁移、副作用写入或删除的只读凭据解析路径，并在运行期间监测 keyring mutation 为零。
- Q: 开发者如何安全启停 trace，并避免一次打开后在后续运行中无感继续捕获？ → A: `debug.trace.enabled` 是仅当前 sidecar 进程有效的 runtime-only arm；开发者直接进入隐藏诊断面、阅读敏感内容警示并确认后才可启用，启用期间应用壳持续显示捕获中提示与停止操作，关闭或重启均立即回到未启用状态。
- Q: 公共 UI 事件是否可以继续包含正常聊天需要展示的 assistant 回复？ → A: 可以；禁止的是仅为 debug 新增的 raw prompt/trace/handoff/media/correlation，不是产品本就需要渲染的 `assistant.message.content`。
- Q: 如果 trace 捕获、脱敏或缓冲写入自身失败，会不会改变真实模型调用结果？ → A: 不会；诊断是 fail-isolated 的旁路观察能力，最多产生安全的诊断缺失/失败状态，不得阻断、替换或改变原业务请求和结果。
- Q: Real Grand Tour 的安全证据如何留存？ → A: 每次人工运行输出不含 prompt、截图或凭据的本地 summary report，并以 commit identity 与 fixed journey identity 关联三次通过证据。

## Baseline Evidence

| Pain point | Reproducible baseline evidence | Target improvement |
|------------|--------------------------------|--------------------|
| 长文本粘贴挤压对话视野 | 当前两个 composer 仅提供普通 textarea 行为；以 7 行或 1201 字符固定文本在 Assistant/Teaching 粘贴即可复现全文展开输入面。 | 同一固定文本触发紧凑预览，实际发送文本逐字一致。 |
| 编排诊断依赖猜测或分散日志 | 当前 Assistant transition 不持久保存 delegated task/result 原文，视觉 helper 还存在绕过统一 chat wrapper 的 model invoke 路径。 | 受控 trace/flow 在一次固定委派与 vision 样本中可定位输入、结果和来源，且不持久化新增 raw detail。 |
| Grand Tour 不可稳定证明真实链路 | 当前 `frontend/tests/e2e/grand-tour.spec.ts` 使用固定 `pause()` 推进并执行 API Key 保存交互。 | 手动 real tour 仅运行固定安全旅程，以公共状态推进、零凭据 mutation，并输出可比较的非敏感报告。 |

## User Scenarios & Testing *(mandatory)*

本功能把三项待办作为一次可独立验收的开发体验增强交付：用户粘贴大段上下文时聊天输入仍然轻便；开发者可以在本地显式开启 trace 配置后检查真实 LLM 交互以及 Agent 之间的交接流转，以调优提示词和定位编排问题；维护者可以手动执行真实后端与真实模型参与的 Grand Tour，验证主流程确实连通。三项能力互不依赖即可交付，但共同降低 Assistant 与 Teaching 流程的调试和回归成本。

### User Story 1 - 长粘贴保持聊天输入轻便 (Priority: P1)

作为在 Assistant 或 Skill Teaching 对话中提供长背景材料的用户，我希望粘贴多行内容后输入区只显示紧凑预览，同时仍然保留并发送完整原文，这样我不会因为一次长粘贴而丢失对话视野或内容。

**Why this priority**: 这是直接影响日常输入体验、风险低且价值立即可见的改进；它不依赖调试页或测试基础设施即可独立交付。

**Independent Test**: 分别在 Assistant 和 Skill Teaching 输入区粘贴超过折叠阈值的多行文本，验证显示折叠预览、可展开/收起/清除，并验证发送给对话的是包含原有草稿位置关系的完整文本。

**Acceptance Scenarios**:

1. **Given** 用户位于 Assistant 的空白输入框，**When** 用户粘贴超过长内容阈值的多行文本，**Then** 输入区显示紧凑预览和内容规模提示，草稿中保留完整原文。
2. **Given** 用户位于 Skill Teaching 对话输入框，**When** 用户粘贴长内容，**Then** 用户获得与 Assistant 一致的折叠、展开、收起、清除和发送行为。
3. **Given** 输入框已有文本且光标或选区位于中间，**When** 用户粘贴长内容，**Then** 粘贴内容在预期位置插入且既有草稿不会被意外覆盖。
4. **Given** 长草稿正处于折叠或展开状态，**When** 用户发送消息，**Then** 对话收到完整、未截断的草稿，发送后输入状态回到空白常态。
5. **Given** 用户通过键盘逐行键入较长内容，**When** 行数越过粘贴折叠阈值，**Then** 系统不因手动输入而自动切换到折叠预览。

---

### User Story 2 - 检视模型调用与 Agent 流转链 (Priority: P2)

作为调试 Assistant、Teaching 流水线与大脑后台工作的开发者，我希望在一个不干扰正常导航的调试视图中同时查看真实 LLM 请求/响应链以及 Agent 之间的任务交接时间线，包括引用内容与交接内容的按需展开，这样我可以发现提示词、工具调用、编排调度和后台沉淀行为的问题。

**Why this priority**: Assistant brain redesign 引入了前台及后台多类模型调用与委派路径，而 Teaching 本身包含 PM、Programmer、Trial 的阶段交接；仅看到单次模型调用仍无法回答任务为何转交、交接了什么、失败后退回哪一步。没有受控的调用与流转可观测性，提示词调优和编排失败定位会依赖猜测或临时日志。

**Independent Test**: 直接访问隐藏诊断面，在看到敏感内容警示后显式开启当前 sidecar 会话的 trace arm，确认应用壳持续显示捕获中提示；触发一次 Teaching 中的需求确认至程序员接手流程、一次 Assistant 对执行体的委派以及一次受支持的视觉模型调用；按 workflow/session 找到 Agent Flow 时间线，从交接节点打开当次短期交接详情和关联 LLM trace，验证视觉记录只展示媒体元数据；再通过提示中的停止操作关闭并重新开启 trace，验证旧临时详情不可恢复，重启后默认未武装。

**Acceptance Scenarios**:

1. **Given** 开发者已通过敏感内容警示确认并武装当前 sidecar 会话的 trace，且访问者拥有当前 sidecar 会话访问权，**When** 发生模型调用，**Then** 调试视图可显示该调用的来源、关联会话或工作单元、调用顺序、实际输入和返回结果。
2. **Given** 一次调用产生工具调用或失败结果，**When** 开发者展开该条记录，**Then** 视图展示足以复现调优判断的真实请求/响应或安全失败摘要，并屏蔽应用已知凭据与运行期授权信息。
3. **Given** 当前本地进程存在可读取的引用内容，**When** 已鉴权开发者在调试视图中请求该引用，**Then** 原始引用内容可展开显示，无论它是否出现在当前选中 trace 中；不存在或已失效的引用显示明确错误。
4. **Given** Teaching workflow 中 PM 已确认需求并把任务交给 Programmer，**When** 开发者查看该 workflow 的 Agent Flow，**Then** 时间线显示 `PM -> Programmer` 的交接时点、触发原因、状态及程序员实际收到的需求交接内容，并可跳转到相关模型调用。
5. **Given** workflow 发生 Review 打回、Trial 失败后分诊、重新派发或最终发布，**When** 开发者查看 Agent Flow，**Then** 分支、回退、重试与终态均按真实发生顺序显示，而不会被简化成一条成功直线。
6. **Given** Assistant 把任务委派给临时 subagent 或固定专员，**When** 执行体返回成功或失败结果，**Then** Agent Flow 显示父会话到执行体、执行体回到 Assistant 的关联链路，并可检查所交付任务与返回结果。
7. **Given** 调试缓存已有多种来源的调用和流转记录，**When** 开发者选择来源、会话、workflow 或最近记录，**Then** 可以在有限步骤内定位目标调用链与交接链，并能够清空本进程新增捕获的调试记录。
8. **Given** 当前 sidecar 会话的 trace arm 未启用或进程已重新启动，**When** 访问调试能力，**Then** 之前捕获的原始 prompt/response 与仅为调试新增的原始细节不可获取，正常用户导航也不会暴露调试入口。
9. **Given** trace 开关开启时发生视觉模型调用，**When** 开发者展开其 trace，**Then** 视图显示文本输入、结果和安全媒体元数据，但不包含可还原截图的原始二进制或 base64 data URL。
10. **Given** 进程内已有 raw trace 或 debug-only flow detail，**When** 开发者关闭再重新开启 trace，**Then** 旧 epoch 数据仍不可读取，且关闭期间完成的旧调用不会重新注入缓存。
11. **Given** 应用在普通运行日志级别处理被追踪请求或委派任务，**When** 开发者检查日志，**Then** 日志仅含安全摘要/标识/状态，不含 raw prompt、response、handoff text 或应用控制的秘密。
12. **Given** 开发者尚未武装 trace，**When** 直接进入隐藏诊断入口，**Then** 页面先显示敏感内容警示且不提供 raw 数据，只有确认启用后才开始新 epoch；启用期间应用壳持续提供可见停止操作，重启后不保留启用状态。
13. **Given** 模型调用会成功或以既定 provider 错误失败，**When** 同时注入 trace 捕获、脱敏或缓冲写入故障，**Then** 原模型结果或原 provider 失败语义保持不变，调试能力最多显示安全的诊断不可用状态。

---

### User Story 3 - 手动运行真实 Grand Tour 验收 (Priority: P3)

作为发布前验证桌面工作流的维护者，我希望运行一套明确为手动、可产生真实模型费用的 Grand Tour 验收，使用真实 Python 后端、当前安全配置的模型能力和可观察的流程状态推进测试，这样我能证明 mock 之外的主路径可以工作。

**Why this priority**: 现有快速界面回归仍有价值，但无法证明 sidecar、事件流和真实模型组合后的完整路径；该验收套件负责补这一层信心，而不是替代常规测试。

**Independent Test**: 在满足真实模型前置条件的开发环境中手动启动一次 Grand Tour，确认费用与录制隐私提示后，按预先准备的无敏感内容安全旅程让 Teaching 场景采集真实目标窗口或浏览器页面；验证各场景使用隔离业务数据完成，长时流程由可观察的业务进度驱动，运行受时长/付费调用预算约束，且结束后录制已停止、日常业务数据与凭据未被修改。

**Acceptance Scenarios**:

1. **Given** 开发者已配置可用的真实模型凭据并主动选择运行真实验收，**When** Grand Tour 启动，**Then** 它连接真实桌面后端会话并明确告知会产生外部模型调用成本，且仅以只读方式使用开发者现有凭据。
2. **Given** 开发者手动启动包含 Teaching 录制的真实验收，**When** 系统准备开始采集当前桌面或浏览器活动，**Then** 它在采集前明确提示录制内容可能包含隐私信息并可能进入模型处理，只有本次已明确启动的验收才继续采集。
3. **Given** Grand Tour 执行 Assistant 对话或 Teaching 真实录制流程，**When** 后端产生进度或完成状态，**Then** 场景按可观察状态继续并断言非空、有正确角色/阶段的结果，而不依赖模型返回固定措辞。
4. **Given** 某一真实录制场景失败、超时或被中止，**When** 运行结束，**Then** 报告指出失败场景、已观察到的最后进度和录制停止/资源清理结果，其他独立场景不因共享业务状态被误判。
5. **Given** 常规快速回归套件被执行，**When** 开发者未选择真实 Grand Tour，**Then** 常规套件不需要真实凭据、不产生模型费用、不启动真实桌面或浏览器录制且继续使用受控测试行为。
6. **Given** 维护者准备运行真实 Teaching 验收，**When** 进入录制步骤，**Then** 维护者按记录在合同中的安全旅程操作一个专用、无隐私数据的窗口或页面，而不是任意浏览日常内容。
7. **Given** 真实验收已达到最长运行时间或最大付费模型调用数，**When** 流程尚未终止，**Then** 套件中止后续付费工作、停止录制并将预算超限作为明确失败报告。

### Edge Cases

- 长内容由混合换行符、空行或超长单行构成时，折叠判断与预览必须稳定，完整发送内容不得被规范化或截断。
- 用户在折叠预览状态清空内容、切换会话、发送失败或发送成功后，临时折叠状态不得泄漏到另一条草稿或另一页面。
- 粘贴的是文件、图片或非文本内容时，本功能不把它误当作可折叠文本；既有支持或不支持行为保持不变。
- 模型调用发生并发、嵌套后台工作或来源元数据缺失时，调试视图仍显示有序的独立记录；未知来源须明确标记，而非丢弃调用。
- Agent 流转已经发生但缺少可关联的模型调用、下游 session 或额外交接详情时，时间线仍须显示权威转移动作并标注缺失关联，不得把流转节点静默隐藏。
- 现有 workflow transition 已因业务恢复或历史需要而持久保存时，Debug Inspector 可以受控展示这些既有事实；仅为 debug 新增的原始模型记录、关联细节或额外展开材料不得因此变成长久审计日志。
- 调试记录包含用户自行输入的敏感文本时，系统不承诺通过启发式扫描将其移除；调试界面必须提示开发者不要粘贴敏感内容，且记录只能留在当前开启 trace 的本地进程的受控短期缓存内，清空、退出或禁用 trace 后不可再次读取。
- 多模态调用包含截图或其它二进制媒体时，诊断记录不得保存可还原媒体的原始字节或 data URL；媒体内容诊断只使用类型、数量、尺寸/字节数等安全元数据。
- trace 被禁用时，所有 debug-only raw 数据与关联必须立即失效；此前已启动而后完成的调用不得跨 epoch 回填旧内容。
- Trace Inspector 的引用展开属于当前本地进程范围内的广域诊断能力；只要 trace 开关已开启且请求已鉴权，就可能读取并非来自当前选中调用链的现存引用原文。
- 模型调用失败、被取消或未返回正常响应时，应尽可能留下可诊断而不泄密的记录，不能让调试页自身崩溃；若诊断采集本身失败，也不得改变原模型调用的业务结果或原始失败语义。
- 普通日志不能作为 raw 诊断数据的旁路存储；即使启用 debug logging，也不得输出原始 prompt、回复、tool arguments 或委派文本。
- 真实模型未配置、凭据不可用、服务不可达或调用超时时，Grand Tour 应快速给出前置条件或运行失败诊断，不应回退为假成功的 mock 结果。
- Grand Tour 触发设置修改、教学状态变化或创建业务对象时，所有变更必须留在隔离测试环境中；测试不得新增、替换或删除开发者日常 keyring 凭据。
- 开发者在真实 Teaching 录制期间切换到含隐私信息的桌面或浏览器内容时，该内容可能进入录制及后续模型处理；验收必须在启动前警示这一风险，并在失败、中止和正常结束路径均停止录制。

## Requirements *(mandatory)*

### Functional Requirements

#### Long-Paste Composer Experience

- **FR-001**: System MUST provide long-text paste collapsing in both the Assistant message composer and the Skill Teaching chat composer.
- **FR-002**: When pasted text causes the resulting draft to exceed the long-content threshold, the system MUST retain the exact resulting draft, including pre-existing text and insertion/selection behavior, while presenting a compact preview rather than an expanded input surface.
- **FR-003**: Automatic collapse MUST be triggered by qualifying paste interactions only; manually typed content MUST remain editable in the regular input surface.
- **FR-004**: A collapsed draft MUST show a recognizable preview, an indication of omitted content, and a content-size indicator sufficient for the user to understand that the full text is retained.
- **FR-005**: Users MUST be able to expand a collapsed draft, collapse a qualifying expanded draft again, and clear the draft from either relevant state.
- **FR-006**: Sending a collapsed or expanded long draft MUST submit the full unmodified text and MUST reset the temporary preview state after the send is accepted.
- **FR-007**: Long-paste controls MUST be keyboard operable and expose understandable names and state to assistive technology.

#### Local Debug Inspector: Model Trace

- **FR-008**: System MUST provide an authenticated hidden diagnostic surface outside normal end-user navigation. Before trace capture is armed, this surface MAY expose only trace-control state and the sensitive-content warning, not raw diagnostic data. No separate development-build or development-launch gate is required.
- **FR-008A**: Trace capture MUST be armed only by an explicit authenticated action after presenting the sensitive-content warning. `debug.trace.enabled` MUST be a unified-configuration, runtime-only value that defaults to `false` at each sidecar process start; while armed, the application shell MUST display a persistent trace-active indicator with a stop action that disables capture and purges ephemeral data.
- **FR-009**: While trace capture is armed, every text, tool-enabled or multimodal/vision LLM request issued through any supported application LLM invocation path MUST produce a bounded trace record containing retained submitted textual conversation input, available tool definitions for tool-enabled requests, returned content/tool calls or a safe failure outcome, timestamp, and available source association, subject to the configured per-record and aggregate retention budgets. Content that cannot fit those budgets MUST be represented by an explicit safe omission record. For binary media inputs, the trace MUST retain only safe diagnostic metadata and MUST NOT retain restorable raw bytes or data URLs. Embedding/vectorization calls are not trace-content records in this feature; their credentials remain part of the secret/redaction and real-tour provider inventory.
- **FR-010**: Trace records MUST support known source associations for foreground agent work and background cognitive work, and MUST visibly label an invocation whose source cannot be associated instead of omitting it.
- **FR-011**: Developers MUST be able to browse recent traces grouped or filtered by source and associated conversation/work unit and expand an individual trace to see its retained recorded input and output; records omitted because of retention budgets MUST visibly explain that limitation instead of presenting incomplete text as complete.
- **FR-012**: While the trace configuration switch is enabled, an authorized developer MUST be able to request and inline-expand any existing reference content in the current application process, whether or not that reference marker appears in the currently selected trace; missing or unavailable references MUST produce a visible diagnostic.
- **FR-013**: Developers MUST be able to clear recorded traces; trace content MUST be held only in a record-count-and-byte-bounded, process-local debug lifetime and MUST NOT become conversation history, ordinary application logs, or durable analytics data. Oversized content that cannot be retained within the bounded policy MUST remain represented by an explicit omission diagnostic rather than silently disappearing.
- **FR-013A**: Disabling tracing MUST atomically invalidate and purge the current ephemeral trace/flow-detail/correlation epoch; re-enabling in the same process MUST start empty, and any request completing after its capture epoch was disabled MUST NOT repopulate that data. Disable and clear operations MUST fail closed: the epoch becomes unreadable and unwritable before best-effort cleanup, so cleanup failure cannot make old raw data visible again.
- **FR-014**: Trace capture and display MUST preserve retained textual user input and model output needed for debugging while redacting application-known secret configuration values, including primary model, vision-model and embedding credentials where present, sidecar runtime session tokens, and other authorization material controlled by the application. The trace view MUST warn developers not to enter sensitive text of their own into traced interactions; arbitrary user-supplied secret detection is out of scope. The warning MUST at minimum state that raw user/model text may be retained, developer-supplied secrets are not heuristically scrubbed, stop/clear/restart destroy the current epoch, and a visible armed indicator remains available while capture is active.
- **FR-014A**: Ordinary application logs MUST NOT contain raw model prompt/response content, raw tool-call arguments, raw diagnostic handoff/result text, application-controlled credentials or runtime authorization tokens; logs MAY contain redacted identifiers, lengths, source labels and status summaries.
- **FR-014B**: Trace capture, redaction, source correlation and bounded-buffer bookkeeping MUST be failure-isolated from the observed model operation. A diagnostic-side failure MUST NOT block, replace, retry or alter the underlying model request or its returned/raised outcome; it MAY only produce a safe diagnostic omission or unavailable status when possible.
- **FR-015**: Access to trace data and expanded references MUST preserve the current local sidecar authentication boundary and MUST fail closed when the trace configuration switch is disabled or authorization is invalid. Reference expansion is intentionally process-wide while access is enabled and authorized; it is not constrained to the selected trace or source group. Large reference responses MUST be bounded through an explicit limit, truncation marker or chunking contract rather than returned as unbounded raw text.

#### Local Debug Inspector: Agent Flow

- **FR-016**: Under the same trace configuration switch and sidecar authorization boundary, the system MUST provide an Agent Flow view that presents agent-to-agent handoffs and workflow state movements alongside model traces without adding a normal end-user navigation entry.
- **FR-017**: Agent Flow MUST show a chronological, workflow-scoped timeline of authoritative orchestration transitions, including agent start or resumption, waiting for user input, task/requirement handoff, completion, review/rejection, retry or backtrack, failure, and terminal publication or completion where applicable.
- **FR-018**: Each visible flow transition MUST identify its workflow or parent-task correlation, ordering/time, originating agent or stage, receiving agent or terminal stage when applicable, transition/status type, triggering reason where available, and inspectable handoff/result information.
- **FR-019**: Agent Flow MUST cover at minimum the Teaching pipeline paths `PM -> Programmer`, `Programmer -> Review -> Programmer` retry or acceptance, `Trial -> PM` failure triage and onward rerouting/publication, plus Assistant delegation to an ephemeral subagent or fixed specialist and the resulting return to Assistant.
- **FR-020**: Developers MUST be able to navigate from a flow transition to any correlated LLM trace records and from a correlated LLM trace back to its workflow flow context; a transition without a captured model trace MUST remain visible and be labeled as unlinked rather than omitted.
- **FR-021**: The debug view MUST let authorized developers inspect the actual diagnostic handoff/result content necessary to understand a transition, such as confirmed requirements delivered to Programmer, review feedback, trial/triage feedback, delegated task text, and delegated result text, subject to the same known-secret/runtime-token redaction and sensitive-content warning as raw model traces. Where an existing persisted transition does not already contain delegated task/result text, that detail MUST be captured only as trace-enabled process-local diagnostic material and visibly marked as ephemeral.
- **FR-022**: Flow representation MUST reflect authoritative orchestration/transition facts rather than being reconstructed solely from model prose or end-user progress presentation. The feature MUST NOT use the ordinary public UI event stream or ordinary logs to expose raw handoff material that is only needed for debugging.
- **FR-023**: If a workflow transition already persists as part of existing business recovery/history behavior, the authorized debug view MAY display that existing transition after process restart and MUST label it as an existing retained fact. Any newly captured raw model trace, extra raw handoff/detail/result content, or trace-correlation enrichment introduced only for this inspector MUST remain bounded and process-local, MUST be cleared by the ephemeral lifecycle controls, and MUST NOT create new durable diagnostic history.

#### Real Grand Tour Acceptance

- **FR-024**: System MUST provide an explicitly opt-in, manually initiated Grand Tour acceptance suite that uses a real local backend session and the developer's already configured real model capability, with a clear notice that running it may consume paid model usage.
- **FR-025**: The real Grand Tour MUST exercise independently reportable scenarios for application readiness, Assistant response, Skill Teaching progression through a real current-desktop or current-browser recording journey, skills/compositions visibility or modification, settings interaction, and cross-screen navigation stability. The recording journey MUST follow a documented, repeatable sequence against an operator-prepared non-sensitive target window or page.
- **FR-026**: Long-running Grand Tour scenarios MUST advance from observable public workflow status or completion signals rather than fixed-duration waiting as their primary synchronization method.
- **FR-027**: Assertions involving model output MUST validate workflow completion, role/stage correctness and non-empty usable output, and MUST NOT depend on exact model-generated wording.
- **FR-028**: Each Grand Tour scenario MUST run against isolated disposable business data and isolated non-secret configuration and MUST clean up its runtime resources. Every real-tour-reachable credential or model construction path, including main, vision, background, settings connection validation, skill-composition/trial helpers, compression, embedding credential lookup and diagnostic redactor inventory, MAY read the developer's securely configured model credential only through an explicitly injected, side-effect-free read-only resolution path, or MUST be skipped before construction as an unmet prerequisite. These paths MUST NOT execute migration, plaintext-config fallback, create, replace, delete, or otherwise mutate the developer's keyring credential or ordinary product data.
- **FR-029**: A failed or timed-out Grand Tour scenario MUST report its last observable workflow state and enough non-secret diagnostic context to identify the failing journey.
- **FR-030**: Existing routine frontend regression execution MUST remain runnable without a real model credential or paid model call; the real Grand Tour MUST not silently replace the controlled fast suite.
- **FR-031**: Before a real Grand Tour Teaching scenario starts capturing the developer's current desktop or browser activity, the system MUST warn that visible/private content may be recorded and processed by the configured model. Capture MUST occur only during an explicitly manually initiated real Grand Tour run and MUST stop on success, failure, timeout, or cancellation.
- **FR-032**: A real Grand Tour run MUST enforce an explicit paid-call and elapsed-time budget, initially no more than 30 model requests and 20 minutes per run, and MUST fail with cleanup rather than continue after either budget is exhausted.
- **FR-033**: Controlled automated verification MUST exercise real-tour runner failure paths, including timeout/cancellation, recording cleanup and attempted secret mutation rejection, without requiring a paid model call or live desktop capture.
- **FR-034**: Each manually initiated real Grand Tour run MUST emit a non-sensitive summary report associated with the tested commit and scripted journey identity, containing per-scenario outcomes, last observable states, budget usage, cleanup status and credential-mutation result, while excluding prompt/response text, captured media and credential material.

### Key Entities *(include if feature involves data)*

- **Composer Draft**: The user's unsent text in Assistant or Skill Teaching, including temporary presentation state for long pasted content; it is not new durable business data.
- **LLM Trace Record**: A process-local diagnostic record for one model interaction, carrying source association, work/session association where available, retained textual input, safe media metadata where applicable, result or safe failure, optional tool-call detail, byte accounting and creation time.
- **Trace Arm State**: The runtime-only current-sidecar authorization state indicating whether new raw diagnostic material may be captured; it is activated only after warning acknowledgement and is reset by disable or process restart.
- **Trace Source/Work Group**: A developer-facing grouping of trace records for a foreground conversation or background cognitive operation, used to locate a chain of related calls.
- **Agent Flow Timeline**: A workflow- or delegation-scoped chronological diagnostic view that connects agent starts, handoffs, waits, retries, failures and completions with available correlated model traces.
- **Workflow Transition / Handoff**: An authoritative orchestration movement from one agent/stage to another agent/stage or a terminal state; existing persisted facts remain distinguishable from any trace-enabled, process-local extra transfer/result detail.
- **Expanded Reference View**: Original content revealed on demand from any reference still addressable in the current process, subject to the same trace-enable and session-authorization boundary; it need not originate in the selected trace.
- **Grand Tour Run**: One opt-in real acceptance execution with isolated business data, injected side-effect-free credential read access, a scripted non-sensitive live recording journey, paid-call/time budgets, explicit capture consent warning, per-scenario results, observed workflow progress, recording/resource cleanup outcome and a non-sensitive evidence report.

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: The feature MUST preserve the existing desktop layering: frontend UI uses typed bridge contracts, the desktop API remains an adapter, and model/business behavior remains owned by business services rather than UI or router code.
- **CC-002**: Debug inspection intentionally exposes retained raw textual prompt/response and diagnostic handoff/result content, including user-supplied text, for local diagnosis. Capture MUST be disabled by default at each sidecar start and MAY only be armed for the current process through an authenticated, warning-gated runtime-only unified-configuration action. While armed, a visible trace-active indicator and stop action MUST remain available. Newly captured raw diagnostic material MUST remain count/byte bounded in memory, omit restorable multimodal bytes, purge on clear/disable/restart, and never persist, enter ordinary logs, enter browser/WebView caches, or enter frontend persisted state/URLs. A locally packaged/user-mode run MAY arm tracing after the same explicit warning; there is no additional build-mode gate. The application MUST redact all application-controlled credentials and runtime authorization material, but does not promise heuristic removal of secrets independently pasted by the developer.
- **CC-002A**: Authorized reference expansion is deliberately not trace-scoped: with tracing enabled, it MAY reveal any reference content still addressable in the current local process. The accepted protection boundary is explicit trace enablement, current sidecar session authentication, process-local lifetime, and no durable trace/reference export.
- **CC-002B**: Agent Flow MAY expose existing persisted workflow transitions already retained for workflow continuity, recovery or history, including their existing payloads where authorized. Existing Assistant delegation facts do not imply persisted raw task/result content; any additional raw delegated task/result view introduced by this feature MUST be ephemeral, trace-gated and visibly distinguished from retained business facts.
- **CC-003**: Debug configuration MUST use the unified configuration boundary. `debug.trace.enabled` MUST be runtime-only and changed only through the authenticated diagnostic control facade, not ordinary Settings persistence; record-count/aggregate-byte/per-record limits MAY be hidden non-secret unified configuration values. This feature introduces no plaintext secret storage or ordinary Settings-page exposure unless a later specification explicitly adds that UI.
- **CC-004**: The real Grand Tour is an explicit manual acceptance exception to the default controlled/mock frontend E2E convention. Routine E2E remains controlled and cost-free; the real run may resolve a pre-existing secure model credential only through an injected no-migration, no-plaintext-fallback, no-write, no-delete provider used by every real-tour-reachable credential/model/redactor path, including main, vision, background, settings validation, skill-composition/trial helpers, compression, embedding credential lookup and diagnostic redaction. Uncovered paths MUST be skipped before construction or fail as unmet prerequisites. The suite MUST restrict settings writes to an isolated non-secret configuration and monitor that keyring mutation remains zero. Implementation MUST update the applicable active project/module guidance so the exception is documented.
- **CC-005**: The Grand Tour MAY observe existing public UI workflow events and authenticated product contracts, but MUST NOT bypass sidecar authorization, expose unsafe internal event payloads, or depend on private database reads.
- **CC-005A**: The real Grand Tour Teaching journey intentionally MAY capture a real desktop or browser target. It MUST remain manual/opt-in, warn before capture, use the documented non-sensitive scripted journey for release evidence, preserve the existing recording filtering and mode boundaries, enforce time/paid-call budgets, and guarantee stop/cleanup handling; unattended CI execution of this real-capture journey is out of scope.
- **CC-006**: The debug inspector MUST cover model work introduced by `010-assistant-brain-redesign` and every supported text/tool/vision LLM invocation path, including vision paths that may currently bypass chat wrappers, and MUST surface genuine Assistant-to-executor delegation transitions. Embedding/vectorization calls are excluded from trace record coverage for this feature but remain subject to credential inventory and no-leak verification. The inspector MUST observe, not change, assistant prompts, agent dispatch semantics, memory semantics, model outcomes, provider failure semantics or the PM/Programmer/Trial workflow behavior solely to support inspection; any failure in observation must fail isolated.
- **CC-007**: This feature does not add rich clipboard attachment handling, trace exporting/persistence, remote debugging, production trace collection, or deterministic grading of model prose.

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

Which layers are affected? Check all that apply:

- [x] **UI** (`frontend/src/`, `src-tauri/`) — Assistant/Teaching composer behavior, a hidden authenticated debug activation/data surface, and a trace-active application-shell indicator with stop action; no new window capability is required.
- [x] **Desktop API Bridge** (`src/desktop_api/`) — authenticated control/data contracts for runtime-only trace arming, model traces, workflow/delegation flow visibility, clearing ephemeral traces, and authorized reference expansion.
- [x] **Business** (`src/business/`) — business-owned trace control facade, failure-isolated observation at a unified model invocation boundary covering text/tool/vision calls, safe logging, secret registration and authoritative agent orchestration/delegation transitions plus ephemeral debug-only delegation detail, without changing model decisions or dispatch behavior.
- [ ] **Execution** (`src/execution/`) — tool execution sandbox
- [x] **Data** (`src/data/`) — runtime-only unified configuration value for trace enablement, hidden record/byte retention values and an injectable side-effect-free real-tour credential resolver only; no new business-record persistence.
- [x] **Recording** (`src/recording/`) — existing desktop/browser capture and filtering boundaries are exercised by the manually initiated real Teaching acceptance journey; no new bypass is permitted.
- [x] **Utils** (`src/utils/`) — transient trace context/buffer support or equivalent shared diagnostic facility.

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: Assistant, ephemeral subagents, specialists, PM, Programmer and Trial are observable through their genuine transitions; existing background brain/model workers remain observable through model traces unless they participate in an actual handoff. No agent behavior is changed by this feature.
- New tools or modified tool handlers? None required for agent decisions; reference expansion is a developer inspection capability over an already authorized reference-loading boundary.
- System prompt changes needed? None. The inspector observes actual prompts but does not alter them.
- Orchestrator dispatch changes? None in behavior; existing or observed transition facts and invocation sources may carry diagnostic correlation while debug tracing is enabled, so the inspector can connect a handoff to its relevant model calls.

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): No new trace persistence solely for inspection; the inspector may read existing workflow-transition history already persisted for orchestration continuity/recovery, while real Grand Tour uses isolated disposable application data.
- **DuckDB** (`src/recording/filtering/`): No new storage behavior is required; real Teaching acceptance may generate disposable recording data, and no filtering boundary may be bypassed.
- **Config** (`src/data/unified_config.py`): Trace enablement is a runtime-only unified-config arm set by the authenticated debug control facade; it defaults off on each sidecar start and drives epoch creation/purge. Record-count/byte retention limits remain hidden non-secret unified configuration values.
- **Secrets** (keyring): No new secret fields; manual Grand Tour main/vision/background client factories and diagnostic redactor may resolve an already configured credential only through an injected side-effect-free read-only provider, and may not trigger plaintext fallback, migration, save, replace or delete actions.

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: None required by the specified product behavior; Agent Flow must follow authoritative orchestration transitions rather than invent an event-triggered dispatch mechanism.
- Modified event payloads: None required for the ordinary product event stream. Existing user-visible output such as `assistant.message.content` remains legitimate product output; only diagnostic-only raw prompt/trace/handoff/media/correlation material must remain behind its authenticated diagnostic contract rather than expanding the allowlisted stream. If Grand Tour needs a missing public workflow completion signal, it must be designed as a safe allowlisted UI event contract before use.
- New event listeners: Manual acceptance-test observation of the authenticated UI event stream only; it does not create a new source of business truth or carry debug-only raw flow payloads.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In both Assistant and Skill Teaching acceptance tests, 100% of qualifying long-text pastes display a compact preview while sending exactly the full draft text, including cases with existing text before and after the pasted insertion.
- **SC-002**: A user can expand, re-collapse, clear, or send a qualifying pasted draft by keyboard in each supported composer, and manual multi-line typing triggers zero automatic collapses.
- **SC-003**: After acknowledging the warning and arming trace for the current sidecar session, a developer can locate and expand a completed foreground or background model interaction within 30 seconds of triggering it, including its retained recorded input and outcome or an explicit retention-budget omission reason.
- **SC-004**: For a verification set containing at least one invocation from each supported available text/tool/vision LLM call source, including an available vision source, 100% of invocations appear as trace records or as explicitly labeled unknown-source/oversized-detail records; none disappear silently, and zero restorable media bytes appear in trace responses. Embedding/vectorization calls are verified through credential/redaction/provider inventory rather than trace-record presence.
- **SC-005**: In verification, clearing traces, disabling then re-enabling tracing, or restarting the process leaves zero previously captured prompt/response or debug-only flow-detail records accessible from backend APIs, frontend state, URLs and browser/WebView caches; primary/vision/embedding credential sentinel values and runtime authorization tokens appear zero times in displayed trace data or ordinary logs, while retained developer-entered text is otherwise preserved verbatim for diagnosis. When tracing is enabled and the caller is authorized, an existing reference outside the selected trace can be expanded successfully within the configured response limit or chunking contract.
- **SC-006**: On a configured developer machine, the opt-in real Grand Tour completes its documented non-sensitive scripted live journey and all defined primary scenarios successfully in 3 consecutive manual runs for the same tested commit and journey identity, with each run producing a non-sensitive summary report of scenario outcomes, budget usage and cleanup status and with zero mutation of the developer's keyring credentials. Release evidence may cite only safe summary fields such as run id, commit, journey id, scenario outcomes, cleanup status, budget usage and credential mutation count.
- **SC-007**: Routine frontend regression runs require zero real-model credentials and initiate zero paid model calls when the developer has not explicitly chosen the real Grand Tour.
- **SC-008**: A failing or timed-out real Grand Tour scenario reports the last observed non-secret progress state for 100% of failures in acceptance verification, enabling the developer to distinguish readiness, model, workflow and cleanup failures.
- **SC-009**: In 100% of real Teaching acceptance runs, a capture/privacy warning is shown before the scripted target window or browser page recording begins, and no recording remains active after success, failure, timeout, cancellation or budget exhaustion.
- **SC-010**: In verification workflows containing PM-to-Programmer handoff, review rejection and retry, Trial failure triage, and Assistant-to-executor delegation, 100% of expected agent/stage transitions appear in chronological Agent Flow order with source, target or terminal state and trigger/status; existing persisted detail and trace-enabled ephemeral delegated task/result detail are visibly distinguished.
- **SC-011**: For each flow transition that has correlated model work captured in the current process, a developer can navigate between the transition and its LLM trace within two interactions; transitions without model correlation remain visible and explicitly marked unlinked.
- **SC-012**: Verification finds zero diagnostic-only raw prompt/trace content, raw handoff/media/correlation payloads or application-controlled secret values in ordinary public UI event output, ordinary application logs, HTTP/WebView caches, frontend persisted state, URL/query/hash values or real-tour artifacts. Existing user-visible product messages such as `assistant.message.content` and authorized workflow-transition history remain available according to their pre-existing product/lifecycle contracts.
- **SC-013**: Under configured trace record, reference-response and byte budgets, oversized text/media/tool/reference inputs produce an explicit safe omission/truncation/chunking diagnostic and the process-local buffer never exceeds its configured aggregate retention budget.
- **SC-014**: Controlled runner verification covers timeout, cancellation, cleanup and credential mutation rejection without live capture or paid calls; manual real runs abort safely once the 20-minute or 30-paid-call budget is reached.
- **SC-015**: Verification proves that an authenticated warning acknowledgement is required before trace capture starts, a trace-active stop control remains visible while armed, disabling immediately purges the epoch, and a new sidecar process begins with trace unarmed regardless of the previous session state.
- **SC-016**: With diagnostic capture/redaction/buffer failures injected, 100% of representative successful and provider-failed model operations preserve their original product outcome or provider failure semantics while exposing at most a safe diagnostic-unavailable indication.

## Assumptions

- The three documents under `docs/local/todo/` describe one intended feature scope; they are input notes rather than active architecture authority.
- Long-content qualification will use a product-defined threshold chosen during planning; this specification fixes behavior, not a particular line count or visual height.
- Trace capture defaults to disabled on every sidecar process start and is intentionally armed only for the current process through an authenticated hidden diagnostic control after warning acknowledgement; because there is no separate development-run gate, a locally packaged/user-mode run may perform the same explicit arm operation.
- Captured textual trace and expanded reference content may contain private user text or sensitive strings deliberately typed by a developer, so an epoch-scoped count/byte-bounded lifetime, an in-view warning and explicit clear/disable semantics are sufficient for this locally enabled diagnostic use case; reference access is intentionally process-wide while authorized, and heuristic redaction of arbitrary user text, restorable media capture, export, durable audit and multi-user authorization are out of scope.
- Existing workflow transitions are already authoritative business artifacts for Teaching or delegated-work continuity/recovery; Agent Flow displays those facts when authorized, while additional Assistant delegated task/result detail and raw LLM/diagnostic correlation captured only for inspection remain process-local.
- Background brain processing that performs model work without dispatching one Agent to another appears in the model trace view rather than being invented as an Agent Flow handoff.
- Existing Assistant brain work and all supported text/tool/vision LLM users, including vision helpers, will be brought under a shared observable invocation boundary; direct provider calls are a coverage risk to audit before implementation is accepted. Embedding/vectorization users are out of trace record scope for this feature, but must remain in credential inventory and direct-call guard allowlists.
- The developer running the real Grand Tour accepts real provider cost and has already configured a valid model credential through the normal secure application setup; the suite resolves that credential only through a no-side-effect read path and validates setting-save behavior using isolated non-secret configuration.
- The developer who manually starts a real Grand Tour Teaching run accepts that the prepared target window or browser page will be recorded and processed by the configured model; release evidence follows the documented non-sensitive script rather than arbitrary day-to-day content.
- Existing controlled frontend tests remain the default quick regression mechanism; the real Grand Tour is a separate manual acceptance gate whose documented exception is limited to that suite.
