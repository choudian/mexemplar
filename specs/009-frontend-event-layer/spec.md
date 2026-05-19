# Feature Specification: Frontend Event Layer

**Feature Branch**: `009-frontend-event-layer`
**Created**: 2026-05-16
**Status**: Completed
**Input**: User description: "Specify the frontend event layer refactor described in docs/design/todo-frontend-event-layer.md: backend-owned UI event projection, typed frontend event consumption, per-subscriber event streaming, resync behavior, and interactive preview confirmation."

## Clarifications

### Session 2026-05-16

- Q: 重连恢复时，前端和后端应采用哪种事件补偿语义？ → A: 前端携带 last-seen sequence；后端只回放当前桌面会话缓冲内可覆盖的事件，若序号缺口、会话不匹配或缓冲已丢失，则要求 resync 并以权威快照恢复。
- Q: 试用预览确认请求的超时语义应由谁定义？ → A: 每个预览请求包含后端生成的 `expires_at`；前端到期禁用操作，后端到期返回 deny/timeout。
- Q: 当 UI event payload 安全校验发现敏感字段或禁止内容时，应采用哪种处理语义？ → A: 拒绝发布该事件；如界面必须恢复状态，只能发布另一个已注册、allowlisted 的安全 resync/summary 事件。
- Q: 多个事件订阅者同时存在时，试用预览确认请求应如何投递和消费？ → A: 请求按作用域广播给所有活跃订阅者；后端只接受 `expires_at` 前第一个有效决策，后续重复/相反决策返回已解决或冲突且不能改变结果。
- Q: 公开 UI event contract 的权威来源应如何定义？ → A: 后端 UI Event Registry 是权威来源；前端事件类型、示例负载和枚举必须由该注册表生成或通过同一导出契约校验。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 前端只消费明确的界面事件 (Priority: P1)

作为桌面应用用户，我希望界面能够根据清晰、稳定的界面事件展示教学阶段、录制状态、试用结果、技能刷新和通知，而不是因为内部业务事件命名变化导致界面行为漂移。

**Why this priority**: 这是本功能的核心价值。只有先建立稳定的界面事件语义，后续录制、教学、试用和技能列表的状态展示才不会继续依赖内部事件名。

**Independent Test**: 可以通过触发一次完整教学流程并观察界面状态、通知和计数更新来独立验证；验证时前端不得依赖内部事件名或内部事件来源字段做展示决策。

**Acceptance Scenarios**:

1. **Given** 用户处于教学流程中，**When** 后端产生阶段、失败、录制、试用或技能目录变化，**Then** 界面收到语义化界面事件并更新对应本地状态。
2. **Given** 一个内部业务事件没有公开界面语义，**When** 该事件被发送，**Then** 它不会默认出现在前端事件流中，也不会生成泛化的前端展示事件。
3. **Given** 同一业务事实需要同时影响多个界面区域，**When** 该事实被通知，**Then** 前端收到按顺序关联的一组界面事件，并且每个界面区域只按自身支持的事件类型更新。

---

### User Story 2 - 事件流断开后界面能恢复权威状态 (Priority: P2)

作为桌面应用用户，我希望在热刷新、网络抖动、慢连接或事件流重连后，教学阶段、成功次数、技能目录和设置状态不会回退、丢失或被旧快照覆盖。

**Why this priority**: 事件流是当前桌面会话内的通知通道，不做长期重放；如果断线恢复不可靠，用户会看到错误阶段、错误计数或过期列表。

**Independent Test**: 可以通过建立多个事件订阅者、强制断开其中一个订阅者并重新进入当前屏幕来验证；恢复后界面状态必须与权威快照一致。

**Acceptance Scenarios**:

1. **Given** 两个前端连接同时订阅事件流，**When** 后端发布一条界面事件，**Then** 两个连接都收到该事件，且不会互相抢占。
2. **Given** 某个订阅者处理事件过慢，**When** 它的事件积压超过允许边界，**Then** 该订阅者收到重新同步提示并关闭当前事件流，其他订阅者继续正常接收事件。
3. **Given** 前端事件流断开，**When** 前端重新连接并刷新当前界面状态，**Then** 新到达的事件在快照写入后按顺序回放，不会出现旧快照覆盖新事件的状态回退。

---

### User Story 3 - 需要用户确认的试用预览安全闭环 (Priority: P3)

作为桌面应用用户，我希望在试用动作需要事前确认时，界面显示可理解的预览和风险摘要，并且我的批准或拒绝能明确返回给等待中的后台流程。

**Why this priority**: 试用预览涉及本地执行风险，必须保持独立确认生命周期，不能被普通通知或 toast 替代。

**Independent Test**: 可以通过触发一次需要预览确认的试用请求来验证；用户批准时后台流程继续，用户拒绝、超时或断开时后台流程得到明确拒绝。

**Acceptance Scenarios**:

1. **Given** 试用流程生成一个需要确认的预览请求，**When** 用户在界面中查看请求，**Then** 界面只展示脱敏且截断后的预览和风险摘要。
2. **Given** 用户批准该预览请求，**When** 决策被提交，**Then** 等待中的后台流程收到批准结果，且该请求不能被再次消费为相反决策。
3. **Given** 用户拒绝、请求超时、事件流断开或应用关闭，**When** 后台流程等待确认结果，**Then** 结果必须是明确拒绝，而不是默认批准。

---

### User Story 4 - 开发者能验证事件契约没有漂移 (Priority: P4)

作为项目维护者，我希望后端发布的界面事件、前端可处理的事件类型、示例负载和枚举值保持一致，并且任何绕过事件层或泄露敏感字段的变更会被测试发现。

**Why this priority**: 该功能会改变跨模块契约，必须通过自动化检查防止前后端类型漂移、未知事件默认转发和敏感数据进入界面事件。

**Independent Test**: 可以通过运行契约一致性和守卫测试独立验证；测试应能发现未注册事件、旧事件来源字段、裸事件发布和敏感字段泄露。

**Acceptance Scenarios**:

1. **Given** 新增或修改一个公开界面事件，**When** 契约测试运行，**Then** 后端事件模型、前端事件类型和示例负载必须保持一致。
2. **Given** 代码尝试把内部业务事件直接暴露给前端，**When** 守卫测试运行，**Then** 该变更被报告为失败。
3. **Given** 事件负载包含令牌、密钥、完整代码、完整命令体或未脱敏错误详情，**When** 发布前校验运行，**Then** 该事件不会作为普通界面事件发送。

### Edge Cases

- 事件发布期间订阅者注册或断开，系统不得丢失其他活跃订阅者的事件，也不得因为并发状态变化导致发布失败。
- 同一个业务事实产生多条界面事件时，这些事件必须保持可关联，并按声明顺序被前端处理。
- 事件序号在同一桌面会话内必须唯一且单调递增；进程重启后前端不得跨会话比较序号。
- 前端收到重复事件、重复消息或重复 toast 时，应以事件 ID、消息 ID 或去重键避免重复展示。
- 前端收到无法解析的事件帧、半帧或非事件心跳时，不能把无效内容写入界面状态。
- 权威阶段、状态、成功次数、发布状态等持久界面状态缺少可信来源时，不得用推测值伪造界面状态。
- 未知内部事件和控制型内部事件不能作为普通界面通知出现。
- 高危确认、试用预览确认和普通 toast 的生命周期必须互不干扰。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose a single public desktop UI event contract for the frontend event stream.
- **FR-002**: System MUST prevent frontend state handlers from using internal domain event names or source-event fields to decide display behavior.
- **FR-003**: System MUST classify internal events as notification, interactive, or control events before any frontend-facing event is produced.
- **FR-004**: System MUST publish only explicitly registered UI event types to the frontend event stream.
- **FR-005**: System MUST avoid default forwarding of unknown internal events to frontend consumers.
- **FR-006**: System MUST convert relevant notification events into zero or more semantic UI events for teaching, recording, trial, skills, compositions, settings, assistant, or backend resync behavior.
- **FR-007**: System MUST require authoritative state values, such as stage, status, failure status, success count, and published state, to come from trusted event payloads or refreshed snapshots rather than inferred guesses.
- **FR-008**: System MUST provide a standard event envelope containing event ID, sequence, causation ID, event type, scope, payload, and creation time for every public UI event.
- **FR-009**: System MUST assign event sequence values that are unique and monotonically increasing within one desktop session.
- **FR-010**: System MUST preserve ordering for multiple UI events produced from the same underlying cause.
- **FR-011**: System MUST deliver each published UI event to every active event subscriber without subscribers competing for the same event.
- **FR-012**: System MUST detect slow or overflowed subscribers and require those subscribers to resynchronize without blocking event producers or other subscribers.
- **FR-013**: System MUST support reconnect recovery by allowing the frontend to reconnect the event stream with its last-seen sequence, replay same-session buffered events in order when the buffer fully covers the gap, and require resync through authoritative snapshots when the session does not match, a sequence gap exists, or buffered events are no longer available.
- **FR-014**: System MUST treat catalog, settings, and resync events as invalidations that cause authoritative state refresh instead of complete business facts.
- **FR-015**: System MUST keep ordinary notifications separate from assistant high-risk confirmations and trial preview confirmations.
- **FR-016**: System MUST broadcast each trial preview request to all active subscribers in the request scope, allow users to approve or deny the request from the frontend, accept only the first valid decision received before `expires_at`, and ensure later duplicate or conflicting decisions report an already-resolved or conflict outcome without changing the backend result.
- **FR-017**: System MUST include a backend-generated `expires_at` value on each trial preview request, disable frontend approval/denial submission after that deadline, and fail closed for interactive preview requests when the user denies, the request expires, the stream disconnects, the subscriber overflows, or the application shuts down.
- **FR-018**: System MUST ensure UI event payloads contain only allowlisted, user-safe fields.
- **FR-019**: System MUST reject any public UI event that would expose runtime tokens, secrets, full code, full command bodies, unredacted stack traces, database paths, raw query results, or unfiltered recording data; if frontend recovery is still required, the system MUST publish a separate registered, allowlisted, user-safe resync or summary UI event instead.
- **FR-020**: System MUST treat the backend UI Event Registry as the authoritative source for the public UI event contract and provide automated validation or generation that keeps frontend event types, example payloads, enum values, and handlers synchronized with that registry.
- **FR-021**: System MUST provide guard coverage that prevents direct frontend-event publishing paths from bypassing validation, envelope creation, and safety checks.
- **FR-022**: System MUST maintain existing architectural layering: UI consumes public desktop contracts, backend business components emit internal facts, and lower layers do not depend on frontend-specific contracts.

### Key Entities *(include if feature involves data)*

- **Domain Event**: An internal backend fact or request used for coordination between backend components; it is not a frontend display contract.
- **UI Event**: A public desktop-session notification with a stable type, scope, payload, ordering metadata, and safety-checked user-facing semantics.
- **UI Event Envelope**: The common metadata wrapper that makes events traceable, ordered, scoped, and deduplicatable.
- **Subscriber**: A frontend event-stream connection that receives its own copy of each published UI event.
- **Authoritative Snapshot**: Current business state retrieved by the frontend after reconnect or invalidation to recover from missed short-lived events.
- **Interactive Request**: A pending user decision with a backend-generated expiration deadline and single-consumption decision semantics that must return an explicit approve or deny result to the backend workflow.
- **UI Event Registry**: The backend-owned authoritative list of public event types, payload shapes, examples, and allowed enum values used to generate or validate frontend event contracts.

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: The backend internal event mechanism remains the source for cross-module backend notifications.
- **CC-002**: Business, execution, recording, and data components must not depend on frontend, desktop UI, or event-stream delivery concerns.
- **CC-003**: The frontend must not read repositories, local databases, configuration files, keyring values, or lower-level storage directly to compensate for missing event data.
- **CC-004**: The sidecar event stream must require the runtime session header; the runtime token must not appear in URLs, cookies, persistent storage, logs, event payloads, or error responses.
- **CC-005**: The feature performs a single final-contract cutover; the frontend does not need to consume old and new event contracts in parallel after the cutover.
- **CC-006**: UI events are session-scoped notifications and must not be treated as persistent business facts or a long-term replay log.
- **CC-007**: Existing high-risk assistant confirmation semantics must remain independent from ordinary toast notifications.
- **CC-008**: Documentation for the desktop event stream, architecture boundaries, and project constraints must be updated when the event contract becomes current behavior.

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

Which layers are affected? Check all that apply:

- [x] **UI** (`frontend/src/`, `src-tauri/`) — React screens, state, API client, Tauri shell, or window commands
- [x] **Desktop API Bridge** (`src/desktop_api/`) — FastAPI routers, schemas, event stream adapters, or sidecar contracts
- [x] **Business** (`src/business/`) — agents, orchestration, services, memory
- [x] **Execution** (`src/execution/`) — tool execution sandbox
- [ ] **Data** (`src/data/`) — models, repositories, migrations, config
- [x] **Recording** (`src/recording/`) — recorder, filtering, browser extension
- [x] **Utils** (`src/utils/`) — events, helpers

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: Assistant, PM, Programmer, Trial
- New tools or modified tool handlers? No new user-facing tools are required; existing flows may need normalized event fields and explicit confirmation outcomes.
- System prompt changes needed? None expected.
- Orchestrator dispatch changes? Existing dispatch should preserve current behavior while emitting enough authoritative state for UI event projection.

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): No new persistent tables are expected; any state displayed after reconnect must be available through existing authoritative business views or explicitly planned extensions.
- **DuckDB** (`src/recording/filtering/`): No raw recording data should be added to UI events; existing filtering and redaction boundaries must remain authoritative.
- **Config** (`src/data/unified_config.py`): No persistent "allow all" or event replay configuration is expected.
- **Secrets** (keyring): No new secret fields are expected; event payloads must not expose keyring values or runtime authentication material.

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: Only if a backend workflow needs to emit a formally named internal fact that does not already exist.
- Modified event payloads: Existing internal event senders may need normalized fields for workflow identity, stage, status, failure status, success count, publication state, user-safe messages, and catalog invalidation scope.
- New event listeners: A desktop-side event adapter should listen only to registered internal events and route them into the public UI event contract.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of frontend event-store display decisions for teaching, recording, trial, skills, compositions, settings, assistant, and backend resync are based on registered UI event types rather than internal event names.
- **SC-002**: 0 unknown internal events are forwarded by default to the frontend event stream during automated event routing tests.
- **SC-003**: Two simultaneous subscribers receive the same published UI event in at least 20 consecutive automated trials, with no event stealing between subscribers.
- **SC-004**: Slow subscriber handling produces a resync-required outcome for the slow subscriber while allowing a healthy subscriber to continue receiving subsequent events in the same test run.
- **SC-005**: Reconnect recovery preserves authoritative teaching stage and trial success count across at least 10 simulated disconnect-and-resync cycles without state rollback.
- **SC-006**: 100% of public UI event payload examples pass safety validation for runtime tokens, secrets, full code bodies, full command bodies, raw stack traces, local database paths, and unfiltered recording data.
- **SC-007**: Trial preview confirmation returns approve, deny, timeout, disconnect, overflow, and shutdown outcomes deterministically in automated tests, with all non-approve outcomes treated as denial.
- **SC-008**: Contract consistency tests detect any UI event type present only on the backend or only on the frontend.
- **SC-009**: Existing core desktop teaching, recording, trial, skills, and assistant flows remain demonstrable after the cutover with no user-visible regression in stage display, notification display, or count display.

## Assumptions

- The source design document is the intended scope for this feature, and its "one final contract" direction is accepted for specification purposes.
- The feature targets the current desktop application and does not add browser-only, mobile, or remote multi-user event semantics.
- UI events remain current-session notifications; persisted business truth is recovered through bootstrap and screen-specific authoritative state APIs.
- Existing backend flows remain responsible for business decisions; this feature changes event projection and frontend consumption boundaries, not the underlying product workflow.
- Existing security rules for runtime session authentication, keyring-managed secrets, and recording data redaction remain mandatory.
