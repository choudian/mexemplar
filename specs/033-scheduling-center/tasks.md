# Tasks: Scheduling Center（调度中心）

**Input**: Design documents from `/specs/033-scheduling-center/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/ (rest-api / ui-events / agent-tools / confirmation-and-unattended), quickstart.md

**Tests**: 本特性的测试**不是可选装饰**——spec 的 CC-001 / CC-002 / CC-005 / CC-006 / CC-007 / CC-008 多处明确写「门卫测试守住」「MUST 由架构门卫测试守住」，plan「测试策略」章节列明了每个测试文件路径与断言，CLAUDE.md 硬规则 #6「改静默失败路径必须补测试」。因此各 story 内的 guard/契约测试与 plan 列出的确定性逻辑测试均作为交付物纳入。

**Organization**: 按 user story 分组（US1 立即 / US2 一次性 / US3 周期 / US4 待办接入 / US5 无人值守安全与接管 / US6 管理屏），每个 story 可独立实现与验证。跨 story 的数据层 / 事件契约 / 全链路透传基础设施归 Setup 与 Foundational。

## Constitution-Driven Minimums

- Repository / migration：`src/data/repos/scheduled_task_repository.py`、`scheduled_task_run_repository.py`、`src/data/migrations.py`（v30，2 新表 + sessions 加 3 列）、`session_repository.py`（exclude_sources）。
- 配置统一入口：新增 `scheduler.*` 键走 `src/data/unified_config.py`（bounded `[5,600]`，默认 30）+ `config.example.json` 受版本控制模板；misfire 补最近一次与 reentry 跳过是 FR-010/FR-011 不可关闭的硬不变量；无新 secret。
- 接线 smoke / guard：SchedulerWorker lifespan 接入、`source` 全链路透传、新 UI 事件注册、新 router 401 保护、工具只在主助理、`unattended_auto_approve` 三重不暴露、todo 不改表 / 恒 one_shot、Segment opt-out、聊天屏排除——均由 guard test 守。
- 活文档更新：`.specify/memory/constitution.md`（CC-005 受控例外，version bump）、`docs/PROJECT_CONSTRAINTS.md`（免确认例外）、`docs/ARCHITECTURE.md`（scheduling 模块 + 调度中心 vs `graph_scheduler` 命名区隔）、根 + `frontend/` + `src/` 的 `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`（四镜像同步，主屏 9→10、新模块入口）。
- Recording / DuckDB 不涉及；`user_todos` 仅以 `todo_id` 字符串外部引用（不建 FK、不写表）。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成任务依赖）
- **[Story]**: 归属 user story（US1~US6）；Setup / Foundational / Polish 不带 story 标签
- 描述含精确文件路径

## Project Paths

- **Python source**: `src/`（business / desktop_api / data / execution / utils）
- **Frontend source**: `frontend/src/`（React UI、typed API client、stores、components、screens）
- **Desktop shell**: `src-tauri/`（Tauri 窗口命令、sidecar 生命周期、capabilities）
- **Python tests**: `tests/`（desktop_api / guardrails / integration / data / business）
- **Frontend tests**: `frontend/tests/unit/` 和 `frontend/tests/e2e/`
- **Python test runner**: `uv run pytest tests/`
- **Python formatter/linter**: `uv run black src/ tests/` 和 `uv run flake8 src/ tests/`
- **Frontend validation**: `npm run lint`、`npm run test`、`npm run test:e2e`（在 `frontend/`）
- **Tauri validation**: `cargo check` 或 `npm run tauri build`（shell/packaging 改动时）

---

## Phase 1: Setup（共享准备）

**Purpose**: 独立性强、不阻塞别人的准备性工作（模块骨架、配置、桌面通知插件、公共函数抽取）。

- [X] T001 创建 scheduling 业务模块骨架 `src/business/scheduling/__init__.py`（空包初始化，后续 phase 逐步填充各文件；并在模块 docstring 点明「调度中心 = 时间维度触发中枢，区别于 `graph_scheduler` 依赖维度推进器」）
- [X] T002 [P] 新增调度配置键到 `src/data/unified_config.py` + `config.example.json`：`scheduler.scan_interval_seconds`（bounded `[5,600]`，默认 30）与确认卡超时键；统一经 `get_unified_config().get_scheduler_*()` 读取，无业务层硬编码；misfire / reentry 按 FR-010/FR-011 固定启用，不提供破坏 MUST 的运行时开关
- [X] T003 [P] 从零安装桌面通知插件（四层）：`src-tauri/Cargo.toml` 加 `tauri-plugin-notification = "2"`、`src-tauri/src/lib.rs` 加 `.plugin(tauri_plugin_notification::init())`、`src-tauri/capabilities/default.json` 加 `"notification:default"`（最小权限，不申请 `notification:all`）、`frontend/package.json` 加 `@tauri-apps/plugin-notification`；`cargo check` 通过；同时以 `tests/guardrails/test_desktop_sidecar_build_script.py` 守住 `scripts/build_desktop_sidecar.ps1` 只打包 `src.desktop_api`、检查原生命令退出码且绝不复制 stale 产物
- [X] T004 [P] 抽取公共函数 `compute_graph_terminal_state(snapshot) -> (all_terminal, all_completed)` 到其语义所有者 `src/business/task_collaboration/graph_terminal.py`，由 scheduling 单向复用（消除 `task_collaboration/graph_scheduler.py:149-163` + `reentry_briefing.py:244-245` 的第三份 inline 复制；必须排除 root 容器 `parent_task_id is None`；既有两处调用改为复用，保持行为不变）

---

## Phase 2: Foundational（阻塞前置）

**Purpose**: 所有 user story 共享的核心基础设施，**必须先完成**才能开任何 story。

**⚠️ CRITICAL**: 未完成本 phase 不得开始任何 user story。

- [X] T005 给 `Session` ORM 加 `source`（user/scheduled，默认 user）/ `scheduled_task_id`（可空）/ `is_scheduled`（INTEGER bool，默认 0）三列，并新增 `ScheduledTask` / `ScheduledTaskRun` ORM 类到 `src/data/models_sqlite.py`（`ScheduledTask.instruction` 独立保存确认卡核定后的真实指令，todo 的 `source_ref` 仍只存外部 id；字段与 data-model.md §实体1/§实体2/§实体3 一一对应；`is_scheduled` 用 `Integer` 映射 bool仿既有 `is_active`）
- [X] T006 实现 `migrate_to_v30(engine)` 到 `src/data/migrations.py` 并在 `_MIGRATIONS` 末尾注册 `(30, migrate_to_v30)`：建含独立 `instruction` 列的 `scheduled_tasks` / `scheduled_task_runs`（CREATE TABLE IF NOT EXISTS + 内联 CHECK + 独立 CREATE INDEX，仿 v18/v21）、sessions 加 3 列（仿 v29 `_add_column_if_missing`，幂等 backfill `source='user'`）、`UPDATE schema_version SET version=30`（与 T005 ORM 同步一致）
- [X] T007 [P] 加 ID 前缀 `ID_PREFIX_SCHEDULED_TASK="sch_"` / `ID_PREFIX_SCHEDULED_TASK_RUN="schr_"` 到 `src/data/repos/base_repository.py`（`generate_id("sch")` / `generate_id("schr")`）
- [X] T008 实现 `ScheduledTaskRepository`（CRUD + 分页 list + 确认后 `instruction` 持久化 + 软删 + CAS `next_fire_at` / `status` / `is_deleted` 条件 UPDATE + rowcount 校验，仿 `UserTodoRepository`）到 `src/data/repos/scheduled_task_repository.py`
- [X] T009 [P] 实现 `ScheduledTaskRunRepository`（复用 `src/data/scheduling_types.py` 的 `RunStatus` + 合法转移表，在 Repository 最终 mutation 边界执行条件 CAS，append-only，仿 `ImprovementProposalRepository`）到 `src/data/repos/scheduled_task_run_repository.py`
- [X] T010 [P] `session_repository.py` 的 `get_by_agent_type`（及聊天屏 list 路径）加 `exclude_sources: list[str] | None = None` 参数到 `src/data/repos/session_repository.py`
- [X] T011 [P] 定义持久枚举与 task/run 合法转移表（`ScheduledTaskStatus` / `RunStatus` StrEnum、`schedule_kind`、来源类型）到 data 可依赖的中立契约 `src/data/scheduling_types.py`，由 `src/business/scheduling/models.py` 重导出业务兼容面，确保 Repository 是状态机最终门卫
- [X] T012 [P] 新增后端内部 blinker 事件到 `src/utils/events.py`：`scheduler_task_changed` / `scheduler_run_terminal` / `graph_scheduler_terminal`（`EventName` + `_EVENT_FIELDS` 注册）
- [X] T013 注册面向前端的公开 UI 事件到 `src/desktop_api/ui_events.py`：`scheduled_task.completed` / `scheduled_task.needs_takeover` / `scheduled_task.changed`（notification）+ `scheduling.confirmation_requested` / `scheduling.confirmation_resolved`（interactive）+ `scheduling.notification`（合并通道，Polish 阶段二选一），含 `required_payload_keys` / `unredacted_payload_keys` / payload enum allowlist（对齐 contracts/ui-events.md）
- [X] T014 [P] `ui_event_projector.py` 新增 `scheduled` / `scheduling` domain 投影 + `_scope_from_payload` 扩展（scope 用 `sessionId` / `taskId`）到 `src/desktop_api/ui_event_projector.py`
- [X] T015 `ChatService.create_session` 用 overload + 运行时校验表达 user/scheduled 与 `scheduled_task_id` 的判别关系，并提供 `create_scheduled_session(scheduled_task_id, ...)`；`SessionRepository.create` 在最终持久边界校验 `source / scheduled_task_id / is_scheduled` 一致；`get_sessions_with_preview` 传 `exclude_sources=["scheduled"]` 到 `src/business/services/chat_service.py`
- [X] T016 scheduled advisory 单点注入：`AssistantPromptBuilder` 从权威 `session.is_scheduled` 判定无人值守并传 `unattended_advisory`，模板加独立 `{advisory_section}` placeholder（**勿复用** `{supplements_section}`），无需改 `AssistantRuntime.dispatch_message` / `run_agent` 签名；改 `src/business/orchestration/agent/assistant_prompt_builder.py`、`src/business/agents/prompts/assistant_prompt.py`
- [X] T017 [P] Segment opt-out 单点收口：`seal_segment()` 开头 early-return `is_scheduled=1` 的会话到 `src/business/brain/segment_service.py`
- [X] T018 [P] v30 migration 测试（推进到 v30、幂等 `_add_column_if_missing`、sessions 既有行 `source='user'`/`is_scheduled=0` backfill、两表 CHECK 约束生效）到 `tests/data/test_migrations_v30.py`
- [X] T019 [P] Repository CAS + 软删测试（`ScheduledTaskRepository` next_fire/status/is_deleted 条件 UPDATE + rowcount；`ScheduledTaskRunRepository.cas_transition` 合法/非法转移、终态不可逆；调用方谎报源状态也不能越过共享合法转移表）到 `tests/data/test_scheduled_repositories.py`（file-based DB，避开 in_memory StaticPool）
- [X] T020 [P] guard：聊天屏列表排除 `source=scheduled`、其余会话读取路径不排除 到 `tests/guardrails/test_chat_list_exclusion.py`
- [X] T021 [P] guard：scheduled 会话不产 BrainSegment（`source=scheduled` / `is_scheduled=1` 触发 early-return） 到 `tests/guardrails/test_scheduled_skips_segment.py`

**Checkpoint**: 数据层 + 事件契约 + 全链路透传就绪——user story 实现可开始。

---

## Phase 3: User Story 1 - 立即触发：现在就帮我做一件事 (Priority: P1) 🎯 MVP

**Goal**: 用户在对话里说「这条事现在就帮我做」，主助理经创建确认卡核对后立即点燃一个 `source=scheduled` 主助理会话执行，完成后 Toast + 桌面通知送达，调度中心历史出现一条 `succeeded` 记录。本 story 拉满基础链路（调度核心 + 会话启动 + 完成判定 + 确认卡 + 工具 + router + 前端通知/历史骨架）。

**Independent Test**: 在对话中提一个立即任务，确认后观察会话被点燃、执行、完成通知送达（Toast + 桌面）、历史出现一条 `succeeded`；聊天屏列表看不到该会话。

### Tests for User Story 1

> 注：以下 guard / 契约测试是 spec CC 条款的硬交付物，写完后须先 RED 再 GREEN。

- [X] T022 [P] [US1] 完成判定三条件测试（首轮 run succeeded 不误报完成 / 含失败/取消图不漏报——不依赖 root=completed / 回流续跑轮后置终态；file-based DB 避开 in_memory StaticPool）到 `tests/business/scheduling/test_completion.py`
- [X] T023 [P] [US1] `/api/scheduled-tasks` 契约测试（CRUD + runs 列表 + takeover + confirmation decision；camelCase DTO；`LookupError→404` / `ValueError→422` 映射；token 不进响应正文）到 `tests/desktop_api/test_scheduled_tasks_api.py`
- [X] T024 [P] [US1] guard：5 工具名 ∈ `build_assistant_tools(sid)()` 且 ∉ `build_delegated_executor_tools(...)` 到 `tests/guardrails/test_scheduled_tool_boundaries.py`
- [X] T025 [P] [US1] guard：`unattended_auto_approve` 不在 5 个工具 schema `properties` / 不在 5 个 handler 源码 / 不在 router create/update 源码（三层静态断言 `inspect.getsource`，比 031 更严）到 `tests/guardrails/test_scheduled_task_unattended_field_isolated.py`
- [X] T026 [P] [US1] guard：`/api/scheduled-tasks` 无 token 返 401 到 `tests/guardrails/test_scheduled_tasks_api_auth.py`

### Implementation for User Story 1

- [X] T027 [P] [US1] `SchedulerService`（CRUD 入口 + 触发时机判定 + 立即触发 `run_at=now` 试算 `next_fire_at` + 列表/详情/暂停/启用/软删/`fire_now` 业务方法）到 `src/business/scheduling/scheduler_service.py`
- [X] T028 [P] [US1] `SessionLauncher`（`launch(scheduled_task_id, instruction, started_at) -> run_id`：先构造 detached `source=scheduled` 会话，再由 Repository 在同一事务提交 session + active run，partial unique index 裁定 first-wins，随后异步投递已核定指令；原子创建失败零 run，dispatch 失败才显式终结已落库 run；生产每次 launch 使用独立 Repository scope；业务层不 import desktop_api，`dispatch_callback` 由 desktop lifespan 注入）到 `src/business/scheduling/session_launcher.py`
- [X] T029 [US1] `SchedulingConfirmationManager`（独立 pending dict + 独立 Lock + first-decision-wins；内存态；`create(draft, session_id) -> request_id` / `submit_decision(...)` confirm 落库 / cancel；提交时在锁内重校验 `expires_at`，SchedulerWorker 周期清理，assistant stop 按 session 结算，事件发布失败撤销隐形 pending，超时/停止/关闭一律 fail-closed 不创建；`request_id` 前缀 `scf_`；emit `scheduling.confirmation_*`）到 `src/business/scheduling/scheduling_confirmation_manager.py`（仿 `clarification_manager.py` + `TrialPreviewRequestManager`，**不复用** 019 后端协议）
- [X] T030 [US1] 5 个主助理工具的 `*_SCHEDULED_TASK_SCHEMA`（plain dict via `make_tool_schema`）+ `create_*_handler`（`create_scheduled_task` 组装 draft + 试算 next_fire + 提交 confirmation manager + emit `scheduling.confirmation_requested`，**不落 scheduled_tasks**；`list_scheduled_tasks` / `update_scheduled_task`（字段白名单拒收 `schedule_*`/`source_*`/`unattended_auto_approve`/`status`）/ `pause_scheduled_task`（CAS active⇄paused）/ `delete_scheduled_task`（CAS is_deleted=1））到 `src/business/agents/tools/assistant_tools.py`（仿 `user_todo` 五件套 + 032 约束写法；handler 签名**不接** `unattended_auto_approve`）
- [X] T031 [US1] `build_assistant_tools` 的 import 白名单 + `static_tools` 追加 5 工具到 `src/business/orchestration/agent/tool_registry.py`（**绝不进** `build_delegated_executor_tools`）
- [X] T032 [US1] `SchedulerWorker`（双 Event：周期扫描 + `notify_scheduler_worker()` 立即唤醒；wait deadline 动态缩短到最近触发；任务创建/状态变化主动唤醒；misfire 只补一次、reentry 固定跳过；并发 active-run 唯一冲突折叠为 skipped）到 `src/business/scheduling/scheduler_worker.py`（仿 `BrainBackgroundWorker`）
- [X] T033 [US1] `RunCompletionMonitor`（双路径触发：`AssistantRuntime` worker 退出后直接调用 + 内部 `graph_scheduler_terminal`/任务活动事件；`has_active_worker` 与 `has_pending_reentry` 由 desktop 注入，图查询失败 fail-closed；三条件静默后全成功→`succeeded`、含失败→`failed`；runtime 反问/明确失败分别原子写 `waiting_user`/`failed`；生产每次评估 fresh Repository scope）到 `src/business/scheduling/run_completion_monitor.py`
- [X] T034 [US1] DTO（`ScheduledTaskItem` / `ScheduledTaskListResponse` / `ScheduledTaskPatchRequest` / `ScheduledTaskRunItem` / `ScheduledTaskRunListResponse` / `TakeoverResponse`，camelCase，对齐 contracts/rest-api.md）到 `src/desktop_api/schemas.py`
- [X] T035 [US1] router `APIRouter(prefix="/api/scheduled-tasks")`（GET 列表 / GET 详情 / PATCH（仅 status + unattendedAutoApprove，严禁 scheduleKind/Payload/sourceType/sourceRef/title）/ POST `/{id}/fire-now` / DELETE 软删 / GET `/{id}/runs` / POST `/{id}/runs/{runId}/takeover` / POST `/confirmations/{requestId}/decision` + GET `/confirmations/pending` 可渲染安全快照）到 `src/desktop_api/routers/scheduled_tasks.py`（仿 `routers/user_todos.py`，零 Depends 鉴权）
- [X] T036 [US1] 接线：`app.py` lifespan 按「注册 runtime launcher → 全量加载 per-task 授权 → 安装 completion monitor → 最后启动 worker」顺序装配，shutdown 反序清理；短生命周期 REST service 复用已注册 launcher，未就绪显式 503；`assistant_runtime.py` 在普通/reentry worker 退出后评估完成并在反问/失败时写 run 状态——改 `src/desktop_api/app.py`、`src/desktop_api/assistant_runtime.py`
- [X] T037 [P] [US1] 前端 typed API client（list/get/patch/fire-now/delete/runs/takeover/confirmation decision/pending）到 `frontend/src/api/scheduledTasks.ts`（经 `requestJson`）
- [X] T038 [P] [US1] 前端镜像新 UI 事件：`uiEventTypes.ts` 加 type 常量 + handler domain + payload enums；`uiEventParser.ts` 加 mapper 到 `frontend/src/api/uiEventTypes.ts` + `frontend/src/api/uiEventParser.ts`
- [X] T039 [P] [US1] `toastStore` 扩展 `ToastTone` success/info/warning + `notifySuccess` / `notifyInfo` / `notifyWarning` 到 `frontend/src/state/toastStore.ts`
- [X] T040 [US1] `StructuredConfirmationCard`（从 `ClarificationCard.tsx` 抽取全局容器，props 对齐 `requestId/draft/expiresAt/onSubmit/onCancel` + 新增 `unattendedAutoApprove` 勾选框附风险说明）挂 `AppShell` 全局（创建可能跨屏发生）到 `frontend/src/components/StructuredConfirmationCard.tsx` + AppShell
- [X] T041 [US1] `scheduledStore`（Zustand：list / runs / detail / pending confirmation；`applyEvent` 消费 `scheduled_task.*` / `scheduling.confirmation_*`；防抖 `createDebouncedRefresh(300)`；缺字段 `markNeedsResync()` + 重拉）到 `frontend/src/state/scheduledStore.ts`
- [X] T042 [US1] `ScheduledScreen` 骨架（历史 run 列表 + 空态指引 + 历史 run 点进会话入口；管理操作 UI 留 US6 补全）到 `frontend/src/screens/ScheduledScreen/ScheduledScreen.tsx`
- [X] T043 [US1] 路由 + NavRail 接入 `/scheduled`（主屏 9→10）：`routes` 数组 + `routePaths["scheduled"]="/scheduled"` + `shellStore` `RouteId` 加 `"scheduled"` 到 `frontend/src/app/routes.tsx` + `frontend/src/state/shellStore.ts`
- [X] T044 [P] [US1] 前端桌面通知消费：收到 `scheduled_task.completed`（success/failed）/ `needs_takeover`（warning）事件时 `sendNotification`（app 运行时）到 `frontend/src/` 事件消费层（scheduledStore / AppShell）；`frontend/tests/unit/desktop-notification.test.ts` 覆盖已授权 / 申请后授权 / 拒绝 / 插件异常 / 非 Tauri，store 测试断言三类事件各发一次正确通知
- [X] T045 [US1] 端到端冒烟：立即任务 创建（确认卡）→ 触发 → scheduled 会话执行 → 完成静默判定 → Toast + 桌面通知 → 历史 `succeeded` 可见、聊天屏不可见；另以真实 blinker `graph_scheduler_terminal` 接线驱动已 connect 的 `RunCompletionMonitor`，覆盖 succeeded/failed 且终态只发一次 到 `tests/integration/test_scheduled_immediate.py`

**Checkpoint**: US1 立即触发最小闭环可独立验证（触发 → 执行 → 通知 → 记账 → 历史可见）。

---

## Phase 4: User Story 2 - 一次性定时：到点再做 (Priority: P1)

**Goal**: 用户说「明天下午 3 点整理本周会议纪要」，主助理解析时间创建一次性定时任务，确认卡用人话核对时刻（防「9 点」听成 21 点），到点秒级触发、执行、通知；一次性任务触发一次后进入终态不再重复。

**Independent Test**: 创建一个 1–2 分钟后到点的一次性任务，等到点后确认会话被触发、执行、通知与历史；`next_fire_at` 与确认卡展示一致，触发后 `status=completed`、`next_fire_at=NULL`。

### Tests for User Story 2

- [X] T046 [P] [US2] `compute_next_fire` 计算 + one_shot misfire 测试（one_shot `run_at` 解析、每天某时、zoneinfo 本地→UTC、DST / 跨日边界、错过补一次 / paused 过点 expired）到 `tests/business/scheduling/test_schedule_calc.py` + `tests/business/scheduling/test_misfire.py`

### Implementation for User Story 2

- [X] T047 [P] [US2] `compute_next_fire(payload, after_local) -> datetime` 纯函数（one_shot `run_at` + daily `time_of_day`，用 `zoneinfo` 按用户本地时区推导再转 UTC naive；DST ambiguous 取 `fold=0` 后向推进并记日志）到 `src/business/scheduling/scheduler_service.py`（或独立 `schedule_calc.py`）
- [X] T048 [US2] `SchedulerWorker` 动态 wait timeout 实现「到点秒级触发」+ one_shot 触发后 CAS `status=completed` / `next_fire_at=NULL` 到 `src/business/scheduling/scheduler_worker.py`
- [X] T049 [US2] 创建确认卡人话时间展示（`scheduleDescription` 如「一次性 7月19日 17:00」核对方「9 点」歧义）到 `src/business/scheduling/scheduling_confirmation_manager.py`（draft 组装）+ `frontend/src/components/StructuredConfirmationCard.tsx`（展示）
- [X] T050 [US2] one_shot misfire 补跑（app 未运行错过补最近一次，然后滚动到下个未来时点；paused 期间过点置 expired 不补跑）到 `src/business/scheduling/scheduler_worker.py`
- [X] T051 [US2] 端到端：一次性 创建 → 到点触发 → 完成 → 通知 → 历史 + 终态不重复 到 `tests/integration/test_scheduled_one_shot.py`

**Checkpoint**: US1 + US2 共同构成「触发维度」完整闭环（立即 + 一次性）。

---

## Phase 5: User Story 3 - 周期任务：按规律重复做 (Priority: P2)

**Goal**: 用户说「每天 9 点查一下竞品价格」或「每周一 8 点整理周报」，创建周期任务按规律滚动触发；错过补跑最近一次（不补全部）、撞上次未完成则跳过记 `skipped`。

**Independent Test**: 创建一个「每隔 1 分钟」的周期任务，观察连续两次滚动触发；构造上次未完成，观察本次被跳过并记 `skipped`。

### Tests for User Story 3

- [X] T052 [P] [US3] 周期 `compute_next_fire` 滚动测试（interval / daily / weekly / weekdays，滚动到未来首点）+ reentry skipped 测试（上次未静默本次跳过、记 skipped、不并发堆积）到 `tests/business/scheduling/test_schedule_calc.py`（recurring 段）+ `tests/business/scheduling/test_reentry.py`

### Implementation for User Story 3

- [X] T053 [P] [US3] `compute_next_fire` 扩展 recurring（`interval_seconds` / `daily` / `weekly`（`weekdays:[1..7]`）/ `weekdays` 工作日，从上次计划触发时刻滚动到下一个未来时点；interval misfire 保持原节拍、不以实际醒来时刻永久平移）到 `src/business/scheduling/scheduler_service.py` + `src/business/scheduling/schedule_calc.py`
- [X] T054 [US3] 周期触发后 CAS `next_fire_at` 滚动到下个未来时点（recurring 不主动 `completed`，持续滚动）到 `src/business/scheduling/scheduler_worker.py`
- [X] T055 [US3] 周期 misfire 补最近一次不补全部 + reentry（到点时上次未静默 → 本次不启动会话、直接记终态 `skipped`；`uq_runs_active_per_task` partial unique index 原子保证 worker / fire-now 并发时同任务最多一个 `running|waiting_user`，冲突方不建第二会话）到 `src/business/scheduling/scheduler_worker.py` + v30 migration / run Repository
- [X] T056 [US3] 端到端：周期滚动 + misfire 补一次 + reentry skipped 到 `tests/integration/test_scheduled_recurring.py`

**Checkpoint**: 三种触发方式（立即 / 一次性 / 周期）全部可用。

---

## Phase 6: User Story 4 - 从待办接入：把待办变成 AI 替我做的事 (Priority: P2)

**Goal**: 用户在待办条目行内点「让 AI 做」，确认卡指令框预填待办 `title + description`（可当场补全）、`schedule_kind` 锁 one_shot，确认后建立一次性任务；完成后待办显示「上次执行」但不自动划掉。不改 `user_todos` 表。

**Independent Test**: 从一条真实待办发起接入，编辑指令后确认，等执行完成，确认待办未被自动改状态、只显示上次执行结果。

### Tests for User Story 4

- [X] T057 [P] [US4] guard：调度路径不写 `user_todos` 表（只读 `todo_id`）+ `source_type='todo'` 恒 `one_shot`（recurring 被拒）到 `tests/guardrails/test_todo_table_untouched.py` + `tests/guardrails/test_todo_source_one_shot_only.py`

### Implementation for User Story 4

- [X] T058 [US4] 待办悬空处理（worker 与 `fire_now` 每次触发前只读校验 `todo_id` 仍存在且未完成；待办被删 / 用户手动标记 done → CAS `status='expired'`；执行使用确认卡编辑后持久化的 `instruction`，旧草稿行才回退当前待办 title+description；**不写 `user_todos`**）到 `src/business/scheduling/scheduler_service.py` + `src/business/scheduling/scheduler_worker.py`
- [X] T059 [US4] `create_scheduled_task` handler 支持 `source_type='todo'`（按 `todo_id` 取待办 `title + description` 预填 draft `source_ref=todo_id`；`schedule_kind` 强制 one_shot）到 `src/business/agents/tools/assistant_tools.py`
- [X] T060 [US4] 待办条目行内「让 AI 做」按钮 → 弹创建确认卡（指令框预填 `title + description` 可编辑；`schedule_kind` 锁 one_shot）到 `frontend/src/screens/`（待办屏 `/todos` 组件）
  - 实现说明：按钮预填助手对话草稿（含标题/描述 + 显式一次性引导）并切到 `/assistant`，由主助理走 `create_scheduled_task` 工具 + 全局确认卡完成创建（FR-005：创建入口仍是主助理工具）。前端不直接构造确认卡 `requestId`，避免与后端 `SchedulingConfirmationManager` 失配。文件：`frontend/src/screens/UserTodoScreen/UserTodoScreen.tsx`
- [X] T061 [US4] 待办侧显示「上次执行：时间 + 成功/失败」（不自动改待办状态；结果页可提供调用既有待办接口的「标记完成」按钮）到 `frontend/src/screens/`（待办屏组件，消费 `scheduled_task.completed`）
  - 实现说明：UserTodoScreen 复用 `scheduledStore.tasks`，按 `sourceType='todo' && sourceRef===todoId` 派生每个待办的「上次让 AI 做」结果（取 `lastRunAt` 最新一条），展示在 meta 区并按 outcome 着色。待办状态不被自动改（FR-017），既有「标记完成」按钮仍在原位由用户决定。文件：`frontend/src/screens/UserTodoScreen/UserTodoScreen.tsx`

**Checkpoint**: 待办作为触发源接入完成，`user_todos` 边界由门卫守住。

---

## Phase 7: User Story 5 - 无人值守安全与人工接管 (Priority: P2)

**Goal**: scheduled 会话在用户不在场时跑——未授权高危动作立即按拒绝处理（不空等超时）、半路反问时通知用户接管（`waiting_user`）、失败可从历史接着聊；用户可为单个任务显式开启 per-task 免确认（默认关闭，仅影响该任务 scheduled 会话，不波及用户正在聊的会话）。

**Independent Test**: 创建一个会触发高危动作的 scheduled 任务（未开免确认），触发后确认高危动作被立即拒绝并汇报列出；再创建一个反问场景，确认 run 停在「需接管」并通知；再为某任务勾选免确认，确认其高危放行而其他会话不受影响。

### Tests for User Story 5

- [X] T062 [P] [US5] per-task 免确认范围 guard（开启某 task 免确认后 `_auto_approve_enabled` 值不变 / 用户会话 `source='user'` 高危仍走原流程 / 另一未授权 scheduled task 仍立即拒 / 即使进程级「全部允许」已开启也不能越权放行未授权 scheduled task / 审计日志记 `CONFIRM_SOURCE_UNATTENDED_TASK`）到 `tests/business/scheduling/test_unattended_scope.py`

### Implementation for User Story 5

- [X] T063 [US5] `UnattendedConfirmationManager`（独立、受锁保护的 authorized task-id `set[str]`，从 SQLite `unattended_auto_approve=1` 全量加载 + 任务创建/开关变更时增量刷新；**完全独立**于进程级 `_auto_approve_enabled`）到 `src/business/scheduling/unattended_confirmation_manager.py`
- [X] T064 [US5] 决策点注入：`builtin_general_tools.py` `_confirm_or_reject` **先于进程级 auto-approve** 调 `_unattended_auto_approve_for(session_id)`（session `source!='scheduled'`→passthrough 走原逻辑；scheduled + 该 task 在授权集→放行，审计记 `CONFIRM_SOURCE_UNATTENDED_TASK`；scheduled + 未授权→**D7 立即拒绝**，不空等 `_CONFIRM_TIMEOUT` 且不允许进程级「全部允许」越权）到 `src/business/agents/tools/builtin_general_tools.py`（判定「session 是否 scheduled + 关联哪个 task」经 v30 新增 `source` / `scheduled_task_id` 字段）
- [X] T065 [US5] `AssistantRuntime` 收到 D10 反问时调用 `RunCompletionMonitor.mark_waiting_user`，原子 CAS `running→waiting_user` 并单次 emit `scheduled_task.needs_takeover`（不标失败不悬空）；接管 REST 返回 `sessionId` 并 CAS 回 `running`，直到下一轮静默——改 `assistant_runtime.py` + `run_completion_monitor.py` + router
- [X] T066 [US5] 详情页 `unattendedAutoApprove` 开关 PATCH（`PATCH /{id}` 唯一 UI 写入该字段路径之一；确认卡勾选是另一路径）→ 刷新 `UnattendedConfirmationManager` 授权集 + emit `scheduled_task.changed`；前端详情页开关 UI——改 `src/desktop_api/routers/scheduled_tasks.py` + `frontend/src/screens/ScheduledScreen/ScheduledScreen.tsx`
- [X] T067 [US5] 端到端：未授权立即拒（不等超时）+ 反问 `waiting_user` 接管续跑 + 显式授权 per-task 放行（其他会话不受影响） 到 `tests/integration/test_scheduled_unattended.py`

**Checkpoint**: 无人值守确定性 fail-closed 边界 + 人工接管通道 + per-task 受控免确认全部到位。

---

## Phase 8: User Story 6 - 调度中心管理屏：一览、审视、回收 (Priority: P2)

**Goal**: 调度中心主屏统一管理所有任务（周期/一次性/待办来源）的标题/状态/调度描述/下次触发/上次结果；开启免确认的任务在列表层一眼可见并可随时回收；空态有创建指引；scheduled 会话只在调度中心历史可见、能点进去接着聊。

**Independent Test**: 创建若干任务（含一个开免确认的），打开调度中心确认列表信息齐全、免确认任务醒目；把 scheduled 会话与聊天屏对照确认隔离；从历史点进一个会话确认可继续对话。

### Implementation for User Story 6

- [X] T068 [US6] `ScheduledScreen` 管理操作：行内 暂停/启用（PATCH status）/ 现在跑一次（POST fire-now）/ 删除（DELETE 软删）+ 列表展示 标题/状态/调度描述/下次触发/上次结果（未跑过标「还没跑过」）+ 空态创建指引（引导去对话创建并附例句）到 `frontend/src/screens/ScheduledScreen/ScheduledScreen.tsx`
- [X] T069 [US6] 列表层免确认醒目标记（⚠ 一眼可见，FR-019）+ 详情页事后双向开关（显式开启 / 回收授权）到 `frontend/src/screens/ScheduledScreen/ScheduledScreen.tsx`
- [X] T070 [US6] 「现在跑一次」REST 落地（`POST /{id}/fire-now` 立即触发动作，不经确认卡，经 `SessionLauncher` 直接点燃；reentry 仍生效；paused 只停自动扫描，手动触发不隐式 resume / 不改原排期）到 `src/desktop_api/routers/scheduled_tasks.py` + `src/business/scheduling/scheduler_service.py`
  - 说明：前端已在 T068 接到 `scheduledStore.fireNow`（既有 store action，调 `POST /api/scheduled-tasks/{id}/fire-now`）；REST 落地由后端 Phase 3 T035 完成。前端无需再开新 client 方法。
- [X] T071 [US6] 端到端：管理操作（暂停/启用/现在跑/删除/详情开关）+ 历史 `waiting_user` 接管接着聊 到 `tests/integration/test_scheduled_management.py`；`frontend/tests/unit/scheduled-screen.test.tsx` 另覆盖 succeeded 直接打开原会话、waiting_user/failed 经 takeover 后选择返回会话并切 assistant 路由

**Checkpoint**: 全部 6 个 story 独立可用，管理与可见性闭环。

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: 跨 story 收口——CC-005 活文档例外、AI 入口四镜像、命名区隔、通知打包实测、双触发决策、quickstart 冒烟、前端 unit/e2e 补齐。

- [X] T072 [P] CC-005 受控例外活文档：`.specify/memory/constitution.md`（Engineering Guardrails / Core Principles 增「受控例外：调度中心 per-task 无人值守免确认」条款 + 四重限定 + 边界，version PATCH/MINOR bump）、`docs/PROJECT_CONSTRAINTS.md`（免确认「不持久化」补 033 显式受控例外）、`docs/ARCHITECTURE.md`（新增 scheduling 模块 + 调度中心 vs `graph_scheduler` vs「100% 调度」三处词汇区隔）
- [X] T073 [P] 四镜像 AI 入口同步：根 + `frontend/` + `src/` 的 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md`（主屏 9→10、新增 `scheduling/` 模块入口、CC-005 例外说明、Recent Changes 加 033 条目）—— 同目录三文件同内容
- [X] T074 新建 `src/business/scheduling/AGENTS.md`（+ `CLAUDE.md` / `GEMINI.md` 镜像）：模块入口、调度中心 vs `graph_scheduler` 命名区隔、CC-005 per-task 免确认例外与四重限定、8 个 task_collaboration 禁碰文件清单、Segment opt-out / 聊天屏排除边界
- [ ] T075 [P] 桌面通知 Windows nsis 打包实测（需人工打包后验证）：`identifier`（`com.mexamplar.desktop`）作 AUMID，实测弹窗不落 Action Center（research.md R5 验证项）
- [X] T076 [P] `RunCompletionMonitor` 双触发落地：主助理普通/reentry worker 从 runtime 注册表移除后确定性重评；`graph_scheduler_terminal(session_id=...)` 与既有任务活动事件提供较早观察；无图会话退化为 worker 退出且无 pending 回流即静默；任何 runtime/图查询未知均 fail-closed
- [X] T077 [P] `scheduling.notification` 合并通道 vs 分立事件二选一（research.md / contracts/ui-events.md 推荐分立），清理未用的事件注册与前端分支
- [X] T078 [P] 配置门卫：确认 `scheduler.scan_interval_seconds` / `scheduler.confirmation_timeout_seconds` 只走 `UnifiedConfigManager`，无硬编码值泄漏到业务代码（bounded `[5,600]` 生效）；misfire/reentry 是不可关闭的规格不变量，不建配置键
- [X] T079 [P] 前端 unit/e2e 补齐：`ScheduledScreen`（列表/管理操作/空态/免确认标记/详情开关）、`StructuredConfirmationCard`（draft 展示/勾选/取消/超时 fail-closed）、`scheduledStore`（applyEvent/resync）到 `frontend/tests/unit/` + `frontend/tests/e2e/`
- [ ] T080 quickstart.md 5 场景冒烟验证（需人工启动应用验证；后端集成测试+前端e2e已覆盖核心逻辑）：立即 / 一次性 / 周期 misfire+reentry / 待办接入 / 无人值守安全+接管 + 管理屏，按 `specs/033-scheduling-center/quickstart.md` 逐场景跑通并记录验证点
- [X] T081 [P] 调度 lifespan 初始化失败不再伪装 ready：清理半初始化组件后把 health/bootstrap 的 `scheduling` check 标为 degraded，并补启动回归测试
- [X] T082 [P] `fire-now` 返回真实 run 判别：仅 `running` 返回类型收窄的 `202 ScheduledTaskStartedRunItem`，active-run 冲突映射 409，会话创建/dispatch 失败映射 503；前端只对 202 显示成功提示
- [X] T083 [P] v31 run 终态事件按代次持久投递确认：`terminal_event_delivered_at` + 单调 `terminal_event_version` + pending index，ack 绑定事件代次，启动与每轮 worker tick 有界补投，覆盖 completion monitor、SessionLauncher 初始失败与 emit/ack 间状态竞态
- [X] T084 [P] pending 调度确认卡权威刷新失败保留旧卡、设置 `lastError + needsResync` 并向 resync 编排传播失败，补 store 回归测试
- [X] T085 [P] scheduling 权威 resync 统一失败协议：任务列表 `load()` 与 pending 刷新任一失败都向 AppShell 传播，整组最多重试 3 次后 degraded；普通屏幕/防抖刷新显式消费 rejected Promise，补“列表失败、pending 成功仍不得解锁”回归测试
- [X] T086 [P] 修复 failed run phantom session：`src/data/repos/scheduled_task_run_repository.py` 与 `src/business/scheduling/session_launcher.py` 将 scheduled session + active run 同事务落库；`src/business/services/chat_service.py`、`src/business/scheduling/scheduler_service.py`、`src/desktop_api/routers/scheduled_tasks.py` 及 `frontend/src/screens/ScheduledScreen/ScheduledScreen.tsx` 对旧 phantom/空会话惰性自愈并返回/预填 `recoveryDraft`；回归覆盖 `tests/business/scheduling/test_session_launcher.py`、`tests/desktop_api/test_scheduled_tasks_api.py`、`frontend/tests/unit/scheduled-screen.test.tsx`
- [X] T087 [P] 非空 root session 无法权威识别时高危确认 fail-closed：`src/business/agents/tools/builtin_general_tools.py` 对缺行/查询异常直接 `reject_immediately`，即使进程级「全部允许」开启也不得越权；回归覆盖 `tests/business/scheduling/test_unattended_scope.py`
- [X] T088 [P] 保持 task collaboration 终态副作用可重试：`src/business/task_collaboration/graph_scheduler.py` 的 `(graph_id, version)` claim 只去重新增 observer event，不门控 root 收口与父侧 reentry；覆盖状态写入和 sink 首次失败后重试到 `tests/business/task_collaboration/test_graph_scheduler_unit.py`
- [X] T089 [P] 统一 one-shot 本地时间契约：`src/business/scheduling/schedule_calc.py` 将无 offset 的 naive ISO 按显式 `tz` 或桌面系统本地时区解释后转 UTC，带 offset ISO 直接转 UTC；同步 agent tool / data-model / research 契约并覆盖 `tests/business/scheduling/test_schedule_calc.py`
- [X] T090 [P] 补齐 T086 接管恢复契约覆盖：`tests/desktop_api/test_scheduled_tasks_api.py` 区分已有空 scheduled session（返回原 session + `recoveryDraft`）与已有 user message（不返回草稿）；`frontend/tests/unit/scheduled-screen.test.tsx` 验证恢复草稿只填空目标草稿，不覆盖用户现有文字且不自动发送
- [X] T091 [P] 隔离完成监听器的同步 observer 异常：`src/business/scheduling/run_completion_monitor.py` 的三条 blinker receiver 在事件边界记录并吞掉评估异常，不反向打断 task collaboration 发送方；主动 `evaluate_session()` 保持原传播语义，回归覆盖 `tests/business/scheduling/test_completion.py`
- [X] T092 [P] 收口 run 生命周期状态集合单一事实来源：`src/data/scheduling_types.py` 统一 active / terminal / event-deliverable / takeover enum 集合及派生持久字符串集合，Repository、terminal delivery、completion monitor、scheduler service 全部复用；`tests/guardrails/test_scheduled_run_status_contract.py` 守住分区关系并拒绝消费者重新手写状态 bundle
- [X] T093 [P] 修正文档与实现的 DST / 分层 / unattended 漂移：`src/business/scheduling/schedule_calc.py` 显式识别 ambiguous/nonexistent wall time、分别选 `fold=0` / 按 gap 前移并记 warning，`tests/business/scheduling/test_schedule_calc.py` 覆盖 one-shot 与日历任务边界；同步 `plan.md` 的 SessionLauncher 分层及 `research.md` 的确认范围/授权集契约
- [X] T094 [P] 缺省本地时区 fail-closed：`pyproject.toml` / `uv.lock` 声明 `tzlocal` 直接运行时依赖，`src/business/scheduling/schedule_calc.py` 在依赖缺失或系统时区发现失败时记录错误并拒绝创建，禁止静默回退 UTC；同步 architecture / plan / research 并覆盖真实依赖及失败路径测试
- [X] T095 [P] 修复迁移顺序守卫的 latest-version 假设：`tests/data/test_specialist_composition_migration.py` 只断言 v29 紧随 v28，不再因 033 合法追加 v30/v31 或未来 migration 产生假失败
- [X] T096 [P] 增加 migration 注册表全局顺序门卫：`tests/data/test_migrations_v31.py` 断言 `_MIGRATIONS` 版本严格递增且无重复，并守住 v29→v30→v31 相邻顺序，避免 runner 推进高版本后静默跳过乱序低版本

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**：无依赖，可立即开始；T002/T003/T004 互相独立可并行
- **Foundational (Phase 2)**：依赖 Setup（T001 模块骨架、T004 `compute_graph_terminal_state`）——**阻塞全部 user story**
- **User Stories (Phase 3–8)**：均依赖 Foundational 完成
  - **US1（Phase 3）**：MVP，拉满基础链路；US2–US6 在其之上做增量
  - **US2（Phase 4）**：依赖 US1 的 SchedulerWorker / RunCompletionMonitor / 确认卡
  - **US3（Phase 5）**：依赖 US2 的 `compute_next_fire` 与动态 wait
  - **US4（Phase 6）**：依赖 US1 确认卡 + US2 一次性链路（待办恒一次性）
  - **US5（Phase 7）**：依赖 US1 router / run 状态机 / 通知；与触发类型正交
  - **US6（Phase 8）**：依赖 US1 `ScheduledScreen` 骨架与全部 REST endpoint
- **Polish (Phase 9)**：依赖期望完成的 story（CC-005 活文档可与 US5 同步起草）

### Within Each User Story

- 测试（含 guard）先写并 RED，再实现 GREEN（项目硬规则 #6 + tdd-guide）
- Models / Repository → Service → handler / router → 前端 store / API / Screen
- 核心实现先于端到端 integration
- 单 story 完成并独立验证后再进下一优先级

### Parallel Opportunities

- Setup：T002 / T003 / T004 互不冲突可并行；T001 先行
- Foundational：T007 / T009 / T010 / T011 / T012 / T014 / T017–T021 标 `[P]` 可并行（不同文件）；T005→T006 顺序（ORM 与 migration 须一致）
- US1：T022–T026 测试可并行；T027 / T028 标 `[P]`；T037 / T038 / T039 / T044 标 `[P]`
- 不同 user story 在 Foundational 完成后可由不同人并行（US4 / US5 / US6 互相正交）
- 同一 story 内标 `[P]` 的 model / 测试可并行

---

## Parallel Example: User Story 1

```bash
# 先并行写 US1 的 guard / 契约 / 完成判定测试（先 RED）：
Task: "完成判定三条件测试 in tests/business/scheduling/test_completion.py"
Task: "/api/scheduled-tasks 契约测试 in tests/desktop_api/test_scheduled_tasks_api.py"
Task: "工具边界 guard in tests/guardrails/test_scheduled_tool_boundaries.py"
Task: "unattended 三重不暴露 guard in tests/guardrails/test_scheduled_task_unattended_field_isolated.py"
Task: "router 401 guard in tests/guardrails/test_scheduled_tasks_api_auth.py"

# 再并行写互不冲突的 Service / Launcher / 前端 API / store：
Task: "SchedulerService in src/business/scheduling/scheduler_service.py"
Task: "SessionLauncher in src/business/scheduling/session_launcher.py"
Task: "前端 typed API client in frontend/src/api/scheduledTasks.ts"
Task: "toastStore 扩展 in frontend/src/state/toastStore.ts"
```

---

## Implementation Strategy

### MVP First（US1 only）

1. 完成 Phase 1 Setup
2. 完成 Phase 2 Foundational（**关键——阻塞全部 story**）
3. 完成 Phase 3 US1（立即触发最小闭环）
4. **停下验证**：按 quickstart 场景 1 独立验证 US1（确认卡 → 立即触发 → 完成 → Toast+桌面通知 → 历史 `succeeded` → 聊天屏不可见）
5. 可演示即发布/演示

> US1 + US2 共同构成「触发维度」完整闭环（立即 + 一次性），均 P1；若资源允许建议一并交付再停下验证。

### Incremental Delivery

1. Setup + Foundational → 基础设施就绪
2. +US1 → 独立验证（MVP：立即）
3. +US2 → 独立验证（一次性，触发维度闭环）
4. +US3 → 独立验证（周期 + misfire + reentry）
5. +US4 → 独立验证（待办接入，`user_todos` 边界守住）
6. +US5 → 独立验证（无人值守 fail-closed + 接管 + per-task 免确认）
7. +US6 → 独立验证（管理屏一览/审视/回收）
8. Polish：CC-005 活文档例外、AI 入口四镜像、通知打包实测、quickstart 全场景冒烟

### Parallel Team Strategy

Foundational 由团队共同完成后：
- Developer A：US1（MVP 链路）→ US2 → US3（触发轴递进）
- Developer B：US5（无人值守安全，与触发类型正交）
- Developer C：US4（待办接入）+ US6（管理屏）
各 story 独立集成、独立验证。

---

## Notes

- `[P]` = 不同文件、无未完成任务依赖
- `[Story]` 标签映射到 spec.md 的 user story（US1~US6）
- 每个 user story 须可独立完成与验证
- guard / 契约测试先写并 RED 再实现（spec CC 条款硬要求）
- 每个任务或逻辑分组完成后提交（commit message 遵循 `<type>: <description>`）
- 任意 checkpoint 可停下验证单 story
- 避免模糊任务、同文件冲突、破坏独立性的跨 story 依赖
- **task_collaboration 内核执行 / 通信 / 恢复语义禁碰**——登记的行为保持型接缝仅有：
  T004 抽取 `compute_graph_terminal_state`，以及 `graph_scheduler` 首次全终态时额外 emit
  `graph_scheduler_terminal` 供外部观察；事件接收方失败不得阻断既有父侧回流，且内核禁止
  反向依赖 scheduling
