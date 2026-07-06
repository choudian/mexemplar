# Feature Specification: 提案审批"讨论"功能（chat about this）

**Feature Branch**: `028-proposal-discussion`
**Created**: 2026-07-06
**Status**: Draft
**Input**: User description: "在 BrainScreen 改进提案审批视图中，用户可以对一条提案的分析内容展开真实对话讨论，而不是只能读静态文本后直接批准/拒绝。提案与讨论会话持久绑定，同一提案再次点击讨论回到同一会话；守住 026 审批前零副作用红线；讨论会话是普通助理会话但以提案上下文开场；终态提案也可讨论（复盘用途）。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 审批前对提案展开讨论 (Priority: P1)

用户在 BrainScreen 复盘视图里看到一条待审批的改进提案（问题/证据/建议），对分析内容有疑问——比如"这个建议的影响范围有多大""证据里提到的重复抓取具体发生在什么场景"。用户点击提案详情区的"讨论"入口，进入一个以该提案完整分析内容开场的助理会话，像平常聊天一样追问细节、讨论利弊，然后回到提案页做出批准或拒绝的决定。

**Why this priority**: 这是功能的核心价值——把审批从"读静态文本二选一"变成"可以对话式弄清楚再决策"。没有它整个 feature 不存在。

**Independent Test**: 选中一条 pending_review 提案，点击"讨论"，验证进入的助理会话开场包含该提案的问题/证据/建议/严重程度内容，可正常问答；回到提案页，批准/拒绝按钮行为与之前完全一致。

**Acceptance Scenarios**:

1. **Given** 一条待审批提案已选中，**When** 用户点击"讨论"，**Then** 界面切换到助理对话，且会话中可见该提案的分析上下文（问题、证据、建议、严重程度，以及已填写的补充说明）。
2. **Given** 用户已进入讨论会话，**When** 用户输入针对提案内容的问题，**Then** 助理基于开场上下文回答，与普通会话一致地流式展示。
3. **Given** 用户讨论后返回提案详情，**When** 用户点击"批准"或"拒绝"，**Then** 审批行为与没有讨论过完全一致（讨论不改变审批语义）。
4. **Given** 用户点击"讨论"进入了会话但没有发任何消息，**When** 查看提案状态，**Then** 提案状态不变，也没有产生任何实施动作。

---

### User Story 2 - 回到上次的讨论继续聊 (Priority: P2)

用户上周对一条提案讨论了几轮还没下决心，今天重新打开应用，进入该提案详情，点击"讨论"，回到的是同一个会话，之前聊过的内容都还在，可以接着上次的思路继续。

**Why this priority**: 用户明确选择了"提案与讨论会话持久绑定"；没有它，每次点开都是新对话，讨论积累的上下文全部丢失。

**Independent Test**: 对一条提案发起讨论并发送消息，重启应用后再次点击该提案的"讨论"，验证回到同一会话且历史消息完整。

**Acceptance Scenarios**:

1. **Given** 一条提案已有绑定的讨论会话且聊过若干轮，**When** 用户再次点击该提案的"讨论"，**Then** 进入的是同一个会话，历史消息完整可见。
2. **Given** 应用完全重启（会话绑定关系需跨进程持久），**When** 用户点击该提案的"讨论"，**Then** 仍回到原会话。
3. **Given** 绑定的讨论会话已被用户从会话列表中删除，**When** 用户点击"讨论"，**Then** 系统创建一个新的讨论会话（重新以提案上下文开场）并更新绑定，不报错不卡死。

---

### User Story 3 - 终态提案的复盘讨论 (Priority: P3)

一条提案已经实施完成（done）或实施失败（failed）或被拒绝（rejected），用户想复盘："当时为什么拒绝了它""实施失败的原因是什么、还值得再试吗"。用户在终态提案详情区同样能点击"讨论"，针对该提案（此时上下文还包含实施结果/失败原因）展开对话。

**Why this priority**: 复盘是自我改进闭环的自然延伸，但不影响审批主流程的可用性。

**Independent Test**: 选中一条 done 或 failed 状态的提案，点击"讨论"，验证会话开场上下文包含实施结果信息。

**Acceptance Scenarios**:

1. **Given** 一条 done/failed/rejected 状态的提案，**When** 用户点击"讨论"，**Then** 讨论入口可用且会话开场上下文包含实施结果摘要或失败原因（如存在）。

---

### Edge Cases

- 绑定的讨论会话被删除后再点"讨论"：创建新会话并重新绑定（US2 场景 3）。
- 用户快速连点"讨论"两次：不得创建两个会话；第二次点击应复用第一次的结果（绑定写入需幂等）。
- 助理正在其他会话中运行时点击"讨论"：进入讨论会话不受影响（会话相互独立，既有会话并行语义不变）。
- 提案功能开关（self_improvement.proposals.enabled）关闭时：整个提案视图不可见，讨论入口自然不可达，无需单独处理。
- 讨论会话中用户要求助理"直接把这个提案实施了"：助理按普通会话的既有能力和限制行事（该风险与本 feature 无关——用户在任何普通会话都能提出该要求）；本 feature 本身不提供任何"从讨论直达实施"的捷径，提案状态转换仍只经审批按钮。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-420**: 提案详情区 MUST 提供"讨论"入口；对任意状态的提案（含 pending_review 与全部终态）均可用。
- **FR-421**: 首次点击"讨论"MUST 创建一个真实的普通助理会话，并以该提案的分析上下文开场：问题（what）、证据（evidence）、建议（suggestion）、严重程度（severity）、类型（findingType）、用户已填补充说明（如有）；终态提案还包含实施结果摘要 / 测试结论 / 失败原因（如有）。上下文序列化 MUST 复用既有 finding 文本拼装逻辑，不另写一份副本。
- **FR-422**: 提案与讨论会话的绑定 MUST 持久化存储并跨应用重启有效；同一提案再次点击"讨论"MUST 回到已绑定会话。
- **FR-423**: 绑定的会话不存在或已删除时，点击"讨论"MUST 自动创建新会话并更新绑定（自愈，不报错终止）。
- **FR-424**: 讨论会话 MUST 是普通助理会话：出现在会话列表、使用既有消息与事件通道、可被用户像普通会话一样重命名/删除；不引入新的会话类型或独立聊天界面。
- **FR-425**: 点击"讨论"与讨论过程本身 MUST NOT 触发任何提案实施副作用（不建 worktree、不建任务图、不改代码、不改变提案审批状态）；提案状态转换仍 MUST 只经既有批准/拒绝操作。允许的唯一提案数据变更是讨论会话绑定关系本身。
- **FR-426**: 打开讨论会话 MUST NOT 自动消耗模型调用；助理从用户在讨论会话中发出第一条消息起才开始回应。
- **FR-427**: 绑定写入 MUST 幂等：并发或重复触发"讨论"时至多创建一个会话（后到者复用先到者的绑定）。
- **FR-428**: 用户在讨论会话中 MUST 能看出讨论对象是哪条提案（开场上下文自身可读，无需跳回提案页对照）。

### Key Entities

- **改进提案（ImprovementProposal）**: 既有实体；新增与讨论会话的可选一对一绑定关系（一个提案至多绑定一个讨论会话；绑定可因原会话删除而更换到新会话）。
- **助理会话（Assistant Session）**: 既有实体；讨论会话是其普通实例，无新增会话属性。

### Constraints & Compatibility

- **CC-160**: 026 的"审批前零副作用"红线保持不变：审批前不得建 worktree / task graph / 执行代码；本 feature 的讨论路径不得成为绕过审批的实施入口。
- **CC-161**: 讨论会话不赋予助理任何新增能力或工具；助理在讨论会话中的能力边界与普通会话完全一致。
- **CC-162**: 0 新公开 UI 事件类型：提案数据变化沿用既有 `improvement_proposal.changed`，会话消息沿用既有 assistant 事件；前端不得为讨论功能消费未注册事件。
- **CC-163**: 既有 approve/reject/list API 行为不变；既有提案审批测试必须继续通过。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **UI** (`frontend/src/`) — BrainScreen 提案详情区"讨论"按钮、跳转到 Assistant 屏并激活目标会话、brainStore 触发动作
- [x] **Desktop API Bridge** (`src/desktop_api/`) — 提案讨论入口 endpoint（创建或返回绑定会话）
- [x] **Business** (`src/business/`) — proposal_service 讨论会话创建/绑定/自愈逻辑；finding 上下文序列化复用 proposal_bridge 既有拼装
- [x] **Data** (`src/data/`) — `improvement_proposals` 表新增 discussion_session_id 列（migration）；Repository 绑定读写

### Agent Impact

- Which Agent(s) are affected: Assistant（仅作为普通会话的承载方，无行为变更）
- New tools or modified tool handlers? 无
- System prompt changes needed? 无
- Orchestrator dispatch changes? 无

### Data Store Impact

- **SQLite** (`src/data/repos/`): `improvement_proposals` 新增可空 `discussion_session_id` 列 + migration（含 downgrade）；`ImprovementProposalRepository` 增加绑定读写（幂等更新）
- **Config**: 无新增配置键
- **Secrets**: 不涉及

### Event Impact

- New events: 无（0 新公开 UI 事件）
- Modified event payloads: `improvement_proposal.changed` 载荷不变（绑定变化不要求实时推送；详情刷新时随 DTO 返回）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-420**: 从提案详情到可输入的讨论会话 ≤ 1 次点击（不含首次加载）；开场上下文完整包含该提案全部已填分析字段。
- **SC-421**: 讨论-重启-再讨论闭环 100% 回到同一会话（绑定跨进程持久）；绑定会话删除后再讨论 100% 自愈成功。
- **SC-422**: 讨论路径产生的提案实施副作用为 0（无 worktree / 任务图 / 代码变更 / 状态转换），由守卫测试断言。
- **SC-423**: 既有提案审批交互（批准带补充说明 / 拒绝 / 刷新 / 权限开关）回归测试 100% 通过。

## Assumptions

- 讨论会话的开场上下文以会话内首条可见内容的形式呈现（具体角色/展示形态由 plan 阶段决定），用户无需离开会话即可读到提案分析全文。
- 打开讨论不自动触发助理回应（FR-426）：用户主导第一问，避免无意义的模型消耗。
- 一个提案至多一个活跃讨论会话；不支持同一提案多个并行讨论线程（单用户桌面应用，无此需求）。
- 讨论会话删除即普通会话删除，提案侧只在下次点击"讨论"时才感知并自愈；不做实时级联。
- 提案实体本身没有删除操作（仅 reject），不存在"提案删除后讨论会话悬挂"的场景。
