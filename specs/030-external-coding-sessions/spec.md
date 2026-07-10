# Feature Specification: 外部 Coding Session（Claude Code / Codex CLI）

**Feature Branch**: `030-external-coding-sessions`
**Created**: 2026-07-09
**Status**: Completed
**Revision**: 2026-07-10 — Finalized after implementation verification and project-memory archival.
**Input**: User description: "把 Claude Code 和 Codex CLI 集成到当前工作助理中。它们作为可被 agent 调用的外部 coding session 工具，负责代码实现；Exemplar 负责派活、计划审查、恢复、审计、合并和回滚。"

## 问题背景

用户已经购买多个订阅型 coding agent 套餐，但这些能力不能稳定转成普通 API provider。当前 Exemplar 助理已经具备长期记忆、任务图调度、专员体系、工具权限、事件流和自我改进经验，但真正写代码时仍依赖用户人工打开 Claude Code、Codex CLI 等工具，手工复制需求、观察进度、判断是否完成、再回到 Exemplar 继续 review 或测试。

本 feature 的目标不是把 Claude Code 或 Codex CLI 变成 Exemplar 的模型后端，而是把它们作为"外部代码执行体"纳入 Exemplar 的任务协作闭环。Exemplar 中的 agent 可以启动一个受记录的 coding session，要求外部工具先产出计划，由派活 agent 判断计划是否偏离目标，再进入实现。外部工具完成后写结果报告，Exemplar 记录产物、可见状态、quota 信号、合并点和回滚线索，最终让任务继续流转。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent 启动外部 coding session 并先审计划 (Priority: P1)

派活 agent 接到一个需要改代码的任务后，不直接自己写代码，而是选择 Claude Code 或 Codex CLI 创建一个 coding session。系统为这次会话创建独立代码工作区和过程产物目录，并要求外部 agent 先只做规划。外部 agent 产出 `PLAN.md` 后，派活 agent 审查目标复述、计划改动、影响范围、假设、风险、测试计划和待确认问题，判断是否允许进入实现。

**Why this priority**: 这是整套能力的核心安全阀。用户最担心外部 coding agent 任务理解不清、反复追问或做偏方向；先计划再实现能让派活 agent 在改代码前纠偏。

**Independent Test**: 可通过创建一个绑定到测试任务的 coding session，验证系统生成会话记录、独立 worktree、handoff 产物，并在外部工具只产出计划时进入 `plan_ready` 而不是直接实现。

**Acceptance Scenarios**:

1. **Given** 一个 agent 正在处理明确绑定 Task 或 Workflow owner 的代码任务, **When** 它启动外部 coding session, **Then** 系统创建唯一 `codingSessionId`、记录 owner、选择的外部工具、工作区、过程产物目录和启动时间，并让外部工具进入 plan-only 阶段。
2. **Given** coding session 没有明确 Task 或 Workflow owner, **When** 任意 agent 试图启动外部 coding session, **Then** 系统拒绝创建无主会话，并说明需要先绑定任务或工作流。
3. **Given** 外部工具已写出 `PLAN.md`, **When** `PLAN.md` 覆盖最低计划项且没有明显偏离目标, **Then** 派活 agent 可以批准进入实现阶段。
4. **Given** 外部工具产出的 `PLAN.md` 内容空泛、缺少关键最低项或与用户目标偏离, **When** 派活 agent 审查计划, **Then** 会话进入 `plan_rejected` 或重新规划状态，并把具体修改要求回传给外部工具。
5. **Given** plan-only 阶段产生了代码改动, **When** 系统或派活 agent 发现工作区变化, **Then** 该会话被标记为协议违规或中断，必须先由派活 agent 裁定是否继续、重开或放弃。

---

### User Story 2 - 外部工具按已批准计划实现并可中断恢复 (Priority: P2)

计划通过后，外部 coding session 进入实现阶段。外部工具优先复用同一个外部会话上下文，在独立 coding worktree 内改代码、运行必要测试并写 `RESULT.md`。如果过程中遇到 quota 耗尽、短期断网、登录状态、模型不可用、进程退出或其它中断，系统把中断报告回流给派活 agent；派活 agent 可以选择等待、resume、重新规划、询问用户或放弃。

**Why this priority**: 外部 CLI 本质是另一个 agent，可能运行很久并遇到订阅、网络、权限或上下文问题。没有可恢复状态机，任务会永久卡住或需要用户重新手工拼接上下文。

**Independent Test**: 可用模拟外部工具先产出计划、再在实现阶段异常退出，验证原任务、计划、日志 tail、外部 session/thread 映射和工作区路径仍可被 `resume` 使用。

**Acceptance Scenarios**:

1. **Given** `PLAN.md` 已由派活 agent 批准, **When** 外部工具开始实现, **Then** 会话进入 `implementing`，并保留同一 `codingSessionId` 与同一个外部工具选择。
2. **Given** 实现过程中发现小幅计划偏差, **When** 偏差不改变目标、不扩大主要范围且不改变公开行为边界, **Then** 外部工具可以继续，但必须在 `RESULT.md` 中记录偏差。
3. **Given** 实现过程中发现原计划不可行、需要扩大范围、改变目标或新增重大决策, **When** 外部工具无法在原计划内完成, **Then** 会话必须回到计划修订或中断状态，由派活 agent 决定下一步。
4. **Given** 外部工具进程退出但没有有效 `RESULT.md`, **When** 系统检查完成条件, **Then** 会话进入 `interrupted`，不能标记为完成。
5. **Given** 外部工具中途 quota 耗尽, **When** QuotaProbe 或输出分类识别到耗尽原因, **Then** 会话固定在原外部工具上进入 `interrupted`，不得静默切换到另一个外部工具。
6. **Given** 外部工具完成实现并写出有效 `RESULT.md`, **When** 派活 agent 检查报告和工作区变化, **Then** 会话可以进入 `completed`，并附带测试、风险、依赖变化和后续建议摘要。

---

### User Story 3 - Exemplar 自动合并完成结果并支持按用户意图回滚 (Priority: P3)

coding session 完成后，Exemplar 可以根据派活 agent 的判断自动把 coding worktree 的结果合并回目标分支。合并前系统分析目标工作区的未提交变化、coding 分支变化、文件重叠和冲突风险。合并失败或风险较高时回流给 agent 裁定。合并后如果用户觉得方向不对，agent 根据用户对话和 git 状态推断合适的回滚方式，必要时引导式询问用户。

**Why this priority**: 用户希望任务完成后能继续自动推进下一个任务，而不是每次手工搬运补丁；同时合并和回滚必须有审计点，避免外部 agent 自己 merge、push 或重写历史。

**Independent Test**: 可用一个完成的 coding 分支验证 Exemplar 在合并前生成 dirty/conflict 分析，记录 merge 前后状态，并在用户要求撤回时提供可解释的回滚路径。

**Acceptance Scenarios**:

1. **Given** coding session 已完成且派活 agent 接受结果, **When** 自动合并启动, **Then** Exemplar 记录目标分支、合并前 HEAD、coding 分支变化、目标工作区 dirty set 和冲突预测。
2. **Given** 目标工作区有未提交变化但与 coding 分支无文件重叠, **When** 派活 agent 判断可以继续, **Then** Exemplar 可以继续合并并记录该裁定。
3. **Given** 目标工作区变化与 coding 分支有重叠或预测冲突, **When** 合并前分析完成, **Then** 系统不得静默合并，必须回流给 agent 处理或上冒用户。
4. **Given** 合并由 Exemplar 完成, **When** 外部 coding agent 曾经尝试自行 merge、push、reset 或 clean, **Then** 派活 agent 能在审计中看到该风险并决定是否信任结果。
5. **Given** 用户在后续对话中表示"这次做得不对"或"彻底回到之前", **When** agent 判断回滚意图, **Then** 系统提供符合意图的受控回滚动作，并在高风险或会影响后续改动时先做引导式确认。

---

### User Story 4 - Agent 自动选择 Claude/Codex 并关注套餐余量 (Priority: P4)

用户不想每次手动指定 Claude Code 或 Codex CLI。系统应在启动 session 前收集可用性和 quota 信号，默认选择更适合当前任务且套餐余量更健康的工具。QuotaProbe 可以读取本机凭证、状态文件或必要的 usage endpoint，但只向 agent 暴露归一化状态，不泄漏凭证原文。

**Why this priority**: 用户集成这些工具的直接原因是有多个订阅套餐。自动选择如果不关注 quota，就会频繁把任务派给已超限工具，造成中断和返工。

**Independent Test**: 可通过注入不同 quota 状态，验证自动选择优先使用 `available` 工具、降权 `low` 工具、避免 `exhausted` 工具，并记录选择理由。

**Acceptance Scenarios**:

1. **Given** Claude Code quota 为 `available` 且 Codex CLI quota 为 `exhausted`, **When** agent 自动选择外部 coding 工具, **Then** 系统优先选择 Claude Code，并记录 quota 选择理由。
2. **Given** 两个工具 quota 均为 `unknown`, **When** agent 自动选择工具, **Then** 系统仍可选择一个工具，但必须记录来源置信度为未知，不因未知余额阻塞任务。
3. **Given** QuotaProbe 读取本机凭证或状态文件, **When** 产生 quota 结果, **Then** 普通日志、前端、事件和会话产物只包含脱敏后的状态、来源、置信度和检查时间，不包含 token、账户明文或原始响应体。

### Edge Cases

- Claude Code 或 Codex CLI 未安装、不可执行或未登录：session 不启动，agent 获得可行动错误；如果可由用户处理，agent 再上冒用户。
- 最高 effort/reasoning 档不可用：会话进入 `interrupted/model_unavailable`，回流给 agent，不自动降级。
- 外部工具在 plan-only 阶段修改文件：标记协议违规，派活 agent 决定保留、回滚、重开或继续。
- 外部工具写了 `RESULT.md` 但未实际改动任何文件：派活 agent 看到空 diff 风险，不能盲目标记用户任务完成。
- `RESULT.md` 声称运行测试但日志或命令记录缺失：标记为自报证据不足，review/test 建议提高优先级。
- 外部工具安装依赖、联网或修改 lockfile：V1 不硬阻止，但必须在 `RESULT.md` 中披露；合并前作为风险呈现。
- 外部工具尝试自行 merge、push、reset 或 clean：标记为高风险协议偏离；合并与回滚仍只能由 Exemplar 执行。
- 主工作区在合并前有用户未提交改动：先做 dirty/conflict 分析；无重叠可由 agent 裁定继续，有风险则处理冲突或询问用户。
- 同一 session 中途想从 Claude 切到 Codex：不允许静默切换；必须放弃当前 session 或创建新 session，并保留旧 session 作为上下文。
- 用户要求回滚时意图不清：agent 用引导式问题确认是否只撤当前 session 的已记录 merge；V1 只支持对该精确 merge commit 执行 `git revert`，不以 reset/clean 丢弃后续变更。
- UI/event stream 断线：前端重连后必须能从权威快照恢复 session 当前状态、artifact 链接和可用操作。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support Claude Code and Codex CLI as the only external coding tools in V1; Gemini, Agy and other tools are out of scope for this feature.
- **FR-002**: System MUST expose external coding session capabilities as configurable agent tools, while refusing to start a session unless the call is bound to a clear Task or Workflow owner.
- **FR-003**: Starting a coding session MUST create a durable `codingSessionId` and record owner, selected tool, launch mode, timestamps, status, phase, external session/thread identifiers when available, worktree path, branch name and artifact directory.
- **FR-004**: Each coding session MUST use a dedicated coding worktree named `.worktrees/coding/<codingSessionId>` and a branch named `coding/<codingSessionId>` by default.
- **FR-005**: Session artifacts MUST be stored under `data/coding_sessions/<codingSessionId>/`, including the handoff, plan, result and logs needed for audit and resume.
- **FR-006**: System MUST support both headless managed launch and interactive supervised launch for supported tools; headless is the default automation path, while interactive completion MUST still rely on explicit artifact reports rather than terminal screen parsing.
- **FR-007**: Every coding session MUST start with a plan-before-code phase unless the calling agent explicitly records why it is resuming an already approved plan.
- **FR-008**: The plan phase MUST request a `PLAN.md` that covers, at minimum, target restatement, planned changes, expected impact area, assumptions/non-goals, risks, test plan, open questions and recommendation on whether implementation should proceed.
- **FR-009**: `PLAN.md` MUST be treated as a soft template with minimum semantic coverage; exact heading text MUST NOT be a hard schema requirement.
- **FR-010**: The plan phase MUST be read-and-investigate oriented; any file mutation during this phase MUST be surfaced as a protocol violation for agent裁定.
- **FR-011**: The dispatching agent MUST review the external plan before implementation begins, and MUST either approve it, reject it with feedback, request clarification, or escalate high-risk product decisions to the user.
- **FR-012**: Implementation SHOULD resume the same external tool conversation when supported; if a new external run is required, it MUST remain under the same `codingSessionId` and record the attempt boundary.
- **FR-013**: A coding session MUST keep the same external tool for its lifetime. Switching from Claude Code to Codex CLI, or the reverse, requires abandoning or completing the current session and creating a new session.
- **FR-014**: System MUST use the highest available reasoning/effort setting for Claude Code and Codex CLI by default. If the highest setting is unavailable, the session MUST interrupt and return control to the dispatching agent rather than silently downgrading.
- **FR-015**: Implementation MAY run tests, lint, type checks, dependency installation or network actions when the external tool judges them necessary; any dependency, network or lockfile-impacting action MUST be disclosed in the result report.
- **FR-016**: External coding tools MUST NOT be trusted to merge, push, reset or clean the target branch. Detected attempts MUST be visible to the dispatching agent as high-risk deviations.
- **FR-017**: A valid completion MUST require a `RESULT.md` that states status, summary, changed files, plan deviations, tests run, test results, known risks, follow-up needs and completion notes at a semantic level.
- **FR-018**: A process exit without a valid `RESULT.md` MUST leave the session interrupted or failed, not completed.
- **FR-019**: Interruptions MUST preserve task brief, plan, logs, external identifiers, worktree path, current diff summary, last error category and resume count so the dispatching agent can retry or abandon without reconstructing context manually.
- **FR-020**: `waiting_user` MUST only be entered after an agent decides the interruption cannot be resolved internally and asks the user for action or clarification.
- **FR-021**: Review and test after external completion MUST be strongly recommended but not mandatory. If independent review/test is skipped, the final summary MUST clearly say so.
- **FR-022**: Exemplar MUST execute automatic merge actions itself and record target branch, pre-merge head, merge result, changed files and any conflict/dirty analysis.
- **FR-023**: Before merge, system MUST compare target workspace dirty files against coding branch changes and surface overlap/conflict risk to the dispatching agent.
- **FR-024**: If merge risk is low, the dispatching agent MAY allow automatic merge; if overlap or predicted conflict exists, the system MUST not silently merge without agent裁定.
- **FR-025**: Rollback MUST be guided by user intent and repository state. In V1 the system MUST only apply an explicitly confirmed `git revert` of the exact merge commit recorded for this coding session after validating the target branch, HEAD, ancestry, merge parents and clean workspace; reset, clean, reverse-patch and manual-apply strategies are unsupported.
- **FR-026**: QuotaProbe MUST support normalized quota states for Claude Code and Codex CLI: `available`, `low`, `exhausted` and `unknown`, with source, confidence and last-checked time.
- **FR-027**: QuotaProbe MAY read local credentials, status files or usage endpoints to determine quota state, but MUST NOT persist or expose credential raw values, raw endpoint responses or account secrets in ordinary logs, UI events, DTOs or session artifacts.
- **FR-028**: Automatic tool selection MUST prefer `available` tools, lower the priority of `low` tools, avoid `exhausted` tools unless explicitly requested by the user, and record the selection reason.
- **FR-029**: Session status, current phase, selected tool, worktree branch, artifact previews, recent log tail and available actions MUST be visible from the related task/subagent detail UI.
- **FR-030**: UI state MUST be recoverable from authoritative backend snapshots after event-stream gaps or restart; process logs and raw external output MUST remain bounded and safe to display.

### Key Entities *(include if feature involves data)*

- **Coding Session**: A durable record of one external coding assignment, including owner, selected external tool, current phase/status, worktree, branch, artifacts, timestamps and final outcome.
- **External Run Attempt**: One concrete invocation or resumed invocation of Claude Code or Codex CLI within a coding session, including launch mode, external identifiers, exit status, logs and interruption reason.
- **Coding Handoff**: The task package given to the external tool, including objective, context, constraints, completion protocol and artifact paths.
- **Coding Plan**: The plan-stage artifact (`PLAN.md`) used by the dispatching agent to decide whether implementation may begin.
- **Coding Result**: The completion artifact (`RESULT.md`) used to decide completion, review recommendations and merge readiness.
- **Quota Signal**: A normalized observation about an external tool's current subscription/usage state, including source and confidence without exposing secrets.
- **Merge Record**: The audit trail for applying a coding session result back to a target branch, including dirty/conflict analysis and rollback reference points.
- **Rollback Decision**: The agent/user decision record describing why a particular rollback path was chosen and what risk confirmation was required.

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: Main Assistant remains a coordinator; user work is still routed through task/workflow owners and executing agents rather than unowned background coding jobs.
- **CC-002**: External coding session tools MUST NOT become general LLM providers for Exemplar.
- **CC-003**: Session state and status must be durable enough to survive process restart; raw logs may be bounded artifacts, but business state must not live only in process memory.
- **CC-004**: Quota credential access is allowed by user decision, but credential raw values remain governed by the project's existing secret handling rules.
- **CC-005**: Merge and rollback authority belongs to Exemplar, not the external coding agent.
- **CC-006**: This feature should not add a new hard sandbox policy comparable to self-improvement proposal guardrails; isolation is provided by worktrees, audit, plan review and merge control.
- **CC-007**: PLAN.md and RESULT.md are soft-template Markdown artifacts. Validation should focus on semantic completeness rather than exact heading text.
- **CC-008**: A single coding session fixes its external tool choice. Cross-tool continuation is represented as a separate session if needed.

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

Which layers are affected? Check all that apply:

- [x] **UI** (`frontend/src/`, `src-tauri/`) — Task/subagent detail surfaces external coding session state, artifacts, merge/rollback actions and bounded logs; Tauri may be involved only for opening local worktree/artifact locations if needed.
- [x] **Desktop API Bridge** (`src/desktop_api/`) — Typed endpoints/snapshots expose session lifecycle, artifacts, quota state, merge analysis and actions.
- [x] **Business** (`src/business/`) — Task/workflow-bound external coding session orchestration, plan approval flow, interruption recovery, quota-aware selection, merge/rollback decision handling.
- [x] **Execution** (`src/execution/`) — Managed external CLI process launch, stdout/stderr capture, process status, timeout/cooldown classification and bounded log handling.
- [x] **Data** (`src/data/`) — Persistent records for coding sessions, attempts, quota observations, merge records and artifact metadata.
- [ ] **Recording** (`src/recording/`) — No recording boundary changes expected.
- [x] **Utils** (`src/utils/`) — Shared helpers for event projection, git/worktree helpers, quota classification or redaction may be needed.

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: Assistant dispatch path, delegated executors, specialists and any configured agent that may receive the external coding session tool.
- New tools or modified tool handlers? New external coding session tools for start/inspect/resume/abandon/approve-plan/merge/rollback-oriented actions, all requiring a clear owner context.
- System prompt changes needed? Agents with the configured tool need guidance that external coding sessions are asynchronous, plan-first, owner-bound, fixed-tool, and review/test remains advisory.
- Orchestrator dispatch changes? Task/workflow reentry is needed when a coding session reaches plan_ready, interrupted, completed, merge_conflict or waiting_user states.

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): New persistent records are expected for coding sessions, external run attempts, quota probe observations and merge/rollback audit. Exact table shape is deferred to planning.
- **DuckDB** (`src/recording/filtering/`): No expected changes.
- **Config** (`src/data/unified_config.py`): External coding tool preferences, launch defaults and quota probe permissions/settings must use the unified configuration path.
- **Secrets** (`UnifiedConfigManager` only): QuotaProbe may read local credentials or status sources, but Exemplar must not persist secret raw values. Any new stored sensitive values must follow masked display, redaction and app settings precedence rules.

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: Coding session status changes may need a backend event source.
- Modified event payloads: Existing task/subagent UI events may need to reference coding-session identifiers or trigger snapshot refresh.
- New event listeners: UI projection must expose only registered, allowlisted public events or require `backend.resync_required` to fetch authoritative snapshots. Raw logs, credentials, full prompts and raw endpoint responses must not enter public UI event payloads.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a representative coding task, an agent can create a Claude Code or Codex CLI session, receive a semantically complete `PLAN.md`, and approve or reject the plan without user manually copying the plan between applications.
- **SC-002**: 95% of completed external coding sessions in controlled validation produce a `RESULT.md`, a worktree diff summary and a visible task detail status within 5 seconds of the external process finishing.
- **SC-003**: 100% of quota, network, login, model-unavailable and missing-result interruptions preserve enough context for the dispatching agent to inspect, resume or abandon the session without asking the user to restate the original task.
- **SC-004**: Automatic merge records pre-merge state, dirty/conflict analysis and post-merge outcome for every merged coding session.
- **SC-005**: QuotaProbe results never expose raw credentials, raw account identifiers or raw usage endpoint responses in ordinary logs, public UI events, front-end DTOs or session artifacts.
- **SC-006**: When one supported tool is marked `exhausted` and the other is `available`, automatic selection chooses the available tool in 100% of routing tests unless the user explicitly requested the exhausted tool.
- **SC-007**: If independent review/test is skipped after completion, the final agent summary visibly marks the result as not independently reviewed/tested in 100% of such cases.

## Assumptions

- Claude Code and Codex CLI are locally installed or can produce a user-actionable setup/login error.
- Claude Code and Codex CLI expose enough non-interactive or resumable behavior for V1 to run managed headless sessions; interactive supervised mode is supported as a weaker path that still relies on artifact reports.
- External tools can be instructed to write `PLAN.md` and `RESULT.md` to absolute artifact paths under `data/coding_sessions/<codingSessionId>/`.
- The default implementation work area is an isolated coding worktree, not the main worktree.
- The user prefers highest available reasoning/effort and does not want automatic downgrade on quota or model failures.
- The user accepts QuotaProbe reading local credentials/status sources for quota assessment, while the project still forbids secret raw values from entering ordinary persisted or displayed data.
- External tools may install dependencies or use the network when they judge it necessary; this is audited rather than hard-blocked in V1.
- Review/test after completion remains advisory, not a required state-machine gate.
