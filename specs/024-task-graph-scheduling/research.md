# Research: 024 Task Graph Scheduling

**Branch**: `024-task-graph-scheduling` | **Date**: 2026-06-24 | **Baseline**: commit `06053db`（023 已落地状态）
**Method**: 4 个并行只读调研代理交叉核对 worktree 代码 + 设计文档 §附的文件清单。

本文档固化 Phase 0 全部决策、锁定 024 将消费的 023 接口契约、明确 claude-code 借鉴机制的适配点，并记录与设计文档的偏差。所有 Technical Context 的 NEEDS CLARIFICATION 在此解析完毕。

---

## 1. 决策固化（NEEDS CLARIFICATION 全部解析）

### DEC-A：节点「需确认」标记承载 → **新增列 `requires_confirmation`**
- 现状：`assistant_tasks` 无任何 needs_confirmation/requires_confirmation 列；`suspend_reason` 枚举（`waiting_user/waiting_system/user_stop`）承载不了该语义且会撞 CHECK。
- `capability_scope` 是 tool whitelist（JSON），语义不符；`TaskGraphSnapshot.requiresReview` 是派生快照字段、非持久化 task 属性。
- **决策**：新增 `assistant_tasks.requires_confirmation INTEGER NOT NULL DEFAULT 0`（migration v17）。scheduler 在派发节点前读此列；为 1 时不直接 dispatch，改为建 pending adjudication 触发主助理裁定。
- 不复用 suspend_reason / capability_scope，避免语义混淆与 CHECK 冲突。

### DEC-B：规划专员形态 → **完整 D4（用户已确认）**
- 调研发现：023 specialist 招募是「累计信号阈值」、无即时 task_pattern 自动匹配；主助理靠显式 `delegate_to_specialist(specialist_name=...)`。要让规划专员「只规划不执行」需新增 `role_kind` + tool_registry 按角色分支 + 招募/调用路径。
- **决策**：现在就做完整规划专员：
  - specialist 模型新增 `role_kind ∈ {executor, planner}`（migration v17 同批）。
  - tool_registry 按角色分支：planner 注入 `build_task_graph`（规划变体，不注入 todo_update/ask_parent/执行器工具）；executor 不变。
  - 主助理识别超阈值任务后 `delegate_to_specialist(specialist_name=<规划专员>)`，任务描述为「为以下需求产出可执行任务图」。
  - 规划专员只规划不执行（深度封顶，不再向下委派执行）。
  - 跨会话拆解经验经现有 brain specialist 经验积累通道沉淀。
- 招募路径：复用现有 specialist recruit（`brain/specialist_service.py`），用规划型信号招募；首版可提供手动/配置注册一个规划专员（避免依赖信号阈值冷启动），后续接累计信号。具体在 tasks 阶段定。

> **Amendment 2026-07-27：规划专员补只读调研工具与专员目录**
>
> **背景**：一次真实 run（见 `docs/local/2026-07-25-mexemplar-sandbox-run-postmortem.md`）暴露规划专员零工具调用直接建图——它手里只有 `build_task_graph`，既读不了目标项目，也看不到有哪些专员可派。产出的六个节点里，凡依赖项目现状的都退化成「先阅读以下文件确认…」把调研甩给下游执行体，且 assignee 两列全部 NULL。
>
> **这不是推翻 DEC-B，是修正实现对它的过度解读**。DEC-B 原文写的是「不注入 todo_update/ask_parent/**执行器工具**」；实现时把整个 `BUILTIN_GENERAL_TOOLS` 都当成执行器工具挡在门外，连纯只读的读取与搜索一并禁掉。
>
> **修订后的 planner 工具边界**：
> - **放行**（只读调研）：`read_file`、`list_dir`、`search_files`、`search_content`、`load_tool_output`。全部 `has_side_effects=False`，门卫测试对此有断言。
> - **新增**（规划必需）：`list_specialists`。`build_task_graph` 的 `assigneeId` 要求填具体 specialist id，没有目录就只能把所有节点退化成临时子代理。专员目录同时按 `brain.specialist_catalog.full_max_items`（默认 15）注入 system prompt，超阈值转本工具按需查询。
> - **仍然禁止**（"只规划不执行"硬边界不变）：`write_file`、`edit_file`、`apply_patch`、`exec`、`process_*`（含无副作用的进程查询——不属于规划职责）、`web_search` / `web_fetch`（无副作用但引入网络与外部内容，另行评估）、以及 `todo_update` / `ask_parent` / `meeting_*` / `delegate_to_subagent` 等执行器协作工具。
>
> **`exec` 明确不给**：Claude Code 的 Plan agent 给 Bash 但靠 prompt 白名单限定只读命令；Exemplar 的 `exec` 已改 shell 模式、只剩 OS 路径一道硬拒，给了即等于完整执行能力，prompt 拦不住。代价是 planner 看不了 `git log`/`git diff`，将来需要时单独做只读 git 查询工具，不开 `exec` 的口子。
>
> **门卫**：`tests/guardrails/test_planner_specialist_tools.py` 同时守正反两侧——禁止清单不得泄漏，只读放行清单不得缺失，且放行清单成员必须 `has_side_effects=False`。

### DEC-C：节点失败自愈 → **在 pending adjudication 阶段介入，裁定动作复用现有三态**
- 调研发现：失败 attempt 默认**不翻 task FAILED**，而是建 pending adjudication（`deliveredStatus ∈ {stuck, failed_input}`）等主助理裁定；只有 `decide(abandoned)` 或 `fail_root_graph` 才翻 FAILED。
- `AdjudicationDecision` 仅 `accepted/returned/abandoned`，**无「问用户」动作**。
- **决策**：自愈在 pending adjudication 阶段介入——回流 briefing 附 advisory「可选自愈动作清单」（重试/换执行器/调输入/跳过/改图/放弃）；主助理据此决策：
  - 重试/调输入 → `decide_task_adjudication(returned)`（打回返工，回 `pending_dispatch` 重新派）。
  - 换执行器 → 改 task 的 `assignee_type/assignee_id` 后 `returned`。
  - 跳过 → 标记节点跳过（节点级状态，见 DEC-D 状态机）+ 下游按其当 completed 处理 或 取消下游。
  - 改图 → 调 graph mutation（新增/删除节点与依赖边）。
  - 放弃 → `decide_task_adjudication(abandoned)`。
  - 兜不住 → 升级用户（主助理用 `ask_user_question`，019 既有工具）。
- 不新增裁定枚举动作；自愈动作清单是 advisory，最终仍由主助理调既有裁定工具落定（CC-008 软约束）。

### DEC-D：「需确认」节点暂停回流 → **复用 adjudication 暂停路径 + 新 reentry_type**
- 调研发现：暂停回流当前仅 `reentry_type=="task_question"` 触发（`dispatcher.py:519`）。
- **决策**：scheduler 派发 `requires_confirmation=1` 节点前，**不 dispatch**，而是为该节点建 pending adjudication（kind 标记为 needs_confirmation，或扩 `_paused_reentry_payload` 新增 `reentry_type="needs_review"`）触发回流；主助理在 briefing 看到「节点 X 即将执行、标记为需确认」→ 裁定放行（accepted→dispatch）/调整（returned+instruction）/放弃（abandoned）。复用 `decide_task_adjudication`，不新增裁定动作。
- scheduler 在节点放行后才对其调 `start_attempt_async`。

### DEC-E：节点 todo 可见性 → **TaskGraphPanel 节点展开（非 014 SubagentDrawer）**
- 调研发现：spec FR-012/US5-AC3 字面说「经现有子任务详情入口（014 SubagentDrawer）查看执行器 todo」，但 023 dispatcher 路径下 task node 执行器（`TaskExecutorAdapter`）**不发 `assistant.subagent` 事件**，SubagentCard 不会为其出卡片——字面复用不可行。
- **决策**：todo 按需可见走 **TaskGraphPanel 内节点展开**——复用现有 `assistantTaskStore.todosByTaskId` + `GET /api/assistant/sessions/{sid}/tasks/{taskId}/todos` + `assistant.todo.changed` 事件，**0 改 014 组件、0 新通道**。默认界面不展示（panel 按节点展开态/`requiresReview` 条件渲染）。
- 这是对 spec FR-012 措辞与 023 现实的消解：**意图保留**（todo 按需可见、默认不展示、复用既有入口），**机制**从 SubagentDrawer 改为 TaskGraphPanel 节点展开。建议同步在 spec 的 Event/Architecture Impact 处加一行说明（plan 已记录，tasks 阶段补 spec 注脚）。

### DEC-F：批量建图 `graph_version` 递增 → **接受 per-edge 递增（建图期不可并发取消）**
- 调研发现：`add_edge` 每次 `root.graph_version += 1`（`assistant_task_repository.py:111-116`），批量建 N 节点 + M 边会让 graph_version 跳 N+M 次。
- **决策**：`build_task_graph` 在单个 `_atomic` 内连建，接受 per-edge 递增。理由：建图期图是全新的、尚未进入调度/不可被并发 cancel/replan（cancel 用 `expected_graph_version` 围栏防的是「replan 插入的新下游逃过取消波」，发生在图已运行后），建图期的递增不破坏围栏语义。若后续发现 cancel 围栏受影响，再优化为批量入口一次性 `+1`。

### DEC-G：`suspendReason` 事件枚举 → **首版纯复用 `waiting_user`，不改事件契约**
- 调研发现：`assistant.task_graph.changed` 的 `suspendReason` enum 为 `{waiting_user, waiting_system, user_stop}`；024「高风险待裁定」语义最接近 `waiting_user`。
- **决策**：首版高风险暂停用 `waiting_user` + `requiresReview=true` + `safeExplanation` 区分，**0 事件改动**，守住 CC-004。若后续需更精确区分，再在 UI Event Registry 扩 `suspendReason` 加 `waiting_confirmation`（payload enum 扩展，非新 type，仍合规）+ 同步前端类型。

### DEC-H：回流包结构化引导 → **briefing 文本段注入（briefing 保持纯文本）**
- 调研发现：`reentry_briefing` 是纯文本 prompt（`build_reentry_briefing(entries)->str`），主助理只收到 program-role 字符串。
- **决策**：024 的「下一步建议/自愈动作清单/todo 概览」作为 briefing **文本段**注入（result 段后追加）。briefing 保持纯函数可单测；确定性「就绪可派节点/是否有待裁定节点/是否全图完成」由 `assistant_runtime._run_assistant_reentry` drain 后查一次 graph snapshot 传入 `build_reentry_briefing`（briefing 不直接做 IO）。自愈动作清单随失败 entry dict 携带（dispatcher/service 计算）。todo 概览从 snapshot 聚合各 task todo 状态。briefing 归 business 层组装，UI adapter 只转发。

---

## 2. 024 消费的 023 接口契约（已锁定签名/位置）

### 2.1 数据层（`src/data/`）
| 契约 | 位置 | 024 用途 |
|---|---|---|
| `assistant_tasks` schema | `migrations.py:1088-1122`, ORM `models_sqlite.py:224-274` | 复用；+`requires_confirmation` 列（v17） |
| `assistant_task_edges` | `migrations.py:1125-1138` | 激活 `edge_type='dependency'`（propagation='blocking'），写入路径新建 |
| `_assert_no_cycle` | `assistant_task_repository.py:108-109, 284-293` | 建图无环校验**已自动触发**（add_edge 内），复用 |
| `add_edge` | `assistant_task_repository.py` | 写 dependency 边；注意 per-edge graph_version+1（DEC-F） |
| `graph_version` 围栏 | `service.py:602-608`（`_bulk_transition` 的 `expected_graph_version`） | cancel/replan 并发围栏，复用 |
| TaskAttempt lease/fence | `models_sqlite.py:340-380`, `attempt_repository.py` | capacity=1 三层守卫 + 原子条件 UPDATE，复用 |
| specialist `role_kind` | `models_sqlite.py` specialist 模型 | +`role_kind ∈ {executor,planner}`（v17，DEC-B） |

### 2.2 task_collaboration 业务层（`src/business/task_collaboration/`）
| 契约 | 签名/位置 | 024 用途 |
|---|---|---|
| `_atomic` UoW | `unit_of_work.py:101-121` | `build_task_graph` 批量原子建图复用此事务边界 |
| `create_root_graph` | `service.py:274-309` | 建根任务样板参考 |
| `create_child_task` | `service.py:311-376` | 原子建 task+edge 参考；024 扩为批量 + dependency 边 |
| `start_attempt_async` | `dispatcher.py:156-191`：`(task_id, executor_type, executor_id, lease_owner, checkpoint_ref=None) -> Future|None` | scheduler 派就绪节点复用此内核 |
| `TaskExecutorAdapter` | `task_executor_adapter.py:42` | 执行器分流（specialist/ephemeral），复用 |
| `decide_task_adjudication` | `adjudication.py:93`：`decide(adjudication_id, decision, decided_by, instruction, session_id)` | 需确认裁定 + 失败自愈落定，复用（accepted/returned/abandoned） |
| `create_parent_adjudication` | `service.py:423` | 失败/需确认建 pending adjudication 触发回流 |
| `stop_graph/continue_graph/cancel_graph` | `service.py:634-669` | 取消/改主意传播，复用 |
| 取消三层 key | `dispatcher.py:528-549`（graph/task/attempt）+ `run_context.request_cancel_key` | 协作式取消信号，复用 |
| `TaskTodoService.list_todos` | `todos.py:31-37` | 节点 todo 概览回流（只读，跨 service 读安全） |
| `build_reentry_briefing` | `reentry_briefing.py:13` | 扩文本段（DEC-H） |
| `_paused_reentry_payload` | `dispatcher.py:518-525` | +needs_review reentry_type（DEC-D） |

### 2.3 agents / orchestration（`src/business/`）
| 契约 | 位置 | 024 用途 |
|---|---|---|
| `ASSISTANT_SYSTEM_PROMPT` | `assistant_prompt.py:8-98`（`format_assistant_prompt` 101-181） | 在 `### 任务分类`(21-26) 与 `### 100% 调度规则`(28-39) 之间插入「复杂度判定与任务分解」段 |
| 工具注册模式 | `make_tool_schema`+`create_xxx_handler`+`ToolDefinition`，装配于 `tool_registry.build_assistant_tools()`(222-428) | `build_task_graph` 按此模式加入 assistant_tools.py + tool_registry |
| `delegate_to_subagent/specialist` | `assistant_tools.py:1171/1429` | 超阈值委派规划专员复用 delegate_to_specialist |
| `build_delegated_executor_tools` | `tool_registry.py:69-78` | +planner 角色分支：planner 注入 build_task_graph 规划变体，不注入 todo_update/ask_parent |
| `todo_update` | `assistant_tools.py:1044-1095`（注入点 `tool_registry.py:140-151`） | 扩 description 引导节点内分解（DEC 见 §3） |
| `_SUBAGENT_WORK_RULES` | `orchestrator.py:61-69` | 弱化第 2/3 条反规划压力 |
| 死代码 | `orchestrator.py` `_build_tools/_build_assistant_tools/_build_delegated_executor_tools`（首行 return） | **不碰**，所有装配改落 tool_registry.py |
| specialist recruit | `brain/specialist_service.py`（`_recruit_from_signal` 321, `_generate_role_definition` 415） | +planner role_kind 招募/注册路径（DEC-B） |

### 2.4 desktop_api（`src/desktop_api/`）— **0 新增**
- UI Event Registry（`ui_events.py`）：7 个 task 事件全覆盖；024 **0 新公开事件 type**（DEC-G）。
- 12 个 task API endpoint（`routers/assistant_tasks.py`）全覆盖（graph 快照含 edges/adjudications、todo 按 taskId、adjudication decision、stop/cancel）；**0 新 API**。
- 复杂度判定 + 触发调度器 hook 在 `AgentOrchestrator` prompt + build_task_graph 工具层，**不动 assistant_runtime**（runtime 只驱动 worker/run_agent/reentry）。

---

## 3. claude-code 借鉴机制适配点（CC-009 逐项确认）

设计 §5.2/§5.4/§5.5 借鉴 claude-code（单用户 CLI）的 4 个机制，适配到办公助理「多专员 + 持久化」场景：

| 借鉴机制 | claude-code 原型 | 024 适配 | 主保障（023 已有） |
|---|---|---|---|
| **就绪硬校验**（claim 层挡前置未完成） | `claimTask` 校验依赖完成 | scheduler 派发 + Repository 层双校验：scheduler 扫就绪节点（所有 dependency 前置 completed）；派发前 `_assert_dependencies_satisfied`（新建，Repository 层）兜底，前置未完成派不出 | capacity=1 三层守卫已挡「同节点并发」；就绪校验挡「跨节点乱序」 |
| **单工作者在办约束** | `claimTaskWithBusyCheck` | 复用 023 capacity=1（v16 partial unique index `uq_assistant_task_attempts_active_executor` 已强制「一执行器一 active attempt」）；并发由多执行器各跑一节点实现 | attempt active-executor unique index |
| **executor 异常 unassign** | `unassignTeammateTasks` | 复用 023 lease 过期回收（`background_worker._fence_expired_attempts` + `resume_callback`）：executor 崩溃/lease 过期 → attempt fenced → 节点退回 `pending_dispatch` → scheduler 重入就绪重派 | lease/fence + background_worker 恢复扫描 |
| **工具结果反向教育** | 工具返回值引导下一步 | DEC-H：回流 briefing 附「下一步建议 + 自愈动作清单 + todo 概览」文本段，主助理在结构化选项里决策 | parent reentry + reentry_briefing |

**结论**：4 个借鉴机制在 023 已有 lease/fence/父侧裁定/capacity=1/reentry_briefing 基础上均可落地；新建项仅「就绪硬校验 `_assert_dependencies_satisfied`」与 scheduler 本身，其余为复用 + 文本段扩展。与 CC-009「以 023 既有为主保障、借鉴机制为增强」一致。

---

## 4. 与设计文档的偏差（已消解）

| 设计文档说法 | 调研结论 | 消解方式 |
|---|---|---|
| §6「复用现有原子创建」 | 只有 `create_child_task`（1 task+1 delegation 边），无批量建图 | 新建 `build_task_graph`（复用 `_atomic` UoW），DEC-F 处理 graph_version |
| §5.2「需确认标记优先复用现有字段」 | 无现成列可复用 | DEC-A 新增 `requires_confirmation` 列 |
| §5.5「回流包结构化引导」 | briefing 是纯文本非结构对象 | DEC-H 文本段注入 |
| §5.5「裁定含问用户」 | 裁定枚举无「问用户」 | DEC-C 用 `ask_user_question`（019 既有）做升级；裁定复用三态 |
| D4「规划专员」 | specialist 无即时匹配、需 role_kind 分支 | DEC-B 完整 D4（用户确认），含 role_kind + tool_registry 分支 + 招募 |
| §5.7/FR-012「todo 经 014 子任务详情入口」 | dispatcher 路径 task executor 不发 subagent 事件，SubagentDrawer 不出卡片 | DEC-E 改走 TaskGraphPanel 节点展开（意图保留、机制修正） |
| §5.4「调度器」 | 023 无「依赖就绪自动唤醒下游」调度循环 | 新建 `graph_scheduler.py`（确定性、非 LLM），复用 dispatcher 派发内核 |

---

## 5. 测试策略锚点（constitution IV，详 data-model.md / tasks.md）

- **架构门卫**：命中超阈值规则的任务必须落库为带 dependency 边 DAG 且由 scheduler 驱动；禁止「复杂任务一把委派」回归；planner specialist 不拿执行器工具。
- **DAG scheduler 单测**：就绪激活、串/并行混合、无环校验、就绪硬校验拒乱序、暂停/恢复。
- **裁定链路**：需确认节点正确暂停回流、主助理裁定后续跑；失败自愈（returned 重试/换执行器、abandoned 放弃、改图）。
- **executor 异常 unassign**：lease 过期后节点退回 pending_dispatch、图不卡死（复用 023 恢复测试范式）。
- **回流引导**：完成/失败回流 briefing 正确附下一步建议/自愈动作/todo 概览。
- **todo 引导生效**：多步节点执行器主动用 todo_update 建清单并实时更新（非整段字符串快照，验证关键语义）。
- **todo 可见性**：主助理回流见 todo 概览；TaskGraphPanel 节点展开可见、默认界面不展示。
- **取消/改主意**：顺图停止、改主意走 cancel+重分解。
- **回归**：简单任务仍走快速委派快捷通道；023 durable accepted/恢复/并发安全路径不退化。
