---
description: "Task list for feature: 主助理对话透明与可控"
---

# Tasks: 主助理对话透明与可控

**Input**: Design documents from `specs/014-assistant-chat-transparency/`
**Prerequisites**: plan.md（已读）、spec.md（5 个用户故事 P1–P3）、research.md、data-model.md、contracts/（ui-events.md、http-endpoints.md）

**Tests**: 本特性**包含测试任务**。依据：spec Constitution Check IV 明确枚举后端/前端测试、quickstart.md 列出 pytest + Vitest + Playwright 自动化、plan.md 要求 `AgentLoop` 行为契约测试与门卫测试。属"改静默失败路径必须补测试"硬规则范围（编排/事件/取消/恢复）。

**Organization**: 任务按用户故事分组，每个故事可独立实现与测试。

**Worktree**: 全部工作在 `E:\code\Exemplar\.worktrees\014-assistant-chat-transparency`（分支 `014-assistant-chat-transparency`）内进行。下列路径均相对该 worktree 根。

**复盘引用**：任务中的 `E#`/`X#`/`P#` 指 critique 报告的发现编号。**带 `C2-` 前缀**指第二轮 `critiques/critique-20260603T2153.md`（压缩历史 / REST 脱敏 / 早停竞态 / reasoning 保真 / 停止×确认 / 双击可达）；**不带前缀**默认指第一轮 `critiques/critique-20260603.md`（同线程不变量 / 代际 token / 历史压缩决议 / 性能门控 / payload allowlist）。

## Constitution-Driven Minimums（适用性核对）

- **无 SQLite 表/迁移**：本特性不新增持久化（data-model.md §「无写入新结构」），子任务列表与过程由既有 `MessageRepository` / `WorkflowTransitionRepository` / `SessionRepository` **只读**重建——故无 `src/data/migrations.py` 任务。
- **无 DuckDB/录制改动**：不触录制分析层。
- **无新配置/密钥**：取消检查节点等阈值如需可调，走 `get_unified_config()` 默认值占位、Settings UI 不暴露（research R1）——本期不新增显式 Settings 任务。
- **接线冒烟 + 门卫测试**：替换/扩展事件与编排路径，必须补门卫（同线程承重不变量、非助理 Agent 零行为变化）与契约测试——见 T008（同线程门卫）、T029（非助理零变化门卫）、T010/T028（行为契约测试）。
- **活文档更新**：`docs/ARCHITECTURE.md`、`frontend/AGENTS.md`+镜像、`src/AGENTS.md`+镜像——见 Polish 阶段。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1–US5）；Setup/Foundational/Polish 无 Story 标签
- 每个任务含明确文件路径

---

## Phase 1: Setup（共享基线）

**Purpose**: 确认隔离 worktree 工具链就绪并取得改动前基线。

- [X] T001 在 worktree 内确认工具链就绪并记录基线：`cd frontend && npm install`（如需）；`uv` 环境就绪；运行 `cd frontend && npm run lint && npm run test` 与 `uv run pytest tests/business tests/desktop_api tests/guardrails -q`，记录当前通过/失败基线，确保后续改动从干净起点出发。

---

## Phase 2: Foundational（阻塞前置 — 所有故事开始前必须完成）

**Purpose**: 取消原语、运行上下文、跨模块事件与公开 UI 事件契约——US1（取消）与 US3/US4（活动/子任务事件门控）共同依赖。

**⚠️ CRITICAL**: 本阶段未完成，任何用户故事不得开工。

- [X] T002 [P] 在 `src/utils/events.py` 声明 4 个新 blinker 事件信号：`assistant_agent_step`、`assistant_subagent_started`、`assistant_subagent_finished`、`assistant_subagent_paused`（仅声明信号对象与文档字符串，不在此处 emit）。
- [X] T003 新建 `src/business/agents/run_context.py`：定义 `ContextVar[{root_session_id, cancel_event}]` + 进程内 `session_id → threading.Event` 注册表 + 每次运行的**代际 token**；提供 `begin(root_session_id)` / `end()` / `get_current()` / `request_cancel(session_id)` API；在文件头与 `begin` 处注释"**同线程同步委派**是深度取消的承重不变量"（E1），并实现代际 token 使陈旧 `set` 无法误取消复用同一 session 的新一轮运行（E2）；另维护一个**待停止 sessionId 集合**——`request_cancel` 在该会话 Event 尚未登记时记录"待停止"意图，`begin()` 命中则立即按取消起步，覆盖"停止早于 `begin()` 登记"的早停竞态（C2-E3）。
- [X] T004 在 `src/desktop_api/assistant_runtime.py` 的 worker 线程入口接入 `run_context.begin()` / `finally: end()`：覆盖 `_run_assistant` 与续跑 worker 两条入口，确保 ContextVar 与 Event 在 worker 线程设置、运行结束清理（非助理流程不调 `begin` → ContextVar 空 → 取消恒 False、零行为变化）；`begin()` 设置时检查待停止集合，若该会话已有早到的停止意图则即刻进入取消（C2-E3）。
- [X] T005 [P] 在 `src/business/agents/config.py` 的 `ResultType` 新增 `CANCELLED` 取值（供 `AgentLoop` 与 `orchestrator` 区分"用户主动停止"与不可恢复错误）。
- [X] T006 [P] 在 `src/desktop_api/ui_events.py` 的 UI Event Registry 注册公开事件契约：`assistant.activity`（scope `{sessionId}`，payload allowlist `subagentId/kind/toolName/text/seq`）与 `assistant.subagent`（scope `{sessionId}`，payload allowlist `subagentId/label/task/status/lastOutput/reason`）；确认 `assistant.progress` 的 key allowlist 不变（`status` 新增取值 `cancelled` 不受 key 约束，无需改 allowlist）。
- [X] T007 [P] 在 `frontend/src/state/assistantStore.ts`（及其类型定义处）扩展共享类型与 state 骨架：`AssistantProgress["status"]` 联合类型新增 `"cancelled"`；新增生产态 `ActivityStep` / `Subagent` / `QueuedMessage` 类型与 store state 字段占位（`activityStepsByTurn`、`subagentsByTurn`、`queuedMessageBySession`），暂不实现各故事 action（后续故事填充）。
- [X] T008 [P] 在 `tests/guardrails/` 新增门卫测试：断言助理委派（子代理/专员）与父在**同一线程同步**执行（E1 承重不变量）——一旦委派改走线程/异步即应失败，提示重审取消机制。
- [X] T009 [P] 在 `tests/business/`（或 `tests/desktop_api/`）新增回归测试：代际 token 使**陈旧** `cancel_session` 的 `set` 不会误取消复用同一 `session_id` 的新一轮运行（E2）；以及**早停竞态**——停止早于 `begin()` 登记 Event 时，该回合启动后仍被取消、不漏停（C2-E3）。

**Checkpoint**: 运行上下文 + 取消注册表 + 事件契约就绪——用户故事可开工。

---

## Phase 3: User Story 1 - 运行时不被误唤醒，并且随时能停 (Priority: P1) 🎯 MVP

**Goal**: 助理"正在处理"时输入被门控、不被误唤醒；用户随时可"停止"，停止**深度穿透**到其同步派出的子任务（父子皆停为可恢复暂停），对话回到就绪态且已产内容不丢。

**Independent Test**: 发起持续任务 → 运行期无法再发送/唤醒；点停止 → 数秒内回就绪、进度"已停止"、已产内容保留；若派了子任务 → 子会话状态变 `suspended`（无"主停子未停"残留）；助理反问（waiting_for_user）时输入可用。

### Tests for User Story 1 ⚠️（先写、先失败）

- [X] T010 [P] [US1] 在 `tests/business/` 写 loop 取消与深度取消测试（先失败）：`AgentLoop` 在迭代开头与 LLM 返回后/工具批次前命中 `cancel_event` → 置会话 `suspended` 并返回 `ResultType.CANCELLED`；父子同线程链路中子 loop 读到父 Event → 父子皆 `suspended`；`CANCELLED` 不被当错误。
- [X] T011 [P] [US1] 在 `tests/desktop_api/` 写运行时与端点测试（先失败）：`AssistantRuntime.cancel_session` 在注册表 `set` 该会话 Event 并返回 `accepted`；`POST /sessions/{id}/stop` 无运行回合时 `accepted=false`、有则 `true`；`CANCELLED` 时 flush 增量 display 消息 + 发 `assistant.progress{status:"cancelled"}`。
- [X] T011a [P] [US1] 在 `tests/integration/`（或 `tests/desktop_api/`）写"确认 pending 时停止"测试（先失败）：回合阻塞在高危确认等待中点停止 → 该确认被 fail-closed 当拒绝、回合唤醒到取消检查点并 `CANCELLED`；CC-001 同步确认协议（first-decision-wins / expires_at）不回归（FR-006b / C2-X1）。
- [X] T012 [P] [US1] 在 `frontend/tests/unit/` 写 composer 门控与停止测试（先失败）：输入可用性由 `progress.status==='running'` 驱动；`running` 时发送按钮变"停止"、点击后 ≤200ms 进入"停止中"反馈、生效前重复点击幂等；`waiting_for_user` 不门控。

### Implementation for User Story 1

- [X] T013 [US1] 在 `src/business/agents/agent_loop.py` 实现协作式取消：每轮迭代开头与"LLM 返回后、执行工具批次前"经 `run_context.get_current()` 读取 `cancel_event`，命中则 `update_session_status("suspended")` 并返回 `ResultType.CANCELLED`（依赖 T003、T005）。
- [X] T014 [US1] 在 `src/business/orchestration/agent/orchestrator.py` 处理 `CANCELLED`：assistant 路径把 `CANCELLED` 当**正常终止**返回、不走 `_emit_agent_error`；`_run_delegated_executor` 把子 loop 的 `CANCELLED` 当"已停止/已暂停"非失败返回，并**先落库**该委派的工具结果（记"子代理 X 已被停止、可 `continue_subagent` 续跑"）再轮父 loop 退出，为"继续任务"留线索（依赖 T013）。
- [X] T015 [US1] 在 `src/desktop_api/assistant_runtime.py` 实现 `cancel_session(sessionId)`（经 `run_context.request_cancel` set Event，含代际校验）；并在收到 `CANCELLED` 结果时 flush 增量 display 消息 + 发 `assistant.progress{status:"cancelled"}`；若该会话此刻存在 pending 高危确认（回合阻塞在确认等待中），`cancel_session` MUST 将该确认 fail-closed 当"拒绝"并唤醒回合到取消检查点，使停止即时生效，且不破坏 CC-001 同步确认协议（first-decision-wins / expires_at）（FR-006b / C2-X1）（依赖 T003、T004）。
- [X] T016 [US1] 在 `src/desktop_api/routers/assistant.py` 新增 `POST /api/assistant/sessions/{sessionId}/stop`：调用 `AssistantRuntime.cancel_session`，返回 `{ "accepted": boolean }`；4xx 翻译为用户可懂文案、不回传 stack/内部 ID（依赖 T015）。
- [X] T017 [P] [US1] 在 `frontend/src/api/assistant.ts` 新增 typed client `stopAssistantRun(sessionId)`（带 `X-Mexemplar-Session`）。
- [X] T018 [US1] 在 `frontend/src/state/assistantStore.ts` 实现：输入门控派生于 `progress.status==='running'`（`waiting_for_user` 视为非忙、可输入）；`stopAssistantRun` action 与"停止中"过渡态；消费 `assistant.progress{status:"cancelled"}` → 解锁输入、回就绪态、保留已产内容（依赖 T007、T017）。
- [X] T019 [US1] 在 `frontend/src/screens/assistant/MessageComposer.tsx` 实现：`running` 时发送按钮切为"停止"；点击 ≤200ms 进入"停止中"反馈；生效前重复点击幂等（不重复取消、不报错）；`waiting_for_user` 输入可用（依赖 T018）。
- [X] T020 [US1] 在 `frontend/src/screens/assistant/AssistantScreen.tsx` 接线停止动作与运行态展示（渲染停止按钮态、消费 progress 解锁）（依赖 T018、T019）。
- [X] T021 [P] [US1] 在 `frontend/src/styles/theme.css` 新增停止/"停止中"/门控禁用输入的样式。
- [X] T022 [US1] 在 `frontend/tests/e2e/` 新增冒烟：发起持续任务 → 运行期不可发送 → 点停止 → 数秒内回就绪、进度"已停止"、对话历史保留已产内容（依赖 T013–T021）。

**Checkpoint**: US1 可独立交付为 MVP——输入门控 + 协作式深度取消停止可用且有测试。

---

## Phase 4: User Story 2 - 它忙的时候我可以先把下一句想好（排队） (Priority: P2)

**Goal**: 助理忙时用户可写好"下一条"排队，离开 running 时自动发出；**每会话仅一条**、可原地编辑（编辑态不外发）；停止则退回普通草稿；排队按会话保留、不持久化到后端。前端驱动（后端 `dispatch_message` 既有 `accepted=False` 作并发安全网）。

**Independent Test**: 运行期写一条 → 排队；回合自然结束（含以反问结束）→ 自动发出；双击可编辑、编辑期不外发、回车/失焦恢复待发；再写仍改同一条；停止后退回草稿；切会话再切回仍在。

### Tests for User Story 2 ⚠️（先写、先失败）

- [X] T023 [P] [US2] 在 `frontend/tests/unit/` 写排队状态机测试（先失败）：三态 `idle/editing/queued`；`running` 提交进 `queued`；回合离开 `running` 时 `succeeded`/`waiting_for_user` 自动派发，`failed` 与 `cancelled` 退回普通草稿、不派发；编辑态 0 例提前外发；每会话仅一条（再写改同一条）；停止或失败退回普通草稿；按 `sessionId` 各存一份、跨会话切换保留。

### Implementation for User Story 2

- [X] T024 [US2] 在 `frontend/src/state/assistantStore.ts` 实现 `queuedMessage` 状态机：按 `sessionId` 存 `{ text, state: 'editing'|'queued' }`；`running` 时提交进 `queued`；监听 progress 离开 `running`，`succeeded`/`waiting_for_user` 自动派发已 `queued` 消息（经既有 `sendAssistantMessage`，撞 `accepted=false` 静默重排），`failed` 与 `cancelled` 时退回普通草稿、不派发；保证单条不变量与跨会话保留（依赖 T007、T018）。
- [X] T025 [US2] 在 `frontend/src/screens/assistant/MessageComposer.tsx` 实现整框三态交互：`running` 输入即进 `editing`；回车或失焦 `editing→queued`；双击 `queued→editing`；编辑态绝不外发（即使此刻助理空闲）；排队态显示可见"双击编辑"提示并提供键盘可达入口（聚焦后回车进入编辑），不以双击为唯一入口（P2-a11y）（依赖 T024）。
- [X] T026 [P] [US2] 在 `frontend/src/styles/theme.css` 新增"排队态/编辑态"整框样式。
- [X] T027 [US2] 在 `frontend/tests/e2e/` 新增冒烟：运行期排队 → 回合结束自动派发；停止后排队退回草稿（依赖 T024–T026）。

**Checkpoint**: US1 + US2 各自独立可用（US2 为纯前端，不依赖 US1 后端，但与 US1 共享 `assistantStore.ts` / `MessageComposer.tsx` / `theme.css`）。

---

## Phase 5: User Story 3 - 看得见主助理自己的思考过程 (Priority: P2)

**Goal**: 主助理推理/工具调用/工具结果**实时**进入回合内**默认折叠、限高内滚**的过程区域；最终回复正常显示且不重复；历史会话可展开回看（既有中间消息重建，已压缩则规整概要）。

**Independent Test**: 发起任务 → 出现默认折叠过程区，运行转圈不自动展开；展开见推理/调用/结果实时追加，最终回复单独显示不重复；过程超限高时内部滚动；重开历史会话仍可展开回看。

### Tests for User Story 3 ⚠️（先写、先失败）

- [X] T028 [P] [US3] 在 `tests/business/` 写活动事件测试（先失败）：`AgentLoop` 仅在 ContextVar 存在时 emit `assistant_agent_step`；`session_id` 取 root、子代理步骤带 `subagent_id`（≠root）；`kind∈{reasoning,tool_call,tool_result}`；单回合事件设上限/合并；并断言 `kind=reasoning` 仅随带 `tool_calls` 的中间消息一同产生（不单独 emit 不落库的纯推理），使实时与历史重建口径一致（C2-E4）。
- [X] T029 [P] [US3] 在 `tests/guardrails/` 写门卫测试（先失败）：非助理 Agent（PM/Programmer/Trial，ContextVar 空）**零** `assistant_agent_step` emit、行为零变化（E4 + CC-005）。
- [X] T030 [P] [US3] 在 `tests/desktop_api/` 写 projector 与端点测试（先失败）：`assistant_agent_step → assistant.activity` 仅对 `assistant/ephemeral_subagent/specialist` 投影、其余返回空；payload 显式走 009 payload safety allowlist **脱敏**（不仅截断，E5）；`GET /sessions/{id}/transcript?subagentId=` 由 `MessageRepository` 重建 `ActivityStep[]`，且重建结果与实时事件一致**走 009 payload allowlist 脱敏**（不仅截断，C2-E2）；已压缩回合带"已压缩/步骤不全"标志（C2-E1）。
- [X] T031 [P] [US3] 在 `frontend/tests/unit/` 写时间线测试（先失败）：`ActivityTimeline` 默认折叠不自动展开；超限高内部滚动、不撑长页面；最终回复不在时间线重复；历史经 transcript 重建；**已压缩回合**展开时以规整概要展示（复用"之前的对话内容"折叠样式）、不报错（FR-020 / C2-E1）；收到 `backend.resync_required` 时活动时间线走权威快照刷新（FR-032 / G1）。

### Implementation for User Story 3

- [X] T032 [US3] 在 `src/business/agents/agent_loop.py` 实现逐步活动事件：在 `save_assistant_message`（带 `tool_calls` 的中间消息）后与 tool 结果后 `emit("assistant_agent_step", session_id=<root>, subagent_id=<self≠root>, agent_type, kind, tool_name?, text=<截断>, seq)`；仅当 ContextVar 存在时 emit；单回合上限/合并；最终无工具调用的回复不进此事件（依赖 T003、T002；与 T013 同文件，US1 之后）。
- [X] T033 [US3] 在 `src/desktop_api/ui_event_projector.py` 实现 `assistant_agent_step → assistant.activity` 投影：按 `agent_type` 过滤（仅 `assistant/ephemeral_subagent/specialist`），payload 走 009 allowlist 脱敏（依赖 T006、T032）。
- [X] T034 [US3] 新建 `src/business/agents/observability.py`（业务读模型）：由 `MessageRepository` 的中间 assistant（含 `tool_calls`）与 tool 结果消息重建 `ActivityStep[]`（主助理 = 无 `subagentId`；指定 `subagentId` = 该子任务），文本截断、不暴露内部术语，并显式走 009 payload allowlist 脱敏（不仅截断，C2-E2）；`kind=reasoning` 仅从带 `tool_calls` 中间消息重建（C2-E4）。
- [X] T034a [US3] 在 `src/business/agents/observability.py` 标记历史回合保真度：**先确认压缩检测信号**——优先复用既有压缩/Segment 沉淀标记（006「之前的对话内容」折叠所依据的压缩痕迹），若无现成标记则按中间消息缺口推断；据此判断某回合中间步骤是否已不完整，在 transcript 重建结果上给出"已压缩/步骤不全"标志（只读、**不补充持久化**，无新表/迁移），供前端按规整概要渲染（FR-020 / C2-E1）。
- [X] T035 [US3] 在 `src/desktop_api/assistant_runtime.py` 暴露 transcript facade 方法并在 `src/desktop_api/routers/assistant.py` 新增 `GET /api/assistant/sessions/{sessionId}/transcript?subagentId={id?}` → 调 `observability.py` 读模型（router 不直连 Repository，经 facade）（依赖 T034）。
- [X] T036 [US3] 在 `frontend/src/api/assistant.ts` 新增 `getSubagentTranscript(sessionId, subagentId?)`（与 T017 同文件，US1 之后）。
- [X] T037 [US3] 在 `frontend/src/state/assistantStore.ts` 实现：消费 `assistant.activity` → 追加到对应回合 `steps`（`subagentId==null` 进主时间线），设前端上限；打开历史会话经 `getSubagentTranscript` 重建过程；收到 `backend.resync_required` 走权威快照刷新（依赖 T007、T036；与 US1/US2 同文件，按序）。
- [X] T038 [US3] 把 `frontend/src/screens/assistant/ActivityTimeline.tsx` 由演示类型（`DemoStep/DemoTurn`）改接**生产 store 类型**：默认折叠、不受控的 `<details>`（运行中头部转圈 + "正在处理"但不自动展开），正文限高 + 内部滚动（复用 `.me-scroll`），最终回复不在此重复（依赖 T037）。
- [X] T038a [US3] 在 `frontend/src/screens/assistant/ActivityTimeline.tsx` 对带"已压缩"标志的历史回合渲染规整概要（复用既有"之前的对话内容"折叠样式），不报错、不暴露内部术语（FR-020 / E1；依赖 T034a、T037）。
- [X] T039 [US3] 在 `frontend/src/screens/assistant/AssistantScreen.tsx` 按回合渲染 `ActivityTimeline`；历史回合展开时触发 transcript 拉取（与 T020 同文件，US1 之后；依赖 T037、T038）。
- [X] T040 [P] [US3] 在 `frontend/src/styles/theme.css` 新增时间线折叠/限高/内滚样式（与 T021/T026 同文件，按序）。

**Checkpoint**: US3 独立可用——主助理过程实时透明 + 历史可回看。

---

## Phase 6: User Story 4 - 看得见它派出去的子任务在干什么 (Priority: P2)

**Goal**: 委派子任务时当前对话出现带动效卡片（任务 + 状态 running/done/suspended/failed），双击展开子任务完整过程（含工具）；子任务归属当前对话；重连/重开经权威端点恢复列表与状态。

**Independent Test**: 派子任务 → 出现卡片实时反映状态；双击 → 抽屉展示该子任务完整过程（含工具与结果）；断连重连/重开会话 → 子任务列表与状态由 `GET …/subagents` 权威恢复。

### Tests for User Story 4 ⚠️（先写、先失败）

- [X] T041 [P] [US4] 在 `tests/business/` 写子任务生命周期事件测试（先失败）：`orchestrator` 委派点在开始/完成/暂停时 emit `assistant_subagent_started/finished/paused`（`session_id=parent`、含 `subagent_id/label/task/status/last_output?/reason?`）。
- [X] T042 [P] [US4] 在 `tests/desktop_api/` 写 projector 与端点测试（先失败）：`assistant_subagent_* → assistant.subagent` 投影 + payload allowlist；`GET /sessions/{id}/subagents` 由 `WorkflowTransitionRepository` + `SessionRepository` 重建权威列表与状态；断言 `lastOutput` 走 009 脱敏（C2-E2）。
- [X] T043 [P] [US4] 在 `frontend/tests/unit/` 写卡片测试（先失败）：`SubagentCard` 实时反映状态、运行动效、双击开详情；活动步骤按 `subagentId` 归类进卡片；`backend.resync_required`/打开会话经 `listSubagents` 兜底。

### Implementation for User Story 4

- [X] T044 [US4] 在 `src/business/orchestration/agent/orchestrator.py` 的委派点 emit `assistant_subagent_started/finished/paused`（`session_id=<parent>`、`subagent_id/label/task/status/last_output?/reason?`）；暂停事件在该委派被取消/暂停时发（与 US1 的 `_run_delegated_executor` CANCELLED 处理衔接）（依赖 T002、T014；与 T014 同文件，US1 之后）。
- [X] T045 [US4] 在 `src/desktop_api/ui_event_projector.py` 实现 `assistant_subagent_* → assistant.subagent` 投影 + payload allowlist 脱敏（与 T033 同文件，US3 之后；依赖 T006、T044）。
- [X] T046 [US4] 在 `src/business/agents/observability.py` 增子任务权威列表读模型：由 `WorkflowTransitionRepository`（委派流转 `assistant_delegation_started/completed/failed/paused`）+ `SessionRepository`（子会话状态）重建 `Subagent[]`；`lastOutput` 等文本字段走 009 payload allowlist 脱敏（C2-E2）（与 T034 同文件，US3 之后）。
- [X] T047 [US4] 在 `src/desktop_api/assistant_runtime.py` 暴露 facade 方法并在 `src/desktop_api/routers/assistant.py` 新增 `GET /api/assistant/sessions/{sessionId}/subagents` → 调读模型，返回 `{ "items": Subagent[] }`（与 T035 同文件，US3 之后；依赖 T046）。
- [X] T048 [US4] 在 `frontend/src/api/assistant.ts` 新增 `listSubagents(sessionId)`（与 T017/T036 同文件，按序）。
- [X] T049 [US4] 在 `frontend/src/state/assistantStore.ts` 实现：消费 `assistant.subagent` → upsert 子任务卡片到当前回合；把 `subagentId` 非空的 activity steps 归类到对应卡片；`backend.resync_required`/打开会话经 `listSubagents` 拉权威列表兜底（与 T018/T024/T037 同文件，按序；依赖 T048）。
- [X] T050 [US4] 把 `frontend/src/screens/assistant/SubagentCard.tsx` 由演示类型（`DemoSubagent`）改接**生产 store 类型**：运行中动效、状态徽标（running/done/suspended/failed）、双击开详情；显示可见"双击查看详情"提示并提供键盘可达入口（Enter/Space 打开详情），不以双击为唯一入口（P2-a11y）（依赖 T049）。
- [X] T051 [US4] 把 `frontend/src/screens/assistant/SubagentDetailDrawer.tsx` 改接生产类型：双击卡片打开，调 `getSubagentTranscript(sessionId, subagentId)` 展示该子任务完整过程（含工具与经脱敏的结果）（依赖 T036、T050）。
- [X] T052 [US4] 在 `frontend/src/screens/assistant/AssistantScreen.tsx` 渲染子任务卡片与详情抽屉，按序与主时间线交织（与 T020/T039 同文件，US3 之后；依赖 T049、T050、T051）。
- [X] T053 [P] [US4] 在 `frontend/src/styles/theme.css` 新增卡片/抽屉样式（与 T021/T026/T040 同文件，按序）。

**Checkpoint**: US4 独立可用——子任务从黑盒变可见（卡片 + 双击详情 + 权威兜底）。

---

## Phase 7: User Story 5 - 被打断/暂停的子任务，能接着干 (Priority: P3)

**Goal**: 暂停态子任务卡片提供"继续任务"：唤醒主助理由其调 `continue_subagent` 续跑（守 100% 调度），可带补充消息；续跑结果走主助理正常回复；运行中不可续；非本会话拒绝；未续跑给兜底提示。

**Independent Test**: 停止跑着子任务的回合使其暂停 → 卡片"已暂停"+"继续任务"；点继续（可填补充）→ 主助理被唤醒续跑、结果作为正常回复；运行中"继续任务"不可用；非本会话子任务被拒绝。

**依赖**: 需要 US1（产生暂停态）与 US4（看见并定位子任务卡片）。

### Tests for User Story 5 ⚠️（先写、先失败）

- [X] T054 [P] [US5] 在 `tests/business/`（或 `tests/desktop_api/`）写续跑测试（先失败）：带 `subagent_id` 的助理消息唤醒主助理 → 调既有 `continue_subagent` 续跑；校验目标子任务由 `suspended→active`（FR-030a），主助理未续跑时给明确兜底而非静默；归属校验复用 `_resolve_subagent_session` 拒绝非己出会话；目标子任务 `status==active`（运行中）时拒绝并发续跑。
- [X] T055 [P] [US5] 在 `frontend/tests/unit/` 写继续任务测试（先失败）：仅 `suspended` 卡片显示可用"继续任务"，`running` 时不可用；补充消息一并带入续跑。

### Implementation for User Story 5

- [X] T056 [US5] 在 `src/business/orchestration/agent/orchestrator.py`（续跑路径）实现"继续任务"语义：处理带 `subagent_id` 的续跑指令唤醒主助理走 `continue_subagent`；续跑后校验 `suspended→active`，未续跑时产出用户可懂兜底提示；归属校验复用 `_resolve_subagent_session`（与 T014/T044 同文件，US4 之后）。
- [X] T057 [US5] 在 `frontend/src/state/assistantStore.ts` 新增 `continueSubagent(sessionId, subagentId, supplemental?)` action：经既有 `sendAssistantMessage` 发带 `subagent_id`（+ 可选补充消息）的续跑指令（**不新增端点**），限定仅本会话子任务（与 T018/T024/T037/T049 同文件，US4 之后；依赖 T056）。
- [X] T058 [US5] 在 `frontend/src/screens/assistant/SubagentCard.tsx` 为 `suspended` 卡片增"继续任务"按钮（`running` 时不可用）+ 可选补充消息输入，触发 `continueSubagent`（与 T050 同文件，US4 之后；依赖 T057）。
- [X] T059 [US5] 在 `frontend/src/screens/assistant/AssistantScreen.tsx` 接线"继续任务"（含未续跑兜底提示展示）（与 T020/T039/T052 同文件，US4 之后；依赖 T057、T058）。
- [X] T060 [P] [US5] 在 `frontend/src/styles/theme.css` 新增"继续任务"按钮与补充输入样式（与既有 theme 任务同文件，按序）。
- [X] T061 [US5] 在 `frontend/tests/e2e/` 新增冒烟：停止跑着子任务的回合 → 卡片"已暂停" → 点"继续任务" → 主助理续跑、结果作为正常回复出现（依赖 T056–T060）。

**Checkpoint**: 全部 5 个用户故事独立可用，闭环（看见 → 停得下 → 接着干）完成。

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: 活文档、文案审查、隔离与全量验证。

- [X] T062 [P] 更新 `docs/ARCHITECTURE.md`：新增取消原语（业务层 ContextVar 运行上下文 + session→Event 注册表）、新 blinker 事件、公开 UI 事件（`assistant.activity`/`assistant.subagent`、`assistant.progress` 增 `cancelled`）、新端点（stop/subagents/transcript）。
- [X] T063 [P] 更新 `frontend/AGENTS.md` 并同步镜像 `frontend/CLAUDE.md`、`frontend/GEMINI.md`：助理屏新交互（输入门控/停止三态/排队三态/活动时间线/子任务卡片+详情/继续任务）。
- [X] T064 [P] 更新 `src/AGENTS.md` 并同步镜像 `src/CLAUDE.md`、`src/GEMINI.md`：取消原语、`assistant_agent_step`/子任务生命周期事件、`ResultType.CANCELLED`、只读读模型 `observability.py`。
- [X] T065 [P] FR-031 / SC-008 文案审查：扫描面向用户的**非过程区**文案（按钮/状态/空态/错误），确认 0 命中内部术语（archive/compression/segment/event sequence/causation/subagent dispatch 等）；过程区为受控透明例外可原样显示。
- [X] T066 移除演示脚手架：生产组件接好真实 store + 事件后，删除一次性演示文件 `frontend/src/screens/assistant/AssistantDemoView.tsx`、`frontend/src/screens/assistant/DemoComposer.tsx`、`frontend/src/state/assistantDemoStore.ts`，并清除对它们的引用/路由；确认 `ActivityTimeline/SubagentCard/SubagentDetailDrawer` 已全部改接生产类型、不再 import `DemoStep/DemoTurn/DemoSubagent`（依赖 T038、T050、T051；删除后 `npm run lint && npm run test` 仍绿）。
- [X] T067 运行 `quickstart.md` 全量验证：`uv run pytest tests/business tests/desktop_api tests/guardrails -q` + `cd frontend && npm run lint && npm run test && npm run test:e2e`，对照 SC-001~SC-008 验收门槛。
- [X] T068 [P] 代码风格收尾：`uv run black src/ tests/`、`uv run flake8 src/ tests/`、`cd frontend && npm run lint`。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始。
- **Foundational (Phase 2)**: 依赖 Setup；**阻塞所有用户故事**（run_context / events / registry / 共享类型）。
- **User Stories (Phase 3–7)**: 均依赖 Foundational 完成。
  - **US5 (P3)** 额外依赖 **US1**（产生暂停态）与 **US4**（卡片定位子任务）。
  - 其余故事在 Foundational 后逻辑上独立，但见下"共享文件"约束。
- **Polish (Phase 8)**: 依赖期望交付的故事完成。

### User Story Dependencies

- **US1 (P1)**: Foundational 后即可开始，无对其他故事依赖 → **MVP**。
- **US2 (P2)**: 纯前端，逻辑独立；与 US1 共享 `assistantStore.ts` / `MessageComposer.tsx` / `theme.css`。
- **US3 (P2)**: 逻辑独立；emit 门控依赖 Foundational 的 run_context。
- **US4 (P2)**: 逻辑独立；子任务暂停态由 US1 的取消处理产生（卡片"已暂停"完整体验需 US1）。
- **US5 (P3)**: 依赖 US1 + US4。

### 共享文件约束（限制跨故事并行）

以下文件被多个故事按序修改，**不可跨故事并行**，建议按优先级 P1→P2→P3 串行实现或严格协调：

- `frontend/src/state/assistantStore.ts`：T018(US1) → T024(US2) → T037(US3) → T049(US4) → T057(US5)
- `frontend/src/screens/assistant/AssistantScreen.tsx`：T020(US1) → T039(US3) → T052(US4) → T059(US5)
- `frontend/src/screens/assistant/MessageComposer.tsx`：T019(US1) → T025(US2)
- `frontend/src/screens/assistant/SubagentCard.tsx`：T050(US4) → T058(US5)
- `frontend/src/styles/theme.css`：T021 → T026 → T040 → T053 → T060
- `frontend/src/api/assistant.ts`：T017 → T036 → T048
- `src/business/agents/agent_loop.py`：T013(US1) → T032(US3)
- `src/business/orchestration/agent/orchestrator.py`：T014(US1) → T044(US4) → T056(US5)
- `src/desktop_api/ui_event_projector.py`：T033(US3) → T045(US4)
- `src/business/agents/observability.py`：T034(US3) → T034a(US3) → T046(US4)
- `src/desktop_api/assistant_runtime.py` / `routers/assistant.py`：T015/T016(US1) → T035(US3) → T047(US4)

### Within Each User Story

- 测试先写并先失败，再实现（本特性测试已请求）。
- 后端原语/读模型 → projector/端点 → 前端 API → store → 组件 → 屏接线 → e2e。

### Parallel Opportunities

- Foundational：T002、T005、T006、T007、T008、T009 标 [P]，可并行（不同文件）；T003 先于 T004。
- 每个故事内部，标 [P] 的测试任务（不同测试文件）可并行先写。
- US1 内：T017（api）、T021（css）、测试 T010/T011/T011a/T012 与各自实现解耦部分可并行起步。
- 因共享文件众多，**跨故事并行收益有限**——优先按 P1→P2→P3 串行交付。

---

## Parallel Example: User Story 1

```bash
# 先并行写 US1 的失败测试（不同文件）：
Task: "T010 loop 取消 + 深度取消测试 in tests/business/"
Task: "T011 runtime cancel + stop 端点测试 in tests/desktop_api/"
Task: "T011a 确认 pending 时停止测试 in tests/integration/"
Task: "T012 composer 门控 + 停止测试 in frontend/tests/unit/"

# 实现期可并行的解耦项：
Task: "T017 stopAssistantRun in frontend/src/api/assistant.ts"
Task: "T021 停止/停止中样式 in frontend/src/styles/theme.css"
```

---

## Implementation Strategy

### MVP First（仅 US1）

1. 完成 Phase 1 Setup。
2. 完成 Phase 2 Foundational（**阻塞所有故事**）。
3. 完成 Phase 3 US1。
4. **STOP & VALIDATE**：独立验证 US1（门控 + 深度取消停止）。
5. 可交付/演示。

### Incremental Delivery

1. Setup + Foundational → 基础就绪。
2. US1（P1）→ 独立验证 → 交付（MVP！）。
3. US2 / US3 / US4（P2）→ 各自独立验证 → 交付（注意共享文件按序）。
4. US5（P3，依赖 US1+US4）→ 独立验证 → 交付，闭环完成。
5. Polish：活文档 + 文案审查 + quickstart 全量验证。

### Notes

- [P] = 不同文件、无未完成依赖。
- [Story] 标签用于可追溯性。
- 每个故事应可独立完成与测试；先确认测试失败再实现。
- 每个任务或逻辑组完成后提交。
- 关键不变量：取消必须**协作式 + 同线程同步委派**（E1 门卫守护）；非助理 Agent（PM/Programmer/Trial）**零行为变化**（E4/CC-005 门卫守护）；面向前端事件必经 UI Event Registry + payload allowlist 脱敏（E5/CC-004）；**无新表/迁移**（CC-006）。
