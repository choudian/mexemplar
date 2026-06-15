# Feature Specification: 结构化多选澄清 (Structured Multi-Choice Clarification)

**Feature Branch**: `019-structured-user-clarification`
**Created**: 2026-06-15
**Status**: Completed
**Input**: User description: "新增主助理专属 ask_user_question 工具：一次询问 1–4 题，每题 2–4 个选项，单/多选 + 始终可用的"其他"自由输入，以输入框上方非模态卡片整组提交，默认 5 分钟超时，超时/取消/停止均不允许模型猜测答案，请求仅存于当前 sidecar 内存。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 主助理在关键岔路口征询用户决策 (Priority: P1)

主助理在执行任务时遇到一个**无法可靠推断**的关键决策（例如：多个文件命名约定都合理、目标范围有歧义、需要在两种执行策略中二选一）。它不再凭猜测继续，也不再用一长串纯文本反复追问，而是一次性抛出一组结构化问题。用户在聊天输入框**上方**看到一张非模态卡片，每个问题以单选或多选形式列出 2–4 个候选项，并始终带一个"其他"自由输入框；用户整组勾选后一次提交，主助理拿到答案后在**同一回合内**继续往下推进。

**Why this priority**: 这是该功能存在的核心价值——把"模型猜错方向后返工"替换为"在岔路口低成本对齐一次"。没有这条用户故事，整个功能没有意义；它本身即可独立交付一个可用的 MVP。

**Independent Test**: 构造一个主助理任务，让模型调用 `ask_user_question` 提出一道单选题；验证 UI 在输入框上方渲染卡片、用户提交后工具结果回填进上下文、主助理在同一 AgentLoop 内消费答案并继续，且全程未新增数据库/迁移/配置。

**Acceptance Scenarios**:

1. **Given** 主助理正在处理一个有歧义的任务，**When** 模型单独调用 `ask_user_question` 提出 1 道 3 选项单选题，**Then** 前端在输入框上方显示非模态澄清卡片，主助理回合在等待用户期间保持挂起而不报错。
2. **Given** 卡片已显示，**When** 用户选择某一选项并提交，**Then** 工具返回 `status="answered"` 与所选标签，主助理在同一回合继续调度，不重新开新回合。
3. **Given** 一组包含 1 道单选 + 1 道多选的问题，**When** 用户在多选题中同时勾选普通选项与"其他"并填入文本后提交，**Then** 工具结果按题返回 `selectedLabels` 与 `otherText`，单选题只返回一个选项或一段其他文本。
4. **Given** 模型在同一批工具调用里把 `ask_user_question` 与其他工具一起发出，**When** AgentLoop 处理该批次，**Then** 该批次内所有工具调用均不执行、统一标记为无效模型输出并完整配对返回，提示模型单独调用。

---

### User Story 2 - 用户选择暂不回答 (Priority: P2)

用户看到澄清卡片，但当下不想回答（信息不全、想先做别的、或干脆觉得这个问题不该问）。用户可以显式"暂不回答"取消该组问题；主助理收到取消信号后**不得猜测答案、也不得在同一回合换个说法再问一遍**，而是按"用户未提供决策"妥善收尾本回合。

**Why this priority**: 保证用户始终掌握主动权，杜绝"模型把澄清当成必答题、反复纠缠或自行脑补"的体验劣化。是核心安全语义的一部分，但相较 P1 可后置验证。

**Independent Test**: 渲染澄清卡片后点击"暂不回答"，验证工具返回 `status="cancelled"`、卡片消失、主助理本回合不再重复发起同一组澄清、也不基于猜测继续执行有副作用的动作。

**Acceptance Scenarios**:

1. **Given** 澄清卡片正在显示，**When** 用户点击"暂不回答"，**Then** 对应请求结算为 `cancelled`，工具返回不含任何用户答案，卡片移除。
2. **Given** 用户已取消一组澄清，**When** 主助理本回合继续，**Then** 它不在同一回合重复发起同一澄清，也不假设任一选项为已选。

---

### User Story 3 - 超时、停止与会话恢复 (Priority: P3)

澄清请求默认等待 5 分钟。若用户既不提交也不取消，请求超时；用户主动停止当前回合，或应用关闭，对应请求都应被确定性地结算（分别为 `timeout` / `stopped` / `shutdown`），并唤醒等待中的后台 worker，绝不让模型在未拿到真实答案时继续。普通 SSE 断线**不**取消请求——用户重连后通过事件回放或 pending 快照接口仍能看到原卡片并作答。

**Why this priority**: 覆盖边界与可靠性，保证长任务、断网、重启等真实场景下不卡死、不泄漏、不误判。价值高但属于稳健性收尾，置于核心交互之后。

**Independent Test**: 启动一个 pending 澄清，分别模拟（a）超过 5 分钟无操作、（b）用户停止回合、（c）SSE 断开后重连，验证三种情形各自的终态/恢复行为，且无任何情形导致模型获得猜测答案。

**Acceptance Scenarios**:

1. **Given** 一个 pending 澄清已等待超过 5 分钟，**When** 超时触发，**Then** 请求结算为 `timeout`，等待中的 worker 被唤醒，工具返回不含答案。
2. **Given** 一个 pending 澄清存在，**When** 用户停止当前回合，**Then** 该请求结算为 `stopped` 并唤醒 worker；当应用关闭时结算为 `shutdown`。
3. **Given** 一个 pending 澄清存在，**When** 前端 SSE 连接断开后重新连接，**Then** 请求不被取消，前端通过事件回放或 pending 快照接口恢复显示原卡片并仍可作答。
4. **Given** 同一回合内两个用户/连接对同一请求并发提交，**When** 后端处理决策，**Then** 仅第一个决策生效（first-decision-wins），其余被安全忽略且不报错崩溃。

---

### Edge Cases

- **同会话多请求**：每个 Assistant 会话同一时刻最多一个 pending 澄清；不支持并发多张卡片堆叠。
- **重复/过期提交**：对已结算请求再次提交（重复点击、过期卡片）必须被幂等拒绝，不改变终态。
- **会话归属错配**：针对 A 会话的请求 ID 通过 B 会话端点提交，必须被拒绝。
- **空输入/超长"其他"**：单选题既未选选项也未填"其他"视为缺答，必须被拒绝；"其他"文本最大 1000 字符，超长拒绝。
- **校验失败的工具入参**：问题数 <1 或 >4、选项数 <2 或 >4、问题文本为空、批次内问题文本重复、同题选项标签重复——工具入参校验失败，返回明确错误而非半成品请求。
- **secret 泄漏防护**：模型不得在问题/选项/预览中放入或索取 secret；卡片预览只按纯文本展示，不渲染 HTML/Markdown。
- **重启失效**：sidecar 重启后所有内存态 pending 请求与未提交草稿自然失效（不持久化）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供一个仅主助理可用的 `ask_user_question` 工具，单次调用可包含 1–4 个问题，每个问题包含 2–4 个候选选项。
- **FR-002**: 每个问题 MUST 可独立配置为单选或多选，并 MUST 始终附带一个可选的"其他"自由文本输入（最大 1000 字符）。
- **FR-003**: 工具入参 MUST 经后端校验：问题文本与短标题必填；同一批次内问题文本不得重复；同一问题内选项标签不得重复；选项可携带可选说明与纯文本预览。
- **FR-004**: 后端 MUST 生成稳定的 `questionId` 与 `optionId`，不得依赖模型生成的 ID。
- **FR-005**: 工具结果 MUST 以固定状态集之一返回：`answered` / `cancelled` / `timeout` / `stopped` / `shutdown` / `unavailable`；`answered` 时按题返回 `{question, selectedLabels, otherText}`。
- **FR-006**: `ask_user_question` MUST 被标记为需独占调用；当模型在同一批工具调用中将其与任何其他工具一起发出时，系统 MUST 不执行该批次任一工具，将其全部记为无效模型输出并完整配对返回，提示模型单独调用。
- **FR-007**: 当 `ask_user_question` 被单独调用时，主助理回合 MUST 等待用户决策，并在拿到结果后于**同一 AgentLoop 内**继续推进，不开新回合。
- **FR-008**: 该工具 MUST 只在主助理工具集中注册；PM、Trial、specialist、subagent 均 MUST NOT 暴露此工具。
- **FR-009**: 系统 MUST 通过会话级接口暴露：查询当前会话 pending 澄清快照；按会话 + 请求 ID 提交决策（提交或取消）。
- **FR-010**: 决策提交 MUST 校验：单选题只能提交一个选项**或**一段"其他"文本；多选题可组合普通选项与"其他"文本；每个问题都必须有答案；空答案/缺答拒绝。
- **FR-011**: 系统 MUST 发出两个公开 UI 事件：`assistant.clarification_requested`（含请求 ID、问题、选项、`expiresAt`、`status=pending`）与 `assistant.clarification_resolved`（含请求 ID 与终态，**不含**任何用户答案）。
- **FR-012**: 澄清请求 MUST 默认 5 分钟超时；超时后自动结算为 `timeout` 并唤醒等待中的 worker。
- **FR-013**: 用户停止当前回合时，相关 pending 请求 MUST 结算为 `stopped` 并唤醒 worker；应用关闭时 MUST 结算为 `shutdown`。
- **FR-014**: 普通 SSE 断线 MUST NOT 取消 pending 请求；重连后用户 MUST 能通过事件回放或 pending 快照接口恢复看到原卡片并作答。
- **FR-015**: 并发决策 MUST 遵循 first-decision-wins：仅第一个有效决策生效，其余被安全忽略；对已结算请求的重复/过期提交 MUST 被幂等拒绝。
- **FR-016**: 决策端点 MUST 校验会话归属：请求 ID 与会话不匹配时拒绝。
- **FR-017**: 前端 MUST 在聊天输入框上方以可访问的非模态卡片（fieldset + radio/checkbox）展示澄清；预览仅按纯文本展示，不渲染 HTML/Markdown。
- **FR-018**: 前端单选题选择"其他"时 MUST 取消其他普通选项；多选题 MUST 允许普通选项与"其他"并存。
- **FR-019**: 前端 MUST 按会话保存 pending 澄清、未提交选择与提交状态；切换会话 MUST 保留草稿，请求 resolved 后 MUST 统一清理；提交期间 MUST 禁用全部控件以防重复提交。
- **FR-020**: 澄清交互 MUST 与高危确认完全分离：不显示"全部允许"、不复用确认 Toast 生命周期。
- **FR-021**: 主助理 system prompt MUST 指导：仅在关键决策无法可靠推断时使用；关联问题一次问齐；不得询问或展示 secret；取消或超时后不得在同一回合重复追问或基于猜测继续执行。
- **FR-022**: 所有澄清请求与未提交答案 MUST 仅驻留当前 sidecar 进程内存；MUST NOT 新增数据库表、迁移或配置项；sidecar 重启后自然失效。

### Key Entities *(include if feature involves data)*

- **ClarificationRequest**：一次澄清请求。属性：请求 ID、会话 ID、问题列表、`expiresAt`、状态（pending 及各终态）、first-decision-wins 同步原语（请求 ID + 事件 + 锁）。仅内存。
- **ClarificationQuestion**：单个问题。属性：questionId（后端生成）、问题文本、短标题、是否多选、选项列表。
- **ClarificationOption**：单个候选项。属性：optionId（后端生成）、标签、可选说明、可选纯文本预览。
- **ClarificationAnswer**：用户对单题的回答。属性：所选 optionId 列表（提交侧）/ 所选标签列表（结果侧）、otherText。
- **ClarificationDecision**：一次决策提交。属性：decision（submit/cancel）、按题答案集合。

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: 不得新增任何 SQLite/DuckDB 表、迁移或配置键；状态完全内存化（项目当前为单用户、未发布、无外部消费者）。
- **CC-002**: 高危确认（`request_id + threading.Event + emit`）协议、Assistant 停止、消息排队、既有 UI Event Registry 契约 MUST 保持回归通过；澄清复用同类同步原语但独立实现，不污染确认链路。
- **CC-003**: 面向前端的事件 MUST 经 UI Event Registry 注册并带 payload allowlist；`assistant.clarification_resolved` MUST NOT 泄漏用户答案；secret MUST NOT 进入事件、DTO 或前端持久化状态。
- **CC-004**: 修正现有 `tests/desktop_api/test_auth_toast_confirmation.py` 中 4 个过时私有函数名引用，使其重新纳入门禁。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **UI** (`frontend/src/`) — 新增 ClarificationCard 组件、Zustand store 分片、按 session 草稿/提交状态、pending 快照刷新
- [x] **Desktop API Bridge** (`src/desktop_api/`) — 新增 pending 查询与 decision 提交两个会话级端点、两个公开事件注册与 payload allowlist
- [x] **Business** (`src/business/`) — 新增线程安全 clarification manager、`ask_user_question` 工具、主助理工具集注册、prompt 更新、AgentLoop 独占工具处理
- [ ] **Execution** (`src/execution/`)
- [ ] **Data** (`src/data/`) — 明确不新增表/迁移/配置
- [ ] **Recording** (`src/recording/`)
- [x] **Utils** (`src/utils/`) — 可能新增 blinker 内部事件用于通知 worker（如需要）

### Agent Impact *(if touching Agent system)*

- 受影响 Agent：仅 **Assistant**（主助理）。PM / Trial / specialist / subagent 均不暴露。
- 新工具：`ask_user_question`（独占调用语义，结果回填上下文）。
- ToolDefinition 新增 `requires_exclusive_call` 标志；AgentLoop 对独占工具与其它工具混批的零执行 + 完整配对处理。
- System prompt 更新：使用时机、一次问齐、secret 禁令、取消/超时后行为。
- Orchestrator dispatch：主助理回合内同步等待并续跑，不新开回合。

### Data Store Impact *(if touching data layer)*

- **SQLite**：无新增表/仓储/迁移（硬约束）。
- **DuckDB**：无影响。
- **Config** (`src/data/unified_config.py`)：无新增配置键。
- **Secrets**：无新增敏感字段；但 prompt 与事件契约必须确保 secret 不进入问题/选项/预览/事件/前端状态。

### Event Impact *(if adding/changing events)*

- 公开 UI 事件（`src/desktop_api/ui_events.py` Registry）：`assistant.clarification_requested`、`assistant.clarification_resolved`。
- 内部通知：停止/关闭时唤醒等待 worker（沿用线程同步原语 + 必要时 blinker）。
- 事件 payload allowlist：requested 携带请求 ID/问题/选项/expiresAt/status；resolved 仅携带请求 ID + 终态，不含答案。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 主助理在一次任务中遇到关键岔路口时，可在**同一回合内**完成"提问 → 用户作答 → 继续执行"，无需重开回合或返工。
- **SC-002**: 单选题、多选题、"其他"自由输入、暂不回答、超时、停止、关闭、断线重连这 8 类路径 100% 可被自动化测试覆盖且通过。
- **SC-003**: 任何超时/取消/停止/关闭情形下，模型获得猜测答案的次数为 **0**。
- **SC-004**: `assistant.clarification_resolved` 事件与普通 DTO 中泄漏用户答案的次数为 **0**；secret 进入问题/选项/预览/事件/前端持久化状态的次数为 **0**。
- **SC-005**: 功能落地后新增 SQLite/DuckDB 表、迁移与配置键数量均为 **0**。
- **SC-006**: 高危确认、Assistant 停止、消息排队及既有 UI event 回归测试全部继续通过；后端相关 pytest、`npm run test`、`npm run lint`、`npm run build` 全绿。

## Assumptions

- 每个 Assistant 会话同一时刻最多一个 pending clarification。
- 请求与未提交答案不持久化；sidecar 重启后自然失效。
- "其他"自由输入始终可用，最大 1000 字符。
- 对标依据为 Claude Code 当前的 AskUserQuestion 输入/输出契约与工具说明。
- 完成后同步 `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`、前后端 AI 入口镜像（AGENTS/CLAUDE/GEMINI），并在 `docs/local/todo/agent-tool-patterns.md` 标记第 ② 项已实现。
- 现有 Agent 会话生命周期、AgentLoop 配对与中断恢复机制保持不变。
