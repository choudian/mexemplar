# Tasks: 提案审批"讨论"功能（chat about this）

**Input**: Design documents from `/specs/028-proposal-discussion/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/discussion-api.md, quickstart.md

**Tests**: Included — Constitution IV（可验证交付）要求确定性逻辑与静默失败路径必须有自动化覆盖。

**Organization**: 按 user story 分阶段；US1 完成即是可用 MVP。

## Project Paths

- Python 源码 `src/`，测试 `tests/`（`uv run pytest tests/ -q`）
- 前端源码 `frontend/src/`，单测 `frontend/tests/unit/`（`npx vitest run`）
- 格式/静态检查：`uv run black src/ tests/`、`uv run flake8 src/ tests/`、`cd frontend && npm run lint`

---

## Phase 1: Foundational（阻塞所有 user story）

**Purpose**: 数据层与序列化单一来源就位

- [ ] T001 在 src/data/models_sqlite.py 的 ImprovementProposal 增加可空 `discussion_session_id` 列定义
- [ ] T002 在 src/data/migrations.py 新增 migrate_to_v25（ALTER TABLE improvement_proposals ADD COLUMN discussion_session_id TEXT）并注册到 _MIGRATIONS；downgrade 对齐 v21-v24 既有写法
- [ ] T003 在 src/data/repos/improvement_proposal_repository.py 新增 bind_discussion_session（条件 UPDATE WHERE discussion_session_id IS NULL + rowcount 返回 bool）与 rebind_discussion_session（无条件 UPDATE）；_to_dict/get_by_id 输出补 discussion_session_id
- [ ] T004 [P] 新建 src/business/self_improvement/proposal_context.py：format_proposal_finding_text(proposal, include_outcome) 单一来源（问题/证据/建议/严重度/类型 + 用户补充；include_outcome 追加实施分支/结果摘要/测试结论/失败原因）
- [ ] T005 重构 src/business/self_improvement/proposal_bridge.py 的 _build_implementation_graph 节点 description，finding 块改调 proposal_context.format_proposal_finding_text（guard_block 等 bridge 专属段保留），行为语义不变
- [ ] T006 [P] tests/data/ 增 v25 migration 往返测试（upgrade 后列存在可写、downgrade 后列移除）；tests/business/self_improvement/ 增 proposal_context 序列化单测（含/不含 outcome、空字段省略）

**Checkpoint**: 数据列 + 序列化 helper 就绪，`uv run pytest tests/data tests/business/self_improvement -q` 通过

---

## Phase 2: User Story 1 - 审批前对提案展开讨论 (P1) 🎯 MVP

**Goal**: 点"讨论"→ 创建以提案上下文开场的普通助理会话 → 跳转可聊；审批语义不变

**Independent Test**: 选中 pending_review 提案点"讨论"，进入会话可见开场上下文可正常问答；回提案页批准/拒绝行为与之前一致

- [ ] T007 [US1] 在 src/business/self_improvement/proposal_service.py 实现 get_or_create_discussion_session(proposal_id)：读提案→绑定存在且会话可用（SessionRepository 行存在且 status ∈ active/suspended/completed/failed）则返回；否则 ChatService.create_session(title="讨论：{what 截 24 字}") → 落 assistant 角色 markdown 开场消息（proposal_context，include_outcome=True，零模型调用）→ bind_discussion_session；claim 失败（rowcount=0）删除孤儿会话并返回已绑定 id；返回 (session_id, created)
- [ ] T008 [US1] 在 src/desktop_api/schemas.py 增 ProposalDiscussionResponse{sessionId, created}，ProposalDto 增可空 discussionSessionId；src/desktop_api/routers/proposals.py 增 POST /{proposal_id}/discussion（404 提案不存在；沿用既有启用检查）
- [ ] T009 [P] [US1] tests/business/self_improvement/ 增 service 行为测试：首次创建（消息含 what/evidence/suggestion/severity/补充说明；会话标题正确；无模型调用）、连续两次同 id 且第二次 created=false、提案不存在报错
- [ ] T010 [P] [US1] tests/desktop_api/ 增 discussion endpoint contract 测试（按 contracts/discussion-api.md 五条行为约束断言，含全库会话数只 +1）
- [ ] T011 [P] [US1] tests/guardrails/test_proposal_guardrails.py 增零副作用守卫：调用 discussion 后无 worktree 目录、无 task graph 行、提案 status 不变；增序列化单一来源守卫（bridge 与 discussion 均 import proposal_context，全库无第二份 finding 模板字符串）
- [ ] T012 [US1] frontend/src/api/（提案 API client 所在文件）增 openProposalDiscussion(proposalId) typed client；frontend/src/state/brainStore.ts 增同名 action（请求期间置 pending 态）
- [ ] T013 [US1] frontend/src/screens/BrainScreen/BrainScreen.tsx 详情区（论证链下方、审批操作上方）增"讨论"按钮：所有状态可见；点击调 action → 成功后切 assistant 路由 + assistantStore.selectSession(sessionId)；请求期间 disable；失败走既有区域错误提示
- [ ] T014 [US1] frontend/tests/unit/proposal-review.test.tsx 增用例：点击"讨论"发起 POST、成功后导航与 selectSession 被调、请求期间按钮 disable

**Checkpoint**: US1 独立可验收——讨论闭环可用，既有审批测试全绿

---

## Phase 3: User Story 2 - 回到上次的讨论继续聊 (P2)

**Goal**: 绑定跨重启持久；绑定会话被删后自愈

**Independent Test**: 讨论后重启应用再点"讨论"回同一会话；删除绑定会话后再点自动新建并重绑

- [ ] T015 [US2] 在 proposal_service.get_or_create_discussion_session 补自愈分支：绑定死亡（行缺失/已归档删除）→ 新建会话 + 开场消息 + rebind_discussion_session 覆盖旧绑定
- [ ] T016 [P] [US2] tests/business/self_improvement/ 增测试：绑定后新 Repository 实例读取仍返回同 id（跨进程持久语义）；删除绑定会话后调用返回新 id 且 created=true 且提案绑定已更新
- [ ] T017 [US2] BrainScreen 详情区按钮文案随 DTO discussionSessionId 切换：无绑定="讨论"、有绑定="继续讨论"；frontend/tests/unit/proposal-review.test.tsx 补文案断言

**Checkpoint**: US2 独立可验收——持久回访与自愈闭环

---

## Phase 4: User Story 3 - 终态提案的复盘讨论 (P3)

**Goal**: done/failed/rejected 提案可讨论，开场含实施结果

**Independent Test**: 选中 done/failed 提案点"讨论"，开场消息含实施结果摘要/失败原因

- [ ] T018 [P] [US3] tests/business/self_improvement/ 增测试：done 提案开场消息含 result_summary 与测试结论、failed 提案含 error、rejected 提案正常创建（无 outcome 字段时省略该段）
- [ ] T019 [US3] frontend/tests/unit/proposal-review.test.tsx 增用例：终态提案详情区"讨论"按钮可用

**Checkpoint**: US3 独立可验收

---

## Phase 5: Polish & Cross-Cutting

- [ ] T020 [P] 活文档：docs/ARCHITECTURE.md 自我改进小节补讨论会话一段；根 AGENTS.md/CLAUDE.md/GEMINI.md Recent Changes 增 028 条目（三镜像同步）；src/AGENTS.md 与 frontend/AGENTS.md（及各自镜像）补一条约束（讨论路径零实施副作用 / 按钮走 typed API + selectSession）
- [ ] T021 全量验证：uv run pytest tests/business/self_improvement tests/desktop_api tests/data tests/guardrails -q；cd frontend && npm run lint && npx vitest run；uv run black src/ tests/（改动文件）+ uv run flake8（改动文件）

---

## Dependencies & Execution Order

- Phase 1（T001→T002→T003 串行；T004/T006 可并行）阻塞全部 story
- US1（T007→T008 串行；T009/T010/T011 并行；T012→T013→T014 前端串行）
- US2 依赖 US1 的 T007（同一 service 方法补分支）
- US3 只依赖 Phase 1 的 T004（include_outcome 已实现，纯补测试 + 前端断言）
- Polish 最后

## Implementation Strategy

MVP = Phase 1 + US1（T001-T014）。US2/US3 增量交付，各自独立可验收。
