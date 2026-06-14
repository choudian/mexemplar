# Exemplar Project Constraints

本文件记录开发约束、反模式和允许例外。长期治理原则仍以 `.specify/memory/constitution.md` 为准。

## Agent Tool Hook Boundaries

- pre_hook 只允许放行、拒绝和观测，不允许改写 handler 入参。
- `ToolCallContext.args` 必须是递归只读隔离视图；顶层和嵌套 dict/list 写入都应抛异常，handler 入参不受影响。
- `PreHookResult` 只表达拒绝结果，不携带替换参数。
- post_hook 不通过 `ToolCallContext` 获取结果；它只能通过第二个 `result` 参数读取 handler 原始字符串结果或普通 handler 异常转换出的标准化错误字符串。
- post_hook 不形成结果流水线；每个 post_hook 看到同一个原始结果，最后一个返回非空 `PostHookResult.result` 的 hook 决定最终文本。
- `ToolSignal` 是 AgentLoop 控制信号，合法中断型工具返回该信号时跳过 post_hook。

## Migrated Gate Ownership

- `builtin_general_tools.read_file`、`write_file`、`edit_file`、`list_dir`、`exec`、`apply_patch`、`search_files`、`search_content` 和 process lifecycle 工具的路径存在性、系统目录拒绝、命令安全分类和用户确认属于 pre_hook / 共享权限 helper。
- `edit_file` 的 `old_text` 查找与唯一性校验属于编辑执行准备，留在 handler。
- assistant 高危确认必须只展示和记录脱敏摘要：`write_file` 只含目标路径，`edit_file` 只含截断片段，`exec` 只含命令首行；不得记录完整文件内容、完整替换文本或多行命令体。
- assistant “全部允许/免确认”只允许是当前进程会话级内存状态，不得写入配置、keyring、SQLite 或 DuckDB；新对话入口必须复位该状态并收敛旧 pending 请求。
- `recording_data_tools.query_data` 的 SQL 拒绝策略属于 pre_hook，但 handler 仍可再次调用 `rewrite(sql)` 生成实际执行 SQL。
- `recording_data_tools.analyze_image` 的单次最多 5 个 action_index 限制属于 pre_hook。
- `trial_tools.run_command` 的单次 `AgentLoop.run()` 调用上限属于 `create_trial_tools()` 内创建的 pre_hook 闭包。

## Agent Built-in Tool Boundaries

- 已升级的通用内置工具必须返回统一 JSON envelope（必含 `schemaVersion`、`tool`、`outcome`、`payload`、`createdAt`，按需含 `error`、`permission`、`limits`、`references`、`warnings`、`verification`）；AgentLoop 保存工具结果时必须经 output governance，畸形结果必须收敛为不含原文的 `handler_contract_violation`，并确保接受、拒绝、未知工具、handler 异常、跳过和 fallback 路径都只有一条配对 tool result。
- 文件读取只能返回有界文本窗口、行号/续读元数据、脱敏内容和 raw-byte baseline；二进制、媒体和解码失败不得把 raw bytes 写入 tool result、普通日志或 UI event。
- 已存在文件的 `write_file`、`edit_file`、`apply_patch` update/delete 必须提供当前 baseline；baseline 缺失或过期必须在落盘前拒绝。新文件创建可以没有 baseline，但仍受 workspace 写权限和确认约束。
- workspace 外读取只能作为高风险检查路径，经确认后短期放行；workspace 外写入、删除、patch 和命令执行一律 fail-closed，不得用相对路径、symlink 或 cwd 切换绕过。
- `search_files` / `search_content` 必须使用结构化遍历、默认忽略依赖/构建/缓存目录、稳定排序、有界分页和脱敏摘要；不要恢复通过 shell `find`/`grep` 解析结果的默认路径。
- `exec` 和 process lifecycle 工具只允许 workspace 内 cwd，并以解析后的 argv 直接启动子进程，不通过 shell；换行、管道、重定向、命令连接符、shell host、内联解释器代码、显式 workspace 外 executable 和 workspace 外路径参数必须在执行前拒绝。当前 Python runtime 的绝对 executable 是测试/运行脚本所需的受控例外。同步命令输出必须截断并脱敏，后台进程数、日志窗口和等待时间必须受统一配置上限约束；进程记录只在当前 sidecar 进程会话内有效，重启后的未知 `proc_*` 必须返回 unavailable 而不是尝试复用系统进程。
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
- 让既有文件写入/编辑/patch 在缺少当前 baseline 时落盘，或允许 workspace 外写入、删除、patch、执行命令。
- 将 assistant 高危确认改回模态阻塞确认，或让普通 Toast 与高危确认浮层复用同一个生命周期引用。
- 将自动放行状态持久化，或把未脱敏的文件内容、替换文本、命令体写入确认日志。
- 让 AgentLoop 内建注入的 `load_reference` 或 `talk_to_user` 进入 tool/global hook 链。
- 绕过 `src/recording/filtering/` 的 SQL 改写或 DuckDB 代理边界读取录制网络数据。
- 让桌面录制 UI 直接访问 Repository 或 Recorder，或绕过 `DesktopRecordingService`。
- 在桌面 mode 中注入 `analyze_image`，或允许桌面工具读取浏览器录制表。
- 让桌面 Trial 继承完整父进程环境、在任意 cwd 执行，或缺少超时清理。
- 让前端、Tauri 命令或 desktop API 直接读取/写入 SQLite、DuckDB 或 config 文件。
- 重新引入 PyQt runtime 依赖、`src.ui` 生产代码、旧 Python GUI E2E，或任何正常用户可触达的 PyQt 启动路径。
