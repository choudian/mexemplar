# Implementation Plan: Scheduling Center（调度中心）

**Branch**: `033-scheduling-center` | **Date**: 2026-07-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/033-scheduling-center/spec.md`（基于已评审设计稿 `docs/superpowers/specs/2026-07-18-scheduling-center-design.md`）

> 本 plan 的全部接入点结论由 4 路并行代码库调查实证支撑（数据层 / worker·session / 完成判定·事件·通知 / typed API·工具·聊天屏·前端），证据见各章 `文件:行`。033 是从零新建（仓库内无任何 `schedul*` 代码、无 `Session.source` 字段、无 `unattended_auto_approve` 命名空间冲突）。

## Summary

**一句话**：给现有任务协作（task_collaboration）加「三种触发方式（立即 / 一次性 / 周期）+ 执行记账 + 完成通知」，到点开一个标记为 `scheduled` 的主助理会话让它全权处理，跑完喊用户、记一笔——**不另起新系统、不改 task_collaboration 内核**。

**技术路线**（设计稿 D1–D12 + 调查实证）：
- 新增 `src/business/scheduling/` 业务模块：`SchedulerService`（CRUD + 触发时机）、
  `SchedulerWorker`（周期扫描 + 事件唤醒双 Event）、`SessionLauncher`（先构造 detached
  scheduled session，再由 Repository 同事务提交 session + active run，partial unique
  index 裁定 first-wins，随后投递）、`RunCompletionMonitor`（runtime 直调 + 内部事件双路径，
  按「会话静默」判定完成）、`UnattendedConfirmationManager`（per-task 免确认）。
- 复用既有入口：会话模型走 `ChatService.build_scheduled_session()` 构造，原子持久化走
  `ScheduledTaskRunRepository.try_create_active_with_session()`；执行/通信/恢复走
  task_collaboration 内核 + `AssistantRuntime.dispatch_message()`（必须复用
  `get_assistant_runtime()` 单例）；为完成观察新增内部图终态事件，但不改变节点推进、
  通信或恢复决策。
- 数据：SQLite migration v30 新增 `scheduled_tasks` / `scheduled_task_runs` 两表 + `sessions` 表加 `source` / `scheduled_task_id` / `is_scheduled` 三列；v31 为 run 终态 UI 投影增加确认时间、单调事件代次与待投递索引；**不碰 `user_todos`**。
- 安全：`unattended_auto_approve` 走「三重不暴露 + 独立 manager + 工具参数门卫」，是对「免确认只允许进程会话级内存」原则的**首次显式受控破例**（CC-005）。

## Technical Context

| 项 | 值 |
|---|---|
| **Language/Version** | Python 3.11+（运行时 3.12）、TypeScript（前端）、Rust stable（Tauri shell） |
| **Primary Dependencies** | FastAPI sidecar、SQLAlchemy（**自定义 Python 函数 migration，非 Alembic**）、Tauri 2、React 18、blinker；**新增** `tauri-plugin-notification`（前后端四层从零安装）、`tzlocal`（缺省本地时区权威发现；失败时调度创建 fail-closed） |
| **Storage** | SQLite（migration v30：2 新表 + sessions 加 3 列；v31：按代次确认终态事件投递）；DuckDB 不涉及 |
| **Testing** | pytest（后端：unit/integration/guardrails）、Vitest + React Testing Library（前端 unit）、Playwright（前端 e2e） |
| **Target Platform** | Windows 11 桌面（Tauri，nsis 打包） |
| **Project Type** | desktop-app |
| **Performance Goals** | 周期任务到点秒级触发；完成判定零误报（首轮 succeeded 不报完成、含失败图不漏报）；per-session 并发无串行化退化 |
| **Constraints** | app 非常驻（misfire 补跑是唯一救济）；无人值守 fail-closed；**不改 task_collaboration 内核**（8 个文件禁碰清单见 §task_collaboration 边界）；**不改 user_todos**；新 API 自动受 `X-Mexemplar-Session` 保护（零 Depends 约定） |
| **Scale/Scope** | 单用户家用、未发布、无外部消费者；主屏 9 → 10；~2 新表 + 1 表加列 + 1 新业务模块 + 1 新前端屏 + 5 新主助理工具 |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | 结论与证据 |
|-----------|---------------|------------|
| **I. 分层边界与事件协调** | 依赖方向 `UI→business→execution→data` 是否保持？跨模块通知是否走 `src/utils/events.py` blinker？ | ✅ **通过（含一处需登记的接缝处理）**。触碰层：UI（新屏 + 路由 + Toast 扩展）、Desktop API（新 router + lifespan wiring）、Business（新 `scheduling/` 模块 + 主助理工具）、Data（v30 + Session 加列 + 2 新 Repository）、Utils（新 blinker 事件）。事件：后端内部走新 blinker（`scheduler_*` + 图终态），面向前端经 UI Event Registry 注册 typed envelope（`scheduled_task.*` / `scheduling.confirmation_*`），emit 走 blinker→projector→`publish_draft_nowait`。**接缝处理（登记）**：`SessionLauncher` 保留在 business 层并只依赖纯接口；desktop lifespan 负责 `AssistantRuntime` 生命周期装配并向 launcher 注入 `dispatch_callback`，因此 business 不反向 import UI adapter。详见 Complexity Tracking CT-2。 |
| **II. 数据边界与持久化纪律** | SQLite/DuckDB 职责是否清晰？Repository 边界是否保持？ | ✅ **通过**。SQLite v30 新增 2 表 + sessions 加列，v31 为 run 终态事件增加确认时间与单调代次，全经 Repository；持久枚举/合法转移下沉到 `src/data/scheduling_types.py`，task/run Repository 在最终 mutation 边界执行条件 CAS，SessionRepository 守住来源三字段关系。业务代码不直写 SQL。`user_todos` 仅以 `todo_id` 字符串外部引用（不建 FK，仿 `discussion_session_id` 惰性自愈先例）。DuckDB 不涉及。 |
| **III. 统一配置与密钥安全** | 配置/密钥是否走 `UnifiedConfigManager`？DTO/UI/log 是否遮罩？ | ⚠️ **通过，但含 1 项显式受控破例（CC-005，须登记 + 修订活文档）**。新配置键（`scheduler.scan_interval_seconds` 等）走 `UnifiedConfigManager`。无新增密钥。**CC-005**：`unattended_auto_approve` 持久化到 SQLite 违反「免确认只允许进程会话级内存、不得写入配置/SQLite/DuckDB」（`docs/PROJECT_CONSTRAINTS.md:21` + CLAUDE.md 硬规则）。这是用户显式拍板的受控例外，四重限定（仅 scheduled 会话 / 仅该任务 / 默认关闭 / 只能 UI 显式开启）+ 工具参数门卫（三重不暴露）+ 独立 manager（不碰进程级 `_auto_approve_enabled`）。须在 implement 同步修订 constitution / `PROJECT_CONSTRAINTS.md` / AI 入口文档落例外条款。详见 Complexity Tracking CT-1。 |
| **IV. 可验证交付** | 确定性逻辑是否有自动化测试？架构接线是否有冒烟/门卫测试？ | ✅ **通过**。确定性逻辑测试：misfire 补跑（错过补一次 / paused 不补 / one_shot expired）、reentry 跳过记 skipped、`next_fire_at` 计算（每天/每周/工作日/每隔N/时区）、完成判定三条件（首轮不误报 / 含失败不漏报 / 回流续跑轮后置终态）、per-task 免确认范围门卫（不波及用户会话/不改全局）、参数门卫（`unattended_auto_approve` 不入工具 schema/handler/facade 三层静态断言）、`source_type=todo` 恒 one_shot 门卫、调度路径不写 `user_todos` 门卫、聊天屏 `source=scheduled` 排除、Segment opt-out（scheduled 会话不沉淀）。架构接线门卫：SchedulerWorker 接入 lifespan、`source` 全链路透传、新 UI 事件注册、新 router 401 保护、工具只在主助理可见。详见 §测试策略。 |
| **V. 活文档与规格驱动交付** | 受影响活文档是否识别？临时材料是否在 `docs/local/`？ | ✅ **通过**。活文档更新清单：`.specify/memory/constitution.md`（CC-005 例外条款，version bump）、`docs/PROJECT_CONSTRAINTS.md`（免确认例外）、`docs/ARCHITECTURE.md`（新 scheduling 模块 + 调度中心 vs graph_scheduler 命名区隔）、根 + `frontend/` + `src/` 的 `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`（主屏 9→10、新模块入口、四镜像同步）。`docs/design/` 放设计决策记录（非当前真相）。临时草稿入 `docs/local/`。 |

## Project Structure

### Documentation (this feature)

```text
specs/033-scheduling-center/
├── spec.md              # /speckit-specify 产出
├── plan.md              # 本文件（/speckit-plan 产出）
├── research.md          # Phase 0：开放问题决策 + 最佳实践
├── data-model.md        # Phase 1：实体 / 字段 / 状态机 / v30 migration
├── quickstart.md        # Phase 1：最小闭环体验路径
├── contracts/           # Phase 1：接口契约
│   ├── rest-api.md             # /api/scheduled-tasks typed CRUD + runs + confirmation
│   ├── ui-events.md            # 新公开 UI 事件 type + payload allowlist
│   ├── agent-tools.md          # 5 个主助理工具 schema + 约束
│   └── confirmation-and-unattended.md  # 确认卡 payload + per-task 免确认协议
└── tasks.md             # /speckit-tasks 产出（本命令不创建）
```

### Source Code（新增 / 修改）

```text
src/business/scheduling/                    【新模块】
├── __init__.py
├── models.py                               # 业务兼容 facade；重导出 data 层持久枚举/转移契约
├── scheduler_service.py                    # CRUD + 触发时机判定 + next_fire_at 计算
├── scheduler_worker.py                     # SchedulerWorker：双 Event（周期扫描 + 立即唤醒）+ misfire/reentry
├── session_launcher.py                     # session+active-run 同事务落库 → dispatch；创建失败零 phantom
├── run_completion_monitor.py               # runtime 直调 + 内部图/任务事件双路径，三条件判静默，写 run 终态 + 通知
├── terminal_event_delivery.py              # v31 终态事件按代次投递/确认 + 启动/tick 有界补投
├── unattended_confirmation_manager.py      # per-task 免确认（独立 pending set + 独立 signal，不碰 _auto_approve_enabled）
└── scheduling_confirmation_manager.py      # 创建确认卡（内存 pending + 原子过期/停止 fail-closed，复用 ClarificationCard 视觉，不复用 019 后端协议）

src/business/task_collaboration/
└── graph_terminal.py                       # 内核自有 compute_graph_terminal_state；scheduling 单向复用

src/business/agents/tools/
└── assistant_tools.py                      # 追加 5 个 *_SCHEDULED_TASK_SCHEMA + 5 个 create_*_handler（不进 executor 路径）

src/data/
├── scheduling_types.py                     # 持久枚举 + task/run 合法转移表（Repository 最终门卫的单一事实来源）
├── models_sqlite.py                        # Session 加来源三列；ScheduledTask 加独立 instruction；新增 ScheduledTask / ScheduledTaskRun ORM
├── migrations.py                           # migrate_to_v30/v31 + 注册（实体/来源 + 终态投递确认）
└── repos/
    ├── base_repository.py                  # 加 ID_PREFIX_SCHEDULED_TASK="sch_" / ID_PREFIX_SCHEDULED_TASK_RUN="schr_"
    ├── scheduled_task_repository.py        # 仿 UserTodoRepository（CRUD + list 分页 + 软开关 + CAS next_fire）
    ├── scheduled_task_run_repository.py    # 复用 scheduling_types 合法转移表 + 条件 CAS
    └── session_repository.py               # 来源关系最终门卫 + get_by_agent_type exclude_sources

src/business/services/
└── chat_service.py                         # user/scheduled 强类型构造入口；is_scheduled 由来源派生；聊天列表排除 scheduled

src/business/orchestration/agent/
├── tool_registry.py                        # build_assistant_tools 的 import 白名单 + static_tools 追加 5 工具（绝不进 build_delegated_executor_tools）
└── assistant_prompt_builder.py             # 从 session.is_scheduled 判定 advisory，不改 runtime/orchestrator 签名

src/business/agents/prompts/
└── assistant_prompt.py                     # 独立 {advisory_section} placeholder

src/business/brain/
└── segment_service.py                      # seal_segment() 开头 early-return scheduled 会话（Segment opt-out 单点收口）

src/utils/
└── events.py                               # 新 blinker 事件：scheduler_task_changed / scheduler_run_terminal / graph_scheduler_terminal（EventName + _EVENT_FIELDS）

src/desktop_api/
├── app.py                                  # lifespan 追加 SchedulerWorker start/stop；include_router 追加 scheduled_tasks
├── assistant_runtime.py                    # scheduling confirmation 随 session stop fail-closed；run completion monitor wiring
├── routers/health.py                       # scheduling 初始化状态进入 health/bootstrap degraded 投影
├── ui_events.py                            # 注册 scheduled_task.completed/needs_takeover/changed + scheduling.confirmation_requested/resolved（失败由 completed.outcome=failed 表达）
├── ui_event_projector.py                   # 新增 scheduled/scheduling domain 投影 + _scope_from_payload 扩展
├── schemas.py                              # ScheduledTask* DTO（camelCase）+ 可渲染 pending/编辑确认 DTO
└── routers/
    └── scheduled_tasks.py                  # /api/scheduled-tasks typed CRUD + /{id}/runs + confirmation decision

src-tauri/
├── Cargo.toml                              # +tauri-plugin-notification = "2"
├── src/lib.rs                              # +.plugin(tauri_plugin_notification::init())
└── capabilities/default.json               # +"notification:default"

frontend/src/
├── app/routes.tsx                          # routes 数组 + routePaths 加 "scheduled":"/scheduled"
├── state/shellStore.ts                     # RouteId 加 "scheduled"
├── state/toastStore.ts                     # ToastTone 扩展 success/info/warning + notifySuccess/Info/Warning
├── state/scheduledStore.ts                 # 【新】Zustand store + applyEvent
├── api/scheduledTasks.ts                   # 【新】typed API client（经 requestJson）
├── api/uiEventTypes.ts + uiEventParser.ts  # 镜像新事件 type + mapper
├── components/StructuredConfirmationCard.tsx  # 【新/抽取自 ClarificationCard】全局确认卡容器（挂 AppShell）
└── screens/ScheduledScreen/ScheduledScreen.tsx  # 【新】调度中心主屏（管理 + 历史 + 空态引导）

tests/
├── business/scheduling/test_session_launcher.py       # session+run 原子创建、并发 first-wins、dispatch 失败终态
├── business/scheduling/test_scheduler_service_invariants.py # 触发/管理不变量
├── business/scheduling/                    # 触发精度 / next_fire / misfire / reentry / 完成判定 / per-task 免确认范围
├── data/test_migrations_v30.py + test_migrations_v31.py     # schema 与终态投递迁移
├── data/test_scheduled_repositories.py     # Repository 状态机 + CAS + 投递代次
├── guardrails/                             # 参数门卫 / todo 不改表 / todo 只 one_shot / 聊天屏排除 / Segment opt-out / 工具只在主助理 / router 401
├── desktop_api/test_health_bootstrap.py    # scheduling degraded 健康投影
├── desktop_api/test_scheduled_tasks_api.py # typed REST + fire-now/takeover 恢复契约
├── frontend/tests/unit/                    # store/resync/screen/通知回归
└── integration/                            # 端到端：创建→触发→执行→完成→通知
```

**Structure Decision**：沿用项目既有分层与命名（业务模块 `src/business/<domain>/` + Repository `src/data/repos/` + router `src/desktop_api/routers/<domain>.py` + 前端 `<Screen>/`）。新模块命名 `scheduling`（内部类 `SchedulerWorker`/`SchedulerService`），在模块文档点明与 `graph_scheduler`（依赖维度推进器）的区隔——调度中心是**时间维度触发中枢**。

### task_collaboration 内核语义边界（仅允许登记的行为保持型接缝）

以下文件 033 **仅外部调用、不改变执行 / 通信 / 恢复决策**（CC-003 零回归）：
`task_collaboration/{service,dispatcher,recovery,adjudication,parent_reentry_sink,background_worker}.py`、
`orchestrator.py` 的 `_dispatch_task_via_unified_model`/`_get_task_dispatcher`/
`_wire_graph_scheduler` 段、`src/execution/` 全部。两处登记的行为保持型接缝是：
(1) T004 把两处既有终态判定抽到内核自有 `task_collaboration/graph_terminal.py`，
`graph_scheduler` / `reentry_briefing` 调同一纯函数；(2) `graph_scheduler` 在首次观察到
执行节点全终态时额外 emit 含 `session_id` 的内部 `graph_scheduler_terminal`，观察者失败
不阻断原父侧回流。“首次观察”的 claim 只去重 observer emit，不门控 root 收口或父侧
reentry；这两条既有副作用在瞬时失败后保持可重试。scheduling 只单向复用 / 监听，
内核禁止反向 import scheduling。

## Complexity Tracking

> Constitution Check 有 2 项需登记的例外/接缝处理。

| Violation / 接缝 | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| **CT-1（CC-005）免确认持久化受控破例** | scheduled 无人值守需 per-task 显式授权高危放行，且授权须跨进程重启存活（内存态会丢，用户每次重启都要重开，体验不可接受）。 | (a) 复用进程级 `_auto_approve_enabled`：它是**进程级单一布尔**（`builtin_general_tools.py:159`，无 session 维度），开启即波及用户正在聊的会话——不可用。(b) 纯 prompt 约束「别触发高危」：LLM 不可靠，违反项目「高危 fail-closed 靠机制不靠 prompt 自觉」一贯原则。(c) 不做免确认：scheduled 会话触发高危即立即拒绝（D7），复杂任务大面积失败，无人值守价值大减。故取**独立 manager + SQLite 持久化 + 四重限定 + 工具参数门卫**，把爆炸半径焊死在「仅该 scheduled 会话」。须修订 constitution/`PROJECT_CONSTRAINTS.md` 落条款。 |
| **CT-2 SessionLauncher 跨层接缝** | 调度中心在 business 层，需触发主助理会话；而 `AssistantRuntime`（`dispatch_message`）在 `src/desktop_api/`（UI adapter 层）。business 直接 import desktop_api 违反依赖方向。 | (a) 把 SessionLauncher 整体放 desktop_api：会让调度启动与 run 记账落到 adapter 层。故取**回调注入**：business 层 `SessionLauncher.launch(scheduled_task_id, instruction, started_at) -> run_id` 先构造 detached scheduled session，再由 Repository 在同一事务提交 session + active run，partial unique index 裁定 first-wins，随后投递已核定指令；原子创建失败不留 run，只有 dispatch 失败才终结已落库 run。desktop lifespan 注入 `dispatch_callback`（实际调单例 runtime）。launcher 会注册成进程级 runtime 依赖，供短生命周期 REST service 复用；未装配时 fire-now 显式 503。 |

## 测试策略（Constitution IV 细化）

**确定性逻辑（unit/integration）**：
- `next_fire_at` 计算：每隔N / 每天某时 / 每周某天某时 / 工作日 / 时区与 DST 边界（`tests/business/scheduling/test_schedule_calc.py`）
- misfire：app 未运行错过补一次 / 错过多周期只补一次 / interval 仍锚定原计划节拍而不随实际醒来漂移 / paused 期间过点不自动补 / one_shot 暂停后 expired（`test_misfire.py`）
- reentry：上次未静默本次跳过记 skipped（`test_reentry.py`）
- 完成判定：首轮 succeeded 不误报 / 含失败图不漏报（不依赖 root=completed）/ 回流续跑轮后置终态（`test_completion.py`，用 file-based DB 避开 in_memory StaticPool）
- per-task 免确认范围：开启仅影响该任务 scheduled 会话 / 不改 `_auto_approve_enabled` / 用户会话不受波及 / 进程级「全部允许」不能覆盖未授权 scheduled 的立即拒绝（`test_unattended_scope.py`）

**架构门卫（guardrails）**：
- `unattended_auto_approve` 不在工具 schema/handler/facade 三层（三层静态断言，仿 `test_skill_origin_closed_enum.py`，比 031 更严）
- 调度路径不写 `user_todos`（`test_todo_table_untouched.py`）
- `source_type=todo` 恒 one_shot（`test_todo_source_one_shot_only.py`）
- 聊天屏排除 `source=scheduled`、其余读取路径不排除（`test_chat_list_exclusion.py`）
- Segment opt-out：scheduled 会话不产 BrainSegment（`test_scheduled_skips_segment.py`）
- 5 工具只在 `build_assistant_tools`、不在 `build_delegated_executor_tools`（`test_scheduled_tool_boundaries.py`）
- `/api/scheduled-tasks` 无 token 返 401（`test_scheduled_tasks_api_auth.py`）

**端到端（integration/e2e）**：创建（确认卡）→ 触发（立即/一次性/周期）→ 主助理会话执行 → 完成静默判定 → Toast + 桌面通知 → 历史可见 → 失败/需接管从历史接着聊。
