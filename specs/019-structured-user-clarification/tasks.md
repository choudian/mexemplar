---
description: "Task list for 019 结构化多选澄清"
---

# Tasks: 结构化多选澄清 (Structured Multi-Choice Clarification)

**Input**: Design documents from `specs/019-structured-user-clarification/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: 含测试任务——constitution IV（可验证交付）与项目硬规则（改编排/事件/恢复/confirmation/AgentLoop 必须补行为契约测试）要求。

**Organization**: 按用户故事分组。Foundational 交付完整后端机制 + 可渲染/提交的前端卡；US1/US2/US3 叠加各自专属路径的测试与接线。

## Constitution-Driven Minimums（适用性说明）

- SQLite/迁移：**N/A**——本特性零持久化（CC-001），不新增表/迁移/Repository。
- DuckDB 过滤边界：**N/A**——不触碰录制分析层。
- 配置/secret：**无新增配置项**；secret 防护走 prompt 禁令 + 事件 payload `ui_event_safety_service` 递归扫描 + resolved 事件不含答案。
- Wiring/guard 测试：✅ 独占工具门卫、subagent/specialist 不暴露门卫、UI 事件注册契约测试。
- 活文档：✅ `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`、根/模块 AI 入口镜像、`docs/local/todo/agent-tool-patterns.md`（Polish 阶段）。

## Project Paths

- Python: `src/`，测试 `tests/`，`uv run pytest tests/`
- Frontend: `frontend/src/`，测试 `frontend/tests/{unit,e2e}/`，`npm run {test,lint,build}`

---

## Phase 1: Setup

**Purpose**: 确认隔离工作区基线干净，铺设独占工具机制的最小入口

- [ ] T001 在 worktree 根运行基线冒烟（`uv run pytest tests/business tests/desktop_api -q` 抽样 + `cd frontend && npm install`），确认起点干净；记录预存在失败（若有）
- [ ] T002 [P] 在 `src/business/agents/config.py` 的 `ToolDefinition` 增加字段 `requires_exclusive_call: bool = False`，更新 docstring 说明"需独占调用：与其他工具同批则全批 invalid_model_output"

**Checkpoint**: 独占语义的声明位就绪

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 交付完整后端澄清机制（manager 全终态 + 工具 + 事件 + decision API + adapter）与可渲染/提交的前端卡。所有用户故事都依赖本阶段。

**⚠️ CRITICAL**: 本阶段完成前任何用户故事不能开工

### 后端机制

- [ ] T003 [P] 新建 `src/business/agents/tools/clarification_manager.py`：`PendingClarification` / `NormalizedQuestion` / `NormalizedOption` / `ResolvedAnswer` 数据类，模块级 `_pending_clarifications` + `_clarification_lock` + 可注入 `_clarification_signal`，常量 `CLARIFICATION_TIMEOUT_S=300`；实现 `register_clarification_signal` / `create_pending` / `get_pending` / `get_pending_for_session` / `get_remaining_timeout_ms` / `reset_clarification_state_for_tests`（结构对标 `builtin_general_tools` 确认机制，但完全独立）
- [ ] T004 在 `clarification_manager.py` 实现 first-decision-wins 终态与唤醒：`submit_decision(session_id, request_id, decision, answers)`（归属校验 + 答案校验 + selectedOptionIds→selectedLabels + 设 answered/cancelled + `event.set()`，已结算幂等忽略）、`settle_clarifications_for_session(session_id, status)`（stopped）、`settle_all_clarifications(status)`（shutdown），全部经 `event.is_set()` 守门
- [ ] T005 在 `src/business/agents/tools/assistant_tools.py` 新增 `ASK_USER_QUESTION_SCHEMA` + `create_ask_user_question_handler(session_id)`：输入校验（1–4 题/2–4 选项/必填/批次内问题不重复/同题标签不重复）失败返回 `error_json` 不创建 pending；后端生成 `q{i}`/`q{i}o{j}` 稳定 ID；从 `run_context` 取归属会话；创建 pending→emit requested→`event.wait(300s)`→按终态组装 `{status, answers}` 结果；signal 未注册返回 `status="unavailable"`；导出到 `__all__`
- [ ] T006 在 `src/business/orchestration/agent/orchestrator.py` 的 `_build_assistant_tools`（`static_tools`）注册 `ask_user_question` 工具（`requires_exclusive_call=True, is_interrupting=False`），handler 用 `create_ask_user_question_handler(session_id)`；确认 `_build_delegated_executor_tools` 不含此工具
- [ ] T007 在 `src/business/agents/agent_loop.py` 的 `_execute_tool_batch` 增加独占混批检查（紧随中断型混批检查后）：`batch_size>1` 且批内任一 `tool_def.requires_exclusive_call` → 对全部 call `_save_error(..., "invalid_model_output", ...)` 并 `return None`；solo 独占 call 落入既有 ordinary 串行路径阻塞执行

### 事件与 desktop adapter

- [ ] T008 [P] 在 `src/desktop_api/ui_events.py` 的 `UI_EVENT_REGISTRY` 注册 `assistant.clarification_requested`（payload `requestId/sessionId/questions/expiresAt/status`，required 去掉 expiresAt，enum `status∈{pending}`，scope `sessionId`）与 `assistant.clarification_resolved`（payload `requestId/sessionId/status`，enum `status∈{answered,cancelled,timeout,stopped,shutdown}`，scope `sessionId`），均按 contracts/events_clarification.md
- [ ] T009 新建 `src/desktop_api/clarifications.py`：`_DesktopClarificationSignal`（emit→`event_queue.publish_nowait("assistant.clarification_requested", payload, {"sessionId":...})`）、`install_clarification_signal`、`clarification_requested_payload(request_id)`、`record_clarification_decision(session_id, request_id, decision, answers)`、`pending_clarification_snapshot(session_id)`、`settle_clarifications_for_session_stopped(session_id)`、`settle_all_clarifications_shutdown()`；resolved 事件经 `event_queue` 发出且不含答案（对标 `confirmations.py`）
- [ ] T010 [P] 在 `src/desktop_api/schemas.py` 增加 DTO：`AssistantClarificationOption/Question/Snapshot`、`AssistantClarificationPendingResponse`、`AssistantClarificationAnswerInput`、`AssistantClarificationDecisionRequest`、`AssistantClarificationDecisionResponse`
- [ ] T011 在 `src/desktop_api/routers/assistant.py` 增加 `POST /sessions/{sessionId}/clarifications/{requestId}/decision`（调 `record_clarification_decision`，422 校验失败/404 归属/200 幂等），按 contracts/api_clarifications.md
- [ ] T012 在 `src/desktop_api/assistant_runtime.py` 构造期 `install_clarification_signal()`（与 `install_confirmation_signal` 并列）

### 前端基础

- [ ] T013 [P] 在 `frontend/src/api/assistant.ts` 增加类型（`ClarificationOption/Question/Request`、Answer 输入）与 `getPendingClarifications(sessionId)`、`submitClarificationDecision(sessionId, requestId, body)`
- [ ] T014 新建 `frontend/src/screens/assistant/ClarificationCard.tsx`：可访问 `fieldset`+`radio`/`checkbox`，每题含选项（label/description/纯文本 preview）+ "其他"输入；"提交"/"暂不回答" 按钮 + 倒计时；提交期间全部控件 `disabled`；独立于 `ConfirmationToast`，不显示"全部允许"
- [ ] T015 在 `frontend/src/state/assistantStore.ts` 增加按 session 的 `pendingClarification` / `clarificationDrafts` / `clarificationSubmitting`，消费 `assistant.clarification_requested`（upsert）与 `assistant.clarification_resolved`（清理 pending+草稿）；`submitClarification` / `cancelClarification` action（提交置 submitting、成功清理、失败置友好错误）；切换会话保留草稿
- [ ] T016 在 `frontend/src/screens/assistant/AssistantScreen.tsx` 输入框上方渲染 `ClarificationCard`（仅当前会话有 pending 时），接 store action

### Foundational 门卫测试

- [ ] T017 [P] 新建 `tests/business/test_agent_loop_exclusive_tool.py`：独占工具 solo 阻塞执行后 loop 续跑；与普通/中断/副作用工具混批 → 全批 `invalid_model_output` 零执行且配对完整
- [ ] T018 [P] 新建 `tests/guardrails/test_clarification_tool_scope.py`：`ask_user_question` 在主助理工具集存在；`_build_delegated_executor_tools`（subagent/specialist）不含此工具；PM/Programmer/Trial 工具集不含
- [ ] T019 [P] 在 `tests/desktop_api/` 新增 UI 事件注册契约测试：两个 clarification 事件已注册、payload allowlist/enum 生效、嵌套 questions 含禁用值（如 `api_key=`/私钥）被 `validate_ui_event_payload` 拒绝、resolved 不接受 answers 键

**Checkpoint**: 后端机制 + 前端卡可端到端跑通"提交/取消"；门卫就位

---

## Phase 3: User Story 1 - 主助理在关键岔路口征询用户决策 (Priority: P1) 🎯 MVP

**Goal**: 模型单独调用 `ask_user_question` → 卡片展示 → 用户提交（单选/多选/其他）→ 工具结果回填 → 主助理同回合续跑

**Independent Test**: 一道 3 选项单选题端到端：UI 渲染卡片、提交后工具返回 `answered`+所选标签、AgentLoop 同 loop 续跑

### Tests for User Story 1 ⚠️（先写并失败）

- [ ] T020 [P] [US1] 在 `tests/business/test_clarification_manager.py` 写 answered 路径单测：单选（一个 optionId）、多选（多 optionId + otherText 组合）、仅 otherText；selectedOptionIds→selectedLabels 映射正确
- [ ] T021 [P] [US1] 新建 `tests/integration/test_clarification_flow.py`：mock 模型发起单道单选题 → requested 事件 → decision API 提交 → tool result 进上下文 → 主助理继续（answered）
- [ ] T022 [P] [US1] 新建 `frontend/tests/unit/clarificationCard.test.tsx`：渲染问题/选项/预览（纯文本不渲染 HTML）、单选选项可选、键盘可达、提交调用 store action

### Implementation for User Story 1

- [ ] T023 [US1] 完善 `clarification_manager.submit_decision` answered 校验：单选恰好一个 optionId 或一段 otherText（二选一）、多选可组合、每题必答、otherText≤1000；非法 → 返回校验错误且不结算
- [ ] T024 [US1] 完善 `ask_user_question` handler 的 answered 结果组装（`question/selectedLabels/otherText`），确保 tool result 为合法 JSON 字符串
- [ ] T025 [US1] `ClarificationCard` 单选交互：选普通选项与"其他"互斥（选"其他"取消普通选项），提交按钮在"每题已答"前 disabled
- [ ] T026 [US1] `assistantStore` 提交流程：optimistic submitting→调 API→成功由 resolved 事件或返回清理；草稿映射到 `selectedOptionIds/otherText`
- [ ] T027 [US1] 在 `src/business/agents/prompts/assistant_prompt.py` 增加 `ask_user_question` 使用指引：仅关键决策无法可靠推断时用、关联问题一次问齐、不得询问/展示 secret

**Checkpoint**: US1 端到端可独立验证（MVP）

---

## Phase 4: User Story 2 - 用户选择暂不回答 (Priority: P2)

**Goal**: 用户点"暂不回答"取消该组问题，主助理不猜测、不在同回合换说法再问

**Independent Test**: 渲染卡片后取消 → 工具 `cancelled` + 卡片消失 + 主助理本回合不重复追问

### Tests for User Story 2 ⚠️

- [ ] T028 [P] [US2] 在 `tests/business/test_clarification_manager.py` 加 cancelled 路径单测（decision=cancel 不带答案，event set，结果 answers=[]）
- [ ] T029 [P] [US2] 在 `frontend/tests/unit/clarificationCard.test.tsx` 加"暂不回答"用例：调 cancel action、卡片移除、提交期间控件 disabled

### Implementation for User Story 2

- [ ] T030 [US2] `clarification_manager.submit_decision` 的 cancel 分支：置 cancelled、answers 空、event set、幂等
- [ ] T031 [US2] `ClarificationCard` + `assistantStore` 接 cancel：调 decision API（decision=cancel）→ resolved 清理
- [ ] T032 [US2] 在 `assistant_prompt.py` 增加规则：用户取消/超时后不得在同一回合重复发起同一澄清或基于猜测继续执行有副作用动作

**Checkpoint**: US1 + US2 均可独立验证

---

## Phase 5: User Story 3 - 超时、停止与会话恢复 (Priority: P3)

**Goal**: 超时/停止/关闭确定性结算并唤醒 worker；SSE 断线不取消，重连经 pending 快照/回放恢复；并发 first-decision-wins

**Independent Test**: 分别验证 5 分钟超时、停止回合、应用关闭、断线重连、并发提交，均不产生猜测答案

### Tests for User Story 3 ⚠️

- [ ] T033 [P] [US3] 在 `tests/business/test_clarification_manager.py` 加：超时（缩短常量后 event.wait 超时→timeout）、`settle_clarifications_for_session`（stopped）、`settle_all_clarifications`（shutdown）、并发两次 submit 仅首个生效、signal 未注册→unavailable、emit 异常不悬挂
- [ ] T034 [P] [US3] 在 `tests/desktop_api/test_clarification_api.py` 写：GET pending 快照（有/无 pending、不含答案）、decision 归属错配 404、重复/过期提交幂等、resolved 事件不泄漏答案
- [ ] T035 [P] [US3] 在 `tests/integration/test_clarification_flow.py` 加停止链路：pending 期间 stop → worker 收到 stopped → 主助理不续用猜测
- [ ] T036 [P] [US3] 在 `frontend/tests/unit/clarificationCard.test.tsx` 加倒计时显示与会话切换保留草稿、resync 刷新用例

### Implementation for User Story 3

- [ ] T037 [US3] 在 `src/desktop_api/routers/assistant.py` 增加 `GET /sessions/{sessionId}/clarifications/pending`（调 `pending_clarification_snapshot`，无 pending 返回 `{clarification: null}`）
- [ ] T038 [US3] 在 `src/desktop_api/assistant_runtime.py` 的 `cancel_session`（`fail_closed_confirmations_for_session` 旁）并排调用 `settle_clarifications_for_session_stopped(sid)`
- [ ] T039 [US3] 在 `src/desktop_api/app.py` lifespan shutdown（`event_queue.shutdown()` 处）调用 `settle_all_clarifications_shutdown()`
- [ ] T040 [US3] `assistantStore`：会话打开与收到 `backend.resync_required` 时调 `getPendingClarifications` 刷新权威快照；断线不清理 pending
- [ ] T041 [US3] `ClarificationCard` 倒计时基于 `expiresAt`，到点 disable 控件（不自行判定终态，等后端 resolved）

**Checkpoint**: 三个故事均独立可用，边界完备

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: 技术债清理、文档同步、全门禁

- [ ] T042 修复 `tests/test_auth_toast_confirmation.py`：`_build_write_summary/_build_edit_summary/_build_exec_summary` 已迁至 `builtin_permissions.py` 改名 `build_*`，更新引用（核对 `_confirm_or_reject` 现状），使该文件重新通过
- [ ] T043 [P] 扩展 `frontend/tests/e2e/assistant.spec.ts`：mock API 下澄清卡渲染/提交/取消 e2e
- [ ] T044 [P] 更新活文档：`docs/ARCHITECTURE.md`（澄清机制概述）、`docs/PROJECT_CONSTRAINTS.md`（澄清与高危确认分离、内存态约束）
- [ ] T045 [P] 同步 AI 入口镜像：根 `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` 与 `src/AGENTS.md`(+镜像)、`frontend/AGENTS.md`(+镜像)，新增澄清工具/事件约束；在 `docs/local/todo/agent-tool-patterns.md` 标记第 ② 项已实现
- [ ] T046 回归门禁：`uv run pytest tests/business tests/desktop_api tests/integration tests/guardrails -q`（含高危确认/停止/排队/UI event 回归）、`uv run python -m py_compile src/desktop_api/app.py`
- [ ] T047 前端门禁：`cd frontend && npm run test && npm run lint && npm run build`
- [ ] T048 按 quickstart.md 手动冒烟清单逐项核对

---

## Dependencies & Execution Order

- **Setup (P1)**：无依赖，先行
- **Foundational (P2)**：依赖 Setup；**阻塞所有用户故事**
- **US1 (P3)**：依赖 Foundational；MVP
- **US2 (P4)**：依赖 Foundational；可与 US1 并行（不同测试/分支逻辑）
- **US3 (P5)**：依赖 Foundational；停止/关闭接线与 pending 快照独立于 US1/US2
- **Polish (P6)**：依赖所需故事完成

### 关键文件串行点（避免同文件并发冲突）

- `clarification_manager.py`：T003→T004→T023→T030→T033（同文件，串行）
- `assistant_tools.py`：T005→T024（串行）
- `assistantStore.ts`：T015→T026→T031→T040（串行）
- `ClarificationCard.tsx`：T014→T025→T031→T041（串行）
- `routers/assistant.py`：T011→T037（串行）

### Parallel Opportunities

- T002 与 Phase 2 中标 [P] 的 T008/T010/T013 可并行（不同文件）
- 各故事测试任务（T020-T022 / T028-T029 / T033-T036）标 [P] 可并行编写
- Polish 中 T043/T044/T045 可并行

---

## Implementation Strategy

1. Setup → Foundational（完整后端机制 + 可提交前端卡 + 门卫）
2. US1（提交 answered，单/多/其他）→ 独立验证 = MVP
3. US2（取消）→ 独立验证
4. US3（超时/停止/关闭/重连/并发）→ 独立验证
5. Polish（修旧测试、文档镜像、全门禁、quickstart 冒烟）

## Notes

- 全程零 SQLite/DuckDB/迁移/配置（CC-001）；状态纯内存。
- 与高危确认链路完全分离（FR-020）：独立 manager、独立事件、独立前端卡。
- 每个任务或逻辑组完成后提交；在每个 Checkpoint 停下独立验证。
