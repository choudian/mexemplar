# Exemplar Project Constraints

本文件记录开发约束、反模式和允许例外。长期治理原则仍以 `.specify/memory/constitution.md` 为准。

## Agent Tool Hook Boundaries

- pre_hook 只允许放行、拒绝和观测，不允许改写 handler 入参。
- `ToolCallContext.args` 必须是递归只读隔离视图；顶层和嵌套 dict/list 写入都应抛异常，handler 入参不受影响。
- `PreHookResult` 只表达拒绝结果，不携带替换参数。
- post_hook 不通过 `ToolCallContext` 获取结果；它只能通过第二个 `result` 参数读取 handler 原始字符串结果或普通 handler 异常转换出的标准化错误字符串。
- post_hook 不形成结果流水线；每个 post_hook 看到同一个原始结果，最后一个返回非空 `PostHookResult.result` 的 hook 决定最终文本。
- `ToolSignal` 是 AgentLoop 控制信号，合法中断型工具返回该信号时跳过 post_hook。
- `ToolDefinition.is_concurrency_safe` 是保守的显式白名单，默认必须为 `False`。AgentLoop 只并发执行连续、普通、无副作用且已标记安全的调用；handler、hook 与 output governance 可在最多 4 个 worker 中重叠，但 `save_tool_result` 和活动事件必须由调用线程按原工具调用顺序执行。
- 并发分区内失败不得级联到兄弟读取或后续串行分区；副作用工具失败仍按既有规则令后续调用写 `not_executed`。共享 SQLAlchemy Session、可变激活缓存、计数写入、进程状态、用户工具、组合工具、委派和文件/命令 mutation 在证明并加固线程安全前不得标记并发安全。

## Migrated Gate Ownership

- `builtin_general_tools.read_file`、`write_file`、`edit_file`、`list_dir`、`exec`、`apply_patch`、`search_files`、`search_content` 和 process lifecycle 工具的路径存在性、系统目录拒绝、命令安全分类和用户确认属于 pre_hook / 共享权限 helper。
- `edit_file` 的 `old_text` 查找与唯一性校验属于编辑执行准备，留在 handler。
- assistant 高危确认必须只展示和记录脱敏摘要：`write_file` 只含目标路径，`edit_file` 只含截断片段，`exec` 只含命令首行；不得记录完整文件内容、完整替换文本或多行命令体。
- assistant “全部允许/免确认”只允许是当前进程会话级内存状态，不得写入配置、SQLite 或 DuckDB；新对话入口必须复位该状态并收敛旧 pending 请求。
- **受控例外（033/034 调度中心，CC-005）**：调度中心 per-task 无人值守免确认（`scheduled_tasks.unattended_auto_approve`，持久化到 SQLite v30）是上条「免确认不得持久化」规则的**唯一显式受控破例**，由用户显式拍板。它必须满足四重限定——仅 `source='scheduled'` 会话生效 / 仅该 `scheduled_task_id` 且该 session 必须精确等于 `scheduled_tasks.session_id` 当前绑定（per-task 授权集经独立 `UnattendedConfirmationManager`，不碰进程级 `_auto_approve_enabled`；034 reset 后的旧 session 立即失权）/ 默认关闭 / 只能由用户显式 UI 操作（确认卡勾选或详情页 PATCH 开关）开启；scheduled 来源、task 归属与 current-session 绑定判定必须先于进程级「全部允许」，未授权或非 current 的 scheduled 会话不得被全局开关越权放行；`unattended_auto_approve` 不得作为创建/更新定时任务工具的参数（LLM 无法经工具调用自行开启），由三层静态门卫测试守住（schema properties / handler 源码 / router create-update 源码均不含该字段）。开启该例外的任务在调度中心列表层带醒目标记、详情页可显式开启或随时回收。
- 结构化多选澄清（`ask_user_question` / `clarification_manager`，019）必须与高危确认链路**完全分离**：独立 pending 表、独立信号、独立终态集，不复用确认的 `_pending_confirms`、审计日志或确认 Toast 生命周期；前端 ClarificationCard 不显示"全部允许"。澄清请求与未提交答案只允许驻留 sidecar 进程内存，不得新增 SQLite/DuckDB 表、迁移或配置项；超时/取消/停止/关闭一律 fail-closed 唤醒 worker，模型不得获得猜测答案；`assistant.clarification_resolved` 事件与普通 DTO 不得携带用户答案，问题/选项/预览不得含 secret。`ask_user_question` 仅主助理工具集注册，PM/Trial/specialist/subagent 不暴露。
- `recording_data_tools.query_data` 的 SQL 拒绝策略属于 pre_hook，但 handler 仍可再次调用 `rewrite(sql)` 生成实际执行 SQL。
- `recording_data_tools.analyze_image` 的单次最多 5 个 action_index 限制属于 pre_hook。
- `trial_tools.run_command` 的单次 `AgentLoop.run()` 调用上限属于 `create_trial_tools()` 内创建的 pre_hook 闭包。

## Agent Built-in Tool Boundaries

- 已升级的通用内置工具必须返回统一 JSON envelope（必含 `schemaVersion`、`tool`、`outcome`、`payload`、`createdAt`，按需含 `error`、`permission`、`limits`、`references`、`warnings`、`verification`）；AgentLoop 保存工具结果时必须经 output governance，畸形结果必须收敛为不含原文的 `handler_contract_violation`，并确保接受、拒绝、未知工具、handler 异常、跳过和 fallback 路径都只有一条配对 tool result。
- 文件读取只能返回有界文本窗口、行号/续读元数据、脱敏内容和 raw-byte baseline；二进制、媒体和解码失败不得把 raw bytes 写入 tool result、普通日志或 UI event。
- 已存在文件的 `write_file`、`edit_file`、`apply_patch` update/delete 必须提供当前 baseline；baseline 缺失或过期必须在落盘前拒绝。新文件创建可以没有 baseline，但仍受 workspace 写权限和确认约束。
- workspace 外读取只能作为高风险检查路径，经确认后短期放行；workspace 外写入、删除和 patch 仍一律 fail-closed。`exec` 只允许 workspace 内 cwd；命令参数中的显式 workspace 外目标属于高风险确认级，只有单次确认或当前进程会话级“全部允许”后才可执行；含独立 `..` 路径段的相对穿越始终 fail-closed，不得用 symlink 或 cwd 切换绕过。
- `search_files` / `search_content` 必须使用结构化遍历、默认忽略依赖/构建/缓存目录、稳定排序、有界分页和脱敏摘要；不要恢复通过 shell `find`/`grep` 解析结果的默认路径。
- `exec` 和 process lifecycle 工具只允许 workspace 内 cwd，并以解析后的 argv 直接启动子进程，runner 不使用 `shell=True`。换行、管道、重定向、命令连接符、反引号、含独立 `..` 路径段的相对穿越和内联解释器代码必须在执行前硬拒绝，当前进程会话级“全部允许”也不能覆盖；shell host、显式 workspace 外 executable 和 workspace 外路径参数必须经过高风险确认，确认后仍作为 argv 子进程直接启动。同步命令输出必须截断并脱敏，后台进程数、日志窗口和等待时间必须受统一配置上限约束；进程记录只在当前 sidecar 进程会话内有效，重启后的未知 `proc_*` 必须返回 unavailable 而不是尝试复用系统进程。
- 大输出原文只能由 `ToolOutputRepository` 管理的私有 blob + SQLite metadata 持久化；业务层不得直接写 tool-output SQL 或暴露 blob 路径。`load_tool_output` 必须按 owner session + workspace 授权、有界窗口读取、脱敏并处理 expired / missing blob；`tool_call_id` 只记录来源，不是授权因子。过期或软删除 blob 删除失败时必须保留可重试清理路径。
- 所有文本 tool result 都经过同一治理边界：小型 legacy/custom 结果保持原格式；原文达到阈值、handler 报告截断/裁剪、或已有 raw reference 时转 compact envelope。compact payload 的 `facts` 和 `preview` 是确定性权威信息；`semanticSummary` 永远是 `advisory=true` 的辅助信息，失败/超时/非法 JSON 时必须直接省略，不能覆盖 facts 或产生第二条 tool result。
- 语义摘要输入必须在 provider 调用前脱敏，并把工具输出声明为不可信数据；模型输出在解析后再次脱敏并受固定 schema/字符上限约束。超过输入上限的选择预算固定保留 head、错误/异常/warning 上下文、均匀采样和 tail；模型调用受总超时、map 数量、并发和 token 上限控制，不做业务重试。
- `extractionGoal` 只允许影响摘要 prompt，不得进入工具执行、权限分类或 handler 业务语义。支持该字段的 built-in schema 最大 1000 字；`web_fetch.prompt` 和 custom tool 常见 goal/query/prompt/pattern 参数只能做保守推导。
- raw output blob 当前不做应用层加密；本地桌面部署依赖应用数据目录访问控制，并在 POSIX 上 best-effort 设置私有文件权限。任何跨用户、远程或同步场景都必须先补充加密和密钥管理设计。
- 新增 tuning knob 走 `get_unified_config().get_agent_tools_*`。Settings UI 只开放 `agent_tools.output.semantic_summary.*` 的独立“工具输出”分区；file/search/process、artifact retention 和 visible cap 等工程限额仍不开放。
- 工具输出摘要使用独立的 `agent_tools.output.semantic_summary.api_key`，不得回退主模型密钥。该密钥与其他 secret 一样只能经 `UnifiedConfigManager` 读写：`config.json` 提供本地默认值，`app_settings` 可覆盖；Settings 保存/删除操作更新统一配置。OpenAI-compatible provider 必须配置 base URL；模型名为空、密钥缺失、endpoint 无效或开关关闭时无损降级为确定性摘要。

## Non-Migrated Boundaries

- `programmer_tools.syntax_check` 整个 handler 即校验本身，不迁移到 hook。
- `recording_data_tools.execute_code` 的受限 builtins、import 控制和超时属于执行内核，不迁移到 hook。
- `src/execution/tool_executor.py` 的 venv 隔离和命令白名单位于 handler 层之下，不迁移到 hook。
- `dynamic_tool_manager` 的发布状态、允许列表、技能发现和技能组合激活属于工具发现阶段，不迁移到 hook。
- 用户能力 FC schema 继续由 `get_tool_detail` 按需激活；`agent_tools.discovery.*` 控制的是 system prompt 中技能/组合摘要目录的 full/deferred 模式，不得把两者混为“全量 schema 注入”。主助理、临时子代理和固定专员必须先按各自授权范围过滤，再计算条目数/字符数阈值；deferred prompt 不得泄漏隐藏名称或描述。
- `search_tools` 是 deferred 目录的权威发现入口：空 query 可浏览，`kind/offset/limit` 提供稳定类型过滤和分页，返回 selector 供 `get_tool_detail` 使用。搜索与详情每次调用必须重校验发布状态、组合可用性、成员授权和白名单；Prompt 或旧激活缓存不得作为授权事实。
- `agent_tools.discovery.*` 通过 `get_unified_config().get_agent_tools_discovery_*` 读取，运行时覆盖影响后续 Prompt/搜索；与 file/search/process 工程限额一致，Settings UI 不暴露。

## Desktop Recording Boundaries

- UI 不直接实例化 `DesktopRecorder`，也不直接读写 Repository；桌面录制只能经 `DesktopRecordingService` / desktop API bridge 进入业务层。
- 桌面录制必须在主窗口完成 minimize 之后启动 hook，避免 UI 点击本身被写入 `desktop_actions`。
- `recording_data_tools` 根据 `RecordingRepository.get_recording_mode(recording_id)` 固定本次工具集 mode；浏览器 mode 只能访问浏览器录制表，桌面 mode 只能访问 `desktop_recordings` / `desktop_actions`，跨 mode 返回 `table_not_in_mode`。
- 浏览器 PM/Programmer/Trial 工具集保持 legacy 路径和 `analyze_image`；桌面 PM/Programmer/Trial 工具集注入桌面专属工具，且不得注入 `analyze_image`。
- `analyze_desktop_action` 只在 `recording.desktop.vision_model` 已配置时注入；缺失时自然降级为文本和结构化数据分析。
- 桌面 Programmer 输出代码先过 `ast.parse` syntax gate；连续重试失败通过 `desktop_syntax_gate_retry_failed` 和 agent error 终止，不进入 Trial 执行。
- 桌面 Trial 子进程由 `src/execution/desktop_trial_runner.py` 创建 `data/trials/<trial_id>/`、设置 cwd、应用 env 白名单、执行 120s 超时和 Windows `taskkill` 清理；business 层只负责编排调用和事件。
- 桌面录制跨模块通知只能走 `src/utils/events.py` blinker 事件；sidecar 只做事件流 adapter，不允许 recording / business / execution 层 import 前端、Tauri 或 legacy UI。
- 桌面 action 必须带 `monitor_index`；DPI awareness 在桌面 recorder/hook 启动前应用，失败只降级记录日志。

## Assistant Task Collaboration Boundaries

- Assistant 任务协作的业务事实源是 `assistant_tasks*` SQLite 表和 `src/business/task_collaboration/` services；`workflow_transitions` 只保留 Debug Inspector/audit breadcrumb，不得作为 task graph、看板、会议、Todo 或恢复语义的 UI/API 真相。
- desktop API router 只能调用 `TaskCollaborationService`、`TaskDispatcher`、`TaskAdjudicationService`、`TaskBoardService`、`TaskMeetingService`、`TaskTodoService` 等业务入口，不得直接访问 Assistant task repositories 或手写 SQL。
- Task 与 TaskAttempt 必须分离：Task 保存持久工作项六态；Attempt 保存 lease、heartbeat、checkpoint、fence token。崩溃恢复必须围栏过期 active attempt，缺安全 checkpoint 时交父侧裁定，不得自动重放未知副作用。
- 所有副作用步骤必须先写 `AssistantTaskOperation` stable operation key，再执行；成功后写 completion marker。`unsafe_to_retry` 或未知幂等性只能进入裁定，不能由 dispatcher 静默重试。
- 主 Assistant 是协调者，不得作为 user-work TaskAttempt executor。实际执行者只能是 `ephemeral_subagent` 或 `specialist`；PM / Programmer / Trial 不进入 assistant task 调度池。
- 停止和取消必须分开：stop 只作用于当前请求 graph，落 `suspended/user_stop` 且可 continue；cancel 是终态级联，旧 replan 或迟到结果不得复活已取消任务。
- 看板认领必须使用 Repository 条件更新和 task_version/claim lease 保障原子性；不得用前端状态或进程内锁单独判断“可认领”。
- 会议通道只传消息，不代理工具调用、不共享工具池、不扩大能力授权；超出轮次/时长预算或无法产出结论时关闭并回父侧裁定。
- agent-to-agent question/resource/capability route 可以持久化；上冒到用户的 pending clarification 和原始答案仍只能在 sidecar 进程内存中，失效后 Task 挂起 `waiting_user` 并重新发起澄清。
- Todo 是 Task + executor scoped 的私人 checklist；不得创建 Task edge、adjudication、board claim 或 brain memory entry，前端展示必须使用独立状态词，不与 Task status 混用。
- 新 task collaboration 前端事件只能通过 `src/desktop_api/ui_events.py` Registry 和 `ui_event_projector.py` 投影：`assistant.task_graph.changed`、`assistant.task_board.changed`、`assistant.task_question.changed`、`assistant.meeting.changed`、`assistant.todo.changed`。事件只作通知；缺口必须用 graph/board/meeting/todo typed API 拉权威快照。

## External Coding Session Boundaries

- 外部 coding session 的业务事实源是 `external_coding_*` SQLite 表、`ExternalCodingSessionRepository` 和 `ExternalCodingSessionService`；desktop API/router、task snapshot 和前端不得绕过 service 直接写 session、attempt、merge 或 rollback 状态。
- 外部 coding 的 11 个工具不得进入常规 delegated executor 工具集，也不得拆成逐工具白名单；它们只属于系统内置、只读、已发布的范围型技能组合“外部 Coding”。只有显式配置该组合的固定 executor specialist 在持久 Task（非空 `current_task_id`）中可先激活组合、再按需获得成员工具；主 Assistant、ephemeral、planner、同步 specialist、试用路径和未配置专员全部 fail-closed。
- 每个 session 必须绑定 owner（`task` 或 `workflow`）和 `codingSessionId`；不得启动无 owner 的外部 agent，也不得只靠本地进程 PID/日志推断业务完成。
- Headless 外部 CLI 默认先产出 `PLAN.md`，经派活 agent 调用 `decide_external_coding_plan` 批准后才进入实现；`PLAN.md` 语义校验是 advisory。Plan 阶段必须相对持久化的 worktree 创建基线检测 staged、unstaged、untracked 和 committed diff；缺基线时 fail-closed，不得进入 `plan_ready`。没有有效 `plan_approved_at` 时不得 resume 到 implement。
- `RESULT.md` 是完成信号之一，但不能替代后续 review/test/merge 判断；review 是强烈建议，不是强制门卫。独立 review/test 尚未完成时，session detail 和最终汇报必须显式保留 `reviewSkippedReason`，不得把外部 CLI 自报测试结果写成独立验证。
- quota observation 只能保存从 Claude `/usage` 或 Codex app-server 响应中归一化出的可用性、来源、置信度、使用率摘要和 reset 提示；原始响应必须在 execution adapter 内丢弃，不得保存订阅 token、账号、email、原始 CLI 输出或密钥路径。探测失败必须降级 `unknown`；Quota state 是调度参考，不是套餐余量的硬保证。
- CLI 命令摘要、attempt log tail、UI event payload 和 DTO 不得持久化完整 prompt、secret、token、raw stack trace 或未脱敏本地敏感路径；完整日志只能作为受控 artifact tail 暴露。
- 外部 coding worktree 必须隔离于目标 worktree；merge 前必须验证 coding 分支存在已提交变更，并分析目标 dirty files、分支 changed files 与 `git merge-tree` 冲突。执行 merge 前必须重验两端 HEAD；no-op、陈旧快照、未提交 coding diff 或 merge 中断必须 fail-closed 并留审计。非低风险 merge 必须有 agent decision 记录。外部 session 工具不得执行 push、reset --hard、clean 或删除目标分支。
- rollback 工具只对本 session 已记录的精确 merge commit 生成可解释 `revert_commit` 方案并要求确认；执行前必须验证目标 HEAD 与 merge 记录，禁止用 reset/hard reset/clean 改写或丢弃无关历史。
- `assistant.external_coding.changed` 只能作为刷新通知；前端必须通过 `/api/external-coding/*` typed API 拉权威详情，不得根据内部 blinker 事件或本地乐观状态推断终态。

## Self-Improvement Proposal Boundaries

- 改进提案的业务事实源是 `improvement_proposals` SQLite 表和 `ProposalService` / `ImprovementProposalRepository`；desktop API 只做 typed DTO、CAS approve/reject 和异步触发，不直接建 worktree、写 task graph 或改 proposal 结果。
- 执行复盘只生成 pending proposal；审批前不得建 worktree、分支、task graph 或执行代码。`approve` 成功后才允许 `proposal_bridge` 创建 `.worktrees/improvement/<proposal_id>` 和 `improvement/<proposal_id>` 分支。
- proposal 自动实施必须通过 `TaskCollaborationService.build_task_graph` 创建 planner → implementer → test DAG；不得绕过 task collaboration 直接启动 AgentLoop 或同步嵌套子代理。bridge 只使用 synthetic `self_improvement:<proposal_id>` session。
- self-improvement 图没有真实父助理裁定者；`TaskCollaborationBackgroundWorker` 的 proposal recovery job 必须负责 scheduler 补踢、pending adjudication 自动决策和 `done/failed` 写回，避免 proposal 永久卡在 `approved` 或 `in_progress`。
- proposal executor 的 mutation 权限必须由内建工具共享权限层硬挡：只允许隔离 worktree 内源码、测试或文档文件；拒绝 `src/business/self_improvement/`、`src/business/orchestration/agent/`、`src/business/task_collaboration/`、`src/desktop_api/`、`src-tauri/`、guardrail tests、legacy/startup 入口、本地 config/env、数据库、依赖目录、缓存和生成产物。
- proposal executor 的 `exec` 只能用于测试、lint、format check 或 typecheck；网络访问、依赖安装、破坏性 git、merge/rebase/reset/clean/push 等命令必须 fail-closed。软 prompt 说明不能替代这个硬门卫。
- failed proposal 被用户 reject 时必须清理 worktree/分支并清空 stale worktree metadata；done/failed/rejected worktree 保留数量只能经 `get_unified_config().get_self_improvement_proposals_worktree_retention_max()` 控制。
- 前端只能通过 `frontend/src/api/improvementProposal.ts` 和 `brainStore` 管理提案；不得根据 task graph、内部 blinker 事件名或本地乐观状态推断 proposal 终态。`backend.resync_required` 的 brain domain 刷新必须重拉 execution reviews 与 improvement proposals。

## User Todo Boundaries

- 用户个人待办的业务事实源是 `user_todos` SQLite 表和 `src/business/user_todos/UserTodoService`；desktop API router 只调用 service，不直接访问 `UserTodoRepository` 或手写 SQL。
- 用户个人待办与 assistant task collaboration 的 executor 私人 Todo 严格隔离：`user_todos.status` 使用 `pending / in_progress / done`，`assistant_todo_items.status` 使用 `todo / doing / done / skipped`；不得复用表、DTO、UI store、事件或状态词。
- `/api/user-todos` 是唯一用户界面入口；前端只通过 `frontend/src/api/userTodos.ts` 和 `userTodoStore` 访问，不从 task graph、Debug transition 或本地缓存推断用户待办事实。
- AI 对话管理用户个人待办必须通过主助理委派临时执行体完成；user_todo 写工具只进入 delegated executor 工具集，不进入主助理、planner、PM、Programmer 或 Trial 工具集。
- 用户待办 V1 不新增公开 UI event；如果后续需要跨窗口或实时推送，必须先在 `src/desktop_api/ui_events.py` 注册 typed event 并补 payload allowlist。
- 删除用户个人待办是物理删除；不要套用 Brain 的 soft-delete/invalidation 规则，也不要把删除动作写入 brain memory。

## Tauri / Frontend / Sidecar Boundaries

- `frontend/` 只能通过 typed API client、Tauri window command 或前端本地状态访问产品能力；不得 import Python 业务代码、读取 SQLite/DuckDB/config，或持久化 secret。
- `src/desktop_api/` 是 UI adapter，只能调用 business services、orchestrator、configuration facade 和事件 adapter；不得成为新的 Repository 层或绕过业务服务写数据。
- 前端事件流只能消费 `src/desktop_api/ui_events.py` 注册的公共 UI event type；React store 不得依赖内部 blinker 事件名、`payload.sourceEvent` 或未知事件默认转发来决定展示状态。
- `src/desktop_api/events.py` 的事件发布必须经过 UI Event Registry、envelope creation 和 payload safety validation；不得新增绕过 `event_queue.publish_nowait()` / projection layer 的直接 SSE 输出路径。
- UI event payload 必须是 allowlist 字段；runtime token、secret、完整代码、完整命令体、未脱敏 stack trace、本地数据库路径、raw query result 和未过滤录制数据不得进入公共 UI event。**例外**：`assistant.activity` 的 `text` 是过程时间线原文（单用户本地、原文本就明文存于 messages 表），命中敏感规则时保留原文并置 `redacted=true`，UI 默认隐藏、用户双击查看；该字段经 `UiEventDefinition.unredacted_payload_keys` 豁免 payload safety value 校验，事件内其余字段及其它事件仍走脱敏。
- event stream 是当前桌面进程会话内通知通道，不是持久业务事实或长期 replay log；重连缺口必须通过 `backend.resync_required` 触发权威快照刷新。
- sidecar API 只允许 localhost/loopback 使用，每次启动必须要求运行期 session token；token 不得写入配置、OpenAPI、日志、前端持久化存储或错误响应。
- 设置页所有值必须经 `get_unified_config()` / `UnifiedConfigManager` 读写；secret 的写入、清除和 API 测试也走同一入口，返回给前端的状态只能是存在性和 masked display。
- React store 可以保存 draft、dirty state、当前 section、事件流状态和 masked secret 状态；不得保存 plaintext API key 或任何长期信任开关。
- `src/main.py`、`mexemplar_gui.py`、`start.bat`、`mexemplar_gui.bat` 只能显式失败并提示 legacy PyQt launcher 已退休；不得恢复可启动 PyQt fallback。
- `src/ui/`、`tests/ui/` 和旧 Python GUI `tests/e2e/` 不再是维护面；新增 UI 行为覆盖应放在 `frontend/tests/unit/` 或 `frontend/tests/e2e/`，后端桥接覆盖放在 `tests/desktop_api/`、`tests/integration/` 或 `tests/guardrails/`。

## Debug Inspector Boundaries

- `/debug` 是隐藏诊断路由，不出现在普通导航；只能通过 typed debug API client 调 authenticated `/api/debug`。
- `debug.trace.enabled` 只能由 DebugInspectorService 以 runtime 配置 arm，不能写入数据库、配置文件或前端持久化存储。
- Raw LLM trace 与 Assistant delegated task/result ephemeral detail 只存在于当前 sidecar 进程内的 epoch buffer；disable、clear、restart 必须销毁它们，mid-flight stale completion 不得回填旧 epoch。
- Flow 中的既有 `workflow_transitions` 是按业务生命周期保留的持久状态事实，不会因 debug clear/disable 删除；reference content 是鉴权后的按需、`no-store` 响应，不写入 debug buffer。离开 `/debug` 只清理前端内存中的 raw 响应状态。
- Raw debug endpoints 必须返回 `Cache-Control: no-store`；URL、ordinary UI event payload、localStorage/sessionStorage/indexedDB、普通日志不得出现 diagnostic-only prompt、trace、handoff、media、correlation 或 credential 字段。
- 模型 text/tool/vision 调用必须走 fail-isolated observation boundary；诊断采集失败不得改变 provider 成功/失败语义。Vision 只保留媒体元数据，不保留 base64/data URL/raw bytes。
- Embedding/vectorization 不生成 LLMTraceRecord，但 credential/callsite 必须登记在 provider/redaction inventory；新增 `LangChainLLMClient(`、`OpenAIEmbeddings(`、`.invoke(`、`embed_query(` 或 credential getter callsite 必须同步 inventory 和 guard tests。
- Assistant delegated task/result 只能作为 trace-gated ephemeral debug detail 暂存，不得持久化到 workflow transition payload、UI event 或普通日志。

## Assistant Failure Recovery Boundaries

- Assistant 终止性失败必须经 `AssistantFailureService` 和 `AssistantRunFailureRepository` 持久化；router、React store 和 `AssistantRuntime` 不得直接写 `assistant_run_failures`。
- 当前失败状态机固定为 `failed → retrying → resolved|failed`。开始重试必须使用原子条件更新拒绝并发重复请求；sidecar 启动必须把遗留 `retrying` 恢复为 `failed`。
- 失败分类器可以内部读取异常链、状态码和异常类型，但普通日志、DTO、`assistant.message` 与 `assistant.progress` 只能包含安全分类和友好文案。原始响应体、endpoint、API key、异常正文、stack trace 和 provider request detail 不得进入这些边界。
- `assistant.message.failure` 只允许 `category / message / suggestion / attemptCount / failedAt`。内部状态码和异常类型只能留在持久化诊断记录或受控 Debug Inspector 路径。
- 终止失败必须先持久化失败记录并发布本回合消息，再发布 `assistant.progress(status=failed)`；普通运行失败不得同时写入前端全局 `lastError` 或发布 `assistant.error` 造成重复 Toast。
- 原样重试必须从后端按 `messageSequence` 读取原用户消息；编辑后重试必须创建新用户回合且不得修改原消息。非当前失败返回冲突，空编辑内容拒绝，手动次数不限。
- 成功重试或新的普通消息必须解决旧失败；编辑后重试再次失败时，新失败只能挂到新用户消息。前端卡片移除和迁移以消息 API / typed event 为准，不得根据本地 progress 自行推测。
- 现有 provider 自动重试策略保持不变；失败恢复不得引入备用模型切换或新的 secret/config 路径。

## Real Grand Tour Boundaries

- 默认 `npm run test:e2e` 必须保持 mock-backed、cost-free、无 live capture；真实验收只走独立 `npm run test:e2e:grand-tour`。
- 独立 Real Grand Tour 命令内置启用 real-tour runtime 和 live capture；执行时只能按 `docs/local/real-grand-tour-safe-journey.md` 的固定无敏感 fixture/script 执行，不再要求 shell opt-in 环境变量。
- Real-tour credential 必须通过 `UnifiedConfigManager` 的普通只读 getter 获取；不得创建独立凭据解析、迁移或写入路径。
- Real-tour provider inventory 必须覆盖 main、vision、background brain、settings validation、skill-composition、compression、embedding 和 diagnostic redactor；未覆盖路径必须在场景前显式 skip 或 fail as unmet prerequisite。
- Real-tour runtime 使用随机 localhost port/token、临时 `EXEMPLAR_DATA_DIR`、paid-call/time budget、public event watcher 和 sanitized summary report。报告和 Playwright artifacts 不得包含 prompt/response、credential、runtime token、raw media、截图、录制正文或完整敏感本地路径；trace/video/screenshot 默认 off。

## Brain Architecture Constraints

- 大脑相关 `brain.*` 配置占位符（decay 曲线阈值、top-N、重试次数、worker 周期等）通过 `get_unified_config()` 读写，数值为占位符（CC-008），待实测调整后再写入 docs。
- Settings UI 暂不暴露 `brain.*` tuning knobs；如需在 UI 可调，须先更新 `docs/PROJECT_CONSTRAINTS.md` 和 `frontend/AGENTS.md` 说明暴露字段。
- Segment 沉淀写入全部 `brain_memory_entries` INSERT 和 Segment 状态转换必须在单个数据库事务内提交；崩溃发生在 commit 前 → 整体回滚，不残留半成品条目。
- 大脑数据不物理删除，`invalidation` 是降权，`soft-deleted` 物理保留但排除在普通检索外。
- 专员管理删除是业务层软删除（`brain_specialists.is_active = 0`），版本历史必须保留；不要从 API/router 走物理删除路径。
- 专员技能组合配置必须走 `SpecialistService`，只接受已发布、非待复核且 assistant-enabled 的组合；`composition_ids` 必须同时写入 `brain_specialists` 与 `brain_specialist_versions`（SQLite v29）。前端勾选组合不得复制成员 ID 到 `tool_whitelist`，运行时也不得把目录快照当授权事实。
- `brain_segments` 表的 `open` 态不持久化——进行中 Segment 由消息表推导，行仅在封存（转入 `pending`）时创建。

## Skill Methodology Constraints

- 方法论资产属于 Brain Service 数据安全边界：`brain_skills` 不物理删除，软删除只写 `status = soft_deleted`；`brain_skill_equipment` 与方法论本体同等保护，卸下、强制裁剪、supersede 转移都只写 `status = unequipped` 与 `unequipped_reason`。
- 所有方法论写入走 `SkillService` / `SkillEquipmentService` / `SkillBootstrapService` 与对应 Repository；desktop API 只做 DTO 和错误映射，不直接写 SQLite。
- `brain.skill.token_budget.warn_threshold`、`brain.skill.token_budget.danger_threshold`、`brain.skill.seed_file_path` 通过 `get_unified_config()` 读取；前端 token 计量条只消费 API DTO 下发阈值，不内置 4096/8192 常量。
- UI 术语中旧录制/列表/组合能力统一称 Tool；旧 UI 事件 `skills.*` 直接改为 `tools.*`，无双发窗口。`skill.*` 事件名只保留给方法论资产。
- 装备者 system prompt 只能注入方法论轻量清单（id、name、description、trigger_conditions），不得注入 `body_markdown`；正文只能由 `load_skill_methodology` 工具 result 以 SKILL.md 形态进入 messages。
- assistant 派活决策路径不得读取方法论清单、正文或 trigger_conditions；specialist 派活时冻结装备清单，本轮 `load_skill_methodology` 鉴权只看该快照，装备改动最快下一轮生效。

## Review Guardrails

Reviewer 必须拒绝下列改动：

- 在 pre_hook 中加入参数改写或参数流水线语义。
- 在 `ToolCallContext` 中加入确认回调、结果字段或可写参数引用。
- 在 handler 中保留已经迁移到 pre_hook 的拒绝、确认、限流或安全策略分支。
- 让已升级内置工具返回旧的纯文本成功/失败形态，或绕过 AgentLoop output governance 直接保存工具结果。
- 在业务层、desktop API、前端或 Tauri 层直接管理内置工具执行状态、后台进程 registry、tool-output SQL 或私有 blob 路径。
- 让既有文件写入/编辑/patch 在缺少当前 baseline 时落盘，或允许 workspace 外写入、删除、patch；让 `exec` 在 workspace 外 cwd 运行、未经确认使用 shell host/显式 workspace 外目标，或让自动放行覆盖控制语法、内联代码与 `..` 路径穿越硬门卫。
- 将 assistant 高危确认改回模态阻塞确认，或让普通 Toast 与高危确认浮层复用同一个生命周期引用。
- 让 Assistant 终止失败只存在于乐观前端消息、绕过 Repository 状态机重试，或把原始 provider 错误暴露到普通聊天 DTO、UI event、Toast 或日志。
- 将自动放行状态持久化，或把未脱敏的文件内容、替换文本、命令体写入确认日志。
- 让 AgentLoop 内建注入的 `load_reference` 进入 tool/global hook 链，或以任何形式恢复已移除的 `talk_to_user` 注入（主助理回复只走 `reply_to_user`）。
- 绕过 `src/recording/filtering/` 的 SQL 改写或 DuckDB 代理边界读取录制网络数据。
- 让桌面录制 UI 直接访问 Repository 或 Recorder，或绕过 `DesktopRecordingService`。
- 在桌面 mode 中注入 `analyze_image`，或允许桌面工具读取浏览器录制表。
- 让桌面 Trial 继承完整父进程环境、在任意 cwd 执行，或缺少超时清理。
- 让前端、Tauri 命令或 desktop API 直接读取/写入 SQLite、DuckDB 或 config 文件。
- 让改进提案审批前创建 worktree/task graph/代码副作用，或让 approve router 直接实施而不是异步调用 `proposal_bridge`。
- 让 self-improvement proposal executor 绕过隔离 worktree、修改 `self_improvement` / `orchestration/agent` / `task_collaboration` / `desktop_api` / `src-tauri` / guardrail tests / startup 核心路径，或执行网络、安装、merge/rebase/reset/clean/push 等非测试型命令。
- 让外部 coding session 无 owner 启动、跳过 PLAN.md 审核直接实现、在 plan 阶段修改目标代码仍标记 plan_ready、把完整 prompt/secret 写入命令摘要或 UI event、未做 dirty/changed overlap 分析就自动 merge，或允许外部 session 工具 push/reset --hard/clean/删除目标分支；以及把 11 个外部 Coding 工具无条件注入、逐项加入专员白名单，或让非正式 Task/非 executor 专员激活系统内置组合。
- 重新引入 PyQt runtime 依赖、`src.ui` 生产代码、旧 Python GUI E2E，或任何正常用户可触达的 PyQt 启动路径。
