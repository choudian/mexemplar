# 架构重构执行计划（交接文档）

> 权威执行 + 交接文档。原始 12 项问题分析见 `docs/local/todo/architecture-improvements.md`（本地未入 repo）。
> 截至 2026-06-24，已完成项在 commit `976dae2`（branch `prepare-github`）。

## 进度

| 批次 | 项 | 状态 | 规模 |
|---|---|---|---|
| 0 | #7a / #7b / #7c / #3a | ✅ done（976dae2） | 小 |
| 1 | #2 projector 注册表化 | ✅ done（976dae2） | 中 |
| 1 | #4a assistant router 下沉 | ✅ done（976dae2） | 小 |
| 1 | **#4bc skills_methodology / brain router** | ⏳ **下一步** | 中 |
| 1 | #11 typed blinker | ⏳ | 巨型 |
| 2 | #12 / #10 / #6 前端 | ⏳ | 中 |
| 3 | #1 / #3c / #3b Brain | ⏳ | 巨型 |
| 4 | #8 / #5 Orchestrator | ⏳ | 巨型 |
| 5 | #9 task_collab | ⏳ | 中 |
| - | 执行工具隔离（A−） | ⏳ 最后 | 中 |

执行顺序：**0 → 1 → 2 → 3 → 4 → 5**，执行工具隔离最后。

## 接手须知（必读）

1. **每项都已完成"属实性核实"**（2026-06-24 并行核实，问题真实）。下方每项的「修正 / 红线」是核实发现的、与原始审查文档的差异，**执行时必须遵守，别按原始审查字面做**。
2. **TDD 纪律**：行为变化先写失败测试（RED）→ 实现（GREEN）→ 重构；纯搬迁重构先写 characterization test 锁定行为再搬迁。已完成项的验证方式可作参照。
3. **测试 teardown flaky**：多文件同 process 跑会撞 closed-database / fatal teardown。**单文件 / 分批跑**：`uv run python -m pytest <单文件> -q`，别 `pytest tests/` 全跑。
4. 每项做完跑该项相关测试 green 再进下一项。
5. 单用户未发布、无外部消费者——**不需要 deprecation 双发兼容，可一刀切**。

---

## 已完成项（commit 976dae2，验证方式可参照）

### 批次 0
- **#3a** `workspace_hash` / `resolve_workspace_root` 下沉 `src/utils/workspace.py`，切断 `tool_output_repository` → `builtin_permissions` 的 data→business 反向 import。
- **#7a** 提取 `src/utils/ids.py::new_id()`（双 UUID 50 hex），brain/specialist/skill 三 repo 统一改用，修 skill 单 UUID 熵减半 + 删 `[:50]` 死代码。
- **#7b** 提取 `src/data/helpers.py::build_like_pattern(term, *, contains=True)`，统一 LIKE 转义，**修 tool / skill_composition 漏转义反斜杠 latent bug**。
- **#7c** 删 `_get_positive_int`，2 处调用改 `_get_bounded_positive_int`。

### #2 projector 注册表化
`src/desktop_api/ui_event_projector.py`：`project_internal_event` 547 行 if-chain → 注册表 `_PROJECTIONS` lookup + 30 个独立 handler（统一签名 `(payload, scope, causation_id) -> list[UiEventDraft]`），task 事件复用 `_TASK_EVENT_PROJECTIONS`，未注册事件从静默丢弃改 warning。

### #4a assistant router 下沉
`src/desktop_api/routers/assistant.py` 3 endpoint 编排下沉：`set_auto_approve` → `AssistantRuntime.set_auto_approve`；`trigger_segment_idle` → `SegmentService.handle_idle_and_cleanup`；`trigger_segment_boundary` → `SegmentService.seal_and_cleanup`。

---

## 待办项（按执行顺序）

### #4bc skills_methodology + brain router 下沉（下一步，中）

**skills_methodology router**（`src/desktop_api/routers/skills_methodology.py`）：
- `edit_methodology_skill`（5 步：get_detail → protected 检查 → `_require_confirmation` → `user_edit_supersede` → get_detail）下沉 `SkillService.edit_with_protection_check()`。
- `soft_delete_methodology_skill`（5 步：get_detail → protected 抛 403 → `_active_equipment_names` 查影响 → 拼中文确认文案 → 弹确认 → `force_soft_delete`）下沉 `SkillService.soft_delete_with_confirmation()`。

**brain router**（`src/desktop_api/routers/brain.py`）：
- 6 个内联 Pydantic body 模型（`EditEntryBody` / `CreateSpecialistBody` / …）移到 `src/desktop_api/schemas.py`。
- 2 处硬编码审计（`create_specialist` `origin="user_management_ui"` / `reason="通过管理界面创建"`；`update_specialist` `changed_by` / `change_reason`）改为 Service 接受 `caller_type` 参数。

**验证**：`tests/desktop_api/test_skills_api.py` + `test_skill_methodology_api.py` + brain api 测试。

### #11 typed blinker（巨型，建议独占一个 session）

`src/utils/events.py`（blinker 全局总线，50 signal，`**kwargs` 无类型）→ `TypedEventRegistry`（每事件一个 dataclass + 类型化 emit / subscribe）。

- **~70 处 emit 迁移**（重灾：`brain/decay_router.py` 8、`orchestration/agent/orchestrator.py` 9、`teaching_failure_tracker.py` 7）+ 6 处 `.send` + 2 个 emit-helper（`task_collaboration/events.py`、`brain/skill_events.py`）。
- **红线**：`emit` 把 listener 异常 try/except 吞掉只记 error（`events.py:262-265`），迁移期会掩盖字段名改动引发的 TypeError → **迁移期临时把该 logger.error 升级为 re-raise 或加 UnitTestMode re-raise 开关**。
- 单用户无外部消费者，可一刀切替换 emit 签名，不保留旧 API；用 `Literal` + `@overload` 把 50 事件名固定成联合类型，让 IDE/mypy 找全调用点。

### 批次 2 前端（中）

- **#12** `frontend/src/api/uiEvents.ts`（1350 行）拆 `uiEventTypes.ts`（763 行类型）+ `uiEventParser.ts`（声明式 mapper registry 替 20 分支 `parseUiEvent`）。
- **#10** `frontend/src/state/assistantStore.ts`：只拆 `applyEvent`（248 行 / 9 分支）为 typed handler。
  - **红线：投影姿态已正确**（不重算 `displayPhase`，缺字段就 `needsResync` 拉权威快照）——**别动投影逻辑，只拆 applyEvent；不要抽 EventDispatcher（核实确认价值被高估）**。
- **#6** 前端 UI 模式：`<SkillCheckboxGrid>`（`SpecialistScreen` / `SkillEditor` 近复制粘贴）+ `useFiltered` hook（5 处搜索过滤）+ `statusToTone`（4 处状态→颜色）。

**验证**：`frontend/tests/unit/` + `frontend/tests/e2e/`。

### 批次 3 Brain（巨型，建议独占一个 session）

- **#1** `src/data/repos/brain_repository.py`（1360 行 / 52 方法）拆 Segment / MemoryEntry / FeedbackSignal / Prediction 四 Repository。
  - **修正**：别名是 **2 对**（`get_segment_by_id`→`get_segment`、`get_entry_by_id`→`get_entry`），非原始审查说的 5 个。
  - **红线**：scoring 三处（`context_builder` 的 hot / subconscious + `retrieval_service`）权重 / 半衰期有意分化（hot 30 天 vs retrieval 365 天），**只抽共享 `_compute_recency_score` helper，别合并成单函数**（会丢语义）。
  - **红线**：`complete_segment_with_entries` 跨 Segment + MemoryEntry 两表事务，拆开后要么 `SegmentRepository` 持 `MemoryEntryRepository` 引用，要么提升到 Service 编排，**不能简单按聚合切**。
- **#3c** `src/business/agents/tools/assistant_tools.py` 直接 import brain 4 子服务（2 顶层 `SpecialistService` / `RetrievalService` + 2 延迟 `BrainContextBuilder` / `SkillReferenceCounter`）。
  - **修正**：**按业务动作拆 2-3 个窄 facade，优先处理 2 个顶层 import；勿全压单一 `BrainContextBuilder`（会变新上帝对象）**。
- **#3b** `ChatService` import `builtin_general_tools.reset_auto_approve` / `settle_pending_confirmations`，`create_session` 隐式改确认状态。提取 `SessionLifecycle` 模块。
  - **红线**：先确认这些状态作用域（进程级 vs 会话级），搬动时**保持 first-decision-wins 语义不变**。

### 批次 4 Orchestrator（巨型，建议独占一个 session）

- **#8** `src/business/orchestration/agent/orchestrator.py`（2703 行 / 76 方法 / 6 概念）拆 `TeachingOrchestrator`（PM→Programmer→Trial 状态机）+ `DelegationOrchestrator`（subagent / specialist 委派与唤回）+ `ToolRegistry`（schema + handler factory + ownership）。
  - **红线：三处耦合必须配套处理**：(a) 共享 `_session_store` / `_get_loop` 改注入；(b) `TaskExecutorAdapter`（`task_executor_adapter.py:26-41`）反调 `_run_ephemeral_via_delegated_executor` 私有方法 → 改走 `DelegationOrchestrator` 公有接口；(c) 工具注册两域共用，`ToolRegistry` 给 Teaching + Delegation 都当依赖。
- **#5** 删 `ports.py`（45 行）+ 4 个 Adapter（`_EventBusAdapter` / `_ReviewStateAdapter` / `_AgentExecutionAdapter` / `_AssistantTaskAdapter`）。**先做 #8 让 #5 自然吸收**。
  - **红线**：`_AgentExecutionAdapter` / `_AssistantTaskAdapter` 带 optional-args 装配（非纯透传），删时改 pre-bound partial；`_ReviewStateAdapter` 包共享 `_review_counts` dict。

**验证**：`tests/integration/test_agent_orchestrator_architecture.py` + orchestration 测试。

### 批次 5 task_collaboration（中）

- **#9** `src/business/task_collaboration/`（18 文件 / 3412 行）合并 5 个浅模块 → 13 文件：`run_control`(15) / `health`(48) / `failure_bridge`(39) 并入 `service` / `dispatcher` / `adjudication`；`events.py` 8 个薄 emit 内联或合并进 `dispatcher`。
- **红线 1**：`cutover.py`(62) 是**生产门卫**（`TaskCollaborationCutoverGuard`，`dispatcher.delegate_task` 前置），**不是测试样板——并入 `dispatcher.py`，不能删**。
- **红线 2**：**绝对不动 `dispatcher.py:361-414` `run_side_effect` 三事务幂等结构**（Tx1 plan → `execute()` 外部副作用必须在事务外 → Tx2 / Tx3 落定）。合并文件时别顺手"重构"它。
- **验证**：`tests/business/agents/test_task_idempotency.py` + `test_task_idempotency_negative.py`（改后必跑）。

### 执行工具隔离（A−，最后，方向已定）

主助理移除 7 个副作用工具（`write_file` / `edit_file` / `apply_patch` / `exec` / `process_stop` / `process_send_input` / `process_close`），保留 7 个信息查找类只读（`read_file` / `search_files` / `search_content` / `list_dir` / `web_search` / `web_fetch` / `load_tool_output`）。`process_*` 5 个只读观察类边界待最终敲定。

- 100% 调度当前是**纯软约束**（仅 prompt 文字 `assistant_prompt.py:28-39`，无任何代码拦截）。需补硬拦截 + 扩 subagent 白名单管线（当前白名单只过滤用户技能，不过滤 19 个 BUILTIN）。
- 方案 B（分级 / prompt 引导）已被 2026-06-17 运行日志证伪（主助理首轮直接调 `web_search`）。
- 业务理由：主助理需保留查找工具以侦察现状、给子代理精确指派；副作用才强制调度。

---

## 已知 pre-existing（非本次架构批次，未 commit，勿混入）

- `src/data/repos/{assistant_summary_repository,teaching_failure_repository}.py`、`src/business/services/skill_composition/service.py`、`docs/FEATURES.md`、`frontend/src/api/brain.ts`、`frontend/tests/unit/brain/setup.ts` —— 会话开始就在的 023 未提交改动。
- `tests/test_skill_composition_regressions.py` 有 3 个 pre-existing 失败（`SkillCompositionService` 缺 `search_published_compositions` / `_build_trial_system_prompt` / `_build_trial_session_snapshot_payload`），与架构批次无关。
- 注：commit 976dae2 中 `specialist_repository.py` / `skill_composition_repository.py` 含此前的 soft-delete 约束清理（移除 `physical delete` / `get_version` 方法），已在 commit message 注明。
