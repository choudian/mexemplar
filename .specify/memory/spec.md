# Main Specification Memory

**Purpose**: Consolidated requirements from all merged features. Single source of truth for what the system does.
**Last Updated**: 2026-07-20
**Revision**: 2026-07-20 — Archived feature 033 (Scheduling Center / 调度中心)

---

## User Scenarios

### US-001: Agent 在 query_data 中识别大字段 (Priority: P1)

Agent 在分析录制数据时，通过 query_data 查询到包含超大文本字段的记录。系统返回结构化占位对象，明确告知 Agent 字段大小、预览片段和继续读取方式，取代旧的 12KB 无差别截断。 [Source: specs/001-recording-field-layering]

### US-002: Agent 分段读取大字段内容 (Priority: P1)

Agent 使用 `read_field_chunk` 工具，按 locator + field + offset + 可选 length 读取单段原文。每次返回不超过 `max_chunk_chars`（默认 1000 字符）。 [Source: specs/001-recording-field-layering]

### US-003: Agent 逐段查看完整字段 (Priority: P2)

Agent 通过多次分段读取逐步拿到完整原始值。支持任意 offset 跳转、EOF 明确标识、Unicode 码点正确切片。 [Source: specs/001-recording-field-layering]

### US-004: 与现有数据发现和查询工具透明集成 (Priority: P2)

Agent 沿用 describe_data → query_data → read_field_chunk 工作流。describe_data 标注大字段提示；query_data 对大字段做占位替换；read_field_chunk 按需分段读取。文档和 prompt 统一为 5 工具模型。 [Source: specs/001-recording-field-layering]

### US-005: 多工具调用完整配对 (Priority: P1)

模型在同一轮响应中返回多个普通工具调用时，AgentLoop 按返回顺序逐个执行并记录结果，确保下一轮模型请求前所有工具调用均有配对结果。 [Source: specs/003-fix-agentloop-tool-calls]

### US-006: 中断型工具行为可预期 (Priority: P1)

中断型工具单独出现时保留既有暂停/完成语义；与任何其他工具同轮出现时判定为模型输出错误，不执行任何 handler 并写入配对错误结果。 [Source: specs/003-fix-agentloop-tool-calls]

### US-007: 会话恢复不重复或遗漏工具 (Priority: P2)

Agent 中断或重启后，系统恢复时识别同轮模型响应中哪些工具调用已有结果、哪些仍缺结果，只补齐缺失结果且不重复已完成调用。 [Source: specs/003-fix-agentloop-tool-calls]

### US-008: 工具执行管线支持统一 Pre/Post Hook (Priority: P1)

Agent 框架维护者可以在任意调用方传入或动态构建的 `ToolDefinition` 工具前后挂载同步 pre/post hook；没有声明 hook 的工具保持透明兼容。 [Source: specs/002-tool-hook-system]

### US-009: 门卫式安全校验迁移到 pre_hook (Priority: P2)

`builtin_general_tools`、`recording_data_tools`、`trial_tools` 中可复用的拒绝、确认、安全策略和限流 gate 统一迁移到 pre_hook；handler 保留执行准备与结果转换。 [Source: specs/002-tool-hook-system]

### US-010: AgentConfig 级全局 Hook (Priority: P3)

当前 `AgentConfig` 可以挂载 `global_pre_hooks` / `global_post_hooks`，对该配置实例下所有参与 hook 管线的 `ToolDefinition` 工具生效。 [Source: specs/002-tool-hook-system]

### US-011: 长会话压缩后 Agent 不再崩溃 (Priority: P1)

用户与 assistant 进行长时间对话涉及大量工具调用，当会话消息数达到压缩阈值时，系统自动触发上下文压缩。压缩完成后 Agent 能继续正常工作，不再出现 400 错误导致会话不可恢复。 [Source: specs/005-fix-compression-tool-pairing]

### US-012: 多次压缩不累积残留 (Priority: P2)

会话经历多次上下文压缩时，前一次压缩时被保留的边界 tool 组在第二次压缩时若已完全落在压缩区内部，会被正常压缩掉，不会无限累积。 [Source: specs/005-fix-compression-tool-pairing]

### US-013: 压缩后"继续"能正常恢复 (Priority: P3)

当因边缘 case 导致孤立 tool result 残留时，用户点击"继续"恢复会话，系统能自动检测并清理孤立消息，会话能正常运行。 [Source: specs/005-fix-compression-tool-pairing]

### US-014: 单次确认改为非阻塞浮层 (Priority: P1)

Assistant Agent 触发高危工具时，主窗口右下角出现非阻塞浮层，显示工具名与关键参数摘要，提供"全部允许 / 同意 / 拒绝"三按钮。用户可正常浏览聊天记录、滚动页面、打开侧边栏。 [Source: specs/004-auth-toast]

### US-015: 会话级"全部允许"快捷通道 (Priority: P2)

浮层"全部允许"按钮一键开启会话级豁免：本次会话内后续所有 Assistant 高危工具请求自动放行。新建对话时自动复位。 [Source: specs/004-auth-toast]

### US-016: 顶栏 Toggle 与浮层状态双向同步 (Priority: P3)

对话窗口顶栏提供"免确认" Toggle，与浮层"全部允许"共享同一会话级状态，任一入口变化后另一处可视状态立刻同步。新对话时一并复位。 [Source: specs/004-auth-toast]

### US-017: AI 回复消息以富文本展示 Markdown (Priority: P1)

AI 回复包含标题、列表、代码块、加粗、链接、图片、表格等 Markdown 元素时，聊天气泡将 AI 回复渲染为富文本结构。用户消息保持纯文本。Markdown 链接/图片不触发外部导航。 [Source: specs/006-chat-ui-polish]

### US-018: 压缩后的旧聊天记录仍可回看 (Priority: P2)

长会话触发上下文压缩后，被归档的早期用户消息与助手回复仍按原时间顺序出现在同一聊天时间线中。不显示归档/压缩分区标签。工具调用/结果/压缩摘要不作为普通聊天记录展示。初始展示最近 10 条，滚动向上分页加载。 [Source: specs/006-chat-ui-polish]

### US-019: 新对话/欢迎界面不展示"免确认"Toggle (Priority: P3)

"免确认" Toggle 仅在当前对话已启动过 Agent 会话后可见。欢迎界面、新对话起始态、清空后的会话不展示。 [Source: specs/006-chat-ui-polish]

### US-020: 录制桌面操作并产出可分析数据 (Priority: P1)

用户在录制页选择桌面模式后，应用最小化主窗并在 minimize 完成后启动全局键鼠 hook、UIA 查询、剪贴板订阅和帧缓冲。停止录制后主窗恢复，sanity check 对话框展示健康统计，用户可继续进入 intent 分析。 [Source: specs/007-desktop-recording]

### US-021: Agent 使用桌面录制数据生成方案 (Priority: P1)

PM / Programmer / Trial 在桌面 mode 下使用 5 个通用录制数据工具的 mode dispatch 和 3 个桌面专属工具分析 `desktop_recordings` / `desktop_actions`，同时浏览器路径工具和 prompt 保持不退化。 [Source: specs/007-desktop-recording]

### US-022: 桌面 Programmer 代码进入隔离 Trial 子进程 (Priority: P2)

Programmer 输出的 `async def execute() -> dict` 先经过 `ast.parse` syntax gate 和最多 2 次自动反馈重试，再由 execution 层子进程在 `data/trials/<trial_id>/` 隔离 cwd、env 白名单和 120s 超时兜底下试用执行。 [Source: specs/007-desktop-recording]

### US-023: 桌面录制健康反馈与早期止损 (Priority: P3)

录制停止后，用户通过 sanity check 颜色、动作总数、UIA 命中率、clip 成功率和三按钮状态机决定继续分析、放弃录制或重新录制；`vision_model` 缺失时以设置区说明和一次性 toast 透明提示降级。 [Source: specs/007-desktop-recording]

### US-024: 使用重新设计的桌面应用壳 (Priority: P1)

用户启动打包后的桌面应用后，进入 Tauri + React 应用壳，使用同一个窗口内的持久导航栏访问 AI Assistant、技能教学、技能列表、技能组合和设置；红/黄/绿自定义窗口控件执行真实关闭、最小化、最大化/还原动作。 [Source: specs/008-ui-stack-redesign]

### US-025: 在重新设计的 AI Assistant 中工作 (Priority: P1)

用户可以创建、选择、搜索、重命名和删除对话，发送消息，查看连续聊天时间线、安全 Markdown 回复、紧凑执行摘要和非模态高危确认；旧消息仍以普通聊天历史呈现，不暴露归档/压缩术语。 [Source: specs/008-ui-stack-redesign]

### US-026: 在重新设计流程中教学技能 (Priority: P1)

用户在技能教学页选择 Browser Recording、Extension Recording 或 Desktop Recording，经过准备检查、录制、意图确认、学习和试用验证等可见阶段；桌面录制保留 minimize 后启动 hook、健康检查和三按钮决策语义。 [Source: specs/008-ui-stack-redesign]

### US-027: 管理技能和技能组合 (Priority: P1)

用户可以查看待验证、已发布和失败技能分类并执行对应操作；也可以创建范围型或顺序型技能组合，选择已发布成员、调整顺序、填写适用场景、试用并发布，成员变化时已发布组合会进入需复核状态。 [Source: specs/008-ui-stack-redesign]

### US-028: 在重新设计设置中配置应用 (Priority: P1)

用户可以在设置页查看和更新 AI、录制、数据和产品信息；所有配置和密钥通过统一配置入口保存，密钥只以遮罩状态展示，设计中可见的操作按钮必须执行真实支持流程或返回真实业务错误。 [Source: specs/008-ui-stack-redesign]

---

## Functional Requirements

### 录制数据大字段按需读取 [Source: specs/001-recording-field-layering]

- **FR-001**: describe_data 基于当前源表 schema 与内置 `StableLocatorRule`，自动标注哪些文本字段在值达到阈值时会进入"大字段占位 + 分段读取"工作流；v1 至少覆盖 `network_requests.response_body`、`actions.dom_tree_snapshot`、`sibling_snapshots.siblings`
- **FR-002**: query_data 对任意文本字段值达到阈值的结果列，返回结构化占位信息；取代原 `_MAX_QUERY_CELL_CHARS = 12_000` 的无差别截断；一旦达到阈值不因"原文 JSON 恰好更短"而豁免
- **FR-003**: 占位信息包含 `__large_field__`、`field`、`size_chars`、`preview`（≤ `preview_chars`）、`locator`、`read_hint`（固定 `read_field_chunk`）
- **FR-003a**: 无法继续读取时占位信息包含 `read_blocked_reason`（稳定枚举：`missing_locator_field` / `computed_or_aggregated_column` / `ambiguous_locator_source` / `unsupported_source_table`）及可选 `read_blocked_message`
- **FR-004**: `read_field_chunk` 接收 locator + field + offset + 可选 length；offset/length 按 Python `str` Unicode 码点计数；缺省 length 取 `max_chunk_chars`
- **FR-005**: `read_field_chunk` 返回固定结构：`content`、`field`、`locator`、`offset`、`returned_length`、`total_length`、`has_more`、`next_offset`、`error`；成功时 `error=null`，失败时 `error={code, message}`
- **FR-006**: 大字段"完整访问"通过多次分段读取实现，不要求一次性返回全文
- **FR-007**: 单次 content 长度限制在 `max_chunk_chars` 内，通过 `returned_length` / `next_offset` / `has_more` 如实告知实际返回范围
- **FR-008**: offset 到达或超过字段结尾时返回空成功响应：`content=""`, `returned_length=0`, `has_more=false`, `next_offset=null`
- **FR-009**: 非法参数、定位失败、字段不存在等错误按固定结构返回 `error.code` 枚举（9 种：`invalid_offset` / `invalid_length` / `unknown_table` / `field_not_found` / `non_text_field` / `unknown_id_field` / `record_unavailable` / `unsupported_continuation` / `internal_error`）
- **FR-010**: 未超过阈值的小字段保持原有行为，直接返回完整内容
- **FR-011**: 阈值、预览长度、单次分段上限通过统一配置管理（`recording.large_field.*`），支持运行时调整；配置变更仅影响后续阈值/预览/chunk 大小，不使既有 locator 失效
- **FR-011a**: `preview_chars` / `max_chunk_chars` 为硬上限，默认均 1000 字符；元数据为固定小结构；不设独立 JSON 预算验收线
- **FR-012**: describe_data 用机器可读字段表达大字段提示：`large_field=true`、`read_via="read_field_chunk"`、`locator_fields=[...]`
- **FR-013**: query_data 占位替换不破坏行列结构，其余正常字段保持原样
- **FR-014**: 缺少稳定定位字段时占位提示 Agent 先补查（`read_blocked_reason="missing_locator_field"`）
- **FR-015**: 续读支持判定：直接源字段选择 + 源表由 StableLocatorRule 覆盖 + 同行保留稳定定位字段；聚合/计算/歧义来源仍触发占位但 `locator=null`
- **FR-016**: 所有活文档、prompt、配置注释更新为 5 工具模型；最小清单：`docs/ARCHITECTURE.md`、`docs/design/pm_agent_design.md`、`docs/design/programmer_agent_design.md`、`docs/design/recording_tools_redesign_todo.md`、`config.example.comments.md`、`src/business/agents/prompts/pm_prompt.py`、`src/business/agents/prompts/programmer_prompt.py`

### AgentLoop 多工具调用结果配对 [Source: specs/003-fix-agentloop-tool-calls]

- **FR-017**: 系统必须支持单条模型响应包含多个工具调用，并将这些调用作为同一轮有序工具序列处理
- **FR-018**: 系统必须按模型返回的工具调用列表顺序执行普通工具调用
- **FR-019**: 系统必须为每一个已记录的工具调用保存一个对应的工具结果，确保后续模型请求中的会话历史不存在未配对工具调用
- **FR-020**: 当普通工具执行返回成功结果时，系统必须保存该工具调用对应的结果，并继续处理同轮后续普通工具调用
- **FR-021**: 当普通工具执行失败时（仅包括未知工具、handler 抛出异常、工具返回顶层 JSON 对象且含 `error` 字段或 `success: false` 的标准化错误结构），系统必须保存该失败工具对应的错误结果，停止真实执行同轮后续工具，并为每个后续未执行工具保存"未执行/需模型重新规划"的工具结果；系统不得通过普通文本是否包含"错误"或"error"等关键词推断失败
- **FR-022**: 当模型在同一响应中返回多于一个工具调用且其中包含至少一个中断型工具时，系统必须保存该模型响应，将该响应判定为模型输出错误，不真实执行任何工具调用，并为响应中的每个 tool call 保存配对错误结果。合法的中断响应必须有且仅有一个工具调用且为中断型
- **FR-023**: 中断型工具单独出现且 handler 成功执行时，系统保留既有暂停或完成语义。中断型工具与任何其他工具同轮出现时的处理由 FR-022 定义。handler 抛异常时按 FR-021 失败语义处理；暂停/完成语义不在失败路径触发
- **FR-024**: 会话恢复时，系统必须识别同一条模型响应中哪些工具调用已有结果、哪些仍缺结果，并只补齐缺失结果
- **FR-025**: 会话恢复不得只取第一条待执行工具调用；多工具响应中的待执行项必须按原始顺序恢复
- **FR-026**: 会话恢复时，如果待补齐工具调用当前没有可用 handler，系统必须按工具失败语义处理：为该工具保存配对错误结果，停止真实执行同轮后续工具，并为后续未执行工具保存"未执行/需模型重新规划"的工具结果
- **FR-027**: 系统必须保留单工具调用场景的现有行为，不能让已有 PM、程序员、试用和 assistant 工作流出现可见回归
- **FR-028**: 系统必须在日志中保留多工具调用数量、执行顺序和恢复缺失结果的关键信息（结构化日志 schema 见 contracts）
- **FR-029**: 系统必须补充覆盖多工具调用完整配对、中断型工具混合报错、工具异常、未知工具、恢复时工具不可用和恢复路径的行为测试
- **FR-030**: 系统必须通过 `ToolDefinition` 上的声明式分类字段 `is_interrupting: bool` 在执行任何 handler 之前识别中断型工具；不得通过 handler 返回值类型或硬编码工具名白名单作为识别依据
- **FR-031**: `not_executed` 与 `invalid_model_output` 配对结果的 content 必须采用标准化错误结构：顶层 JSON 对象，含稳定 `error` 字段与 `message`，可附加 `upstream_tool_call_id`、`code` 等诊断字段
- **FR-032**: 系统必须强制 `ToolDefinition.is_interrupting` 与 handler 实际返回类型一致：`is_interrupting=True` 必须 `ToolSignal`，`is_interrupting=False` 必须 `str`。不一致按 FR-021 失败语义处理（`handler_contract_violation`）

### Agent 工具执行 Hook 系统 [Source: specs/002-tool-hook-system]

- **FR-033**: `ToolDefinition` 必须支持可选 `pre_hook` / `post_hook` 字段；`AgentConfig` 必须支持实例级 `global_pre_hooks` / `global_post_hooks`，默认均为空。
- **FR-034**: pre_hook 可通过 `PreHookResult(error=...)` 拒绝本次工具调用；被拒绝时 handler 与全部 post_hook 不执行，LLM 收到标准化 `pre_hook_rejected` 工具错误，普通批次后续工具触发 `not_executed` 级联。
- **FR-035**: pre_hook 不得修改 handler 入参；`ToolCallContext.args` 是 LLM 原始入参的递归只读隔离视图，顶层或嵌套写入必须抛异常且不得影响 handler 实际参数。
- **FR-036**: post_hook 只可改写普通字符串工具结果；所有 post_hook 都接收 handler 原始字符串结果或 handler 异常转换后的 error 字符串，链不流水线，最后一个非空 `PostHookResult.result` 生效。
- **FR-037**: hook 执行顺序为工具级 pre_hook -> 当前 `AgentConfig` global pre_hooks -> handler -> 工具级 post_hook -> 当前 `AgentConfig` global post_hooks；任意 pre_hook 返回 error 即短路后续步骤。
- **FR-038**: hook 未捕获异常必须记录 WARNING 级或更高日志且不污染工具结果；pre_hook 异常停止剩余 pre_hook、执行 handler 并跳过全部 post_hook；post_hook 异常停止剩余 post_hook 并返回 handler 原始结果。
- **FR-039**: 普通 handler 未捕获异常必须转换为标准化 error 字符串；若没有发生 pre_hook 异常短路，该 error 字符串仍进入 post_hook 链，批处理失败级联依据原始失败状态而非 post_hook 改写文本。
- **FR-040**: 合法 `ToolSignal` 不进入 post_hook 并原样上抛 AgentLoop；普通工具返回 `ToolSignal` 或中断型工具返回 `str` 均视为 handler 契约违规并按标准化错误处理。
- **FR-041**: callable 动态工具路径必须每轮刷新 handler、hook 与 `is_interrupting` 元数据；AgentLoop 注入的 `talk_to_user` / `load_reference` 不进入工具级或 global hook 管线。
- **FR-042**: `read_file`、`write_file`、`edit_file`、`list_dir`、`exec` 的路径存在性/类型、系统目录拒绝、命令安全判断和用户确认 gate 必须位于对应 pre_hook；确认请求失败必须 fail-closed 返回拒绝。`edit_file` 的 `old_text` 查找与唯一性校验保留在 handler。
- **FR-043**: `query_data` SQL 安全策略与 `analyze_image` 单次最多 5 个 `action_index` gate 必须位于 pre_hook；`query_data` pre_hook 复用既有 `rewrite(sql)` / 过滤策略，不新增 raw-text 注释或字符串分号禁用规则。
- **FR-044**: `trial_tools.run_command` 的 5 次调用上限必须由单次 `AgentLoop.run()` 范围内的闭包计数器 pre_hook 实现，不跨 run、session 或进程持久化。
- **FR-045**: `programmer_tools.syntax_check`、`recording_data_tools.execute_code` 沙箱、`tool_executor` venv 隔离/命令白名单、`dynamic_tool_manager` 发布状态与允许列表不得迁移到 hook。
- **FR-046**: hook 系统必须保留 AgentLoop 003 多工具批处理语义：执行前分类、混合中断批次不执行 hook/handler、普通批次失败级联 `not_executed`、合法单中断成功 `ToolSignal` 直接返回既有 AgentResult。

### 上下文压缩 tool_call/tool_result 配对修复 [Source: specs/005-fix-compression-tool-pairing]

- **FR-047**: 压缩切分时，必须识别跨越压缩/保留边界的 tool 组（assistant 消息含 tool_calls 在压缩区，但其部分或全部 tool result 在保留区）
- **FR-048**: 跨越边界的 tool 组必须整体移入保留区——包括 assistant(tool_calls) 消息及其所有 tool result 消息，保证配对完整
- **FR-049**: 完全在压缩区内部的 tool 组正常压缩，不做特殊处理——它们内部配对完整，压缩后通过摘要中的 tool_call_id 后处理保留信息
- **FR-050**: 保留区调整后若压缩区为空，必须跳过 LLM 压缩调用，直接构建 `system | [保留区消息]` 的消息列表
- **FR-051**: `assemble_context` 返回前必须校验消息列表中不存在孤立的 tool result（有 tool_call_id 但无对应 tool_call 的 tool 消息），发现时剔除该孤立消息并记录 warning 日志
### 高危操作确认 Toast 化 [Source: specs/004-auth-toast]

- **FR-052**: 当 Assistant Agent 调用受确认管控的高危工具（`write_file` / `edit_file` / `exec`）时，系统 MUST 在主窗口右下角显示非阻塞浮层并要求用户决策
- **FR-053**: 浮层 MUST 是非模态的——出现期间用户对主窗口其它控件的输入 MUST 不被阻塞
- **FR-054**: 浮层 MUST 显示足够上下文信息（至少工具名 + 关键参数摘要），摘要 MUST 包含目标路径或命令首行等关键字段，长参数 MUST 截断，且 MUST NOT 展示完整文件内容
- **FR-055**: 浮层 MUST 提供三个按钮："全部允许" / "同意" / "拒绝"，每个按钮的语义与本规范定义一致
- **FR-056**: 用户点击"同意" MUST 仅对当前一次确认请求放行，不影响后续请求
- **FR-057**: 用户点击"拒绝" MUST 仅对当前一次确认请求拒绝，不影响后续请求
- **FR-058**: 用户点击"全部允许" MUST 既放行当前请求，又使本次会话内 Assistant 的后续全部高危确认请求被自动放行（不再弹浮层）
- **FR-059**: 当"全部允许"或顶栏 Toggle 开启时，系统 MUST 将确认队列中尚未展示的 Assistant 高危请求立即按自动放行处理
- **FR-060**: 系统 MUST 在用户开启新对话时自动复位"全部允许"状态为关闭
- **FR-061**: 对话窗口顶栏 MUST 提供"免确认"开关，与"全部允许"内部状态双向同步
- **FR-062**: 浮层 MUST 设置超时机制；超时时间不晚于 Worker 阻塞确认超时阈值，超时按"拒绝"语义关闭
- **FR-063**: 多个并发确认请求 MUST 被全部处理（按到达顺序排队展示），任何请求都不能因同时出现而丢失
- **FR-064**: 确认浮层与普通 Toast（成功/错误提示）MUST 独立管理生命周期，互不覆盖
- **FR-065**: 当"全部允许"或顶栏 Toggle 处于开启状态时，UI MUST 给出可见提示
- **FR-066**: 现有的 `IntentConfirmationUI`（PM/Trial Agent）和 `ToolExecutionDialog` MUST 不受本变更影响
- **FR-067**: 系统 MUST 为每次确认决策写入脱敏结构化日志（request_id、工具名、决策结果、决策来源、等待耗时与摘要），MUST NOT 记录完整工具参数或完整文件内容
- **FR-068**: 确认浮层 MUST NOT 提供普通关闭按钮，也 MUST NOT 因点击浮层外区域而关闭；只能通过三按钮或超时结束
- **FR-069**: 当用户在旧会话仍有未决确认请求时开启新对话，系统 MUST 将这些请求按拒绝/超时语义收敛并清空，MUST NOT 泄漏到新对话

### 聊天界面体验完善 [Source: specs/006-chat-ui-polish]

#### Story 1 — AI 回复 Markdown 渲染

- **FR-070**: AI 回复在聊天气泡中展示时，系统 MUST 将其按 Markdown 语法解析并渲染为对应的富文本结构（至少包含标题、有序/无序列表、加粗、斜体、行内代码、代码块、引用、链接样式文本、远程图片、GitHub 风格 pipe table、分隔线）
- **FR-071**: 用户消息（非 AI 回复）MUST 不进行 Markdown 解析，保持纯文本展示
- **FR-072**: 渲染层 MUST 安全处理 AI 回复中的潜在脚本与裸 HTML：MUST NOT 执行任何脚本，MUST NOT 直接渲染未声明的 HTML 标签；未支持或不安全的内容 MUST 降级为纯文本
- **FR-073**: AI 回复在流式输出过程中，未闭合的 Markdown 记号 MUST 不导致明显的样式抖动或大段重排；最终消息收敛后渲染结果 MUST 与一次性传入的渲染结果在视觉上一致
- **FR-074**: 不含任何 Markdown 记号的纯文本 AI 回复 MUST 在视觉上与变更前一致
- **FR-075**: Markdown 链接 MUST 只渲染为带链接视觉样式的文本，MUST NOT 提供点击打开或浏览器跳转能力；Markdown 图片 MAY 渲染远程 http(s) 图片资源，但 MUST NOT 可点击或触发导航

#### Story 2 — 压缩后的旧聊天记录可回看

- **FR-076**: 当前会话存在已被内部归档的用户消息或助手回复时，聊天框 MUST 将这些旧消息与当前未压缩消息按原 sequence 合并为同一条连续聊天时间线展示
- **FR-077**: UI MUST NOT 把内部归档状态做成用户可见概念；MUST NOT 显示独立归档区、"已归档"、"已压缩"、分隔条或特殊底色
- **FR-078**: 完整聊天时间线 MUST 按时间顺序、按发送方（用户/助手）渲染，遵循现有聊天气泡一致的发送方区分规则
- **FR-079**: 工具调用、工具结果和压缩摘要等内部消息 MUST NOT 作为普通聊天记录展示
- **FR-080**: 当会话从未发生过压缩时，聊天框 MUST 与今天的历史记录展示一致
- **FR-081**: 压缩前旧消息中的用户消息与助手回复 MUST 默认完整展示原文，不因内部归档状态做每条消息折叠
- **FR-082**: 用户开启新对话或清空当前会话时，旧消息 MUST 立即清空
- **FR-083**: 聊天框打开存在大量历史的会话时，系统 MUST 初始展示最近 10 条展示消息，并在用户向上滚动时分页加载更早历史

#### Story 3 — 新对话/欢迎界面隐藏免确认 Toggle

- **FR-084**: 应用停留在欢迎界面时，对话窗口顶栏 MUST NOT 展示"免确认" Toggle
- **FR-085**: 用户进入新对话起始态时，对话窗口顶栏 MUST NOT 展示"免确认" Toggle
- **FR-086**: 一旦当前对话已启动过 Agent 会话，对话窗口顶栏 MUST 持续展示"免确认" Toggle，行为完全沿用 004-auth-toast 中定义的同步语义
- **FR-087**: Toggle 显示/隐藏切换 MUST 不破坏顶栏其余控件的位置与样式

### 桌面录制 Phase 1 [Source: specs/007-desktop-recording]

#### 录制层

- **FR-088**: 系统 MUST 支持桌面录制模式，从 `RecordingMixin._on_recording_started` 经 `DesktopRecordingService` / business bridge 路由到 `DesktopRecorder`；UI 层不得直接实例化或启动 Recorder。
- **FR-089**: 桌面录制 MUST 通过 pynput 全局 hook 捕获鼠标左/右/中键、滚轮、拖拽、特殊键、组合键和 typing 序列；hook 注册失败 MUST 阻塞录制启动并弹错。
- **FR-090**: 桌面录制 MUST 在 hook 触发时同步查询 UIA `ElementFromPoint`，50ms 超时后排异步队列回填；UIA COM 初始化失败降级启动并通过 toast 提示。
- **FR-091**: 桌面录制 MUST 订阅剪贴板变更并在 Ctrl+V 时立即读取最新剪贴板内容；文本超阈值走 large-field 占位，图片落 `clipboard/<recording_id>_<event_seq>.png`。
- **FR-092**: 桌面录制 MUST 维护 15fps、30 帧 FIFO ring buffer；每个动作落多帧 PNG，mp4 clip 受 `recording.desktop.enable_clip` 控制，clip 失败不得影响 PNG。
- **FR-093**: 进程启动期 MUST 在 QApplication 前应用 Per-Monitor V2 DPI awareness；坐标、UIA 和截屏统一使用 physical pixel，`desktop_actions.monitor_index` 记录动作时刻屏幕。

#### 数据层

- **FR-094**: 系统 MUST 新增 `desktop_recordings` / `desktop_actions` DuckDB 表；帧、clip、剪贴板图落 `data/recordings/<recording_id>/` 目录，`desktop_recordings.health_stats` 在停止时一次性写入。
- **FR-095**: `desktop_actions` MUST 包含动作类型、坐标、`monitor_index`、`window_title`、`uia_summary`、剪贴板字段、typing 文本、时间戳、duration、frame_count 和 has_clip 等桌面动作字段；drag 以 mouse_up 终点作为坐标和时间语义。
- **FR-096**: `RecordingRepository.save_recording_session()` 的 `recording_mode` 默认值 MUST 修正为 browser 或必填，避免浏览器录制误写为 desktop。
- **FR-097**: 配置模型和 UI fallback 的默认录制模式 MUST 统一为 browser，不得把桌面模式作为默认启动模式。

#### Agent 工具层

- **FR-098**: 5 个通用录制数据工具 MUST 通过 `RecordingRepository.get_recording_mode(recording_id)` 查询 mode 一次，并按 browser / desktop mode 内部切表。
- **FR-099**: `describe_data` / `query_data` MUST 按 mode 严格隔离 allowlist；跨 mode 表访问由 sqlglot security gate 拒绝并返回 `table_not_in_mode` 标准错误。
- **FR-100**: 桌面 mode MUST 提供 `list_desktop_actions`、`analyze_desktop_action`、`read_action_clip` 三个桌面专属工具，分别支持动作分页、最多 2 个动作的多模态分析和 clip 元数据读取。
- **FR-101**: `analyze_desktop_action` MUST 始终返回字符串；失败 action 段写入 `[error: <reason_code>]`，reason_code 至少覆盖 `vision_timeout`、`vision_unauthorized`、`vision_failed`，且每次调用写 INFO 成本审计日志。
- **FR-102**: 桌面 mode 下 PM / Programmer / Trial 工具集 MUST 用 3 个桌面专属工具替换浏览器 `analyze_image`；browser mode MUST 保留 `analyze_image` 且不注入桌面专属工具。

#### Agent 编排层

- **FR-103**: 系统 MUST 提供 `build_pm_prompt(mode)` / `build_programmer_prompt(mode)`；browser mode 返回 legacy prompt，desktop mode 返回桌面专用三段 prompt。
- **FR-104**: Orchestrator 启动 PM / Programmer 前 MUST 用 `dataclasses.replace(..., system_prompt=...)` 构造临时 AgentConfig；不得改造 `agent_loop.format_system_prompt()`。
- **FR-105**: Orchestrator MUST 在 Programmer 输出交给 Trial 前执行 `ast.parse` syntax gate；语法错误时最多自动反馈重试 2 次，连续失败后以用户可见 Toast 和进程日志收敛。
- **FR-106**: `execution_strategy` MUST 支持 `desktop` 取值，并同步 Programmer 工具 schema、trial model 注释和 Trial 分发语义。
- **FR-107**: 桌面 PM prompt MUST 引导 Agent 先看首尾摘要、按 `window_title` 聚焦、跳过冗余动作并按需调用 `analyze_desktop_action`；桌面 Programmer prompt MUST 强约束 `async def execute() -> dict`。

#### 试用层

- **FR-108**: 桌面试用 MUST 走"事前提示对话框 -> 用户开始 -> 跑期间无遮挡 -> 跑完普通 Toast"流程，事前提示展示代码预览和共享高危 API 检测标签。
- **FR-109**: 桌面试用代码 MUST 由 `src/execution/desktop_trial_runner.py` 通过 `subprocess.Popen` 独立子进程执行，使用 `data/trials/<trial_id>/` cwd、env 白名单、stdout/stderr 落盘、120s 超时和 Windows `taskkill /F /T` 兜底。
- **FR-110**: Trial wrapper MUST 捕获任意异常并把 `{"ok": false, "summary": ..., "details": {"traceback": ...}}` 写 stdout 末行；stdout 无有效 JSON 时 runner MUST 用 stderr 末 5 行生成失败 Toast 摘要。

#### UI 与配置

- **FR-111**: 录制页 MUST 提供右下角可拖录制浮窗；点"开始"后主窗最小化，hook/ring buffer/UIA/剪贴板订阅 MUST 在 minimize 完成回调后启动，停止后恢复主窗并弹 sanity check modal child。
- **FR-112**: Ctrl+Alt+S MUST 注册为全局停止快捷键；注册失败不阻塞录制启动，但 UI MUST 一次性提示用户改用浮窗按钮。
- **FR-113**: sanity check 对话框 MUST 通过 `DesktopRecordingService.get_health_stats(recording_id)` 间接读取 `desktop_recordings.health_stats`，显示健康指标并提供"继续分析 / 放弃录制 / 重新录制"三按钮状态机。
- **FR-114**: 浏览器、桌面、扩展触发三种录制模式 MUST 两两互斥，互斥判定基于 in-memory active recorder state，UI 禁用和业务拒绝双保险。
- **FR-115**: 系统 MUST 新增 `recording.desktop.enable_clip`（默认 true）和 `recording.desktop.vision_model`（无默认）配置，均通过 `get_unified_config()` 入口读写。
- **FR-116**: `recording.desktop.vision_model` 未配置时 MUST 不注入 `analyze_desktop_action`，并在设置页说明和桌面 intent 页一次性 toast 中提示降级；provider 和 API key 沿用 `analyze_image` 现有统一配置 entry。
- **FR-117**: Phase 1 MUST 不引入录制数据 retention、cleanup、compress 或 disk quota；放弃录制为软删除状态，Trial 调试目录 7 天 startup cleanup 与录制数据保留边界分开。

### UI Stack Redesign [Source: specs/008-ui-stack-redesign]

- **FR-118**: 系统 MUST 以 Tauri 2 + React 18 + TypeScript + Vite 作为维护中的主桌面 UI 栈，并把现有 Python 业务/数据/执行/录制能力作为打包 sidecar 暴露给前端。
- **FR-119**: 系统 MUST 启动到同一个重新设计的桌面应用壳，覆盖 AI Assistant、技能教学、技能列表、技能组合和设置五个主屏；正常用户流程不得再依赖单独的 legacy PyQt 窗口。
- **FR-120**: 前端 MUST 只通过 typed API/Tauri command/Bridge 访问能力，不得直接 import Repository、SQLite、DuckDB、配置文件或 Python 数据层实现。
- **FR-121**: Python sidecar API MUST 绑定 `127.0.0.1` 的随机端口，并要求每次启动生成的 runtime token；token 不得持久化、不得写入普通日志，Tauri 权限必须按 HTTP/shell/window 能力收敛。
- **FR-122**: `src/desktop_api` MUST 作为 FastAPI adapter 调用业务服务、orchestrator 和事件适配器，不得成为新的数据访问层；跨模块通知继续以 `src/utils/events.py` blinker 为后端来源。
- **FR-123**: 应用壳 MUST 展示 backend `starting | ready | degraded | failed | shutting_down` 等连接状态，并在启动、健康检查、失败和关闭路径提供可恢复用户状态。
- **FR-124**: 自定义红/黄/绿窗口控件 MUST 在 Windows 上执行真实 close、minimize、maximize/restore，并支持键盘操作、可访问名称/状态和可见焦点。
- **FR-125**: 所有来自设计原型的静态样例数据、假计数和无效点击控件 MUST 在验收前移除、禁用并给出真实不可用状态，或接入真实业务/API/Tauri command/验证错误；控制项追踪以 `control-inventory.md` 为准。
- **FR-126**: AI Assistant MUST 支持会话创建、选择、搜索、重命名、删除、消息发送、连续时间线展示、Markdown 安全渲染、执行摘要和高危确认决策 endpoint/event 流。
- **FR-127**: AI Assistant MUST 保留旧聊天历史的连续时间线语义，不得把内部归档/压缩状态展示为用户可见分区、标签、底色或特殊列表。
- **FR-128**: Assistant 高危确认 MUST 保留既有非模态队列和会话级免确认语义，前端一次只展示一个 active confirmation，普通 toast 生命周期独立。
- **FR-129**: 技能教学 MUST 通过业务服务/API 暴露 browser、extension、desktop 三种录制模式准备状态、启动/停止、桌面健康决策、意图回复/确认、学习和试用启动。
- **FR-130**: 技能教学 MUST 保留桌面录制 minimize 完成后启动、健康统计三按钮、syntax gate retry、trial success threshold 和失败记录/重试语义。
- **FR-131**: 技能列表 MUST 展示 pending、published、failed 三类技能及真实计数，并通过现有业务工作流支持 trial、元数据更新、删除验证、失败重试和忽略/关闭。
- **FR-132**: 技能组合 MUST 支持列表、创建、更新、适用场景生成、推荐顺序、试用和发布；range 模式表示可选工具箱，ordered 模式表示显式顺序执行契约。
- **FR-133**: 已发布技能组合在成员技能变化或下线时 MUST 标记 `needs_review`，对 Assistant 隐藏直到复核完成，并在 UI/API 中以独立展示状态呈现。
- **FR-134**: 设置页 MUST 通过 `UnifiedConfigManager` 读取/更新 AI、录制、数据和产品设置；密钥值只允许遮罩展示和写入/删除动作，不得明文返回。
- **FR-135**: 设置页的连接测试、备份、导出、清除记忆、更新检查、文档、changelog 和证书安装等设计可见 action MUST 调用真实支持流程或返回真实业务验证/不可用错误。
- **FR-136**: 系统 MUST 新增并维护 `frontend/`、`src-tauri/`、`src/desktop_api/`、相关业务 service/facade 和前端 Zustand/API/state/screen 结构，且这些结构必须与分层边界一致。
- **FR-137**: 旧 PyQt 正常启动入口和主 UI 模块 MUST 在新 shell 通过验收后移除或降级为 legacy 失败提示；guard test 必须阻止正常路径重新打开维护中的 PyQt UI。
- **FR-138**: 打包路径 MUST 能构建 Tauri shell 和 PyInstaller Python sidecar，并通过 build 脚本/安装文档说明外部二进制 handoff。
- **FR-139**: 系统 MUST 对每个主屏至少保留一个主工作流回归覆盖，并覆盖 backend bridge 失败状态、可见控制 wiring、无样例数据、键盘/可访问性、sidecar token 安全和 legacy local data 不静默变更。
- **FR-140**: 设计原型是 2026-05-09 Mexemplar prototype；布局、导航、密度、组件层级和页面流的 blocker/major 偏离必须在验收前修正或经新的基线批准。
- **FR-141**: Windows 是首要验收平台；新 shell 依赖系统 WebView2/Tauri，fresh-install profile 是主验收档案，旧本地用户数据迁移不在本 feature 范围内。
- **FR-142**: 系统 MUST 避免启动时静默损坏、删除或修改未迁移的 legacy local data，并通过专门安全检查验证。
- **FR-143**: 前端交互控件 MUST 键盘可操作、提供可访问名称/状态、可见焦点、可读对比，并尊重 reduced-motion 偏好。
- **FR-144**: 前端 server state 以 Python 服务/API 为权威；Zustand 仅维护 route、draft、选中 ID、局部面板、乐观 UI 标志和 sidecar 连接等本地 UI 状态。
- **FR-145**: `DesktopAgentRuntime` / sidecar orchestrator 接线后续应收敛为业务拥有的 factory/service，避免 FastAPI adapter 长期直接组装 config、LLM client 和 `AgentOrchestrator`；当前作为 cleanup 技术债追踪。

---

## Key Entities

### LargeFieldConfig
运行时配置，namespace `recording.large_field.*`。字段：`threshold_chars`（默认 1000）、`preview_chars`（默认 1000）、`max_chunk_chars`（默认 1000）。验证：均为正整数。 [Source: specs/001-recording-field-layering]

### StableLocatorRule
每张源表的稳定定位字段映射。v1 覆盖：`network_requests`→`request_id`、`actions`→`action_id`、`sibling_snapshots`→`snapshot_id`。字段：`table`、`recommended_id_field`、`describe_locator_fields`。 [Source: specs/001-recording-field-layering]

### ProjectionBinding
SQL AST 分析结果：`output_name`、`source_table`、`source_field`、`is_direct_column`。由 `query_projection_analyzer.py` 基于 sqlglot 生成。 [Source: specs/001-recording-field-layering]

### LargeFieldLocator
续读定位指针：`table`（StableLocatorRule 覆盖）、`id_field`（稳定定位列）、`id_value`（int | str）。 [Source: specs/001-recording-field-layering]

### LargeFieldPlaceholder
query_data 返回的占位对象：`__large_field__`、`field`、`size_chars`、`preview`、`locator`、`read_hint`、`read_blocked_reason`、`read_blocked_message`。 [Source: specs/001-recording-field-layering]

### ChunkReadRequest
read_field_chunk 请求：`locator`、`field`、`offset`（≥0）、`length`（可选，默认 max_chunk_chars）。 [Source: specs/001-recording-field-layering]

### ChunkReadResponse
read_field_chunk 响应（成功/失败共用）：`content`、`field`、`locator`、`offset`、`returned_length`、`total_length`、`has_more`、`next_offset`、`error`。`error=null` 表示成功。 [Source: specs/001-recording-field-layering]

### ChunkReadError codes
9 种枚举：`invalid_offset`、`invalid_length`、`unknown_table`、`field_not_found`、`non_text_field`、`unknown_id_field`、`record_unavailable`、`unsupported_continuation`、`internal_error`。 [Source: specs/001-recording-field-layering]

### ToolCallBatch [Source: specs/003-fix-agentloop-tool-calls]
一条 assistant 消息中包含的一个或多个工具调用。状态：`complete`（全部配对）、`incomplete`（部分缺结果）、`invalid_output`（含混合中断型，无 handler 执行）。

### StandardizedErrorStructure [Source: specs/003-fix-agentloop-tool-calls]
AgentLoop 发出的配对错误结果通用格式：顶层 JSON 含 `error`（枚举）、`message`、可选 `tool_name`、`upstream_tool_call_id`、`code`。枚举：`unknown_tool`、`handler_exception`、`handler_contract_violation`、`not_executed`、`invalid_model_output`。

### ToolDefinition.is_interrupting [Source: specs/003-fix-agentloop-tool-calls]
`bool` 字段，标记工具是否为中断型。`True` → handler 必须返回 `ToolSignal`；`False` → handler 必须返回 `str`。运行时校验不一致则触发 `handler_contract_violation`。

### ToolCallContext [Source: specs/002-tool-hook-system]
单次工具调用只读上下文。字段：`tool_name`、`args`、`session_id`、`agent_type`、`iteration`。不包含 `result` 字段、不包含用户确认回调；`args` 是递归只读隔离视图。

### PreHookResult [Source: specs/002-tool-hook-system]
pre_hook 返回值。字段：`error: str | None = None`。`error` 有值时拒绝本次工具调用；不包含 `args` 字段，不支持参数 merge、替换或删除。

### PostHookResult [Source: specs/002-tool-hook-system]
post_hook 返回值。字段：`result: str | None = None`。只用于替换普通字符串工具结果；`ToolSignal` 不进入 post_hook。

### ToolDefinition hook fields [Source: specs/002-tool-hook-system]
`ToolDefinition` 在 `name`、`schema`、`handler`、`is_interrupting` 基础上新增 `pre_hook` / `post_hook`，默认 None。没有 hook 的工具行为保持透明。

### AgentConfig global hooks [Source: specs/002-tool-hook-system]
`AgentConfig.global_pre_hooks` / `global_post_hooks` 是当前配置实例范围内的列表，不跨 AgentConfig 共享，也不作用于 `talk_to_user` / `load_reference`。

### Tool Group [Source: specs/005-fix-compression-tool-pairing]
由一条 assistant 消息（含 tool_calls 字段）和紧跟其后的所有 tool result 消息组成的原子单元。识别规则：assistant 消息的 tool_calls 中每个 id 必须在后续连续的 tool 消息中找到对应 tool_call_id。

### Boundary Tool Group [Source: specs/005-fix-compression-tool-pairing]
tool 组中 assistant(tool_calls) 消息位于压缩区，但其部分或全部 tool result 消息位于保留区的 tool 组。
### PendingConfirmation [Source: specs/004-auth-toast]
高危工具确认请求的运行时记录。字段：`request_id`（UUID）、`tool_name`（write_file/edit_file/exec）、`summary`（脱敏摘要）、`created_at`（monotonic 时间戳）、`event`（threading.Event）、`result`（bool）、`decision`（枚举：accepted/rejected/timeout/auto_approved/confirm_error）、`source`（枚举：toast_accept/toast_reject/toast_timeout/toast_allow_all/top_toggle/auto_scope/new_chat_reset/system_error）。每个请求恰好到达一个终态决策。

### AutoApproveScope [Source: specs/004-auth-toast]
会话级自动放行状态。字段：`enabled`（bool，默认 False）、`source`（最近变更来源）。生命周期等于一次对话；新对话复位。不持久化到 config/DB。

### AuthToastSurface [Source: specs/004-auth-toast]
UI 层非模态确认浮层组件。字段：`request_id`、`tool_name`、`summary`、`timeout_timer`（QTimer singleShot）。三按钮："全部允许"/"同意"/"拒绝"。无普通关闭按钮；不响应外部点击关闭。与普通 Toast 独立生命周期。

### DisplayChatMessage [Source: specs/006-chat-ui-polish]
业务层返回给 UI 的展示 DTO，不持久化。字段：`sequence`（int）、`role`（user/assistant）、`content`（str，已过滤空内容）、`created_at`（datetime or None）。映射自一条 SQLite Message，不包含 `is_archived`/`message_type`/`tool_calls` 等内部状态。

### ChatHistoryPage [Source: specs/006-chat-ui-polish]
业务层返回给 UI 的分页结果，不持久化。字段：`messages`（list[DisplayChatMessage]，按 sequence 升序）、`has_more_before`（bool）、`next_before_sequence`（int or None）。

### MarkdownMessageView [Source: specs/006-chat-ui-polish]
聊天气泡内部渲染 widget。使用 Qt `QTextDocument.setMarkdown(MarkdownDialectGitHub)` 渲染。属性：`navigation_enabled` 固定 false；`allowed_image_schemes` 限 http/https；渲染前对 raw HTML/script 做安全降级。

### AutoApproveToggleVisibility [Source: specs/006-chat-ui-polish]
ChatWidget 内部视图状态，不持久化。状态：`session_list`→隐藏、`new_chat_empty`→隐藏、`conversation_started`→显示、`conversation_cleared`→隐藏。

### DesktopRecordingSession [Source: specs/007-desktop-recording]
一次桌面录制 session，对应 `desktop_recordings` 表。字段：`recording_id`、`recording_mode='desktop'`、`start_time`、`end_time`、`monitor_index`、`status`（`recording` / `stopped` / `abandoned`）、`health_stats`。桌面录制不要求镜像写入 `recording_sessions`。

### DesktopAction [Source: specs/007-desktop-recording]
桌面录制中的单个动作，对应 `desktop_actions` 表。字段：`action_id`、`recording_id`、`type`（mouse_left / mouse_right / mouse_middle / wheel / drag / typing / hotkey）、`coord_x`、`coord_y`、`monitor_index`、`window_title`、`uia_summary`、`clipboard_text`、`clipboard_image_path`、`text_content`、`timestamp`、`duration_ms`、`frame_count`、`has_clip`。typing 一段一行；drag 使用 mouse_up 终点语义。

### DesktopHealthStats [Source: specs/007-desktop-recording]
停止时写入 `desktop_recordings.health_stats` 的 JSON 汇总。字段：`uia_hit`、`uia_total`、`clip_success`、`clip_total`、`clipboard_event_count`、`action_type_counts`、`frame_total`、`duration_ms`。颜色规则：动作总数为 0 红；UIA 命中率低或 clip 失败率高黄；否则绿。

### DesktopTrialResult [Source: specs/007-desktop-recording]
桌面 Trial 子进程结果 DTO。字段至少包含 `ok`、`summary`、`details`、`exit_code`、`timed_out`、`stdout_path`、`stderr_path`、`trial_id`。SC-003 的"试用通过"要求 exit code 0、stdout 末行 JSON 解析成功且 `ok=True`。

### DesktopRecordingConfig [Source: specs/007-desktop-recording]
运行时配置 namespace `recording.desktop.*`。字段：`enable_clip`（bool，默认 true）、`vision_model`（str | None，无默认）。provider 和 API key 沿用 `analyze_image` 当前统一配置 entry。

### HighRiskApiDetection [Source: specs/007-desktop-recording]
桌面 Trial 事前提示与"走捷径"判定共用的静态检测结果。命中规则覆盖 `subprocess`、`os.startfile`、`webbrowser`、Win32 协议 URL（排除 Windows 盘符路径）、pywin32 高级 API、pywinauto 控件级 API；纯 pyautogui 坐标点击不算捷径。

### DesignBaseline [Source: specs/008-ui-stack-redesign]
2026-05-09 Mexemplar prototype 与 `control-inventory.md` 的组合验收基线。字段：`baseline_id`、`prototype_root`、`screens`、`feature_document`、`approved_controls`。所有已接受屏幕必须可追踪到该基线，样例数据、假计数和 no-op 控件不得进入正常状态。

### DesignControl [Source: specs/008-ui-stack-redesign]
单个可见原型控件到产品行为的追踪记录。字段：`control_id`、`source_file`、`screen`、`visible_label_or_affordance`、`required_disposition`（wire/validate/disable/remove）、`requirement_refs`、`implementation_refs`。

### AppShell [Source: specs/008-ui-stack-redesign]
Tauri/React 顶层桌面体验。字段：`route`、`window_state`、`backend_state`、`navigation_counts`、`user_display`、`theme_state`。默认 route 为 assistant；导航和窗口控件必须真实可用且可访问。

### BackendConnectionState [Source: specs/008-ui-stack-redesign]
Python sidecar 的用户可见状态。字段：`status`（starting/ready/degraded/failed/shutting_down）、`port`、`auth_token_state`、`health_checks`、`message`、`last_checked_at`。runtime token 不暴露给 UI 展示层。

### AssistantExecutionSummary [Source: specs/008-ui-stack-redesign]
工具/推理进度的紧凑可展开表示。字段：`summary_id`、`session_id`、`status`、`headline`、`steps`、`started_at`、`finished_at`。默认紧凑展示，不显示 prompt、archive 或 compression 内部术语。

### SkillTeachingRun [Source: specs/008-ui-stack-redesign]
从录制模式选择到 trial 验证的教学工作流 DTO。字段：`workflow_id`、`mode`、`stage`、`readiness`、`recording_summary`、`intent_questions`、`learning_progress`、`trial_progress`、`failure`。

### Skill [Source: specs/008-ui-stack-redesign]
技能列表与组合成员选择中的学习能力视图。字段：`tool_id`、`tool_name`、`description`、`parameters`、`source`、`workflow_id`、`status`、`trial_success_count`、`usage_metadata`、时间戳。

### TeachingFailure [Source: specs/008-ui-stack-redesign]
技能列表失败分类中的诊断记录。字段：`record_id`、`workflow_id`、`tool_name`、`failed_stage`、`error_summary`、`error_type`、`status`、`retry_count`、时间戳。

### SkillCompositionView [Source: specs/008-ui-stack-redesign]
技能组合 UI/API 视图。字段：`composition_id`、`composition_name`、`description`、`applicability`、`mode`、`status`、`displayStatus`、`assistant_enabled`、`recommend_order`、`needs_review`、`members`、时间戳。

### SkillCompositionMemberView [Source: specs/008-ui-stack-redesign]
组合和已发布技能的成员关系视图。字段：`member_id`、`composition_id`、`tool_id`、`selected_order`、`execution_order`、`created_at`。ordered 模式要求连续执行顺序。

### AppSetting [Source: specs/008-ui-stack-redesign]
设置页展示的配置/动作项。字段：`key`、`label`、`section`、`value_kind`、`value`、`masked_display_value`、`validation_rules`、`effective_change`、`status`。secret 类型只能遮罩展示，并通过 `UnifiedConfigManager` 写入/删除。

### SidecarApiSession [Source: specs/008-ui-stack-redesign]
Tauri 与 Python sidecar 之间的运行期连接授权状态。字段：`port`、`auth_token`、`tauri_origin`、`started_at`、`expires_at`；不持久化。

---

## Constraints & Compatibility

- **CC-001**: 不修改原始录制数据；占位和续读为查询时派生
- **CC-002**: 与 reference_handler 正交；两者不互相依赖
- **CC-003**: 不破坏 query_data SQL 语义；变化仅在结果交付环节
- **CC-003a**: network_requests 占位与续读必须复用 filter/sanitize 边界
- **CC-004**: 占位生成和续读元信息确定性，不依赖 LLM
- **CC-005**: 与 noise-filter 正交
- **CC-006**: 不引入敏感信息自动识别或脱敏
- **CC-007**: 不做结构骨架提取或语义摘要
- **CC-008**: blocked/unsupported/error 路径必须产出可检索的结构化日志

### AgentLoop 多工具调用约束 [Source: specs/003-fix-agentloop-tool-calls]

- **CC-009**: 修复必须保持 AgentLoop 不直接感知 UI；上层仍通过现有结果状态接收暂停、完成或错误
- **CC-010**: 修复必须兼容模型仍只返回单个工具调用的主路径
- **CC-011**: 修复不得依赖模型或供应商一定遵守串行工具设置；系统自身必须保证历史消息配对完整
- **CC-012**: 修复不得改变工具 handler 的业务返回协议；普通字符串结果和中断型结果仍按既有语义处理
- **CC-013**: 修复不得让已完成工具在恢复时重复执行

[Sources: specs/001-recording-field-layering, specs/003-fix-agentloop-tool-calls]

### Agent 工具执行 Hook 约束 [Source: specs/002-tool-hook-system]

- **CC-014**: 本系统不引入第三方依赖、持久化表、运行时配置、密钥或 UI。
- **CC-015**: hook 协议保持同步契约，不把现有同步 handler 改造成异步。
- **CC-016**: pre_hook 不做参数流水线，post_hook 不做结果流水线；不得重新引入 `PreHookResult.args`、`ToolCallContext.result` 或确认回调字段。
- **CC-017**: 被迁移的 gate 判断必须从 handler 中删除，不保留作为备用路径；执行必需的解析、规范化、查询准备和结果转换可保留。

### 上下文压缩配对修复约束 [Source: specs/005-fix-compression-tool-pairing]

- **CC-018**: 修改后 `compress` 方法的返回值（List[Message]）结构必须保持兼容——调用方 `context_manager.assemble_context` 不需要修改其对压缩结果的处理方式
- **CC-019**: 当边界调整后压缩区仍非空时，持久化行为保持不变；若压缩区为空，则跳过 compressed 消息创建和归档
- **CC-020**: `_post_process_summary` 的 tool_call_id 替换逻辑保持不变——完全在压缩区内部的 tool 组仍需要此逻辑来保留 tool 信息
- **CC-021**: reference_handler 对大内容 tool result 的替换不受影响——移入保留区的是 DB 中的原始 Message 对象，引用替换在 `assemble_context` 中统一执行
- **CC-022**: 不影响 `get_pending_tool_calls` 的现有行为——它检测的是 assistant 消息中有 tool_calls 但无对应 tool result 的场景，与本次修复方向互补
### 高危操作确认 Toast 化约束 [Source: specs/004-auth-toast]

- **CC-018**: 现有 Worker → UI 的跨线程信号机制（pyqtSignal + Event 等待）MUST 保持不变；仅替换 UI 端展示形态
- **CC-019**: 高危工具判定清单不变，不扩展也不收缩
- **CC-020**: 浮层超时 MUST 不晚于 Worker 阻塞超时（120s），二者同步收敛
- **CC-021**: 普通 Toast 行为不变；确认浮层与普通 Toast 通过独立生命周期管理共存
- **CC-022**: "新对话"边界 MUST 同时复位会话级自动放行状态并清空旧会话未决确认

### 聊天界面体验完善约束 [Source: specs/006-chat-ui-polish]

- **CC-023**: 现有压缩边界处理与孤立 tool result 兜底的行为 MUST 不被本 feature 改动；完整历史回看只读取现有数据，不改变压缩输入/输出契约
- **CC-024**: 004-auth-toast 中 Toggle 与浮层的双向同步、新对话复位等语义 MUST 保持完全一致；本 feature 仅控制控件的可见性，不变更其行为
- **CC-025**: Markdown 渲染 MUST NOT 改变现有用户消息渲染路径，MUST NOT 影响普通 Toast、确认浮层、IntentConfirmationUI、ToolExecutionDialog
- **CC-026**: 渲染层 MUST 不执行 AI 回复中的脚本或裸 HTML，避免 XSS/注入风险
- **CC-027**: 现有跨线程信号、Worker 阻塞确认机制 MUST 不被本 feature 改动
- **CC-028**: 若现有 UI 可访问接口不能直接提供完整历史消息，允许在业务层增加最小只读接口；UI MUST NOT 直接调用 Repository，且该接口 MUST NOT 改变存储 schema 或压缩契约

### 桌面录制 Phase 1 约束 [Source: specs/007-desktop-recording]

- **CC-029**: Phase 1 仅支持 Windows 10/11；macOS / Linux 桌面录制不在本期范围。
- **CC-030**: 5 个通用录制数据工具的 mode dispatch MUST 保持浏览器路径 byte-equal，不得破坏 `network_requests.filtered = FALSE` 视图和 `recording_data_tools.py` 不直接 import sqlglot 的 guard。
- **CC-031**: PM / Programmer 浏览器 prompt MUST 字节级保留；桌面 prompt 使用双轨构建，不把浏览器 prompt 改成动态分支。
- **CC-032**: Phase 1 不做运行期隐私机制或上传确认；原始录制数据仅本地落盘，vision 分析按工具调用上传本次涉及的最多 2 个动作帧和关联剪贴板图。
- **CC-033**: 桌面录制 MUST 与浏览器录制、扩展触发录制互斥，不支持中途切换或并发录制。
- **CC-034**: 性能目标为软退出标准：CPU 单核 < 15%、鼠标延迟 < 50ms、内存 < 500MB、磁盘 IO 突发 < 50MB/s；Phase 1 通过 manual e2e 主观判断和日志审计，不设自动化硬门。
- **CC-035**: 单次桌面录制不设时长、动作数或磁盘占用硬上限；崩溃孤儿和超量录制数据由开发/内测用户手动处理，硬限制推迟到 Phase 2。

### UI Stack Redesign [Source: specs/008-ui-stack-redesign]

- **CC-036**: 008 是完整主 UI 替换，不是单页实验；五个主屏必须在同一接受版本内完成。
- **CC-037**: 前端和 desktop API adapter 不得绕过业务服务直接触达 Repository、SQLite、DuckDB 或配置文件。
- **CC-038**: 设计词汇必须面向用户：使用"技能教学"、"技能列表"、"技能组合"、"范围型"、"顺序型"等概念，不把归档/压缩或内部方法名暴露为 UI 概念。
- **CC-039**: 2026-05-09 prototype 约束可见设置和动作；无样例数据、假计数、假按钮可进入验收状态。
- **CC-040**: 新 UI 接受后，legacy PyQt 不再是正常用户或开发者可依赖的维护 fallback；恢复 PyQt 正常入口必须先变更规格和活文档。
- **CC-041**: Sidecar API 只绑定 loopback，使用 per-launch token；日志、DTO 和前端状态不得泄漏 token 或明文 secret。
- **CC-042**: 新增 settings/action 能力必须遵守统一配置、secret 遮罩/日志脱敏、业务验证和事件边界，不得为了完成设计按钮而引入文件直写或直接 SQL。
- **CC-043**: Fresh-install profile 是主要验收路径；不迁移旧本地数据可以接受，但不得静默破坏或修改旧数据。

---

## Success Criteria

- **SC-001**: 单个大字段占位对象 preview ≤ `preview_chars`（默认 1000），元数据固定小结构
- **SC-002**: 多次分段读取可查看 1MB+ 字段任意区段，单次 content ≤ `max_chunk_chars`
- **SC-003**: 占位替换额外延迟 ≤ 200ms（in-process，单条 1.2MB 行，仅计占位构造增量）
- **SC-004**: 小字段（< 阈值）行为零回归
- **SC-005**: FR-016 所列最小文档清单不含陈旧 4 tools 描述
- **SC-006**: blocked/unsupported/error 路径在日志中可结构化检索

### AgentLoop 多工具调用验收标准 [Source: specs/003-fix-agentloop-tool-calls]

- **SC-007**: 两工具响应：100% 工具调用在下一轮模型请求前有配对结果
- **SC-008**: 三工具响应：执行顺序与模型返回顺序完全一致
- **SC-009**: 三工具中第二个返回标准化错误：前两个得到结果，第三个 not_executed，下一轮模型请求被接受
- **SC-010**: 工具返回含"error"纯文本但非标准化错误结构时，后续工具仍正常执行
- **SC-011**: 混合中断型+普通工具响应：原响应被持久化，所有 tool call 得到 invalid_model_output 配对结果，无 handler 执行
- **SC-012**: 部分结果恢复：只补齐缺失调用，不重复已完成调用
- **SC-013**: 恢复时 handler 缺失：该调用得到 error 结果，后续得到 not_executed 结果
- **SC-014**: 现有单工具工作流无可见回归

[Sources: specs/001-recording-field-layering, specs/003-fix-agentloop-tool-calls]

### Agent 工具执行 Hook 验收标准 [Source: specs/002-tool-hook-system]

- **SC-015**: 现有 Agent 与工具相关单元/集成测试零修改通过。
- **SC-016**: 空操作 hook 全链路（工具 pre + 1 个 global pre + 工具 post + 1 个 global post）相对无 hook 单次调用额外开销不超过 5 ms。
- **SC-017**: 迁移 gate 覆盖 `write_file` 系统目录、`exec` 元字符/非白名单、`query_data` 多语句/非查询/隐藏或系统表、`run_command` 第 6 次、`analyze_image` 6 个 action_index，同时保留 query_data harmless 注释和字符串内分号允许路径。
- **SC-018**: handler 函数体不再出现已迁移的拒绝/确认/限流/安全策略判断；静态 guard 固定非迁移边界。
- **SC-019**: 新增全局 pre_hook 的挂载成本不超过 30 行，且不需要修改任何工具 handler 或 AgentLoop 引擎本体。
- **SC-020**: callable 动态工具同名替换 hook 或 `is_interrupting` 后，下一轮工具调用使用最新定义。
- **SC-021**: 协议测试覆盖 `ToolCallContext.args` 顶层和嵌套只读隔离，误写不会影响 handler 入参且本次 post_hook 被跳过。
- **SC-022**: 多工具批处理语义保持 003 行为：hook 拒绝/handler 失败级联 `not_executed`，混合中断批次不执行 hook/handler，合法单中断 `ToolSignal` 直接返回既有 AgentResult。

### 上下文压缩配对修复验收标准 [Source: specs/005-fix-compression-tool-pairing]

- **SC-023**: 任何会话经历上下文压缩后，消息列表中不存在孤立的 tool result（100% 无 400 错误）
- **SC-024**: 多次压缩后上下文大小可控——每次压缩只额外保留边界处跨越的 tool 组，不随压缩次数累积
- **SC-025**: 会话恢复（failed → active）后，assemble_context 的兜底校验能检测并清理孤立 tool result，不阻塞恢复流程
### 高危操作确认 Toast 化验收标准 [Source: specs/004-auth-toast]

- **SC-023**: 浮层弹出期间，用户在主窗口其它区域的点击响应延迟 ≤ 100ms
- **SC-024**: 同一会话连续 10 次高危操作，开启"全部允许"后无需再做任何点击决策
- **SC-025**: 新对话开启后，前一会话的"全部允许"100% 失效
- **SC-026**: 顶栏 Toggle 与浮层"全部允许"双向同步成功率 100%（同帧或下一帧内同步）
- **SC-027**: 5 个 Worker 同时发起确认请求，所有请求都被排队展示并得到一次决策或超时，无请求丢失
- **SC-028**: 浮层超时关闭时间与 Worker 阻塞超时阈值的差值 ≤ 1 秒
- **SC-029**: 同意、拒绝、超时、自动放行四类决策路径均产生 1 条脱敏结构化日志

### 聊天界面体验完善验收标准 [Source: specs/006-chat-ui-polish]

- **SC-030**: 包含标题、列表、代码块、加粗、链接、图片、表格的 AI 回复 100% 以富文本展示，原始 Markdown 记号不可见，链接/图片点击 0 次触发外部导航
- **SC-031**: 不含 Markdown 记号的纯文本 AI 回复，渲染前后视觉无可识别差异
- **SC-032**: 压缩后聊天框 100% 展示旧用户消息与助手回复，与当前消息按原时间顺序组成连续记录；0 条工具调用/结果/压缩摘要作为普通聊天消息可见
- **SC-033**: 发生过压缩和从未压缩的会话都不显示任何内部状态提示
- **SC-034**: "免确认" Toggle 在四类状态下可见性正确率 100%
- **SC-035**: Toggle 显隐切换帧内完成，不出现视觉闪烁或布局抖动
- **SC-036**: ≥1000 条旧消息时首屏加载 ≤2s，滚动/输入 UI 阻塞 ≤100ms
- **SC-037**: AI 回复含脚本/裸 HTML 时 0 次脚本被执行，0 次裸 HTML 渲染为活动元素

### 桌面录制 Phase 1 验收标准 [Source: specs/007-desktop-recording]

- **SC-038**: 5 个标准场景全部录制成功；客观判定为 `health_stats.action_type_counts` 之和 > 0，US4 完成后 sanity check UI 颜色非红。
- **SC-039**: 5 个标准场景 Agent 均能进入 intent 页并给出可执行方案；PM 到达 talk_to_user 终态，Programmer 输出代码通过 `ast.parse`。
- **SC-040**: 5 个标准场景中至少 3/5 试用通过；客观判定为子进程 exit code 0、stdout 末行 JSON 解析成功且 `ok=True`。
- **SC-041**: 5 个标准场景中至少 3/5 生成代码命中"走捷径"规则；先用共享 high-risk detector 机械判定，再由人工 spot check 复核误伤。
- **SC-042**: 浏览器路径门卫不变量 1-7 在 mode dispatch 改造前后 100% 通过，5 个通用工具 canonical JSON baseline byte-equal。
- **SC-043**: 浏览器 PM / Programmer prompt 行为级守卫测试 100% 通过，关键短语断言不退化。
- **SC-044**: 5 场景 manual e2e 期间用户主观判断"不卡"，鼠标响应和整体流畅度无感知卡顿。
- **SC-045**: installer 公开发版前完成产品/安全侧对"全局录制 + 无隐私机制 + vision 按需上传"的隐私风险签字。

### UI Stack Redesign 验收标准 [Source: specs/008-ui-stack-redesign]

- **SC-046**: 五个主屏在打包或 dev Tauri shell 中全部可达，产品评审无 blocker 或 major 视觉/流程偏离 2026-05-09 设计基线。
- **SC-047**: AI Assistant happy path 在 2 分钟内完成：启动、创建或选择对话、发送消息、收到回复并看到可展开执行摘要。
- **SC-048**: 技能教学 happy path 在受控 fixture 下 5 分钟内从录制模式选择推进到 trial-ready 状态。
- **SC-049**: 用户可以查看 pending/published/failed 技能分类并对每类触发正确下一步动作，无 legacy UI fallback。
- **SC-050**: 用户可以创建 range 和 ordered 两类技能组合，包含适用场景、成员验证、trial 和发布路径，且无直接数据存储编辑。
- **SC-051**: 设置页支持查看和更新非密钥设置，secret 在 100% 正常 UI 状态下保持遮罩。
- **SC-052**: backend startup、ready、degraded、failed、shutdown 状态在 UI 中可见；目标开发机上正常启动 95% 在 10 秒内达到 interactive ready 或可恢复 degraded。
- **SC-053**: 自动化或脚本回归至少覆盖每个主屏一个主工作流，以及至少一个 backend bridge 失败状态。
- **SC-054**: 五个屏幕的正常、空、加载、降级和错误状态不包含可发货的样例记录、假计数或 pretend action。
- **SC-055**: Windows 红/黄/绿窗口控件通过手动和自动 smoke：close、minimize、maximize/restore 均调用真实窗口行为。
- **SC-056**: `control-inventory.md` 中每个可见控制 100% 执行真实支持流程，或返回真实业务验证/不可用错误。
- **SC-057**: Fresh-install 验收不依赖预置本地用户数据，legacy local data 安全检查确认启动不静默修改旧数据。
- **SC-058**: 键盘和可访问性 smoke 覆盖导航、窗口控件、assistant compose/send、教学模式选择、技能/组合 tab 与动作、组合表单、设置表单、非模态确认和 toast/action feedback。

---

## Edge Cases

- 阈值边界：`>=` 阈值即触发；`<` 阈值保持原样
- 同一结果多个大字段：各自独立占位
- 缺少定位字段：`locator=null` + `read_blocked_reason`
- 长度超限：返回 cap 范围内容并告知实际范围
- 非法参数（offset<0, length≤0）：返回明确错误
- 运行时配置变更：不影响既有 locator 有效性
- 刚达阈值即使原文更短也必须占位
- 记录删除后续读：返回 `record_unavailable`
- offset 超过结尾：空成功响应
- join 歧义：保守判定为不支持续读
- 聚合/计算列：触发占位但 `locator=null`

[Source: specs/001-recording-field-layering]

---

### AgentLoop 多工具调用 [Source: specs/003-fix-agentloop-tool-calls]

- 模型在串行工具设置下仍返回多个工具调用
- 同轮多个工具调用中包含未知工具名
- 同轮多个工具调用中某个工具执行抛出异常
- 同轮多个普通工具调用中，前序工具返回标准化错误结构，后续工具不得继续真实执行
- 普通工具返回文本中包含"错误"或"error"等词但不是标准化错误结构时，不得仅凭关键词判定为失败
- 同轮工具调用中混有普通工具、中断型工具，作为模型输出错误处理
- 同轮响应包含多个中断型工具也作为模型输出错误处理
- Solo 中断型工具 handler 抛异常时不触发暂停/完成语义；按 FR-021 失败语义处理
- 会话恢复仅检查最近一条 assistant 消息中的未配对调用（crash 只发生在执行中途）
- 动态工具列表恢复前变化导致待恢复工具不存在时，按工具失败语义补齐

### Agent 工具执行 Hook [Source: specs/002-tool-hook-system]

- pre_hook 返回 error：handler 与全部 post_hook 均不执行，结果为标准化 `pre_hook_rejected`
- pre_hook 写入 `ToolCallContext.args` 顶层或嵌套容器：抛出 hook 异常，handler 使用原始入参，本次 post_hook 跳过
- pre_hook 抛异常：停止剩余 pre_hook，执行 handler，跳过全部 post_hook
- post_hook 抛异常：停止剩余 post_hook，返回 handler 原始结果，丢弃前序 post_hook 的部分改写
- 确认类 pre_hook 的确认请求失败：fail-closed，返回拒绝而不是让 AgentLoop 通用 pre_hook 异常策略放行 handler
- handler 抛异常：转换为标准化 error 字符串并进入 post_hook，批处理失败级联仍按原始异常状态判定
- 合法 `ToolSignal`：跳过 post_hook；普通工具返回 `ToolSignal` 或中断工具返回字符串均为 handler 契约违规
- `talk_to_user` / `load_reference`：作为 AgentLoop 注入工具参与既有批处理控制，但不进入 hook 管线

### 上下文压缩配对修复 [Source: specs/005-fix-compression-tool-pairing]

- 压缩区末尾可以连续存在多个 tool 组，但真正跨越压缩/保留边界的只会是最后一个；仅将该边界 tool 组（含其所有 tool results）移入保留区
- 压缩区调整边界后压缩区为空（只有边界 tool 组和保留区）——跳过 LLM 压缩调用
- 保留区首条消息是 tool result，其对应的 assistant(tool_calls) 在压缩区中——核心修复场景
- tool 组中 tool_result 内容已被 reference_handler 替换为指针，移入保留区后指针仍然有效
- 会话恢复（`get_pending_tool_calls`）检测到的未配对 tool_call 与孤立 tool_result 同时存在的场景
### 高危操作确认 Toast 化 [Source: specs/004-auth-toast]

- 多 Worker 并发确认请求：按到达顺序排队展示，前一个关闭后下一个再显示
- 排队中开启"全部允许"：当前请求放行，队列中尚未展示的请求立即自动放行
- 普通 Toast 与确认浮层共存：独立管理，互不覆盖
- 浮层超时与 Worker 阻塞对齐：浮层超时不晚于 Worker 超时
- 会话切换时存在未决确认：所有未决请求按超时/拒绝语义收敛，不得泄漏到新对话
- "全部允许"安全可见性：开启状态下 Toggle 文案变化
- 手动关闭限制：浮层只能通过三按钮或超时结束
- 非 Assistant Agent 的工具确认：PM/Trial 走 IntentConfirmationUI，不受影响

### 聊天界面体验完善 [Source: specs/006-chat-ui-polish]

- Markdown 含 raw HTML/script 片段：渲染层降级为纯文本，不执行脚本
- Markdown 链接/图片目标安全：只渲染带样式文本和远程 http(s) 图片，不打开浏览器
- 压缩边界与完整聊天记录冲突：工具调用/结果不作为普通聊天记录展示，压缩摘要不可见
- "清空对话"清除旧消息，不在新会话中残留
- Toggle 在会话生命周期边界的瞬态：显隐必须与目标视图严格对齐
- 大规模旧消息性能：初始展示最近 10 条，向上滚动分页加载
- IntentConfirmationUI / ToolExecutionDialog / 普通 Toast 不在本 feature 改动范围
- 顶栏其它控件不受 Toggle 隐藏影响

### 桌面录制 Phase 1 [Source: specs/007-desktop-recording]

- pynput hook 注册失败：阻塞录制启动并弹错；UIA、剪贴板、Ctrl+Alt+S 失败：降级启动并 toast 提示。
- 点"开始"按钮污染首动作：hook / ring buffer / UIA / 剪贴板订阅必须延迟到主窗 minimize 完成回调之后启动。
- 录制启动后马上产生首动作：前置帧取 ring buffer 里所有可用帧，不补帧、不等齐 1 秒。
- 多显示器和拖拽跨屏：每条 action 记录动作时刻 `monitor_index`；drag 使用 mouse_up 终点屏幕、坐标和时间。
- `vision_model` 缺失：`analyze_desktop_action` 不注入工具集，设置页说明和 intent 页一次性 toast 提示降级。
- vision timeout / unauthorized / failed：`analyze_desktop_action` 在对应 action 段返回 `[error: <reason_code>]`，与成功段拼接为同一字符串。
- Trial 子进程超时：120s 后 terminate 并用 `taskkill /F /T` 兜底，Toast 标题为"试用超时"。
- Trial stdout 无有效末行 JSON：runner 用 stderr 末 5 行生成失败摘要，完整 stdout/stderr 保留在 `data/trials/<trial_id>/`。
- 三模式并发尝试：UI 禁用和业务拒绝双保险；互斥判定不依赖崩溃残留 DB 行。
- 录制中崩溃：Phase 1 不自动恢复或清理 `desktop_recordings` 与录制目录，用户手动清理；Trial 调试目录 7 天 startup cleanup 是独立边界。

### UI Stack Redesign [Source: specs/008-ui-stack-redesign]

- Sidecar 启动失败：Tauri shell 保持可恢复失败状态，不静默退出或显示空白应用。
- runtime token 缺失、过期或错误：API/event stream 必须拒绝请求，前端只展示可恢复连接错误，不泄漏 token。
- 设计控件没有真实后端能力：必须禁用/移除并给出真实不可用状态，或接入真实业务验证错误，不允许 no-op。
- backend 事件流断开：前端应保留当前屏幕状态并显示 degraded/retry 状态，后端仍以 `src/utils/events.py` 为事件来源。
- 大量聊天历史：初始显示最近页，向上分页；不得把工具调用、压缩摘要或归档状态当作普通聊天消息。
- 密钥设置更新失败：UI 不能回显明文 secret；失败只返回脱敏状态与业务错误。
- legacy PyQt 正常入口被调用：应显示 legacy 失败/迁移提示或被 guard 阻断，不得启动维护中的旧 UI。
- 旧本地数据存在但不迁移：新 shell 可按 fresh-install 验收，但启动不得静默删除、改写或腐化这些数据。

---

## Frontend Event Layer [Source: specs/009-frontend-event-layer]

完整 User Stories、FR、Key Entities、CC、SC 和 Edge Cases 见 `specs/009-frontend-event-layer/spec.md`。这里只摘录最稳定的契约。

### User Stories

- **US-026 (P1)**: 前端只消费明确的界面事件——所有 frontend store 展示行为基于注册过的 UI event type，不再依赖内部 blinker 事件名或 `sourceEvent`。
- **US-027 (P2)**: 事件流断开后界面能恢复权威状态——重连按 `sessionId + last-seen sequence` 回放；缺口、会话不匹配或 buffer 丢失 → `backend.resync_required` → 拉权威快照。
- **US-028 (P3)**: 需要用户确认的试用预览安全闭环——广播 + first-decision-wins，每条带 `expires_at`；超时、断连、关闭 fail-closed 当拒绝。
- **US-029 (P4)**: 开发者能验证事件契约没有漂移——契约一致性测试 + guard 测试覆盖未注册事件、旧来源字段、敏感字段泄露。

### Key Contracts

- **UI Event Registry**：后端 `src/desktop_api/ui_events.py` 是公开事件 type、payload 形状、enum 的权威来源；前端类型由它生成或校验。
- **UI Event Envelope**：`eventId / sequence / sessionId / causationId / type / scope / payload / createdAt`。
- **Subscriber**：每个订阅者独立队列；订阅者积压超阈值单独被踢，不阻塞其他订阅者和发布者。
- **Interactive Request**：带后端生成的 `expires_at` + 单次消费决策语义；后续重复或冲突决策返回已解决/冲突，不能改变结果。

### Constraints & Compatibility

- **CC-044**: 后端 blinker 仍是跨模块通知来源；business/execution/recording/data 不依赖前端 UI 或 event-stream 投递。
- **CC-045**: 前端不得读 Repository、local DB 或 config 来补偿缺失的事件数据。
- **CC-046**: sidecar event stream 必须带 runtime session header；token 不进 URL、cookie、持久化、日志、event payload 或错误响应。
- **CC-047**: 单次最终契约切换；不维护新旧事件契约并行。
- **CC-048**: UI 事件是会话内通知，不是持久业务事实，不是长期 replay log。

### Success Criteria

- **SC-059**: 100% frontend display 决策（teaching/recording/trial/skills/compositions/settings/assistant/backend resync）基于注册过的 UI event type。
- **SC-060**: 0 未知内部事件默认转发到前端事件流。
- **SC-061**: 两订阅者至少 20 trial 收到同一事件，无 event stealing。
- **SC-062**: 慢订阅者单独 resync 不影响 healthy 订阅者继续接收。
- **SC-063**: 重连恢复至少 10 个 disconnect-resync 周期，无状态回退。
- **SC-064**: 100% UI event payload example 通过 token/secret/code/command/stack/db path/raw recording 安全校验。
- **SC-065**: trial preview 6 种结果（approve/deny/timeout/disconnect/overflow/shutdown）确定性发生，非 approve 一律按拒绝处理。
- **SC-066**: 契约一致性测试发现任何只存在于后端或只存在于前端的 UI event type。

---

## Assistant Brain Redesign [Source: specs/010-assistant-brain-redesign]

完整 User Stories、FR、Key Entities、CC、SC 和 Edge Cases 见 `specs/010-assistant-brain-redesign/spec.md`。这里只摘录最稳定的契约。

### User Stories

- **US-030 (P1)**: 跨对话延续的工作记忆——Segment 沉淀写入 hot/persistent zone；冷启动走 icebreaker；防抖期内回到同一对话继续不提前封存。
- **US-031 (P2)**: 永久身份 + 可回溯历史档案——assistant 画像迁入 persistent zone；archive zone 按时间/主题轴聚合，显式 `retrieve_archive` 下钻。
- **US-032 (P3)**: 100% 调度 + 可复用 specialist——任务派给临时 subagent 或固定专员；主助理不直接执行；PM/Programmer/Trial 不在 assistant 调度池。
- **US-033 (P4)**: 避坑（failure zone）+ 人格感知（subconscious zone）+ 自我校准（prediction zone 后台 worker 自动验证 hit/miss/partial/expired）。
- **US-034 (P5)**: 自动招募 specialist + 大脑管理模块（`/brain`、`/brain/specialists`）覆盖 6 zone 编辑 + skill pool。

### Key Entities

- **Cognitive Zone**：6 个：hot（当前生活语境）、persistent（永久事实 + 稳定长期经验）、archive（按时间/主题分层的历史索引）、subconscious（隐性人格特征 + 反感、参考性而非规则）、failure（带 scope 的硬伤教训）、prediction（可验证的自校准预测）。
- **Memory Entry**：含 content、`status`（`active` / `fading` / `invalidated` / `soft-deleted`）、`entry_type`（`event` / `insight`，决定衰减路由）、`origin`、`reason`、`applicable_scope`、`loaded_count`、`referenced_count`、`superseded_by`、时间戳；prediction 额外含 `verification_checkpoint` / `verification_status` / `verification_rationale`。
- **Segment**：一段 open-to-close 对话；状态 `pending` / `distilling` / `completed` / `failed`；`open` 态不持久化；CAS 状态转换；崩溃时 `distilling` 回 `pending`，重试计数器不变。
- **Distillation**：单次结构化 LLM 调用，phase-aware schema；entries INSERT + 状态转换在单事务内；all-empty 触发一次重试，仍空标 `failed`。
- **Specialist**：persistent named executor，含 role、tool whitelist、origin、reason、version history；白名单必须是 skill pool 子集；软删除 `is_active=0`，版本历史保留。
- **Ephemeral Subagent**：单次、无名、不持久化的执行体。
- **Reason**：每个自动产物必须附 traceable 解释，默认展开不折叠。
- **Recruitment Signal**：后台检测到的派发模式信号，驱动自动招募 specialist。

### Constraints & Compatibility

- **CC-049**: 复用现有 AgentLoop 作为 assistant、subagent、specialist 的执行引擎；不替换。
- **CC-050**: 不改变 PM / Programmer / Trial 录制流水线 Agent 或其编排链。
- **CC-051**: 不引入新中间件（MQ、cache、message bus、vector DB）；复用现有 DB 队列 + background worker 模式。
- **CC-052**: 既有 assistant 画像迁入 persistent zone，过渡保持后向兼容。
- **CC-053**: distilled data 永不物理删除——invalidation 是降权，user delete 是 soft-delete，user edit 是新条目 + `superseded_by` 链。
- **CC-054**: brain `decay/top-N/debounce/idle/retry/limit/periodic` 数值是占位符，待实测调整；稳定契约是 zone set、entry 属性、触发条件和行为保证。
- **CC-055**: 分阶段交付（5 个 user story 独立可发布）。
- **CC-056**: 高危确认语义对 executor 执行的任务保持不变。
- **CC-057**: brain zone 数据不额外加密；与现有消息历史共享 OS 文件系统 + SQLite 安全边界。

### Success Criteria

- **SC-067**: 用户关闭对话后回来，10 次试验至少 9 次 assistant 引用上一段脉络无需复述。
- **SC-068**: 任务样本（≥10 个）中至少 9/10 触发派发，0 个 accepted run 让 assistant 直接执行；纯对话不计入。
- **SC-069**: Segment 封存后沉淀产物在下一轮对话对 assistant 可用，用户无需手动步骤。
- **SC-070**: 100% 自动产物展示具体可追溯的 reason。
- **SC-071**: 新用户回答最多 2 个问题就能进入正常使用，无表单或 onboarding wizard。
- **SC-072**: 用户可在大脑管理模块定位并编辑/删除 6 zone 任一 entry。
- **SC-073**: 持续派发同类任务后，一个招募扫描周期内自动创建 specialist 并附 reason。
- **SC-074**: 每个 prediction entry 可验证——含具体声明，到验证点后得到 hit/miss/partial/expired 状态。
- **SC-075**: 系统永不物理删除 distilled data；找不到 active 结果时仍返回 invalidated entry + invalidation factor。
- **SC-076**: 大脑管理模块对任何自动产物 0 弹"是否要…"确认。
- **SC-077**: 既有 assistant 画像数据在 brain 启用后出现在 persistent zone，display name/style/notes 无丢失。
- **SC-078**: PM / Programmer / Trial 录制流程在重构后无可见回归。

### Edge Cases

- 冷启动 6 zone 全空：走 icebreaker，1-2 个核心问题，绝不展开问卷；无 onboarding 引导。
- Segment 强制切：消息量/token 触达上限立即封存（不走防抖期）。
- 沉淀失败（schema 不符）：超过重试上限 Segment 置 `failed`（不产生 Memory Entry），管理界面"沉淀失败可手动重试"。
- 崩溃后 `distilling` 残留：启动扫描重置回 `pending`，重试计数不变；崩溃属基础设施失败不计入内容质量配额。
- 进行中（`open` 态）Segment 崩溃：不持久化为 DB 行，由消息表推导；下次会话边界正常封存。
- 复活推翻型：旧记忆不物理撤销，产生失效信号、被标记为已被覆盖。
- 检索无 active 结果：仍返回失效条目并标失效系数。
- 临时 subagent 对话：不进入归档与沉淀分析。
- 历史会话迁移：brain 启用前的既有会话不自动批量沉淀，仅最底层档案可检索。
- 用户沉默：既不计入正向也不计入反向信号。
- specialist 白名单越权：必须是 skill pool 子集。
- 潜意识误判：用户在管理界面删除条目，作为"判断偏了"反向信号写入 `feedback_signals`。

---

## 子代理可唤回机制 [Source: specs/013-subagent-resumable]

### User Stories

- **US-035 (P1)**: 迭代超限后唤回续跑——临时子代理撞迭代上限不丢工作，转可唤回暂停；主代理凭 `subagent_id` 唤回从断点续跑直至完成，可重复唤回。
- **US-036 (P1)**: 调用失败后保活、待恢复再续——账单/网络类 LLM 调用最终失败时子代理原地冻结保活、暂停原因可区分；外部恢复后（含进程重启）凭 `subagent_id` 唤回续跑。
- **US-037 (P2)**: 诊断"任务复杂"还是"走弯路"——主代理在不消耗额外模型调用的前提下查看子代理工作概览（轮数/工具调用次数/最后产出/状态），据此决定续跑还是新开。
- **US-038 (P3)**: 对已完成但未达标的结果返工——对已正常完成的子代理带追加指令唤回，在原有上下文基础上补齐返工，不从零重派。

### Functional Requirements

- **FR-146**: 临时子代理达到迭代上限而未完成时，系统 MUST 将其转为"暂停（可唤回）"状态并完整保留其工作历史，而非作为失败丢弃。
- **FR-147**: 临时子代理的模型调用经既有重试后仍最终失败（账户配额/账单超限、网络持续中断等）时，系统 MUST 将其转为"暂停（可唤回）"状态并保留工作历史，而非作为错误丢弃。
- **FR-148**: 暂停结果 MUST 携带可区分的**暂停原因**，至少区分"迭代超限"与"调用失败（账单/网络）"两类，使主代理能采取不同策略。
- **FR-149**: 委派与暂停结果 MUST 返回一个**子代理标识符**，供后续查看与唤回使用。
- **FR-150**: 主代理 MUST 能获取指定子代理的**工作概览**：迭代轮数、调用过的工具及次数、最后一次产出、当前状态；该操作 MUST NOT 触发额外的模型调用。
- **FR-151**: 主代理 MUST 能**唤回**任意属于自己的子代理继续执行，包括因中断而暂停的、以及已正常完成的；唤回时 MUST 允许附加可选的追加指令。
- **FR-152**: 唤回 MUST 基于**持久化的工作历史**恢复，不依赖应用进程内存；即使期间进程重启，凭子代理标识符仍可唤回。
- **FR-153**: 唤回与查看 MUST 校验子代理**归属**，拒绝针对"非当前主代理派出的会话"的访问，且不得泄露其内容。
- **FR-154**: 被唤回的子代理若再次中断（超限或调用失败）MUST 仍可被再次唤回（支持重复唤回）。
- **FR-155**: 系统 MUST 在主代理的决策层提供明确**引导**，使主代理知道：暂停后先查看概览诊断、任务复杂则续跑、走弯路则新开、账单/网络类失败需等恢复、已完成但未达标可带指令返工。
- **FR-156**: 对**非临时子代理**的其它 agent，迭代超限与调用失败的既有处理行为 MUST 保持不变（无回归）。

### Key Entities

- **Subagent Work Session (可唤回语义)**：一次委派对应的、持久化的子代理对话历史。关键属性：子代理标识符（= executor session id）、归属主代理（`workflow_id` 格式 `dlg_{parent[:12]}_{16hex}`）、当前状态（`active` / `suspended` / `completed` / `failed`）、可用工具范围。暂停时 `active → suspended`，唤回时 `suspended/completed/failed → active`。承载于既有 `sessions` / `messages` 行，无新表。 [Source: specs/013-subagent-resumable]

- **Pause Reason**：描述子代理为何暂停的字符串，至少两类：`"已达迭代上限（{N} 轮）"` 和 `"LLM 调用失败（账单或网络），可恢复后续跑"`。主代理据 reason 走不同策略。承载于 `AgentResult.error` → 工具返回 `reason`。 [Source: specs/013-subagent-resumable]

- **Work Overview**：对子代理工作会话的机械式只读摘要——迭代轮数（`assistant_turns`）、各工具调用次数（`tool_call_counts`）、最后产出（`last_output`）、状态（`status`）。由 `_inspect_subagent` 从 `MessageRepository` 聚合返回，不含模型再加工，零模型调用。 [Source: specs/013-subagent-resumable]

- **ResultType.PAUSED**：`config.py` 枚举新值 `paused`，表示会话已置 `suspended`、工作历史保留、可唤回。 [Source: specs/013-subagent-resumable]

- **AgentConfig.resumable_on_failure: bool = False**：为真时 AgentLoop 把"迭代上限/LLM 调用最终失败"转 `PAUSED`；默认假保证非临时 Agent 零回归。 [Source: specs/013-subagent-resumable]

### Constraints & Compatibility

- **CC-058**: 子代理工作历史 MUST 依赖持久化会话存储而非进程内存，以保证跨进程重启的可唤回性（支撑账单超限等长时间等待场景）。
- **CC-059**: "100% 调度"约束不变——主代理本体不直接执行任务，唤回的仍是子代理；本特性不引入主代理直接执行的路径。
- **CC-060**: 已沉淀/会话数据"不物理删除"的原则不受影响——唤回是基于既有历史的恢复，不删除、不改写历史条目。
- **CC-061**: 默认 agent 的中断处理不得回归（见 FR-156）。

### Success Criteria

- **SC-079**: 子代理被迫中断后，其已完成工作 100% 保留并可唤回继续——零工作丢失。
- **SC-080**: 主代理唤回一个暂停子代理时，无需重述原始任务即可让其从断点继续（恢复不要求重新铺垫上下文）。
- **SC-081**: 因账单/网络失败而暂停的子代理，在外部条件恢复后（含应用进程已重启的情况）仍可被成功唤回。
- **SC-082**: 主代理可在**不消耗任何额外模型调用**的前提下获取子代理工作概览。
- **SC-083**: 同一子代理支持被多次重复唤回（续跑→再暂停→再续跑）直至完成。
- **SC-084**: 对非临时子代理的其它 agent，迭代超限与调用失败的处理行为零变化（既有相关测试全部通过）。
- **SC-085**: 针对非本主代理派出的会话标识符的查看/唤回请求，100% 被拒绝且不泄露其内容。

### Edge Cases

- **重复唤回**：续跑后再次中断（超限或失败）→ 仍可被再次唤回，次数不设硬上限（由主代理判断停止）。
- **唤回不存在/非己出的子代理**：标识符无效，或指向并非"当前主代理派出"的会话 → 系统拒绝唤回/查看，返回明确错误，绝不泄露他人会话内容。
- **续跑时上下文过长**：子代理历史很长导致单次上下文偏大 → 由既有的上下文管理（按需压缩）处理；注意账单类失败属于配额问题，压缩不能解决，需等外部恢复。
- **唤回一个仍在运行的子代理**：标识符指向尚未停止的会话 → 拒绝并发唤回，提示当前不可恢复。
- **空产出的暂停**：子代理几乎没产出就暂停（如第 1 轮即调用失败）→ 概览如实反映（轮数极少、无有效产出），主代理据此多半选择重新委派。
- **不可恢复的 LLM 错误**：400 bad request、凭据配置错、序列化 bug 等异常不可恢复 → 仍走 `ERROR` 置会话 `failed`，不转 PAUSED，主代理不被误导"等恢复后再续"。
- **已完成子代理不带 instruction 唤回**：`_continue_subagent` 回明确提示"需带 instruction 说明要补齐/修正什么"，不执行模型调用。

---

## 主助理对话透明与可控 [Source: specs/014-assistant-chat-transparency]

把 AI Assistant 主屏从"黑盒运行"扩展为看得见、停得下、接得上的透明对话体验。范围包括运行时输入门控、协作式深度取消、单条原地排队、默认折叠的活动时间线、子任务卡片与详情，以及暂停子任务的继续任务入口。

### User Stories

- **US-039 (P1)**: 运行时不被误唤醒，并且随时能停——助理正在处理时不能再次被新消息误唤醒；用户点击停止后，当前回合和同步派出的子任务都在安全节点进入可恢复暂停，已产内容保留。
- **US-040 (P2)**: 它忙的时候，我可以先把下一句想好——每个会话只保留一条可原地编辑的排队消息；回合成功或等待用户回答时自动发出，失败或停止时退回普通草稿。
- **US-041 (P2)**: 看得见主助理自己的思考过程——每个回合实时显示可展示的模型过程、工具动作和工具结果；过程区域默认折叠、限高内滚，历史回看可重建。
- **US-042 (P2)**: 看得见它派出去的子任务在干什么——当前对话显示子任务卡片、状态和完整过程详情；断连或重开后通过权威端点恢复列表与状态。
- **US-043 (P3)**: 被打断/暂停的子任务能接着干——暂停子任务提供继续任务操作，可带补充消息，并经主助理调度既有 `continue_subagent` 完成续跑。

### Functional Requirements

- **FR-157**: 当助理处于 `running` 状态时，系统 MUST 阻止用户发出会再次唤醒助理执行的新消息。
- **FR-158**: 当助理处于 `waiting_for_user` 状态时，系统 MUST 允许用户正常输入并回答，不施加运行态门控。
- **FR-159**: 输入控件可用性 MUST 由助理真实运行状态驱动，而非一次发送请求的瞬时状态驱动。
- **FR-160**: 助理正在处理时，用户 MUST 能触发停止来中断当前回合。
- **FR-161**: 停止 MUST 同时作用于该回合派出的正在运行子任务，使父子执行链一并停下。
- **FR-162**: 停止 MUST 为协作式取消，在下一个安全节点生效，不采用强制杀线程或杀进程。
- **FR-163**: 用户点击停止后，系统 MUST 立即进入可见的"停止中"反馈；重复点击 MUST 幂等。
- **FR-164**: 若停止发生时存在 pending 高危确认，系统 MUST fail-closed 当拒绝并唤醒回合到取消检查点，同时保留 first-decision-wins / `expires_at` 同步确认协议。
- **FR-165**: 用户主动停止 MUST 视为可恢复暂停而非错误；被停止的会话与子任务保留已产生的工作并可后续继续。
- **FR-166**: 停止后对话 MUST 回到可继续/就绪态，且已产生内容保留在对话历史中。
- **FR-167**: 助理忙时提交的下一条消息 MUST 进入排队待发；回合成功或等待用户回答时自动发出，回合失败或被停止时退回草稿。
- **FR-168**: 系统 MUST 对每个会话仅保留一条生效待发的排队消息，后续输入修改同一条。
- **FR-169**: 排队消息 MUST 归属所在会话，并在切换会话后再切回时保留。
- **FR-170**: 排队消息 MUST 可原地编辑；输入框进入排队态，双击和键盘可达入口都能进入编辑态。
- **FR-171**: 排队消息处于编辑态时 MUST NOT 被发出，即使此刻助理已空闲。
- **FR-172**: 用户按回车或使输入框失焦 MUST 被视为编辑完成，消息恢复排队待发。
- **FR-173**: 自动发出 MUST 仅针对已提交排队消息，编辑态消息不参与自动发出。
- **FR-174**: 对每个助理回合，系统 MUST 实时呈现可取得的完整过程，包括模型过程文本、采取的动作和动作结果；工具结果经既有敏感字段过滤后尽量完整展示。
- **FR-175**: 过程区域 MUST 默认折叠、不自动展开，用户可手动展开/收起。
- **FR-176**: 助理最终回复 MUST 正常显示，且 MUST NOT 在过程区域中重复出现。
- **FR-177**: 过程区域 MUST 限定高度，超出时内部滚动，不撑长整页。
- **FR-178**: 历史会话 MUST 可展开回看回合过程；详细步骤仍在时展示全过程，已压缩/概要化时展示规整概要，不隐藏、不报错且不新增持久化要求。
- **FR-179**: 助理把任务派给子助手时，系统 MUST 在当前对话中以卡片呈现子任务，显示任务描述和状态。
- **FR-180**: 子任务卡片 MUST 实时反映状态变化，运行中 SHOULD 有可感知动效。
- **FR-181**: 用户双击或通过键盘可达入口打开子任务卡片详情时，系统 MUST 展示该子助手自己的完整过程，包括工具调用与过滤后的完整结果。
- **FR-182**: 子任务信息 MUST 归属并显示在发起它的当前对话中。
- **FR-183**: 重连或重新打开会话时，系统 MUST 能取到该会话子任务的权威列表与状态。
- **FR-184**: 处于暂停状态的子任务卡片 MUST 提供继续任务操作。
- **FR-185**: 继续任务 MUST 通过唤醒主助理并由主助理续跑目标子任务实现，不能让用户直连操纵子任务。
- **FR-186**: 用户 MAY 在继续任务时附加补充消息；若提供，该消息 MUST 被一并带入续跑。
- **FR-187**: 子任务正在运行时，继续任务 MUST 不可用；系统 MUST 校验子任务归属，拒绝非当前对话子任务访问或操纵。
- **FR-188**: 继续任务触发后，系统 SHOULD 校验目标子任务确实转为运行；若主助理未续跑目标子任务，MUST 给用户明确兜底提示而非静默无反应。

### Key Entities

- **Turn**：一次"用户消息 → 助理过程 → 最终回复"的展示单元，承载过程步骤、子任务和回合状态。
- **Activity Step**：助理或子助手的一步活动，类型为 `reasoning` / `tool_call` / `tool_result`，可归属于主助理或某个子任务。
- **Subagent Task**：助理委派出的执行单元，含任务描述、状态、过程和产出；状态包括 `running` / `done` / `suspended` / `failed`。
- **Queued Message**：每会话唯一的下一条待发消息，状态为 `editing` 或 `queued`，属于前端临时意图，不持久化到后端。
- **Run Context / Cancellation Registry**：业务层 ContextVar 运行上下文与进程内 session→Event 注册表，支持协作式深度取消和代际 token 防陈旧取消。
- **ResultType.CANCELLED**：用户主动停止产生的显式结果类型，语义为可恢复暂停，不能与不可恢复错误混同。

### Constraints & Compatibility

- **CC-062**: MUST 保留既有高危确认同步确认协议与会话级免确认语义，不得回归 first-decision-wins、`expires_at` 或 fail-closed 行为。
- **CC-063**: MUST 保持办公助理 100% 调度约束；主助理不直接执行任务，继续任务也经由主助理调度子任务完成。
- **CC-064**: 取消 MUST 为协作式且类型安全，不得把用户主动停止与不可恢复错误混为一谈，也不得硬杀线程。
- **CC-065**: 面向前端的新事件 MUST 经 UI Event Registry 注册后以受控 typed envelope 发出；前端不得依据内部事件名或未注册载荷做展示决策。
- **CC-066**: 非助理执行链路（技能教学、学习、试用、PM、Programmer、Trial）MUST 零行为变化。
- **CC-067**: 大脑沉淀数据永不物理删除等既有数据约束 MUST 不被破坏；本特性只读重建历史过程和子任务列表，不新增物理删除路径。
- **CC-068**: 本特性不为外部脚本/API 消费者新增 deprecation、双发或额外兼容范围；当前边界是单用户本地桌面应用。

### Success Criteria

- **SC-086**: 助理 running 期间误唤醒发生率为 0；waiting_for_user 状态下输入 100% 可用。
- **SC-087**: 点击停止后 UI 约 200ms 内进入停止中反馈；当前回合在当前步骤后的下一个安全节点停止并回到就绪态，且父子链无"主停子未停"残留。
- **SC-088**: 排队消息在助理空闲或等待用户回答后自动发出；编辑态排队消息提前外发为 0。
- **SC-089**: 用户可查看每个助理回合与被委派子任务的过程；运行时展示完整过程，历史回看展示全过程或规整概要。
- **SC-090**: 被停止的子任务可被继续任务续跑并完成，续跑结果以主助理正常回复呈现。
- **SC-091**: 停止/中断后，对话历史 100% 保留已产生内容。
- **SC-092**: 非助理流程上线前后行为一致，相关回归用例 100% 通过。
- **SC-093**: 除过程区域原样展示的内容外，普通界面文案中不出现 archive、compression、segment、event sequence 等内部机制术语。

### Edge Cases

- `waiting_for_user` 不算忙，用户必须能回答反问。
- 停止是协作式取消，当前慢步骤返回前不会硬中断；生效前重复点击保持幂等。
- 停止不等于失败，进度状态使用 `cancelled` 并保留可恢复线索。
- 排队消息在失败或停止后退回普通草稿；编辑态不自动外发。
- 历史回合已压缩时，展开过程显示规整概要，不新增持久化。
- 单回合过程项很多时，过程区域内部滚动；活动事件有上限/合并策略并走 payload safety allowlist。
- 事件流缺口或会话不匹配时，前端按 `backend.resync_required` 拉权威快照，不凭内部事件猜测状态。
- 停止遇上 pending 高危确认时，确认 fail-closed 当拒绝并唤醒回合到取消检查点。

## Agent Built-in Tools Upgrade [Source: specs/015-agent-builtin-tools-upgrade]

**Revision note (2026-06-09)**: Archived merged feature 015 into main memory; continued requirement, compatibility, and success-criteria numbering from the existing project memory.

### User Stories

- **US-044 (P1)**: Agent 可以安全检查文件内容，以有界窗口、行范围、继续读取元数据和敏感值脱敏来理解上下文，不把大文件、二进制或媒体原文塞进会话。
- **US-045 (P1)**: Agent 修改文件前必须证明它观察过当前内容；既有文件写入、编辑、删除和 patch update/delete 使用 raw-byte baseline 防止 stale mutation。
- **US-046 (P2)**: Agent 可以通过结构化 `search_files` / `search_content` / `apply_patch` 完成仓库搜索和多文件变更，结果有分页、忽略目录、验证状态和稳定错误码。
- **US-047 (P2)**: Agent 可以区分同步命令和长运行进程，启动、轮询、读取日志、等待、停止、发送输入和关闭当前 sidecar 进程会话内的 background process。
- **US-048 (P3)**: 大工具输出在进入 Agent 会话前压缩为安全摘要，完整原文通过持久 `ToolOutputReference` 按授权恢复，跨 sidecar 重启仍受 retention 与 cleanup 约束。

### Functional Requirements

- **FR-189**: 系统 MUST 为升级后的内置基础工具提供稳定结构化成功/失败 envelope，包含工具身份、outcome、可行动 payload、permission scope、truncation/limits、verification、reference 和稳定错误码。
- **FR-190**: 受影响的内置工具调用方 MUST 在对应交付 slice 内迁移到新 contract；本 feature 不保留 legacy 参数或结果格式兼容作为验收要求。
- **FR-191**: 文件、搜索、patch、删除和命令执行 MUST 在任何副作用前解析到 authorized workspace 边界并分类；workspace 外读取只可走高危确认，workspace 外写入、删除、patch 和执行一律拒绝。
- **FR-192**: `read_file` MUST 支持有界文本窗口、行号/范围、总量/剩余信息、继续读取元数据和大文件明确行为。
- **FR-193**: 二进制或不支持媒体读取 MUST 返回元数据或 unsupported outcome，不得把 raw bytes/base64 放入 Agent 可见文本。
- **FR-194**: 文件读取、命令输出和可见工具结果 MUST 脱敏常见凭据样式，同时保留继续处理所需上下文。
- **FR-195**: 同一运行中重复读取相同有界窗口 MUST 返回 loop-prevention metadata，但不得阻断有意的后续读取。
- **FR-196**: 文件创建和替换 MUST 做写后验证和变更摘要；新文件可无 baseline，替换既有文件必须要求当前 baseline，除非未来另有显式 force mode、确认和测试。
- **FR-197**: 既有文件 replace/edit/delete/patch update/delete 在缺 baseline 或 baseline stale 时 MUST 在落盘前拒绝，并提示重新读取当前内容。
- **FR-198**: `edit_file` MUST 支持单个或多个不重叠 replacement，以及显式 replace-all 模式。
- **FR-199**: 文件编辑 SHOULD 保留可检测的原始文本风格，包括 newline、BOM/final newline 和 leading marker。
- **FR-200**: 编辑失败 MUST 返回附近候选位置或可行动诊断，并建议读取合适窗口后重试。
- **FR-201**: `apply_patch` MUST 支持 workspace 内 add/update/delete 的多文件 patch，在 mutation 前做 dry-run-equivalent validation，update/delete 要求 baseline，并在 mutation 后验证。
- **FR-202**: `search_files` MUST 返回有界、确定性排序的文件名结果，默认排除常见 generated/dependency 目录，并提供 continuation metadata。
- **FR-203**: `search_content` MUST 返回按文件分组的匹配、行号、可选上下文、多种输出模式、有界结果和 continuation metadata。
- **FR-204**: 内置工具和命令请求 MUST 有统一 risk classification，使 read-only、workspace mutation、elevated-risk 动作可被一致允许、确认或拒绝。
- **FR-205**: 高危确认 MUST 保留既有 fail-closed 语义；确认不可用、中断、超时或断连时拒绝动作。
- **FR-206**: `exec` MUST 返回 status、exit outcome、timeout classification、有界 stdout/stderr、truncation 信息和可用 raw-output reference metadata。
- **FR-207**: 后台 process lifecycle 工具 MUST 支持当前 sidecar 进程会话内的 list/poll/logs/wait/stop/send-input/close。
- **FR-208**: 系统 MUST 在 Agent 尝试继续或查看既有长运行进程时防止重复启动相同 background process。
- **FR-209**: 大工具结果进入 Agent 会话前 MUST compact，并在需要时保存可持久恢复的 raw-output reference，同时保留关键成功/失败事实。
- **FR-210**: 每个执行、拒绝、中断、压缩、fallback 或失败的 tool call MUST 仍只产生一条配对 tool result。
- **FR-211**: full raw output、media payload 和敏感本地细节 MUST 不进入普通 Agent 可见文本；只能经授权 reference-loading path 显式读取，且受 retention/cleanup policy 管控。
- **FR-212**: 工具 envelope MUST 暴露足够调试和测试的 metadata，包括 permission、truncation、compression mode、verification、error code 和 artifact reference。
- **FR-213**: 自动化覆盖 MUST 包含文件读取、文件 mutation、搜索、patch、命令执行、process lifecycle、权限边界、confirmation fail-closed 和 tool-result compaction。
- **FR-214**: tool caps、retention、workspace policy、process limits 和 output governance 的运行时 tunables MUST 通过统一配置边界定义，或显式标记为有理由的 fixed constants。
- **FR-215**: 系统 MUST 提供 log-safe runtime health metadata，覆盖 compacted output、raw-reference create/load failure、stale mutation rejection、process cleanup、confirmation fail-closed 和 retention cleanup failure。

### Key Entities

- **Built-in Foundational Tool**: Agent 共享的文件访问、搜索、patch、命令执行、process lifecycle 或 output recovery 能力。
- **Tool Result Envelope**: 升级后内置工具的统一可见结果，包含 outcome、payload、error、permission、limits、references、warnings 和 verification。
- **Authorized Workspace**: 常规文件读写、搜索、patch 和命令执行允许所在的会话工作区边界。
- **Permission Decision**: 工具请求的 scope、risk、decision、safe summary 和 stable reason。
- **File Baseline**: Agent 先前读取内容对应的 raw-byte hash/metadata，用于既有文件 stale mutation detection。
- **Process Record**: 当前 sidecar 进程会话内可管理的后台命令记录；重启后旧记录不可当作 live process 管理。
- **Tool Output Reference**: 持久 raw output/media metadata 指针，普通可见结果只暴露 opaque reference、大小、类型、digest 和过期信息。
- **ToolOutputRepository**: 管理 raw-output reference SQLite metadata 的 Repository 边界；blob 路径不进入业务可见文本、普通日志或 UI event。

### Constraints & Compatibility

- **CC-069**: 015 对 handler 参数和结构化 envelope 的升级范围仅限 Agent 内置 foundational tools；用户创建的业务工具、录制 workflow tools 和 specialist methodology assets 不采用该 handler 契约。016 仅把共享的保存时文本结果治理扩展到 legacy/custom 工具结果，不改变其 handler 参数、权限或业务语义。 [Updated by Source: specs/016-tool-output-semantic-summary]
- **CC-070**: AgentLoop 既有 tool-call/tool-result pairing 语义 MUST 保持，单工具和多工具轮次都不得出现孤立 tool result 或重复配对。
- **CC-071**: 高危确认必须继续是 session-scoped、fail-closed，且"全部允许/免确认"不得持久化到配置、SQLite 或 DuckDB。
- **CC-072**: permission 和 confirmation summary 不得包含完整文件内容、完整替换文本、完整多行命令、凭据或 raw large output。
- **CC-073**: UI 和 desktop API 不得直接管理内置工具执行状态；未来可见状态必须走既有 bridge 和 UI Event Registry 公开契约。
- **CC-074**: 新增 retention、threshold、workspace/output cap 配置必须走 `get_unified_config()` / `UnifiedConfigManager` 和安全数据边界。
- **CC-075**: 搜索、mutation、patch 和 terminal 能力必须拒绝 workspace 外 mutation/execution；只读外部路径检查是唯一可高危确认的外部路径操作。
- **CC-076**: 每个已交付 tool family 必须完整迁移到新 contract，不能维护 legacy/new 双兼容窗口。
- **CC-077**: workspace 外读取是 exceptional high-risk inspection；工具描述和确认摘要不得鼓励广泛探索本机文件系统。

### Success Criteria

- **SC-094**: 小文本、大文本、二进制、媒体和 secret-like fixture 的读取 100% 返回有界结构化 outcome，continuation、refusal 或 redaction 行为正确。
- **SC-095**: mutation safety 测试中，既有文件 replace/edit/delete/update 缺 baseline 或 baseline stale 的尝试 100% 在内容变更前拒绝。
- **SC-096**: patch boundary 测试中，workspace 外目标的 patch operation 100% 在 mutation 前拒绝。
- **SC-097**: search fixture 默认排除 generated/dependency 目录，每页结果不超过配置 page size，并正确报告 `hasMore` / continuation。
- **SC-098**: 100,000+ 字符命令输出的可见 tool result 保持在配置 conversation cap 以下，并为每个 oversized result 保留可恢复 raw reference。
- **SC-099**: 代表性失败输出压缩后 100% 保留失败项名称、主错误信息和最终摘要。
- **SC-100**: AgentLoop 多工具测试中，执行、拒绝、中断、压缩、失败、跳过和 fallback 的内置工具调用 100% 只有一条配对结果。
- **SC-101**: 高危动作测试中，确认失败、超时或断连 100% 拒绝动作。
- **SC-102**: 每个已交付 tool family 的内部调用方和测试 100% 使用新 built-in tool contract，无 legacy 参数或结果格式依赖。
- **SC-103**: Agent continuation 脚本 100% 能利用 `nextPageToken`、line-window metadata、baseline guidance 和 `load_tool_output` reference 继续完成任务。
- **SC-104**: runtime health 测试证明 compacted output、raw-reference failure、stale rejection、process cleanup、confirmation fail-closed 和 retention cleanup diagnostics 不泄漏 raw secrets 或本地 artifact 路径。

### Edge Cases

- 重复读取同一窗口只给 loop-prevention metadata，不阻断有意 reread。
- 相对路径穿越、绝对路径、隐藏/system/link target 和 symlink escape 必须先解析和分类；外部只读路径需高危确认，外部 mutation/execution fail-closed。
- 多个工具调用并发修改同一文件时必须串行化或拒绝，不能静默覆盖。
- tool result hook、compaction 或 artifact 写入失败时，原始 tool call 仍必须得到 exactly-one safe fallback result。
- background process 超出发起回合但仍在同一 sidecar 会话内时，后续 inspection 能看到 active/completed/timed_out/terminated 状态。
- sidecar 重启后，旧 process id 返回 unavailable-after-restart，不当作可管理 live process。
- raw binary/media output 不进入普通对话文本；只保留受授权和 retention 管控的 reference。

---

## 工具输出语义摘要 [Source: specs/016-tool-output-semantic-summary]

**Revision note (2026-06-11)**: Archived merged feature 016 into main memory; continued user-story, requirement, compatibility, and success-criteria numbering from the existing project memory.

**Credential revision (2026-06-12)**: Removed the external credential-store contract. All credentials now use `UnifiedConfigManager`; `config.json` supplies local defaults and `app_settings` supplies runtime overrides.

### User Stories

- **US-049 (P1)**: Agent 面对大或截断的工具结果时，获得有界 compact envelope，其中确定性 `facts`、`preview`、原始字符数、payload keys 和可授权恢复的 raw reference 不依赖模型可用性。
- **US-050 (P1)**: Agent 可获得固定结构的 advisory 语义摘要，用于快速理解概览、关键发现、错误、重要数据和下一步；无效 JSON、provider 失败、Map-Reduce 失败或超时会确定性省略摘要。
- **US-051 (P2)**: Agent 可通过 `extractionGoal`、`web_fetch.prompt` 或保守推断的常见 goal/query/prompt/pattern 参数，让摘要聚焦当前工具调用目的，而不改变工具执行和权限语义。
- **US-052 (P2)**: 用户可在 Settings“工具输出”分区配置独立低成本摘要模型、兼容端点、温度、预算和独立密钥，并执行不返回模型原文的连接测试；部署方也可通过统一配置文件提供本地默认值。

### Functional Requirements

- **FR-216**: Governance MUST 处理每个文本工具结果，同时保持未触发治理的小型 legacy/custom 结果原格式不变。
- **FR-217**: 原始文本达到 `trigger_chars`、`limits.truncated` 为真、已有 raw reference，或 handler metadata 报告 clipping/truncation 时 MUST 触发 compact。
- **FR-218**: Governance MUST 在 LLM 不可用时仍保留确定性 `preview`、`facts`、`rawChars`、`originalPayloadKeys` 和授权 reference。
- **FR-219**: 不存在可复用 reference 且 artifact 限额允许时，系统 MUST 在语义摘要调用前持久化原始工具结果。
- **FR-220**: 语义摘要失败 MUST 直接省略 `semanticSummary`，不得替换确定性事实或为同一 tool call 创建第二条结果。
- **FR-221**: 语义模型的输入和输出 MUST 脱敏、有界，并始终作为不可信数据处理。
- **FR-222**: 输入超过 `max_input_chars` 时 MUST 按 15% head、35% error context、35% uniform sample、15% tail 的预算选择内容。
- **FR-223**: Map-Reduce MUST 遵守配置的 chunk size、map count、concurrency、token budget 和 total timeout，业务层不得额外重试。
- **FR-224**: `semanticSummary` MUST 标记 `advisory=true`，且 MUST NOT 覆盖已验证的 facts、exit code、错误码或状态。
- **FR-225**: Extraction goal MUST 只影响摘要 prompt，MUST NOT 改变工具执行、权限判断或 handler 语义。
- **FR-226**: 摘要配置及全部高级限额 MUST 通过 `get_unified_config()` / `UnifiedConfigManager` 访问。
- **FR-227**: 独立摘要 API key MUST 使用 `agent_tools.output.semantic_summary.api_key`，只允许通过 `UnifiedConfigManager` 读写，不得回退主模型密钥；`config.json` 提供本地默认值，`app_settings` 可覆盖。
- **FR-228**: 支持的 provider MUST 包含 Anthropic、OpenAI、DeepSeek、Qwen、Zhipu、Moonshot 和 custom OpenAI-compatible endpoint。
- **FR-229**: Runtime health counters MUST 覆盖 attempts、successes、timeouts、partial summaries、invalid summaries、map/reduce failures 和 input characters。
- **FR-230**: 新 provider callsite MUST 注册到 Debug provider inventory 和 Real Grand Tour credential/budget coverage，并使用 trace source `tool_output_summary`。
- **FR-231**: 本特性 MUST NOT 引入数据库迁移；摘要保存在既有 tool-result message 中，raw output 继续由 `ToolOutputRepository` 拥有。

### Key Entities

- **Governed Text Tool Result**: 任意 legacy、custom 或 upgraded 工具产生的文本结果。小结果可保持原格式；达到治理条件后统一进入保存时 compact 流程。
- **Deterministic Compact Envelope**: 有界可见结果，至少包含 `facts`、`preview`、`rawChars`、`originalPayloadKeys` 和可用 reference；这些字段是执行真相，不依赖 LLM。
- **Semantic Summary**: 可省略的 advisory JSON，固定字段为 `overview`、`keyFindings`、`errors`、`importantData`、`nextActions`、`extractionGoal`、`coverage`、`mode` 和 `advisory`。
- **Extraction Goal**: 最长 1000 字符的摘要聚焦提示；来源可以是显式 `extractionGoal`、`web_fetch.prompt` 或 custom tool 常见参数，不传入 handler 执行分支。
- **Semantic Summary Configuration**: `agent_tools.output.semantic_summary.*` 下的 provider/model/base URL/temperature、触发阈值、采样、Map-Reduce、deadline、token 和输出字符预算。
- **Tool Output Summary Credential**: `agent_tools.output.semantic_summary.api_key` 下的独立 secret；由 `UnifiedConfigManager` 按 `app_settings` 覆盖 `config.json` 默认值的规则解析。DTO、日志和 UI 只暴露 masked presence/status；Real Grand Tour 使用相同的只读 getter。
- **Semantic Summary Health Metrics**: log-safe 进程内计数器，记录摘要尝试、成功、超时、部分成功、非法结果、Map/Reduce 失败和输入字符数。

### Constraints & Compatibility

- **CC-078**: 小型 legacy/custom 文本结果在未触发治理时必须保持原格式，避免扩大 016 的兼容性影响。
- **CC-079**: `facts` / `preview` 是确定性权威信息；模型摘要只能辅助阅读，不能成为 exit code、错误码、状态或权限决策的来源。
- **CC-080**: artifact、governance、provider、JSON validation 或 timeout 失败时必须 fail-open 到一个安全、有界、exactly-one 的 tool result。
- **CC-081**: 已授权的现有 raw reference 必须复用；需要新 reference 时必须先完成持久化，再进行摘要调用，摘要失败不得丢失恢复入口。
- **CC-082**: 原始工具输出属于不可信数据；prompt 必须阻止其覆盖摘要协议，输入/输出和最终 compact envelope 都必须执行敏感值脱敏与字符上限。
- **CC-083**: `extractionGoal` 只用于摘要语义，不得进入 workspace policy、高危确认、工具参数改写或业务执行条件。
- **CC-084**: 摘要配置和 secret 必须走 `UnifiedConfigManager`；响应 DTO、UI state 和普通日志不得暴露明文。Real Grand Tour 使用相同的只读 getter；disabled、空 model、缺 secret 或无效 compatible endpoint 时不得发起 provider 调用。
- **CC-085**: 本特性不新增数据库 schema；既有 `ToolOutputRepository`、message persistence 和 exactly-one pairing 边界保持不变。

### Success Criteria

- **SC-105**: 100k、1MB 和超过 artifact limit 的 fixture 均生成不超过 `visible_char_cap` 的可见结果。
- **SC-106**: 位于输出开头、中间或结尾的诊断信息均能被确定性 facts/preview fixture 保留。
- **SC-107**: 摘要成功、provider 失败、非法 JSON、超时和 fallback 场景中，每个 tool call 均只持久化一条结果。
- **SC-108**: 原始 secret 不出现在 semantic prompt、summary、普通日志、UI event 或可见 compact envelope 中。
- **SC-109**: 现有 reference 被复用，且 Repository 重新实例化后仍可按授权加载。
- **SC-110**: 后端设置、统一 secret 存储、连接动作、前端保存/删除/测试和可行动错误展示测试全部通过。
- **SC-111**: `config.json` 默认值、`app_settings` 覆盖、空值清除、DTO 遮罩和普通日志脱敏均有自动化覆盖。

### Edge Cases

- 大 legacy/custom/upgraded 结果都进入 compact；小 legacy/custom 结果保持原样。
- 已有 raw reference 时复用而不重复创建；artifact 超限或存储失败时仍保留有界确定性结果。
- 单块摘要返回非法 JSON、provider 异常或 deadline 耗尽时省略 `semanticSummary`。
- Map-Reduce 允许部分 map 成功后 reduce；所有 map 失败、reduce 失败或总超时均省略摘要。
- 工具输出中的 prompt injection 文本只能作为待总结数据，不能修改固定 JSON 协议或系统指令。
- `load_tool_output` 读取出的第二阶段大结果会再次进入同一治理边界，同时保持授权和可见上限。
- 配置文件密钥作为本地默认值；Settings 写入后由 `app_settings` 覆盖，Settings 删除会写入空覆盖值并屏蔽文件默认值，直到再次保存或显式移除该覆盖。

---

## 大脑记忆质量提示词升级 [Source: specs/020-brain-memory-quality]

**Revision note (2026-06-15)**: Archived the migrated feature into main memory; records the implemented
brain prompt quality rules while preserving the distinction between LLM guidance and deterministic validation.

### User Stories

- **US-053 (P1)**: 办公助理大脑只沉淀未来对话中有决策价值、可减少重复询问或避免重复踩坑的信息；聊天过程摘要、通用知识和缺少证据的宽泛印象被明确列为低质量输出。
- **US-054 (P2)**: 潜意识区只归纳跨对话反复出现、可帮助预判用户取舍的具体行为模式；单次事件、用户已明确表达的偏好和泛化人格标签不构成潜意识模式。
- **US-055 (P3)**: 猜测区只生成具体、可证伪、带验证时机且有多条记忆支撑的未来行为预测；后台验证使用一致的 `hit / partial / miss / expired` 状态语义。

### Functional Requirements

- **FR-232**: Segment 沉淀 prompt MUST 提供面向未来使用价值的筛选标准。
- **FR-233**: Segment 沉淀 prompt MUST 要求记忆自包含且一条只表达一个事实或判断。
- **FR-234**: Segment 沉淀 prompt MUST 明确排除聊天过程摘要、通用知识、无证据宽泛印象和把单次事件误判为稳定偏好等低质量输出。
- **FR-235**: 各 phase 已激活认知分区 MUST 提供可操作的判断问题、适用内容和正反例；低 phase MUST NOT 提前包含未激活分区指导。
- **FR-236**: Prompt MUST 明确允许没有合格内容时返回空数组，不得要求模型为填满分区而提取。
- **FR-237**: 用户反馈信号 MUST 仅作为提取参考，不得要求模型逐条转换为新记忆。
- **FR-238**: 潜意识沉淀 prompt MUST 将跨对话重复证据作为模式判断依据，并要求 `reason` 指明支撑该模式的记忆来源。
- **FR-239**: Prediction 生成 prompt MUST 要求猜测具体、可证伪、带 `verification_checkpoint`，并由至少两条记忆支撑；依据不足时允许空结果。
- **FR-240**: Prediction 验证 prompt MUST 明确定义 `hit`、`partial`、`miss` 和 `expired` 的判定语义，并保持既有前缀解析兼容。
- **FR-241**: `distillation_output`、`subconscious_distillation_output` 和 `prediction_generation_output` 的工具名称、schema、phase 激活范围、Repository 写入、worker 调度、重试和解析行为 MUST 保持兼容。

### Constraints & Compatibility

- **CC-086**: 本特性仅修改 `src/business/brain/` 内部 LLM prompt，不新增 SQLite、DuckDB、Repository、migration、配置、secret、API、事件或前端契约。
- **CC-087**: “至少两条记忆/不同对话证据”属于 LLM prompt 软约束；在 schema 或业务代码加入确定性校验前，不得宣称为运行时硬保证。
- **CC-088**: Prompt 允许诚实返回空数组，但 Segment 仍保留 010 定义的既有 all-empty 一次重试行为。
- **CC-089**: Prompt 更长可以增加少量输入 token，但 MUST NOT 增加额外 LLM 调用、二次模型评审或规则引擎。

### Success Criteria

- **SC-112**: Prompt 回归测试可验证 P1/P2/P4 只包含各自已激活分区及既有结构化输出指令。
- **SC-113**: Prompt 回归测试可验证价值判断、自包含、一条一事、低质量反例、空结果许可和反馈信号边界。
- **SC-114**: 潜意识 prompt 回归测试可验证重复证据规则、排除项和证据来源要求。
- **SC-115**: Prediction prompt 回归测试可验证多条证据、可证伪性、验证点及四种验证状态语义。
- **SC-116**: 既有 brain distillation 和 prediction worker 聚焦测试继续通过，且无 schema 或持久化回归。

### Edge Cases

- 所有候选信息都不值得保存时，结构化输出允许为空；Segment service 仍按既有规则执行一次 all-empty 重试。
- 近期用户反馈信号只影响提取方向，不能被机械复制成新记忆。
- P1/P2 prompt 不包含 P4 的潜意识区和失败区规则。
- 模型可能违反证据数量指导；当前系统依赖结构化 schema 保证形状，不对证据数量做确定性计数。
- Prediction 验证仍依赖既有前缀解析，调用失败继续按既有重试和 `expired` 回退处理。

---

## Desktop UX、Debug Inspector 与真实 Grand Tour [Source: specs/011-desktop-ux-debug-regression]

**Revision note (2026-06-15)**: Backfilled the completed 011 feature. The original keyring-specific
Grand Tour credential design is superseded by the current constitution and 2026-06-14 UnifiedConfigManager migration.

### User Stories

- **US-056 (P1)**: Assistant 与 Skill Teaching 的长文本粘贴会折叠为紧凑预览，同时保留完整草稿、插入位置和发送内容。
- **US-057 (P2)**: 开发者可通过隐藏且鉴权的 Debug Inspector 检视有界 LLM trace、Agent Flow 和当前进程可寻址 reference。
- **US-058 (P3)**: 开发者可手动运行显式 opt-in 的真实 Grand Tour，在隔离数据、费用/时长预算和安全报告边界内验收桌面主流程。

### Functional Requirements

- **FR-242**: Assistant 与 Teaching composer MUST 共享长粘贴折叠规则；只有满足阈值的 paste 自动折叠，手工输入不自动折叠。
- **FR-243**: 折叠状态 MUST 保留完整 draft、既有文本和 selection 插入语义，并展示预览、省略提示和内容大小。
- **FR-244**: 用户 MUST 可通过键盘展开、重新折叠、清空或发送长草稿；发送 MUST 提交完整原文并重置临时展示状态。
- **FR-245**: 系统 MUST 提供不进入普通导航的隐藏 `/debug` 诊断入口，并继续使用 sidecar runtime token 鉴权。
- **FR-246**: Trace capture MUST 默认关闭，仅能在明确敏感信息警告后由 authenticated control 以 runtime-only `debug.trace.enabled` arm；armed 时 shell MUST 显示持续可见的停止入口。
- **FR-247**: Trace 开启时，受支持的文本、tool-enabled 和 vision/multimodal LLM 路径 MUST 产生有界 trace 或明确 omission；媒体只保留不可还原的安全元数据。
- **FR-248**: Trace MUST 记录可用的 source/session/workflow/work-unit 关联；无法关联的调用 MUST 标记 unknown source，不能静默消失。
- **FR-249**: Debug Inspector MUST 支持按 source/work unit 浏览、筛选和展开 trace，并明确标注因预算省略或不可用的内容。
- **FR-250**: Trace 开启且调用方已鉴权时，Debug Inspector MUST 可展开当前进程仍可寻址的 reference；响应必须有界并执行同等脱敏。
- **FR-251**: Raw trace、额外 handoff detail 和 correlation MUST 仅存在于记录数、单记录字节和总字节均有上限的进程内 epoch。
- **FR-252**: clear、disable、离开 debug 页面或 sidecar restart MUST 使当前 ephemeral epoch 不可读不可写；迟到请求不得重新填充旧 epoch。
- **FR-253**: Trace 保存和返回 MUST 脱敏应用已知 secret、provider credential 和 runtime token，并明确警告无法保证识别开发者自行粘贴的任意 secret。
- **FR-254**: 普通日志 MUST NOT 包含 raw prompt/response、完整 tool args、raw diagnostic handoff/result、credential 或 runtime authorization token。
- **FR-255**: Observation、redaction、correlation 或 buffer 故障 MUST 与业务调用隔离，不得改变 provider 成功结果、失败语义或重试行为。
- **FR-256**: Trace、flow 和 reference API MUST 在 trace disabled、鉴权失败或数据不可用时 fail-closed，并使用 `no-store` 响应边界。
- **FR-257**: Agent Flow MUST 从权威 orchestration transition 投影 chronological workflow timeline，而不是从模型文本或普通进度 UI 猜测。
- **FR-258**: Agent Flow MUST 覆盖 Teaching 的 PM/Programmer/Review/Trial 路径和 Assistant 到 ephemeral subagent/fixed specialist 的委派及返回。
- **FR-259**: Flow transition MUST 展示 workflow correlation、顺序/时间、source/target、状态、reason 和可用 detail，并支持与 trace 双向导航。
- **FR-260**: 没有相关 trace 的 transition MUST 保留并标记 unlinked；已有持久 transition 与仅 trace epoch 存在的 raw delegated task/result MUST 明确区分来源。
- **FR-261**: 真实 Grand Tour MUST 是显式人工 opt-in 的独立 Playwright suite，运行前提示真实模型费用和桌面/浏览器录制隐私风险。
- **FR-262**: Grand Tour MUST 独立报告 readiness、Assistant、Teaching live recording、skills/compositions、settings 和跨屏稳定性场景。
- **FR-263**: 长流程 MUST 依靠公开 workflow state/UI event 推进；模型输出断言只验证阶段、完成状态和可用结果，不依赖精确措辞。
- **FR-264**: 每次 Grand Tour MUST 使用隔离业务数据和非敏感配置；所有 provider/secret 读取通过 UnifiedConfigManager 的只读路径，secret mutation 必须拒绝。
- **FR-265**: Grand Tour MUST 限制付费调用数和总时长，预算耗尽、失败、超时或取消时停止录制并清理资源。
- **FR-266**: Routine E2E MUST 保持 mock-backed、无真实 credential、无付费调用；controlled tests MUST 覆盖 real-tour timeout/cancel/cleanup/budget failure。
- **FR-267**: 每次人工 Grand Tour MUST 生成不含 prompt、response、media 或 secret 的 summary report，关联 commit、journey、scenario outcomes、last state、预算和 cleanup。

### Key Entities

- **Composer Draft**: 未发送文本及其临时折叠展示状态，不是新的持久业务数据。
- **LLM Trace Record**: 当前 trace epoch 内的一次模型调用诊断记录，包含安全文本、来源、结果/失败和字节计量。
- **Trace Arm State**: 当前 sidecar 进程内的 trace authorization state，重启后默认关闭。
- **Agent Flow Timeline**: 权威 workflow transitions 与可选 ephemeral trace detail 的诊断投影。
- **Grand Tour Run**: 一次隔离、预算受控、可清理并产生安全报告的真实验收运行。

### Constraints & Compatibility

- **CC-090**: Debug UI 必须保持 `frontend -> desktop_api -> business` 分层，router 不直接读 Repository 或拥有 raw trace 生命周期。
- **CC-091**: Diagnostic raw data 不得持久化到 SQLite/DuckDB、普通日志、公共 UI event、URL、浏览器缓存或前端持久化状态。
- **CC-092**: Reference expansion 的保护边界是 trace enabled + 当前 sidecar auth + process lifetime；它不是 selected-trace scoped。
- **CC-093**: Debug observation 只能观察，不能改变 Assistant、Teaching、brain worker、provider 或 workflow 行为。
- **CC-094**: Real Grand Tour 是受控的人工验收例外；默认自动化仍必须无费用、无真实捕获。
- **CC-095**: Grand Tour credential 路径以当前 `UnifiedConfigManager` 为权威，不得恢复 011 历史 keyring resolver。
- **CC-096**: 011 不引入 trace export、远程 debug、生产 trace 收集或模型文本的确定性评分。

### Success Criteria

- **SC-117**: 两个 composer 的合格 paste 100% 折叠但发送原文，手工多行输入自动折叠次数为 0。
- **SC-118**: 开启 trace 后，开发者能在 30 秒内定位并展开前台或后台模型调用，或看到明确 omission。
- **SC-119**: 支持的 text/tool/vision 调用不会静默缺失，trace 中可还原媒体字节数量为 0。
- **SC-120**: clear/disable/restart 后旧 raw trace 与 debug-only detail 可访问数量为 0。
- **SC-121**: 应用控制 secret/runtime token 在 trace、普通日志、公共事件和前端持久化状态中的泄漏数量为 0。
- **SC-122**: 代表性 workflow transition 全部按权威顺序显示，linked trace 可在两次交互内双向导航。
- **SC-123**: 诊断故障注入不会改变被观察调用的成功或 provider failure 结果。
- **SC-124**: 默认 frontend regression 发起真实模型付费调用数量为 0。
- **SC-125**: Real Grand Tour 的失败、超时、取消和预算耗尽均报告 last safe state 并完成录制/资源 cleanup。
- **SC-126**: 同一 commit/journey 的三次人工 run 可仅凭安全 summary 证明场景、预算、cleanup 和 credential mutation 状态。

---

## Skill Methodology 方法论资产层 [Source: .specify/archive/012-skill-methodology-layer]

**Revision note (2026-06-15)**: Backfilled the completed 012 feature from `.specify/archive/`.
The physical spec folder had been archived previously, but its requirements were never merged into main memory.

### User Stories

- **US-059 (P1)**: 原“工具技能”三屏面向用户统一使用 Tool 术语，为 Skill Methodology 方法论资产腾出 Skill 语义。
- **US-060 (P2)**: 用户可通过 Assistant 创建/修订方法论，并在 Skill Methodology 页面事后编辑、软删除和查看版本链。
- **US-061 (P3)**: Assistant 本体和 specialists 可装备有序的方法论轻量清单，执行时按需加载完整 SKILL.md 正文。
- **US-062 (P4)**: 方法论的来源、版本、装备历史、加载/引用统计和 supersede 演化可审计且不物理删除。

### Functional Requirements

- **FR-268**: 原 Skill Teaching/List/Composition 的用户导航和文案 MUST 使用 Tool 术语；旧 `/skills` 路由 MUST 重定向到 `/tools/*`，方法论保留 `/skills/methodology`。
- **FR-269**: 原 `skills.*` Tool 域公开事件 MUST 直接切换为 `tools.*`；方法论域使用独立的 `skill.changed` / `skill.equipment.changed`。
- **FR-270**: 方法论 MUST 作为与 specialist 平级的 Brain 资产持久化，包含 name、description、trigger conditions、required tools、Markdown body、status、version chain、origin、source、统计和可装备元数据。
- **FR-271**: 方法论核心字段 MUST 可渲染为 Anthropic Agent Skills 风格 SKILL.md；trigger conditions 至少一条非空字符串，required tools 可为空。
- **FR-272**: 方法论 origin MUST 是封闭枚举：`system_bootstrap`、`user_edit`、`assistant_tool_call`、`specialist_tool_call`、`external_import`；非法值在业务、Repository 和数据库边界拒绝。
- **FR-273**: 方法论状态 MUST 为 `active -> superseded|soft_deleted`，记录永不物理删除；全库同名精确字符串最多一个 active 版本。
- **FR-274**: 每个方法论 MUST 保留 archive/failure source segments 及 session provenance；创建工具缺少合法来源时拒绝。
- **FR-275**: Supersede MUST 在单事务内完成旧版本失活、新版本 active、统计继承和所有 active equipment 转移；并发 supersede 采用 first-writer-wins 的线性接力链。
- **FR-276**: Assistant/specialist 与方法论之间 MUST 使用带状态和时间/原因的 N:M equipment rows；unequip、soft-delete 裁剪和 supersede transfer 不得物理删除历史行。
- **FR-277**: 每对装备者/方法论最多一条 active equipment；再次装备必须创建新 active 行并保留历史 unequipped 行。
- **FR-278**: 新 specialist 默认装备当时所有普通 active 方法论；新普通 active 方法论默认传播到现有 specialists 和 Assistant。
- **FR-279**: `system_bootstrap` 链根默认只装备 Assistant，不自动传播给 specialists；用户主动装备后的 specialist 在后续 supersede 中继续跟随版本。
- **FR-280**: SpecialistScreen MUST 支持 specialist 和固定 Assistant 卡片的装备、卸下、排序、required-tool warning 和 token 计量；风险颜色只提示，不阻断保存。
- **FR-281**: 派活时 system prompt MUST 只注入按顺序排列的轻量清单（id/name/description/trigger conditions），不得注入 body Markdown。
- **FR-282**: `load_skill_methodology(skill_id)` MUST 仅允许加载调用方冻结装备快照内的 active 方法论，以 SKILL.md 文本返回正文并增加 loaded count。
- **FR-283**: `load_skill_methodology` MUST 无单轮频次硬上限；失败仅限越权、soft-deleted 或 superseded 等契约错误。
- **FR-284**: Equipment 修改对正在执行的派单轮不生效；调用权限按派活时冻结快照判断，最快下一轮生效。
- **FR-285**: `create_skill_methodology` MUST 同时支持新建和 supersede，并由工具白名单鉴权；未授权 specialist 不得调用。
- **FR-286**: 所有对话式创建/修订方法论请求 MUST 经 Assistant 调度；SpecialistScreen 不提供绕过 Assistant 的直接命令入口。
- **FR-287**: 创建结果默认直接 active；新建模式遇精确同名 active 必须拒绝，supersede 模式允许沿用名称。
- **FR-288**: 创建和 supersede MUST 校验非空 trigger conditions 与至少一个 archive/failure source segment。
- **FR-289**: Assistant 默认拥有创建工具和“如何创建方法论”bootstrap 方法论；specialists 默认不拥有写方法论能力。
- **FR-290**: 新 active、supersede、编辑和 equipment 变化 MUST 经 blinker 事件和 UI Event Registry 通知前端，公开 payload 不含完整 body。
- **FR-291**: Bootstrap seed 缺失、空白或读取失败时 MUST fail-open 使用内置 fallback，记录状态并发非阻塞提示；后续真实 seed 可覆盖未被用户编辑的 fallback 版本。
- **FR-292**: `system_bootstrap` 链根 MUST 禁止软删除；用户编辑需走高危确认，拒绝时不产生新版本。
- **FR-293**: 普通方法论用户编辑 MUST 直接形成 supersede 接力，不增加二次确认；软删除被装备方法论必须走高危确认并原子裁剪 equipment。
- **FR-294**: Skill Methodology UI MUST 展示 active 列表、详情、编辑器、版本链、source、equipment audit 和 bootstrap 状态。
- **FR-295**: 列表 MUST 支持按最近变更、loaded count、referenced count、equipped count 排序，并支持从未引用/最近 30 天未引用筛选。
- **FR-296**: loaded count 只在 agent 成功调用 load 工具时增加；人工查看不增加。
- **FR-297**: referenced count MUST 从 reply metadata `skills_referenced` 计数，重复归一化去重、旧版本归一到当前 active 链；缺失或格式错误 fail-soft 跳过。
- **FR-298**: Supersede 后的新版本 MUST 继承资产维度的 loaded/referenced/last-referenced 统计；equipped count 随 equipment 转移自然继承。
- **FR-299**: 审计视图 MUST 可双向回放方法论版本演化和装备者的 equip/unequip 历史。
- **FR-300**: `external_import` 仅作为未来扩展枚举锚点；当前 desktop API MUST 拒绝外部导入写入且不得创建导入 endpoint。
- **FR-301**: v12 MUST 在 SQLite 创建 `brain_skills`、`brain_skill_source_segments`、`brain_skill_equipment` 及状态/枚举/唯一性/防 DELETE 约束。
- **FR-302**: 方法论数据 MUST 经 `SkillRepository` / `SkillEquipmentService` / `SkillService` 访问，desktop API 不直接读写表。
- **FR-303**: `brain.skill.*` token threshold 和 seed path MUST 走 UnifiedConfigManager；无新 secret。
- **FR-304**: Tool 录制/list/composition 的既有业务行为 MUST 在术语切换后保持不变。

### Key Entities

- **Skill Methodology**: 有版本、来源、正文、状态、统计和 origin 的方法论资产。
- **Skill Source Segment**: 方法论与 archive/failure Segment 的审计关联。
- **Skill Equipment**: Assistant 或 specialist 与方法论之间永不物理删除的状态化装备记录。
- **Methodology Version Chain**: 以 chain root、parent 和 superseded_by 形成的线性演化链。
- **Bootstrap Methodology**: 系统内置“如何创建方法论”，默认只装备 Assistant 并受额外保护。

### Constraints & Compatibility

- **CC-097**: 方法论和 equipment 与 brain memory 一样永不物理删除。
- **CC-098**: 012 不改变 Assistant 100% 调度，不新增固定“方法论工匠”专员。
- **CC-099**: UI/API/业务/Repository 依赖方向保持不变；新增表只能经 Repository 访问。
- **CC-100**: 方法论正文不得进入 system prompt、UI event 或 Tool 域事件 payload。
- **CC-101**: `skills.* -> tools.*` 是一次性公开事件切换，不恢复双发兼容。
- **CC-102**: 装备修改不影响 in-flight executor，创建/接力/删除的多表修改必须单事务。
- **CC-103**: 本 feature 不允许 subconscious 自动创建方法论。
- **CC-104**: Tool Teaching/List/Composition 只改用户术语和路由，不改变录制/发布/组合业务语义。

### Success Criteria

- **SC-127**: 旧 Tool 三屏和旧 `/skills` 路径全部使用新术语/重定向，旧 `skills.*` Tool 事件发布数量为 0。
- **SC-128**: 用户从 Assistant 要求沉淀方法论到 active 卡片出现可在 30 秒内完成或返回明确错误。
- **SC-129**: 编辑/supersede 后 3 秒内版本链、列表和全部 equipment 指向一致，无旧 active 残留。
- **SC-130**: Effective system prompt 中方法论 body 出现次数为 0，完整正文只通过 load tool result 进入 messages。
- **SC-131**: 方法论和 equipment 的 API/Repository/直连 SQL 物理 DELETE 尝试均被拒绝。
- **SC-132**: 未授权 specialist、非法 source、空 trigger、非法 origin 和同名 active 新建请求 100% 被拒绝。
- **SC-133**: system_bootstrap 默认传播、保护编辑、seed fallback 和后续 seed 修复行为都有守卫测试。
- **SC-134**: Supersede 的版本、统计和 equipment 转移在成功时全部提交，故障时整体回滚。
- **SC-135**: Skill Methodology 页面提供四种排序、两种引用筛选和三项统计展示。
- **SC-136**: `skills_referenced` 的正常、重复、旧版本归一、soft-delete 和 malformed 路径均有 fail-soft 测试。
- **SC-137**: `load_skill_methodology` 的成功计数、越权拒绝、无频次硬上限和人工查看不计数均有自动化覆盖。
- **SC-138**: Equipment 历史可按方法论和装备者双向回放，并保持最多一条 active pair。
- **SC-139**: Tool Teaching/List/Composition 既有 E2E 全部继续通过。
- **SC-140**: 前端 token 计量随装备和排序实时更新，超过阈值只变色不阻断保存。

---

## AgentLoop 并行工具执行 [Source: specs/017-parallel-tool-execution]

**Revision note (2026-06-15)**: Backfilled the completed 017 feature.

### User Stories

- **US-063 (P1)**: 同一模型响应内连续且显式标记安全的独立读取工具可并行完成。
- **US-064 (P2)**: 副作用或未证明安全的工具继续串行，失败级联语义保持不变。
- **US-065 (P3)**: 并行读取中的单个失败不取消 sibling，也不阻断后续串行分区。

### Functional Requirements

- **FR-305**: `ToolDefinition` MUST 提供默认 `False` 的 `is_concurrency_safe` opt-in 标志。
- **FR-306**: 只有经过线程安全审查的无副作用工具可以标记为并发安全。
- **FR-307**: AgentLoop MUST 将普通调用划分为连续 safe partitions 和单调用 serial partitions，并保持模型顺序。
- **FR-308**: 每个并发分区最多使用 4 个 worker。
- **FR-309**: Handler、hook 和 output governance MAY 在 worker 执行，使摘要等延迟可重叠。
- **FR-310**: Tool result persistence 和 activity sequence emission MUST 回到 caller thread 按原顺序完成。
- **FR-311**: 并发分区内失败 MUST 正常保存，但不得建立串行副作用失败级联。
- **FR-312**: Unknown、interrupting、single-call 和 side-effect failure semantics MUST 保持既有行为。
- **FR-313**: 会修改缓存/计数的 discovery/methodology、process、用户工具、写入、执行和委派工具默认保持串行。

### Constraints & Compatibility

- **CC-105**: 并发只改变 business 层执行调度，不新增事件、schema、配置或 secret。
- **CC-106**: SQLite message persistence 和活动 sequence allocation 必须保持 caller-thread 串行。
- **CC-107**: 并发资格必须显式 opt-in，不能根据工具名或“看起来只读”动态猜测。
- **CC-108**: Tool-call/result pairing、interrupting tool、hook、cancellation 和 output governance 契约不得回归。

### Success Criteria

- **SC-141**: 两个 safe calls 的 handler 和 governance 执行时间发生重叠。
- **SC-142**: `[safe, safe, unsafe, safe]` 被划分为三个有序分区。
- **SC-143**: 保存的 tool results 与 assistant tool calls 顺序和配对 100% 一致。
- **SC-144**: 并发读取失败不取消 sibling，既有 AgentLoop 回归测试继续通过。

---

## Assistant 失败消息重试与恢复 [Source: specs/018-assistant-failed-message-retry]

**Revision note (2026-06-15)**: Backfilled the completed 018 feature; root AI guidance existed,
but main specification, plan, and changelog were missing.

### User Stories

- **US-066 (P1)**: Assistant 回合终止失败后，用户消息下显示可跨重启恢复的内联失败卡并可原样重试。
- **US-067 (P2)**: 用户可编辑失败请求后创建新回合重试，原消息保持不可变。
- **US-068 (P3)**: 用户可从失败卡按 session 打开 Debug Inspector，并理解未预先开启 trace 时历史 raw detail 不可用。

### Functional Requirements

- **FR-314**: 每个终止性 Assistant 回合失败 MUST 在发布 failed progress 前持久化。
- **FR-315**: Failure record MUST 关联 session 和触发 user message sequence，并保存安全分类、建议、内部稳定码、异常类型名、attempt count、状态和时间。
- **FR-316**: Failure 状态机 MUST 为 `failed -> retrying -> resolved|failed`；sidecar 启动时遗留 `retrying` MUST 恢复为 `failed`。
- **FR-317**: 分类 MUST 覆盖 authentication、invalid request、quota/rate limit、network、provider/server、iteration limit 和 internal。
- **FR-318**: 普通 DTO、UI event 和日志 MUST NOT 暴露 provider raw response、endpoint、credential、stack trace 或异常正文。
- **FR-319**: 失败时 backend MUST 先发布已持久化 display messages，再发布 `assistant.progress(status=failed)`。
- **FR-320**: User message DTO/event MAY 带一个安全 failure projection：category/message/suggestion/attemptCount/failedAt。
- **FR-321**: Retry API MUST 接收 `messageSequence` 与可选 `content`；缺省 content 原样重试，提供 content 则创建新 user turn。
- **FR-322**: Retry MUST 拒绝非当前 failure、空编辑内容、缺失/非 Assistant session。
- **FR-323**: 并发 retry MUST 通过数据库条件更新确保最多一个 claim 到 `retrying`。
- **FR-324**: Manual retry 次数 MUST 不设上限，且不得改变既有自动 provider retry 或增加备用模型。
- **FR-325**: 成功 retry MUST resolve source failure 并从权威消息历史移除卡片。
- **FR-326**: 编辑后 retry 再失败时，新 failure MUST 归属新 user message。
- **FR-327**: 同 session 发送新的普通消息前 MUST resolve 旧的 unresolved failure。
- **FR-328**: 前端 MUST 将恢复卡渲染在对应 user bubble 下方，提供 retry、edit-and-retry、cancel edit 和 debug。
- **FR-329**: Retry 提交期间控件 MUST disabled；retry API 自身失败后卡片 MUST 恢复可操作。
- **FR-330**: Assistant terminal failure MUST NOT 写入产生重复 Toast 的全局 `lastError`；其他 API/debug errors 保持既有行为。
- **FR-331**: Debug action MUST 导航到 `/debug?sessionId=...`，按 session 过滤并优先选择最新 failed trace。
- **FR-332**: 未在失败前 arm trace 时，Debug Inspector MUST 明确说明历史 raw detail 不可恢复。
- **FR-333**: `backend.resync_required` 后前端 MUST 重拉权威 messages/failures，不从本地 progress 推断失败卡。

### Key Entities

- **AssistantRunFailure**: v14 SQLite 中与 session/message 关联的失败生命周期记录。
- **Failure Summary**: 仅包含 allowlisted 用户可见字段的安全投影。
- **Retry Request**: 指向当前 failed message、可携带替换文本的用户动作。

### Constraints & Compatibility

- **CC-109**: Failure 业务数据必须经 Repository 和 `AssistantFailureService`，router 不直连 SQLite。
- **CC-110**: 原始 provider 诊断只可内部分类使用，不得进入普通 DTO/event/log。
- **CC-111**: Persisted message/failure state 是权威来源，event replay 仅用于通知。
- **CC-112**: Cancellation、paused subagent、confirmation、queueing 和 100% dispatch 语义保持不变。
- **CC-113**: 018 不增加备用模型或修改 AgentLoop 自动重试。

### Success Criteria

- **SC-145**: 终止失败跨应用重启后 100% 恢复到正确 user message。
- **SC-146**: 并发重复 retry 只接受一次并只触发一次 Assistant dispatch。
- **SC-147**: 分类 fixture 不泄漏 secret、endpoint 或 raw response text。
- **SC-148**: 原样与编辑重试均通过 backend、frontend unit 和 mock E2E。
- **SC-149**: Assistant failure journey 产生重复全局 error Toast 的数量为 0。
- **SC-150**: Focused pytest、Vitest、Playwright、lint/format 和 diff checks 通过。

---

## 结构化多选澄清 [Source: specs/019-structured-user-clarification]

**Revision note (2026-06-15)**: Backfilled the merged 019 feature. One manual quickstart smoke task
remains explicitly incomplete; automated implementation and regression tasks are complete.

### User Stories

- **US-069 (P1)**: 主助理在无法可靠推断的关键岔路口，一次提出结构化问题并在同一 AgentLoop 回合中根据答案继续。
- **US-070 (P2)**: 用户可“暂不回答”，主助理收到 cancelled 后不得猜测或在同一回合换一种说法重复追问。
- **US-071 (P3)**: 超时、停止、关闭和 SSE 重连均有确定性生命周期；pending 卡片可通过 replay/快照恢复。

### Functional Requirements

- **FR-334**: 系统 MUST 提供仅主助理可用的 `ask_user_question`，每次包含 1–4 题、每题 2–4 选项。
- **FR-335**: 每题 MUST 支持单选/多选并始终提供最多 1000 字符的“其他”文本。
- **FR-336**: Handler MUST 校验 question/header/label、批次问题唯一性和题内 label 唯一性。
- **FR-337**: 稳定 `questionId` / `optionId` MUST 由后端生成，忽略模型提供的 ID。
- **FR-338**: Tool result 状态 MUST 限定为 answered/cancelled/timeout/stopped/shutdown/unavailable；answered 返回 question/selectedLabels/otherText。
- **FR-339**: `ask_user_question` MUST `requires_exclusive_call=True`；与任何其他工具混批时全批零执行并完整写 `invalid_model_output` 配对。
- **FR-340**: Solo clarification MUST 阻塞等待用户决策，返回结果后在同一 AgentLoop 内继续。
- **FR-341**: 该工具 MUST 只注册到主助理，PM/Programmer/Trial/specialist/subagent 均不得暴露。
- **FR-342**: API MUST 提供按 session 查询 pending 快照和按 session/request 提交 decision。
- **FR-343**: Submit MUST 校验每题有答案、单选互斥、多选可组合 other、option ownership 和 other 长度。
- **FR-344**: UI Event Registry MUST 注册 `assistant.clarification_requested` 与 `assistant.clarification_resolved`；resolved payload 不含答案。
- **FR-345**: 请求 MUST 默认 5 分钟超时并唤醒等待 worker。
- **FR-346**: Stop 和 shutdown MUST 分别结算 stopped/shutdown；普通 SSE disconnect 不取消请求。
- **FR-347**: 并发 decision MUST first-decision-wins；重复/过期提交幂等拒绝。
- **FR-348**: Decision API MUST 校验 session ownership，归属失败不泄漏请求存在性。
- **FR-349**: 前端 MUST 在输入框上方用可访问的非模态 fieldset/radio/checkbox 卡片展示，preview 只作纯文本。
- **FR-350**: 单选“其他” MUST 排斥普通选项；多选 MUST 允许普通选项与“其他”并存。
- **FR-351**: Pending、draft 和 submitting MUST 按 session 保存在内存 store；切换会话保留草稿，resolved 后统一清理。
- **FR-352**: 澄清链路 MUST 与高危确认完全分离，不显示“全部允许”且不复用 confirmation Toast lifecycle。
- **FR-353**: Assistant prompt MUST 限制仅关键决策使用、关联问题一次问齐、不得询问 secret、非 answered 后不得猜测继续。
- **FR-354**: Pending 与未提交答案 MUST 仅驻留当前 sidecar/frontend 内存，不新增数据库、migration 或配置。
- **FR-355**: Existing high-risk confirmation、stop、queue 和 UI event contracts MUST 保持回归通过。

### Key Entities

- **PendingClarification**: `request_id + session_id + questions + threading.Event + status + answers` 的权威进程内记录。
- **NormalizedQuestion/Option**: 后端生成稳定 ID 的校验后题目和选项。
- **ResolvedAnswer**: 仅进入 tool result、不进入公开 resolved event 的答案。
- **Clarification Draft**: 前端按 session 保存且不持久化的未提交选择。

### Constraints & Compatibility

- **CC-114**: 澄清状态完全内存化，不新增 SQLite/DuckDB 表、migration 或配置键。
- **CC-115**: Confirmation、Assistant stop、queue 和 UI Event Registry 边界不得被澄清实现污染。
- **CC-116**: 请求/选项/event payload 必须经过公开 UI event safety 检查；resolved event、普通 DTO 和持久化状态不得包含答案或 secret。
- **CC-117**: Non-answered 结果必须 fail-closed，模型获得猜测答案的次数为 0。

### Success Criteria

- **SC-151**: 关键岔路口可在同一回合完成提问、作答和继续执行。
- **SC-152**: 单选、多选、其他、取消、超时、停止、关闭和重连路径均有自动化覆盖。
- **SC-153**: timeout/cancel/stop/shutdown 后模型获得猜测答案的次数为 0。
- **SC-154**: Resolved event/普通 DTO 泄漏答案或 secret 的次数为 0。
- **SC-155**: 新增数据库表、migration 和配置键数量为 0。
- **SC-156**: Confirmation、stop、queue、UI event、pytest、frontend unit/lint/build 回归继续通过。

---

## 工具目录渐进式延迟加载 [Source: specs/021-tool-catalog-deferred-loading]

**Revision note (2026-06-15)**: Archived the completed 021 feature after merge into
`prepare-github`.

### User Stories

- **US-072 (P1)**: 主助理、临时子代理和固定专员在授权能力目录较小时继续看到完整名称和描述；目录超过条目数或字符数阈值时只看到统计和按需发现说明，避免每轮重复携带大目录。
- **US-073 (P1)**: Agent 可通过 `search_tools` 空查询浏览或按关键词、类型稳定分页搜索全部当前授权能力，并使用无歧义 selector 调用 `get_tool_detail` 激活定义。
- **US-074 (P2)**: 技能发布状态、组合可用性、白名单或运行时发现配置变化后，下一次 Prompt、搜索、详情和激活刷新立即使用当前事实，不允许旧目录或缓存扩大权限。

### Functional Requirements

- **FR-356**: 系统 MUST 对授权过滤后的技能与技能组合目录同时应用条目数阈值和完整渲染字符数阈值。
- **FR-357**: 目录不超过两个阈值时 MUST 为三类 Agent 注入完整名称和描述；仅当严格超过任一阈值时进入 deferred 模式。
- **FR-358**: Deferred Prompt MUST 只包含技能数、组合数、总数和 `search_tools` / `get_tool_detail` 使用说明，不得包含隐藏能力的名称、描述、适用场景或成员名称。
- **FR-359**: 主助理、临时子代理和固定专员 MUST 复用同一目录策略，并在各自授权过滤之后独立判断模式。
- **FR-360**: `search_tools` MUST 支持可选 query、`all|tool|composition` 类型过滤、offset/limit 分页和无关键词目录浏览。
- **FR-361**: 搜索结果 MUST 返回 query、kind、offset、实际 limit、total、items、nextOffset；每项 MUST 包含 kind、name、无歧义 selector 和有界描述。
- **FR-362**: 搜索排序 MUST 按名称精确、名称前缀、名称包含、描述/适用场景包含的优先级确定性排序，同级按类型和名称稳定排序。
- **FR-363**: 搜索、详情加载和激活定义刷新 MUST 重新校验当前发布状态、组合可用性、组合成员授权和 Agent 白名单。
- **FR-364**: `get_tool_detail` MUST 保持非并发安全和现有动态激活/LRU 语义；受局部锁保护的 `search_tools` MAY 保持并发安全。
- **FR-365**: 发现策略 MUST 通过 `agent_tools.discovery.*` 和 `UnifiedConfigManager` 管理，运行时覆盖在下一次 Prompt 或搜索生效，且不新增 Settings UI。
- **FR-366**: 模式选择日志 MUST 只记录 Agent 类型、授权条目数、完整候选字符数和模式，不得记录能力名称、描述或 secret。
- **FR-367**: 现有仅传 query 的 `search_tools` 调用 MUST 保持兼容；非法 kind、offset 或 limit MUST 返回可恢复结构化错误且不得改变激活状态。
- **FR-368**: 系统 MUST 支持至少 100 项授权目录的无重复、无遗漏分页遍历；100 项 deferred 目录区段 MUST 小于 1000 字符。
- **FR-369**: 本功能 MUST NOT 新增 UI、desktop API、公开 UI event、数据库 schema、迁移、secret 或前端持久化状态。

### Key Entities

- **Authorized Capability Catalog**: 经过发布状态、组合状态、成员完整性和当前 Agent 白名单过滤后的技能与技能组合集合。
- **Capability Discovery Policy**: 完整目录双阈值、搜索页大小和结果描述长度的统一配置快照。
- **Capability Search Page**: 带稳定排序、total、nextOffset 和 selector 的授权目录分页结果。

### Constraints & Compatibility

- **CC-118**: 目录读取继续经 `ToolRepository` / `SkillCompositionService`，业务代码不得直接写 SQL 或绕过 Repository。
- **CC-119**: 阈值必须在授权过滤后计算；Prompt 快照不得被当作搜索或详情调用时的授权事实。
- **CC-120**: Deferred Prompt 和安全日志不得泄漏隐藏目录内容；搜索结果只能包含调用时仍获授权的能力。
- **CC-121**: `agent_tools.discovery.*` 只能通过统一配置入口读取，默认值必须同步配置模型、示例和文档。
- **CC-122**: AgentLoop 工具配对、动态激活 LRU、并发安全声明和三类 Agent 的既有委派语义不得回归。

### Success Criteria

- **SC-157**: 100 项授权目录在三类 Agent 中均进入 deferred 模式，目录区段小于 1000 字符且隐藏名称/描述泄漏数为 0。
- **SC-158**: 100 项目录可通过连续分页遍历 100%，无重复、无遗漏。
- **SC-159**: 阈值边界、授权隔离、排序、分页、非法参数、失效重校验、动态激活和安全日志均有自动化行为测试。
- **SC-160**: 小目录完整摘要和只传 query 的旧调用保持兼容。
- **SC-161**: 运行时配置在下一次 Prompt/搜索生效，无需重启或数据迁移。

---

## 子进程事件推送 [Source: specs/022-process-event-push]

**Revision note (2026-06-15)**: Archived the completed 022 feature after merge into
`prepare-github`. 主要替代 subagent / specialist 循环 poll 后台进程的旧模式。

### User Stories

- **US-075 (P1)**: subagent / specialist 对自己起的后台进程使用 `wait_for_process_event` 阻塞等到状态边界(running→completed/failed/terminated)即返回，毫秒级拿到 status + exitCode，超时返回空事件 + 当前状态(非错误)。
- **US-076 (P2)**: 进程累计写出字符过配置阈值时,subagent 收到一条不含原文的 log_chunked 信号(totalChars / deltaChars),可继续走 `process_logs` 读真实日志,token 友好。
- **US-077 (P3)**: 进程在 running 状态下静默时长超阈值时收到一条 stalled 信号(idleMs);同一静默周期不刷屏;进程从未输出过的纯 sleep 场景也按 `last_output_at = started_at` 基线触发一次。

### Functional Requirements

- **FR-370**: 系统 MUST 暴露新工具 `wait_for_process_event`,签名 `(processId, sinceCursor?, timeoutMs?)`;仅供 subagent / specialist 调用,主助理不暴露。
- **FR-371**: 工具 MUST 复用 `_process_for_current_session` 归属校验;跨会话调用返回 `permission_denied` 且不暴露目标进程存在性。
- **FR-372**: `ProcessRecord` MUST 维护有界事件队列、per-process 单调 `event_sequence`、与 `ProcessManager._lock` 共享的 `threading.Condition`,以及 `last_output_at` / `last_chunk_announce` / `total_output_chars` / `last_stalled_announce_output_at` 状态字段。
- **FR-373**: 三类事件 MUST 均不携带原文 payload —— `state_changed` 含 status/exitCode、`stalled` 含 idleMs、`log_chunked` 含 totalChars/deltaChars。
- **FR-374**: `state_changed` MUST 在 status 从 running 转到 completed/failed/terminated 时由 `_refresh_locked_with_emit` 或 `stop()` 内 emit;`close()` 路径不触发事件。
- **FR-375**: `log_chunked` MUST 由 reader 线程在累计输出字符过阈值时 emit;阈值复位顺序 MUST 为"先保存 delta、再推进 last_chunk_announce、最后 emit",避免 delta 计算错乱。
- **FR-376**: `stalled` MUST 由 `wait_for_event` 入口懒判定;`last_output_at` MUST 在 ProcessRecord 创建时初始化为进程启动时刻,所以"从未输出 + 静默达阈值"等同"产生过输出后再静默达阈值"。
- **FR-377**: `wait_for_event` MUST 在 deque 中存在 sequence > sinceCursor 的事件时立即按 sequence 升序返回;否则在 `event_condition` 上阻塞至超时,超时返回空 events + 当前 status(非错误)。
- **FR-378**: `wait_for_event` MUST 始终返回 `cursor` 字段:若 deque 非空取最新事件 sequence,空队列取 `record.event_sequence`;`cursorTooOld=true` 路径同样返回 cursor,subagent 可直接续 wait 无须切换兜底。
- **FR-379**: 工具 MUST 沿用 process_* 系列约束 —— **不**标记 `is_concurrency_safe`、`timeoutMs` 钳位到 `[1, max_timeout_ms]`、内部异常映射到 `internal_error`(沿用 `builtin_contracts.ERROR_CODES` 通用码)。
- **FR-380**: 三个新配置键 `agent_tools.process.event_buffer_size`(默认 64,上限 512)、`stalled_threshold_ms`(默认 10000,上限 600000)、`chunk_threshold_chars`(默认 4096,上限 65536) MUST 走 `UnifiedConfigManager`;Settings UI 不暴露。
- **FR-381**: 既有 `process_poll` / `process_logs` / `process_wait` 签名 + 行为 + 既有测试 MUST 全程零回归。
- **FR-382**: 事件 MUST NOT 进入 `UI Event Registry` / blinker / SSE / 前端;主助理也不订阅 —— 100% 调度纯净。
- **FR-383**: 事件 MUST NOT 跨 sidecar 进程持久化;旧 processId 在重启后走既有 `process_missing` / `process_unavailable_after_restart` 路径。
- **FR-384**: 环形 deque 满后 MUST 自动覆盖旧事件,`event_sequence` 仍单调,不抛错;sinceCursor 早于 deque 最旧 sequence 时返回 `cursorTooOld=true`。

### Key Entities

- **ProcessEvent**: 一条派生信号,frozen dataclass 含 `sequence`(per-process 单调)、`type`(state_changed / stalled / log_chunked)和 type-conditional payload 字段;不携带原文。
- **ProcessEventCursor**: 调用方在连续 wait 调用间传递的整数游标,单调推进;仅在单个 processId 上下文有效。
- **ProcessRecord(扩展)**: 既有进程记录新增 events deque + sequence + condition + 输出时间戳/累积统计字段,均为内部状态。

### Constraints & Compatibility

- **CC-123**: 既有 `process_poll` / `process_logs` / `process_wait` 工具 MUST 不变;不允许借本 feature 顺手重构。
- **CC-124**: 100% 调度约束 MUST 保留 —— 主助理对子进程的可见度仍走既有 014 子任务活动事件,不开新通道。
- **CC-125**: secret 与日志原文 MUST NOT 出现在事件 payload。
- **CC-126**: 归属判定 MUST 100% 复用 `_process_for_current_session`,无新分支。
- **CC-127**: 配置 MUST 仅来自 `UnifiedConfigManager`(`agent_tools.process.*` 命名空间),不引入新文件 / 表 / migration。
- **CC-128**: 事件机制 MUST 不增加跨进程 / 持久化 / 通用事件总线等基础设施;第二类事件源出现再做增量重构。

### Success Criteria

- **SC-162**: 进程状态切换到 subagent 唤醒的延迟在本机 idle 环境下 ≤ 200 ms(由 `test_wait_wakes_up_on_new_event_within_200ms` 显式断言)。
- **SC-163**: 进程产生 ~16 KB 输出时 subagent 至少收到一条 log_chunked,totalChars 与同期 process_logs 实际差异 ≤ 阈值;事件 payload 字段集 ⊆ {sequence, type, totalChars, deltaChars}。
- **SC-164**: 同一静默周期内 wait 任意次只产生一条 stalled,新输出后再次静默达阈值才再发一条。
- **SC-165**: 跨会话调用、processId 不存在、cursor 已被覆盖三种异常路径返回各自既定语义(permission_denied / process_missing / cursorTooOld=true + cursor 字段非空),且不污染其它工具或 ProcessManager 状态。
- **SC-166**: 既有 `process_poll` / `process_logs` / `process_wait` 测试 + guardrails 在引入本 feature 后 100% 通过。
- **SC-167**: 三层测试金字塔(ProcessManager 单测 16 个、工具层单测 6 个、集成行为契约 3 个)全绿。

---

## 统一任务模型 + 多范式协作 [Source: specs/023-unified-task-collaboration]

**Revision note (2026-06-24)**: Archived 023 after merge. 把隐式子任务/委派收口为显式一等 Task 图 + TaskAttempt 运行时 + 父侧裁定,并提供委派/会议/认领三种协作范式 + 私人 Todo。作为跨全栈大 feature,完整 FR-001~026、Key Entities 字段、Data Model、Contracts、Acceptance Scenarios 见 `specs/023-unified-task-collaboration/spec.md`,这里摘录最稳定的契约。

### User Stories

- **US-078 (P1)**: 多步任务可观测、可恢复地完成 — 复杂请求拆成带依赖的 Task 图,跨执行者真并行,实时看进度;崩溃围栏旧 attempt、从 checkpoint 续跑,迟到结果幂等拒绝,不留永久 running 僵任务。
- **US-079 (P2)**: 干完/卡住都交裁定,失败有交代,随时可叫停 — 执行者交回派活方裁定(认可/打回/放弃),失败沿链冒泡到根触发 run 级失败卡(安全投影);停止作用于整个请求图(留工可续),取消终态不返工不复活。
- **US-080 (P3)**: 协调者临场切换协作范式 — 点名委派 / 看板开放认领(原子认领 + 租约 + 兜底临时执行者) / 受监督二方会议(轮次/时长预算 + 结论 + 仅传消息不扩权)。
- **US-081 (P4)**: 执行者私人 Todo 防遗忘 — 单任务私人 checklist,持久化,不进任务图/裁定/大脑,状态词独立。

### Key Contracts / Entities

- **Task**:持久工作项/编排节点,六态(pending_dispatch / running / suspended / completed / failed / cancelled);"等待裁定"是父侧项,**不是** Task 状态值。
- **TaskAttempt**:一次易朽运行,带 lease / heartbeat / checkpoint / fence_token;重启围栏崩溃前 running attempt → Task `suspended(waiting_system)`,只从 checkpoint 续跑,缺则交父侧裁定。
- **Adjudication**:父侧待裁定项(独立表),承载 accept(→完成) / return(→返工) / abandon(→失败 + 级联取消下游)。
- **Board Claim / Meeting Channel / Todo**:看板认领(原子 + 租约 + reject history + 兜底)、受监督二方消息通道(预算 + 结论要求 + message-only,不得借工具/扩权)、执行者私人清单(独立状态词,永不进 brain distillation)。
- **容量=1**:DB-backed(条件 UPDATE + active-attempt partial unique index),非进程锁;paused/fenced/terminal 都释放槽。
- **副作用幂等**:Operation(stable operation_key)+ completion marker;非幂等或未知副作用崩溃后交裁定,**不**自动重放;迟到 fenced 结果幂等拒绝。
- **run 级失败桥接**:主助理显式 `abandon_request_graph` → root FAILED → `failure_bridge` → `AssistantRunFailure` 卡(018 安全投影);仅 root 终态失败冒到用户。
- **Typed UI events**:`assistant.task_graph.changed` / `task_board.changed` / `meeting.changed` / `todo.changed` / `task_question.changed` 经 UI Event Registry + allowlist + 脱敏投影;缺口走 `backend.resync_required` 拉权威全图快照。

### Constraints & Compatibility

- **CC-129**: 沿用现状拓扑(枢纽单层 + 一级延伸),唯一增量是专员起至多一个临时子代理;结构上杜绝调用环。
- **CC-130**: 复用既有安全协议(高危确认 fail-closed、面向用户澄清仅进程内、子进程/越权 fail-closed、密钥不入日志/明文 DTO/前端持久化)。
- **CC-131**: 用户停(可恢复暂停)映射为 `suspended(user_stop)`;新增取消(终态作废)是不同语义,显式区分,不得复用同名概念。
- **CC-132**: 任务级失败在图内消化,只有冒到顶仍无法挽回(经 `abandon_request_graph`)才升级为 run 级;run 级只暴露安全投影。
- **CC-133**: 委派起点的隐式状态(transition + 子会话重建)整体迁移到显式 Task 实体;单用户未发布一次性切换(clean-start guard),不双写。
- **CC-134**: 跨执行者并行不破坏既有并发安全(共享 session / 可变激活缓存 / 计数写入 / 进程状态须线程安全或独立 session)。
- **CC-135**: 100% 调度边界保留 — user-work `TaskAttempt.executor_type` 只能是 `ephemeral_subagent` / `specialist`,主助理只协调;PM/Programmer/Trial 不进调度池。

### Success Criteria

- **SC-168**: ≥3 步、≥2 执行者请求全程可见结构化任务进度(节点 + 状态);互不依赖子任务真并行,总耗时显著短于串行。
- **SC-169**: 有 checkpoint 的崩溃/暂停 100% 从断点续跑、0 重复副作用、0 丢步;无 checkpoint 100% 进父侧裁定并给安全说明;注入式崩溃/重启 0 个永久 running。
- **SC-170**: 停止后整个用户请求图在"当前轮结束"内暂停、产出保留、可继续;不影响其他会话/请求;取消自上而下传播,被取消下游不被 late planning 复活。
- **SC-171**: 同一开放看板任务并发认领压力下 0 次双认领/重复执行。
- **SC-172**: run 级失败对用户仅呈现安全说明;0 次原始 provider 错误/密钥/堆栈泄露。
- **SC-173**: Task / Adjudication / Todo 三者 UI 与数据始终可区分(独立状态词/渲染/表)。
- **SC-174**: 既有安全与边界回归全绿(高危确认 fail-closed、澄清不落库、100% 调度、并发安全门卫、顺图取消契约)。

### Edge Cases

- 跨专员并行崩溃 / 同步子树崩溃释放专员占用 / 取消 × 重规划竞态(新下游不漏取消)/ 一条消息多顶层部分失败归属 / 向上提问无人答 → 挂起等回话(fail-closed)/ 会议死锁(等待环)/ 资源权限被拒落"放弃"/ 暂停三因(等回话 / 等系统恢复 / 用户停)唤醒方式不同。

完整功能需求(FR-001~026)、Key Entities 字段、Data Model、Contracts、Acceptance Scenarios 见 `specs/023-unified-task-collaboration/spec.md` 与 `data-model.md` / `contracts/assistant-task-collaboration.md`。

---

## Task Graph Scheduling（复杂任务"先分解，再按图执行"纠偏） [Source: specs/024-task-graph-scheduling]

**Revision note (2026-06-26)**: Archived 024 after merge. 把复杂任务从"一把委派/边想边派"纠正为"识别复杂度→分解成带依赖DAG→确定性调度器按依赖自动推进→遇高风险节点或失败时停下让主助理裁定"。

### User Stories

- **US-082 (P1)**: 复杂任务被分解成有序任务图并按序执行——操作者给办公助理一个多步跨领域复杂任务，助理在执行前产出多个由依赖关系连接的任务节点，并按正确顺序完成全部节点。无依赖节点可并行、有依赖节点按序执行；任务图是分解与执行之间的交接物。
- **US-083 (P1)**: 简单任务继续走快速通道、不建图——1-2 步、单领域的简单任务继续走现有快速委派路径，不受新图机制影响。
- **US-084 (P2)**: 高风险步骤执行前暂停等待确认——不可逆/高风险节点在分解时被标记；依赖前置完成后，助理暂停该分支、在执行前向主助理/操作者裁定。
- **US-085 (P2)**: 节点失败先自愈，兜不住再升级——节点失败时助理先尝试自愈（重试/换执行器/调输入/跳过/改图），兜不住才升级操作者。
- **US-086 (P3)**: 中途可见进度、能取消/改主意——操作者能感知整体任务进度并按需查看执行器 todo 进度；取消顺图传播，改主意按"取消旧图+重新分解"处理。

### Functional Requirements

- **FR-385**: 系统 MUST 将到达主助理的任务按复杂度至少分三路路由：简单（现有快速委派）、中等（主助理自行分解）、超阈值（委派给固定规划专员）。
- **FR-386**: 对中等与超阈值任务，系统 MUST 在执行前产出一整张任务图结构（节点+依赖边）作为分解与执行之间的交接物，且两条分解路 MUST 产出同一种图结构、由下游无差别消费。
- **FR-387**: 任务图 MUST 通过依赖边表达先后；一个节点 MUST NOT 在其所有依赖前置节点完成之前执行（就绪校验在派发/认领层强制兜底）。
- **FR-388**: 系统 MUST 在建图时拒绝会形成环的依赖边。
- **FR-389**: 对超阈值任务，系统 MUST 委派给固定规划专员产出任务图，且规划专员 MUST 只规划不执行（深度封顶，不再向下委派执行）。
- **FR-390**: 系统 MUST 提供一个确定性的调度器，依据依赖完成情况自动推进就绪节点，而不依赖 LLM 临场判断来决定执行顺序。
- **FR-391**: 系统 MUST 强制单执行器同时在办约束：一个执行器（专员/子 agent）同时只持有一个未完成节点。
- **FR-392**: 执行器崩溃/租约过期时，系统 MUST 自动将其持有的未完成节点退回可重派状态，使整图不卡死。
- **FR-393**: 高风险/不可逆节点 MUST 在分解时被标记，且 MUST 在执行前暂停等待裁定。
- **FR-394**: 节点失败时，系统 MUST 提供结构化自愈动作集（重试/换执行器/调输入/可容忍则跳过/改图），且 MUST 仅在自愈无效时才升级操作者。
- **FR-395**: 执行器 MUST 能把多步节点分解成内部 todo 清单，并实时更新其状态。
- **FR-396**: 节点 todo 进度 MUST 对主助理可见（供裁定），且 MUST 对操作者按需可见（经 TaskGraphPanel 节点展开，复用 `assistantTaskStore.todosByTaskId` + `GET /tasks/{id}/todos`）；MUST NOT 展示在默认任务界面（DEC-E 消解：todo 按需可见走 TaskGraphPanel 节点展开而非 014 SubagentDrawer——023 dispatcher 路径下 task executor 不发 `assistant.subagent` 事件，SubagentCard 不出卡片；意图保留，机制修正）。
- **FR-397**: 操作者取消 MUST 顺图传播（回收运行中执行、取消未开始节点）；改主意 MUST 按"取消旧图+重新分解"处理。
- **FR-398**: 简单任务 MUST 继续走现有快速委派路径、不构建任务图（无回归）。
- **FR-399**: 主助理 MUST 能基于节点回流结果做结构化裁定——回流包 MUST 在节点完成时附带"下一步建议"（就绪可派节点/是否有待裁定节点/是否全图完成），在节点失败时附带"可选自愈动作清单"，而非让主助理开放自由发挥。

### Key Entities

- **任务图 (Task Graph / DAG)**：分解与执行之间的交接物，由节点和依赖边组成；执行者照图走。复用 023 `graph_id` 聚合，激活 `edge_type='dependency'` 边语义。
- **任务节点 (Task Node)**：一个执行器的一次连贯执行单元，复用 023 `assistant_tasks`，新增 `requires_confirmation` 列。
- **依赖边 (Dependency Edge)**：节点间先后关系（blocking=串行前置；非阻塞=可并行），复用 023 `assistant_task_edges` 的 `edge_type='dependency'` 闲置枚举值。
- **规划专员 (Planning Specialist)**：新增固定专员类型 `role_kind='planner'`，为超阈值任务产出任务图；只规划不执行；tool_registry 按角色分支装配工具。
- **DAG 调度器 (DAG Scheduler)**：新增的确定性 runtime 组件 `graph_scheduler.py`，按依赖就绪自动推进节点，并在需确认/失败时触发裁定与自愈。不持久化。
- **需确认标记 (Needs-Confirmation Marker)**：`requires_confirmation=1` 标注在高风险/不可逆节点上、强制执行前暂停的标记（migration v17 新列）。
- **节点 Todo (Node Todo)**：执行器对多步节点的内部子步骤清单，复用 023 todo 能力；按需经 TaskGraphPanel 节点展开可见。
- **回流包 (Reentry Briefing)**：节点完成/失败时回流的结构化结果包，扩展承载下一步建议/可选自愈动作/节点 todo 概览文本段（DEC-H）。

### Constraints & Compatibility

- **CC-136**: MUST 完整复用 023 基础设施（持久任务图、durable accepted 即委派即落库、dispatcher 线程池+TaskAttempt lease/fence、parent reentry、父侧裁定、取消顺图传播），MUST NOT 重写其持久化/恢复/并发安全机制。
- **CC-137**: MUST NOT 强制简单任务建图（避免过度工程化）。
- **CC-138**: 本阶段 MUST NOT 引入任务图的前端可视化编辑（仅消费、不前端编辑图）。
- **CC-139**: MUST NOT 改变现有 UI 事件契约与前端投影方式（如有新裁定/暂停类展示需求，按项目规则在 UI Event Registry 注册公开事件后再消费）。
- **CC-140**: `todo_update` 是副作用工具，MUST NOT 标记 `is_concurrency_safe`、MUST NOT 进入并行执行池。
- **CC-141**: 复杂度分类是 LLM 软判定；凡需硬保证处（如"超阈值必须走规划专员""复杂必须落库为带依赖 DAG"）MUST 由落库层架构门卫校验，MUST NOT 假定 LLM 分类一定正确。
- **CC-142**: 本特性建立在 023 分层越权重构稳定后的地基上；MUST 只消费 023 的稳定接口，两者不冲突。
- **CC-143**: 分解质量约束、阈值规则、自愈动作选择均为模型软约束（advisory），非确定性保证；文档与调用方 MUST 如此描述，需要硬保证时另行增加 schema/业务校验与行为测试。
- **CC-144**: 就绪硬校验、单工作者约束、executor 异常 unassign、回流结构化引导等借鉴自 claude-code（单用户 CLI 场景）的机制，MUST 在 plan 阶段逐个确认对办公助理"多专员+持久化"场景的适配点；以 023 已有的 lease/fence/父侧裁定为主保障，借鉴机制为增强。

### Success Criteria

- **SC-175**: 复杂多步任务（≥3 步、跨≥2 领域/工具族）在常规执行段内无需操作者介入即可端到端完成——全部节点按依赖顺序执行完毕。
- **SC-176**: 100% 的高风险/不可逆节点在执行前暂停等待操作者裁定——没有任何危险节点在未确认情况下静默执行。
- **SC-177**: 在存在可行恢复动作的情况下，节点失败的自愈成功率（不升级操作者即解决）占多数。
- **SC-178**: 操作者取消/改主意能在现有取消传播延迟内停下一张运行中的图，无遗留的孤儿执行。
- **SC-179**: 简单任务（1-2 步、单领域）无行为回归——仍走快速委派路径、延迟与体验与改造前一致。
- **SC-180**: 多步节点的执行器对非平凡节点产出并推进内部 todo 清单（不再退回"边想边做"）。
- **SC-181**: 现有 023 稳定路径（durable accepted、崩溃恢复、并发安全、取消传播）在本特性上线后不退化。

### Edge Cases

- 执行器崩溃/租约过期/被杀（节点执行中途）：该执行器持有的未完成节点自动退回可重派状态，整张图不卡死。
- 单执行器同时在办约束：一个执行器同时只能持有一个未完成节点；需要并行时由多个执行器各跑一个节点。
- 依赖边成环：建图时直接拒绝（复用现有无环校验）。
- 分解质量问题（节点粒度不当、依赖画错）：建图时无环校验+关键裁定兜底+分解 prompt 软约束。
- 复杂度误判（LLM 软判定）：落库层架构门卫校验"命中超阈值规则的任务必须落库为带依赖边的 DAG、必须由调度器驱动"。
- 高风险节点正处于裁定暂停时操作者取消：按取消传播处理，暂停分支一并停止。
- 简单任务被误判为复杂（或反之）：门卫测试守边界；落库层区分"快捷委派图"与"分解 DAG 图"。
- `suspendReason` 首版纯复用 `waiting_user`（DEC-G）；需更精确区分时扩 enum 加 `waiting_confirmation`。
- 跳过节点下游处理：默认可容忍跳过→视为完成推进下游；不可容忍→取消下游子图。
- `graph_version` 首版接受 per-edge 递增（DEC-F）；若 cancel 围栏语义受影响再优化为批量入口一次性 +1。

---

## 用户个人待办列表 [Source: specs/025-user-todo-list]

**Revision note (2026-07-07)**: Backfilled 025（merged 2026-06-27，归档时被跳过）。独立个人待办业务层——SQLite v18 `user_todos` 表、`/api/user-todos` typed CRUD、delegated executor 专用 user_todo 工具，与 `assistant_todo_items` 执行者私人 checklist 完全隔离。0 新公开 UI 事件。

> ID 说明：025 早于 026-029 合并但归档滞后；为保 memory 既有 ID 不重排，其编号续在当前最高号之后（US-099~103 / FR-453~459），与文档中相邻的 024/026 段号段不连续，属预期。

### User Stories

- **US-099 (P1)**: 创建待办——用户在 `/todos` 主屏创建个人待办（标题/描述/优先级）。
- **US-100 (P1)**: 查看和筛选待办——用户查看待办列表并按状态/优先级筛选。
- **US-101 (P1)**: 完成和撤销完成——用户标记待办完成或撤销完成。
- **US-102 (P2)**: 编辑和删除待办——用户编辑已有待办或删除。
- **US-103 (P2)**: 通过 AI 助手管理待办——用户在对话中让 AI 管理待办，AI 经被调度执行体的 user_todo 工具操作，不复用主助理工具集。

### Functional Requirements

- **FR-453**: 系统 MUST 支持创建、查看、编辑、完成/撤销完成、删除个人待办。
- **FR-454**: 系统 MUST 将个人待办存储在本地 SQLite `user_todos` 表（v18 migration）。
- **FR-455**: Desktop API MUST 只调用业务 service，不直接访问 Repository。
- **FR-456**: 前端 MUST 通过 typed API client（`/api/user-todos`）访问待办能力。
- **FR-457**: AI 管理待办 MUST 通过被调度执行体的工具完成，不把待办写工具加入主助理工具集。
- **FR-458**: 用户待办 MUST 与 task collaboration 的 `assistant_todo_items` 私人 checklist 完全隔离。
- **FR-459**: V1 MUST 不新增公开 UI event；UI 操作后通过 API 刷新权威列表。

### Key Entities

- **UserTodo**: 用户个人待办条目。属性：id、标题、描述、状态（pending/in_progress/done）、优先级、时间戳。存储在 SQLite `user_todos` 表（v18 migration），经 `UserTodoRepository` / `UserTodoService` 访问；与 `assistant_todo_items`（执行器私人 checklist）完全隔离。

## 自我改进提案（B 阶段：人审批、机器实施） [Source: specs/026-self-improvement-proposals]

**Revision note (2026-07-02)**: Archived 026 after merge. 在 A 阶段（执行复盘·只读报告制）上加一层「人审批 + 机器实施」：`worth_changing` 发现落成可审批提案，用户批准（带补料）后由桥接 service 建独立 git worktree + 程序化任务图，执行体在隔离 worktree 内改源码并跑测试，结果回写提案。停在 B，不引入机器自批自改（C）。完整 User Stories 验收场景、Assumptions、Architecture Impact 见 `specs/026-self-improvement-proposals/spec.md`。

### User Stories

- **US-087 (P1)**: 看见可执行的改进提案并人工把关——执行复盘跑完后，BrainScreen 复盘视图展示由 `worth_changing` 发现自动生成的提案列表；用户逐条阅读（问题/证据/建议/严重度）并批准（带补料文本）或拒绝；同发现幂等、跨复盘同类去重不刷屏、待审提案有可发现提示。
- **US-088 (P2)**: 批准后机器自动改源码并回报——用户批准后系统无需进一步操作即创建独立 git worktree + 特性分支，由规划专员拆解、执行体在隔离 worktree 内改源码并跑测试，完成后把分支名 + 测试通过与否 + 安全摘要回写到提案；失败转 `failed` 并展示安全摘要，不自动合并、不污染主工作区。
- **US-089 (P3)**: 隔离与可回滚的安全保证——每次自动改造关在独立 worktree 内、只允许改源码、合并由用户手动、随时可凭 git 删分支/弃 worktree 干净回滚；执行体对非源码/外部副作用/自我改进核心的修改尝试被 fail-closed 阻断。

### Functional Requirements

- **FR-400**: 系统 MUST 在某条执行复盘落库后，为其中每个 `worth_changing=true` 的发现生成一条改进提案；同一发现 MUST 幂等不重复生成（`UNIQUE(source_review_id, finding_index)`）。
- **FR-400a**: 系统 MUST 抑制跨复盘的同类提案堆积（系统性低效在多次复盘反复报出）：同类发现按 `dedup_key` 走去重/合并或冷却窗口（默认 24h），不每条复盘各生近重复提案。advisory 软保证（见 Known Issues）。
- **FR-401**: 每条提案 MUST 关联来源复盘记录，并保留可展示的问题描述、证据、建议、严重度。
- **FR-402**: 提案 MUST 有明确生命周期 `pending_review → approved → in_progress → done | failed`（及 `pending_review → rejected`、`failed → rejected`）；状态流转 MUST 持久化（条件 UPDATE + rowcount CAS）。
- **FR-403**: 提案生成 MUST NOT 改变 A 阶段执行复盘的存储、产出或只读语义。
- **FR-404**: 用户 MUST 能在 BrainScreen 复盘视图内查看提案列表并逐条阅读详情，不新增独立主屏。
- **FR-405**: 用户 MUST 能批准一条提案并附补料文本（改造方向/注意事项）；补料 MUST 持久化并传递给后续实施。
- **FR-406**: 用户 MUST 能拒绝一条提案；拒绝 MUST NOT 触发任何实施动作或副作用。
- **FR-407**: 用户批准之前，系统 MUST NOT 对任何提案发起实施或产生不可逆副作用（advisory-only 直到人点头）。
- **FR-408**: 批准一条提案后，系统 MUST 无需用户进一步操作即把它交给任务协作系统实施。
- **FR-409**: 实施 MUST 在独立隔离的 git worktree + 特性分支内进行（一提案一工作区）；提案 MUST 记录工作区路径与分支名。
- **FR-410**: 系统 MUST 程序化构建实施任务图（规划专员只规划、执行体改源码并跑测试）并经进程级调度器单例踢起推进；调度器尚未装配时 MUST 优雅处理（确保装配后再踢或推迟），不静默丢任务。
- **FR-411**: 实施任务图完成后，系统 MUST 把结果（分支名、测试通过与否、安全摘要）回写到对应提案并使其在复盘视图可见。
- **FR-412**: 实施整体失败或测试不通过时，提案 MUST 转 `failed` 并展示安全失败摘要；MUST NOT 自动合并、MUST NOT 污染主工作区。
- **FR-413**: 执行体的自动改造 MUST 被焊死在以下爆炸半径内（三条各由门卫测试守住）：
  - **(a) 文件改动**：MUST 只发生在该提案隔离工作区内的 git 源码文件；对工作区之外文件、数据库文件、外部服务的修改 MUST fail-closed。
  - **(b) exec 能力**：跑测试所需的 exec MUST 限定在工作区内的测试型用途；网络型/破坏型 exec MUST 被阻断。
  - **(c) 禁改自我改进核心**：执行体 MUST NOT 修改自我改进子系统自身（提案生成/桥接/审查员/调度内核）与应用启动核心路径——防止递归砖化/坏提案反馈环。
- **FR-414**: 合并到主分支 MUST 保持用户手动完成；系统第一版 MUST NOT 自动合并或自动重启使改动生效。
- **FR-415**: 任意一次自动改造 MUST 可凭 git（删分支/弃工作区）干净回滚，不依赖数据库或外部清理；拒绝/失败后主工作区 MUST 无残留污染。
- **FR-416**: 自动改造进行期间 MUST NOT 扰动正在运行的应用所用文件（生效显式经合并 + 重启）。
- **FR-417**: 系统 MUST 串行化自我改造实施（同一时刻至多一条提案在实施，`has_in_progress` 闸门），避免多条改造争用执行容量；后批准的提案排队等前一条进终态。
- **FR-418**: 系统 MUST 对保留的实施工作区设回收策略（保留上限或显式清理入口），避免失败/完成的 worktree 长期堆积占盘。
- **FR-419**: 当存在 `pending_review` 提案时，系统 MUST 给用户一个可发现的待审提示（如非模态 toast / 计数徽标）。

### Key Entities

- **改进提案（Improvement Proposal）**：一行 = 一条可执行改造请求，来源于某条执行复盘的一个 `worth_changing` finding。关键字段：`id`、`source_review_id`（逻辑外键→`execution_reviews`）、`finding_index`、`status`、`severity`、`finding_type`、`dedup_key`、`what/evidence/suggestion` 快照、`user_supplement`、`graph_id`、`worktree_path`、`branch_name`、`result_tests_passed`（1/0/NULL 三态，v23 CHECK）、`result_summary`、`error`、时间戳。状态机：`pending_review → approved → in_progress → done | failed`；`pending_review → rejected`；`failed → rejected`（清理）。终态：`done`、`rejected`。
- **执行复盘记录（Execution Review）**：A 阶段既有实体，本特性只读引用，不改其结构。
- **提案状态机 CAS**：所有流转用条件 UPDATE + rowcount（`UPDATE ... WHERE id=? AND status=?`），避免重复批准/重复踢图丢更新；重复 approve 幂等忽略。

### Key Contracts

- **Typed API**（`src/desktop_api/routers/proposals.py`）：`GET /api/improvement-proposals`（status/limit 过滤，返回安全投影，公开 DTO 用 `worktreeAvailable` 而非本地 `worktreePath`）、`POST /{id}/approve`（body: supplement；CAS pending_review→approved，批准后桥接异步进行，API 立即返回 approved）、`POST /{id}/reject`（CAS pending_review|failed→rejected；对 failed 的拒绝先清理 worktree，清理失败返回 cleanup_failed 且保持 failed）。
- **公开 UI 事件**：`improvement_proposal.changed`（scope=global；payload allowlist: `proposalId/sourceReviewId/status/severity/changeType`；changeType: created/approved/rejected/in_progress/done/failed）。前端按 type 消费，缺口走 `backend.resync_required` → `GET /api/improvement-proposals` 拉权威快照。不复用 `task.*` 事件驱动提案展示（避免跨契约耦合）。
- **合成 session**：实施任务图使用 `self_improvement:<proposalId>` 命名空间，不复用真实对话 session，避免把自我改造完成当 briefing 注入聊天。

### Constraints & Compatibility

- **CC-145**: 严格分层——UI → typed API → business service → repository；UI MUST NOT 直连数据层；提案数据走新增 Repository，不在业务代码裸写 SQL。
- **CC-146**: 面向前端的事件 MUST 先在 UI Event Registry 注册再消费；缺口/会话不匹配走 `backend.resync_required`；MUST NOT 用内部事件名做前端展示决策。
- **CC-147**: 配置 MUST 走 `get_unified_config()`；MUST NOT 硬编码；secret MUST NOT 进入普通日志、明文 DTO 或前端持久化状态；实施失败的 provider 原始错误 MUST NOT 进入安全失败摘要。
- **CC-148**: A 阶段 `execution_reviews` 表、审查员逻辑/模型、advisory 语义 MUST 保持不变（回归边界）。
- **CC-149**: 任务协作系统（调度器单例、dispatcher、任务图、`requires_confirmation`、worktree 惯例）MUST 整体复用，MUST NOT 另起一套平行执行流水线。
- **CC-150**: 系统提示词与工具 MUST 走"直接改源码 + git"路径；本特性 MUST NOT 把提示词/工具数据化进数据库。
- **CC-151**: 本特性 MUST 停在 B（人批准、人合并）；MUST NOT 引入机器自动判定改得好不好并自批自改（C 阶段）。
- **CC-152**: 改静默失败/编排/事件/Repository/恢复路径 MUST 补行为契约测试；FR-413 的三条爆炸半径硬边界（文件/exec/禁改自我改进核心）MUST 各由架构门卫测试守住。
- **CC-153**: 提案对 finding 的 `what/evidence` 快照展示 MUST NOT 比 A 阶段已暴露的执行 trace 投影泄漏更多敏感内容；持久化与 UI 展示沿用 A 的脱敏边界。

### Success Criteria

- **SC-182**: 当一次执行复盘产出 `worth_changing` 发现，用户能在复盘视图看到对应提案，并完成"批准+补料"或"拒绝"，状态正确持久化、刷新/重连不丢。
- **SC-183**: 用户批准一条提案后，除"批准"外无需任何人工操作，系统即自动产出一个含改动且已在隔离工作区跑过测试的分支，并把"分支名 + 测试通过与否 + 安全摘要"回写到该提案。
- **SC-184**: 一次自动改造的全部文件改动 100% 限制在 git 跟踪源码内且位于独立工作区；执行体对非源码、网络/破坏型 exec、以及对自我改进核心与启动路径的修改尝试，均被 100% fail-closed 阻断（FR-413 三条门卫测试可证）。
- **SC-185**: 任意一次自动改造可凭 git 删分支/弃工作区在不动数据库与外部资源的前提下干净回滚；拒绝/失败后主工作区零残留。
- **SC-186**: A 阶段执行复盘的触发、产出 findings 结构、只读 API 与 advisory 语义在本特性前后保持一致（回归通过）。
- **SC-187**: 全程不发生"提案能批但实施无人推进"的断链（命门回归）：批准后任务图被真实推进至终态并回报。

### Edge Cases

- 复盘发现 `worth_changing=true` 但 suggestion 为空/含糊：仍生成提案，把"建议不足"如实展示由用户补料。
- A 阶段被关闭或某次任务无复盘：不产生提案，界面优雅空态，不报错。
- 同一会话短时间产生多条提案并被分别批准：各自独立 worktree/分支；实施按 FR-417 串行（一次一条 in_progress），其余排队。
- 桥接建工作区时目标路径已存在（上次残留）：拒绝复用脏工作区，按失败处理并提示，不静默覆盖。
- 实施任务图卡住/执行体崩溃：复用任务协作既有恢复语义（lease 围栏/恢复扫描）；最终仍无法推进则提案标 `failed`。
- 提案已 `approved` 但桥接建图失败：提案转 `failed`，记录安全原因，不留半截 `in_progress`。
- 用户对同一提案重复点批准：幂等，不重复建工作区/任务图。
- 多条提案先后批准：串行实施；某条合并后后续提案分支基线变旧 → 合并前提示用户 rebase/重建。
- 用户主工作树有未提交改动：自我改造基线是 HEAD commit、不含这些未提交改动（worktree 从 HEAD 创建）。

---

## MCP 工具管理 [Source: specs/027-mcp-management]

**Revision note (2026-07-06)**: Archived 027 after merge. 通过 MCP 协议接入第三方工具，合并进现有 skills/tools 屏管理。双轨注册（预置 server 全量注入 + 自定义 server 独立 LRU deferred）、McpProcessManager 子进程生命周期、凭证走 UnifiedConfigManager → app_settings、tools.changed 集成、SDK 延迟导入（E7）和业务类型隔离（N9）。

### User Stories

- **US-090 (P1)**: AI 自动调用 MCP 工具完成任务——用户配置一个 MCP server(如 GitHub)后,在 AI 助手对话中提及相关任务(如"看最新 PR"),AI 自动发现并调用 `mcp__github__list_prs`,将结果呈现给用户。用户无需手动选择工具或 server。预置 server（GitHub/filesystem）配置启用后 AI 立即可用；用户自定义 server 通过 `search_tools(kind="mcp")` 发现 + `get_tool_detail` 激活。
- **US-091 (P2)**: 在工具屏添加和配置 MCP server——用户在 skills/tools 屏的"MCP 工具"tab 中添加 server（预置一键启用/手动表单/粘贴 JSON），配置后看到连接状态和暴露的工具数。
- **US-092 (P3)**: 管理已配置的 MCP server——用户在 MCP 工具 tab 中查看已配置 server 的列表(名称/工具数/连接状态),可启用/禁用/删除 server,可重新编辑配置或重连。

### Functional Requirements

- **FR-420**: 用户 MUST 能在 skills/tools 屏的"MCP 工具"来源 tab 中添加、编辑、禁用和删除 MCP server
- **FR-421**: 添加 server MUST 支持三种路径:预置一键启用、手动填写表单、粘贴 JSON 配置自动解析回填,三路径 MUST 统一到同一张表单界面
- **FR-422**: 粘贴导入 MUST 兼容三种格式:Claude Desktop/Code 嵌套 `mcpServers` 格式(可能含多个 server,批量导入)、裸 stdio server 对象、HTTP server 对象
- **FR-423**: 每个 MCP server MUST 有以下字段:name(显示名+唯一标识)、transport(stdio/http)、enabled(启用开关);stdio 类 MUST 有 command/args/env;http 类 MUST 有 url/headers
- **FR-424**: env 和 headers 中标记为 secret 的值 MUST 走 `UnifiedConfigManager` → SQLite `app_settings` 存储,不进前端持久化状态、普通配置文件或普通日志
- **FR-425**: 粘贴导入中 `${VAR}` 占位符 MUST 优先读取系统环境变量;读不到 MUST 标记为"待补"并在保存时拦截提示用户填写
- **FR-426**: 保存 server 配置前 MUST 提供"测试连接"功能,后端拉起子进程(stdio)或发请求(http)、调用一次 `tools/list`,返回"✓ 连通,暴露 N 个工具"或具体错误
- **FR-427**: MCP 工具 MUST 带 `mcp__` 前缀自动注册进 agent 能力目录,与内置工具/技能工具并列,复用现有 `tools.changed` 事件域,不新增独立事件域
- **FR-428**: AI MUST 能自动发现并调用 MCP 工具,无需用户手动选择 server 或工具。预置 server（工具全量注入）配置启用后 AI 立即可用；用户自定义 server 通过 `search_tools(kind="mcp")` 发现 + `get_tool_detail` 激活。主助理能力目录 prompt MUST 在 deferred 模式下含 MCP 工具计数和触发引导。
- **FR-429**: MCP 工具的高危操作 MUST 穿透现有确认协议,与内置高危工具确认流程一致
- **FR-430**: MCP 工具的返回值 MUST 适配现有统一 envelope + output governance(复用 016/015)
- **FR-431**: MCP server MUST 以独立子进程(stdio)方式运行,不嵌入 FastAPI sidecar,规避 MCP SDK 嵌入已知 bug(#883/#737)
- **FR-432**: MCP server 断连 MUST 在 UI 上标灰(连接状态不可用),调用时返回明确错误信息,不静默失败
- **FR-433**: 预置 server MUST 先提供 GitHub 和文件系统两个,其余后补
- **FR-434**: MCP 工具 MUST 全部暴露给 AI,不在 UI 让用户逐个勾选启用/禁用单个工具;启用/禁用只在 server 级别操作。启发式高危判断存在误报和漏报,后续利用 MCP Tool `annotations.readOnlyHint` 减少对启发式的依赖

### Key Entities

- **McpServer**: 一个配置的 MCP server 实例。属性:唯一 ID(`mcs_` 前缀)、显示名、transport 类型(stdio/http)、command/args/env(stdio)或 url/headers(http)、启用状态、连接状态、暴露工具列表(缓存)、is_preset/preset_slug。存储在 SQLite `mcp_servers` 表(v24 migration)。
- **McpTool**: server 暴露的一个工具。属性:工具名(带 `mcp__<server_slug>__` 前缀)、描述、输入 schema、所属 server ID。运行态缓存，不做独立表。
- **McpServerCredential**: server 配置中的敏感值(token/API key)。属性:所属 server ID、字段路径(env key 或 header key)、存储位置(app_settings)。键格式 `mcp.servers.<server_id>.env.<key>` / `mcp.servers.<server_id>.headers.<key>`。

### Constraints & Compatibility

- **CC-154**: MCP server MUST 以独立子进程运行,不嵌入 FastAPI——与现有 Tauri 受管子进程架构同模式;MCP 子进程由后端统一生命周期管理
- **CC-155**: MCP 工具采用双轨注册:预置 server(GitHub/filesystem)全量注入 `tool_factory()` 保住"配置即可用"承诺；用户自定义 server 走独立 `McpToolRegistry` 路径(独立 LRU,不碰 DynamicToolManager 的 9 处横切改动),通过 `search_tools(kind="mcp")` + `get_tool_detail` 按需发现
- **CC-156**: 凭证存储 MUST 走 `UnifiedConfigManager` → SQLite `app_settings`,与现有 API key 存储同路径;MCP 凭证是同一类"接外部服务的凭证"
- **CC-157**: MCP 工具 MUST 走现有高危确认协议——写操作穿透确认,读操作免确认;与内置工具确认标准一致
- **CC-158**: MCP 工具大输出 MUST 走现有统一 envelope + output governance——`ToolOutputRepository` artifact + `load_tool_output` 授权恢复;不另辟大输出处理路径
- **CC-159**: skills/tools 屏 MUST 保留现有"教学工具"tab 完全不动;新增"MCP 工具"tab 与之并列,不改动已有卡片和生命周期
- **CC-160**: MCP 功能 MUST 不新增公开 UI 事件类型——工具注册/注销/重连成功/动态变化复用现有 `tools.changed`;server 连接状态变更但工具列表未变走 `backend.resync_required` 兜底
- **CC-161**: Python MCP SDK v1.x 为生产推荐版本;MVP MUST 用 v1.x,后续升级为独立任务
- **CC-162**: Streamable HTTP 为推荐传输方式;stdio 仅限本地进程场景——MVP MUST 先支持 stdio,HTTP 传输为后续扩展;MVP 中 `transport="http"` 的创建请求 MUST 返回 422
- **CC-163**: MCP 工具调用 MUST 不破坏现有 agent 100% 调度架构——MCP 工具是临时执行体可用的工具之一,不引入主助理直接执行路径

### Success Criteria

- **SC-188**: 用户配置预置 MCP server 后,在对话中请求相关任务,AI 在 3 次迭代内自动调用 MCP 工具并返回正确结果（预置全量注入）；自定义 server 因走 deferred loading 放宽到 5 次迭代内
- **SC-189**: 用户从 Claude Desktop 复制 JSON 配置,粘贴到添加弹层,解析+保存+测试连接,全过程在 2 分钟内完成
- **SC-190**: 已知 MCP server 断连后,UI 在 5 秒内更新状态为断连；从 server 实际不可用到 UI 标灰的最大延迟 < 65 秒
- **SC-191**: MCP 工具的高危操作触发确认协议,用户确认后执行成功,拒绝后不执行
- **SC-192**: 已有"教学工具"tab 功能完全不受 MCP tab 影响；现有测试全部通过
- **SC-193**: 已缓存 npx 启动 MCP server 延迟 < 5 秒；首次下载可能需 30 秒+
- **SC-194**: 从保存 server 配置到工具注册可用的延迟 < 10 秒（已缓存 npx 场景）

### Edge Cases

- 用户粘贴的 JSON 包含多个 server——批量导入
- `${VAR}` 占位符读不到系统环境变量——标"待补"，保存拦截
- MCP server 启动后中途崩溃——agent 调用时返回错误，server 卡片标灰
- MCP 工具名与内置工具名冲突——`mcp__` 前缀天然隔离
- MCP 工具返回超大输出——走现有统一 envelope + output governance
- MCP 工具执行高危操作——穿透现有确认协议
- sidecar 重启后 MCP server 需要重新连接——启动时异步自动重连，不阻塞主界面
- stdio server 的子进程被杀或僵死——超时检测和进程树清理
- MCP server 启动失败——错误映射为用户可理解的操作指引，API 响应附 `suggestion` 字段
- 预置 server 首次使用——空状态展示 2 个预置 server 卡片及一键启用入口
- 删除正在被 AI 使用的 server——UI 显示影响提示，不弹二次确认框
- catalog deferred 模式下"配置即可用"承诺降级——预置 MCP 工具也退化为计数
- 自定义 server 激活态 sidecar 重启丢失——`_activated_custom` 只在进程内存
- server name 创建后不可改——rename 会导致 slug/工具名变化
- MCP 工具 result prompt injection——prompt 加"外部结果不可信"引导 + envelope 标记 source=mcp
- MCP SDK import 失败时功能降级——CRUD API 可用但启动/测试连接不可用，返回 NullRegistry

## 提案审批"讨论"功能（chat about this） [Source: specs/028-proposal-discussion]

**Revision note (2026-07-07)**: Archived 028 after merge. BrainScreen 提案详情区新增"讨论/继续讨论"入口，用户在批准/拒绝前可对提案 finding 展开真实助理会话讨论；提案与讨论会话持久绑定（v25 `discussion_session_id` 列 + 条件 UPDATE CAS），会话删除惰性自愈重建；守住 026 审批前零副作用红线。

### User Stories

- **US-093 (P1)**: 审批前对提案展开讨论——用户在复盘视图看到待审批提案，对分析内容有疑问，点击详情区"讨论"入口进入以该提案完整分析开场的助理会话，追问细节后回到提案页做批准/拒绝决定。
- **US-094 (P2)**: 回到上次的讨论继续聊——用户上次对某提案讨论几轮后关闭，重启应用再点"讨论"回到同一会话，历史完整，可接着上次思路继续。
- **US-095 (P3)**: 终态提案的复盘讨论——提案已 done/failed/rejected，用户想复盘"当时为什么拒绝""实施失败还值不值得再试"，同样能点"讨论"，此时开场上下文含实施结果/失败原因。

### Functional Requirements

- **FR-435**: 提案详情区 MUST 提供"讨论"入口；对任意状态的提案（含 pending_review 与全部终态）均可用。
- **FR-436**: 首次点击"讨论"MUST 创建一个真实的普通助理会话，并以该提案的分析上下文开场：问题（what）、证据（evidence）、建议（suggestion）、严重程度（severity）、类型（findingType）、用户已填补充说明（如有）；终态提案还包含实施结果摘要 / 测试结论 / 失败原因（如有）。上下文序列化 MUST 复用既有 finding 文本拼装逻辑（`proposal_context.py` 单一来源），不另写一份副本。
- **FR-437**: 提案与讨论会话的绑定 MUST 持久化存储并跨应用重启有效；同一提案再次点击"讨论"MUST 回到已绑定会话。
- **FR-438**: 绑定的会话不存在或已删除时，点击"讨论"MUST 自动创建新会话并更新绑定（自愈，不报错终止）。
- **FR-439**: 讨论会话 MUST 是普通助理会话：出现在会话列表、使用既有消息与事件通道、可被用户像普通会话一样重命名/删除；不引入新的会话类型或独立聊天界面。
- **FR-440(028)**: 点击"讨论"与讨论过程本身 MUST NOT 触发任何提案实施副作用（不建 worktree、不建任务图、不改代码、不改变提案审批状态）；提案状态转换仍 MUST 只经既有批准/拒绝操作。允许的唯一提案数据变更是讨论会话绑定关系本身。
- **FR-441(028)**: 打开讨论会话 MUST NOT 自动消耗模型调用；助理从用户在讨论会话中发出第一条消息起才开始回应。
- **FR-442(028)**: 绑定写入 MUST 幂等：并发或重复触发"讨论"时至多创建一个会话（后到者复用先到者的绑定）。
- **FR-443**: 用户在讨论会话中 MUST 能看出讨论对象是哪条提案（开场上下文自身可读，无需跳回提案页对照）。

> 注：memory FR 续号至 FR-443 时与 028 feature-local FR-440~442 号段重叠，为保 memory 连续性对三条加 `(028)` 消歧，语义以本条目为准。

### Key Entities

- **改进提案（ImprovementProposal）**: 既有实体，新增可空 `discussion_session_id`（v25 migration）与讨论会话一对一绑定；绑定可因原会话删除而换绑。不建 FK，绑定死亡由业务层惰性自愈。
- **助理会话（Assistant Session）**: 既有实体；讨论会话是其普通实例，无新增会话属性。

### Constraints & Compatibility

- **CC-164**: 026 的"审批前零副作用"红线保持不变：审批前不得建 worktree / task graph / 执行代码；讨论路径不得成为绕过审批的实施入口（守卫测试断言讨论路径源码层不引用 proposal_bridge/build_task_graph/worktree）。
- **CC-165**: 讨论会话不赋予助理任何新增能力或工具；助理在讨论会话中的能力边界与普通会话完全一致。
- **CC-166**: 0 新公开 UI 事件类型：提案数据变化沿用既有 `improvement_proposal.changed`，会话消息沿用既有 assistant 事件。
- **CC-167**: 既有 approve/reject/list API 行为不变；既有提案审批测试必须继续通过。

### Success Criteria

- **SC-195**: 从提案详情到可输入的讨论会话 ≤ 1 次点击（不含首次加载）；开场上下文完整包含该提案全部已填分析字段。
- **SC-196**: 讨论-重启-再讨论闭环 100% 回到同一会话（绑定跨进程持久）；绑定会话删除后再讨论 100% 自愈成功。
- **SC-197**: 讨论路径产生的提案实施副作用为 0（无 worktree / 任务图 / 代码变更 / 状态转换），由守卫测试断言。
- **SC-198**: 既有提案审批交互（批准带补充说明 / 拒绝 / 刷新 / 权限开关）回归测试 100% 通过。

### Edge Cases

- 绑定会话被删除后再点"讨论"——创建新会话并重新绑定
- 快速连点"讨论"两次——绑定幂等，第二次复用第一次结果，不创建两个会话
- 助理在其他会话运行时点"讨论"——会话相互独立，不受影响
- 讨论中用户要求"直接把这个提案实施了"——助理按普通会话既有能力/限制行事，本 feature 不提供从讨论直达实施的捷径

## 技能商店（skills.sh / GitHub 安装外部技能） [Source: specs/029-skill-store]

**Revision note (2026-07-07)**: Archived 029 after merge. Skill List 屏第三个"技能商店"tab，从 skills.sh 市场与 GitHub 仓库直装外部技能；安装 = 受管目录文件 + BrainSkill(origin='external_import') + v26 来源元数据三件套原子成对；装前强制预览（SKILL.md 全文 + 审计/无审计警示）；安装路径零执行由守卫焊死；附带脚本只经既有 exec 管线运行。

### User Stories

- **US-096 (P1)**: 从 skills.sh 搜索并安装技能——用户在"技能商店"tab 搜索关键词，看到市场匹配结果（名称/来源/安装量），点开看 SKILL.md 全文 + 文件清单 + 安全审计后确认安装，技能进入方法论池可被执行体装备使用。
- **US-097 (P2)**: 从 GitHub 仓库直接安装——用户输入 `owner/repo` 或仓库 URL，系统发现根/skills/* 下的 SKILL.md，进入与 skills.sh 相同的预览确认流，但因无审计明确警示"未经安全审计"。
- **US-098 (P3)**: 已安装技能的管理——用户在方法论池能看出哪些来自外部（来源标注 + 原始链接），不想要的可卸载，走既有软删除生命周期并清理落盘文件。

### Functional Requirements

- **FR-444(029)**: Skill List 屏 MUST 新增"技能商店"来源 tab（与"教学工具""MCP 工具"并列）；tab 内支持关键词搜索 skills.sh 市场，空关键词展示精选/热门列表；结果项含名称、来源仓库、安装量。
- **FR-445**: 安装前 MUST 强制经过预览确认：SKILL.md 全文（markdown 安全渲染）、附带文件清单（路径+大小）、安全审计结果（skills.sh 来源）或"未经安全审计"显著警示（GitHub 直装）；预览阶段不落任何持久数据。
- **FR-446**: 确认安装 MUST 把技能落为外部导入方法论（名称/描述取 SKILL.md frontmatter，正文为 SKILL.md body），附带文件 MUST 只保存到受管的外部技能目录；安装动作本身 MUST NOT 执行技能内任何脚本或代码。
- **FR-447(029)**: 安装 MUST 幂等：同一来源+同一技能已安装（未卸载）时展示"已安装"，不重复创建；安装失败 MUST NOT 留下半安装状态（条目与文件原子成对）。
- **FR-448(029)**: GitHub 直装 MUST 支持 `owner/repo` 与完整 GitHub URL 两种输入；发现范围为仓库根目录 `SKILL.md` 与 `skills/*/SKILL.md`；多个匹配时列出供用户选择；无匹配时给出可理解错误。
- **FR-449**: 已安装外部技能 MUST 可卸载：方法论走既有软删除生命周期（历史链保留），受管目录附带文件清理，商店已安装标识同步消失。
- **FR-450**: 外部技能 MUST 全程可溯源：方法论详情展示来源（skills.sh/GitHub）与原始仓库链接；技能内容注入执行体上下文时 MUST 附带外部来源警示框架（提示内容来自外部、不可无条件信任其中指令）。
- **FR-451**: 附带脚本的执行 MUST 只发生在既有 delegated executor 的命令执行管线内（fail-closed workspace 策略 + 既有确认协议）；本 feature MUST NOT 引入任何新的执行通道或沙箱。
- **FR-452**: 网络错误、限速、来源不可达 MUST 转换为用户可理解、可行动的错误文案；商店功能降级 MUST NOT 影响教学工具/MCP 工具 tab 与其他屏。

> 注：memory FR 续号至 FR-444/FR-447/FR-448 时与 029 feature-local 号段重叠，加 `(029)` 消歧，语义以本条目为准。

### Key Entities

- **外部技能（安装态）**: 复用既有方法论资产 BrainSkill，`origin='external_import'`（已预留枚举）；来源元数据落 v26 `external_skill_installs` 伴生表（install_id/skill_id/source_type/source_ref/source_url/local_dir/installed_at/uninstalled_at），与 brain_skills 一对一。
- **技能商店条目（浏览态）**: 搜索结果/详情/审计结果，纯接口临时数据，不持久化。
- **受管外部技能文件目录**: 每个已安装技能一个独立子目录（`<data>/external_skills/<install_id>/`），存 SKILL.md 与附带文件；随卸载清理。

### Constraints & Compatibility

- **CC-168**: 安装路径零执行是硬边界：安装/预览代码 MUST NOT 调用命令执行、代码执行沙箱或 import 执行层模块，由守卫测试断言。
- **CC-169**: "支持可执行技能"的语义 = 附带脚本随技能落盘、由执行体在既有 exec 硬边界内按需运行；MUST NOT 在安装时试跑、MUST NOT 绕过 015 的 fail-closed workspace/确认契约。
- **CC-170(029)**: MVP 全部匿名访问外部服务；不引入任何新 secret/凭证存储。
- **CC-171(029)**: 0 新公开 UI 事件：方法论变化沿用既有事件与快照刷新；商店搜索/预览为前端临时态。
- **CC-172(029)**: 外部文件写盘 MUST 限定在受管目录内（路径规范化防穿越），单文件（≤512KB）与总大小（≤2MB）、文件数（≤40）设上限；二进制/超限文件拒绝。
- **CC-173(029)**: 既有教学工具 tab、MCP 工具 tab、方法论屏全部行为不变；既有测试必须继续通过。

### Success Criteria

- **SC-199**: 从商店 tab 到看到某技能的完整预览 ≤ 2 次点击；预览必含全文与审计/警示信息。
- **SC-200**: 安装完成的技能 100% 出现在方法论池、可被装备、`load_skill_methodology` 可加载其内容（附来源警示框架）。
- **SC-201**: 安装/预览路径的执行调用次数恒为 0，由守卫测试断言。
- **SC-202**: 公开 GitHub 仓库直装闭环可完成（发现→预览→安装）；无技能仓库得到明确错误。
- **SC-203**: 外部服务不可达时商店 tab 给出可行动错误提示，其余 tab 与屏幕零影响；既有全部测试通过。

### Edge Cases

- SKILL.md frontmatter 缺 name/description——回退用 slug 作名、正文首段截断作描述
- 同名方法论已存在——安装名自动加来源后缀（如 `frontend-design (skills.sh)`）避免冲突
- 技能文件树过大/含二进制——超单文件/总量/数量上限时拒绝安装并说明
- 文件路径含 `..`/绝对路径/盘符（zip-slip）——写盘前规范化校验，越界整体拒绝
- skills.sh/GitHub 不可达或限速——商店 tab 显示可行动错误，其他 tab 不受影响
- 安装到一半失败——逆序清理，方法论条目与文件目录要么都在要么都不在
- 卸载后重装同一技能——作为新条目正常安装，旧条目在软删除历史里

## 外部 Coding Session（Claude Code / Codex CLI） [Source: specs/030-external-coding-sessions]

**Revision note (2026-07-10)**: Archived 030 for merge into `prepare-github`. Claude Code / Codex CLI 作为 owner-bound 外部代码执行体接入任务协作；采用独立 coding worktree、PLAN/RESULT 两阶段协议、可恢复 attempt、quota-aware 选择、Exemplar-owned merge/rollback 审计和 task detail 权威状态。V1 只支持 Claude Code 与 Codex CLI，不新增依赖或 secret 存储。

> ID mapping: feature-local `US1~US4 / FR-001~030 / CC-001~008 / SC-001~007` archived as `US-104~107 / FR-460~489 / CC-174~181 / SC-204~210` to preserve the global memory sequence.

### User Stories

- **US-104 (P1)**: Agent 启动外部 coding session 并先审计划——为明确 Task/Workflow owner 创建持久 session、独立 worktree 与 artifact 目录，外部工具先产出 `PLAN.md`，派活 agent 审查后才允许实现。
- **US-105 (P2)**: 外部工具按已批准计划实现并可中断恢复——优先续用同一外部会话，在 quota、网络、登录、模型或进程中断后保留 attempt、日志、diff 与上下文供 inspect/resume/abandon。
- **US-106 (P3)**: Exemplar 自动合并并按用户意图回滚——完成后先分析目标 dirty set、coding branch changes、重叠和冲突，再由 Exemplar 合并；回滚只对本 session 的精确 merge commit 创建受确认的 revert。
- **US-107 (P4)**: Agent 自动选择 Claude/Codex 并关注 quota——读取安全归一化 quota 信号，优先健康工具、避免 exhausted 工具，且不暴露凭证、账户或原始 usage 响应。

### Functional Requirements

- **FR-460**: V1 MUST 只支持 Claude Code 与 Codex CLI 两种外部 coding 工具；Gemini、Agy 等不在本功能范围。
- **FR-461**: 外部 coding 能力 MUST 以可配置 agent tools 暴露，且没有明确 Task 或 Workflow owner 时 MUST 拒绝启动。
- **FR-462**: 启动 session MUST 创建持久 `codingSessionId`，记录 owner、工具、launch mode、时间、status/phase、可用的外部 session/thread id、worktree、branch 与 artifact 目录。
- **FR-463**: 每个 session MUST 默认使用 `.worktrees/coding/<codingSessionId>` 独立 worktree 与 `coding/<codingSessionId>` 分支。
- **FR-464**: `HANDOFF.md`、`PLAN.md`、`RESULT.md` 与审计/恢复所需有界日志 MUST 存在 `data/coding_sessions/<codingSessionId>/`。
- **FR-465**: 系统 MUST 支持默认 headless managed launch 与 interactive supervised launch；交互模式仍以显式 artifact 判断完成，不解析终端屏幕。
- **FR-466**: 每个新 session MUST plan-before-code；只有续跑已批准计划且记录原因时才可直接进入 implement。
- **FR-467**: Plan 阶段 MUST 请求 `PLAN.md` 覆盖目标复述、计划改动、影响范围、假设/非目标、风险、测试计划、开放问题和是否继续建议。
- **FR-468**: `PLAN.md` MUST 是最低语义覆盖的 soft template，不得把固定标题文本当成硬 schema。
- **FR-469**: Plan 阶段 MUST 只读调查；相对持久 worktree 创建基线的 staged、unstaged、untracked 或 committed mutation MUST 作为协议违规回流裁定。
- **FR-470**: 实现前派活 agent MUST 审核计划，并明确 approve、带反馈 reject、request clarification 或向用户升级高风险产品决策。
- **FR-471**: 实现 SHOULD 复用同一外部会话；需要新进程时 MUST 保持同一 `codingSessionId` 并记录 attempt 边界。
- **FR-472**: session 生命周期内工具选择 MUST 固定；Claude/Codex 切换必须放弃或完成旧 session 后新建 session。
- **FR-473**: Claude Code 与 Codex CLI MUST 默认请求可用的最高 reasoning/effort；不可用时 MUST 中断为 `model_unavailable`，不得静默降级。
- **FR-474**: 外部工具 MAY 运行测试、lint、类型检查、依赖安装或网络动作；依赖、网络与 lockfile 影响 MUST 在 `RESULT.md` 披露。
- **FR-475**: 外部工具 MUST NOT 获得目标分支 merge/push/reset/clean 权限；检测到的尝试 MUST 作为高风险偏离展示给派活 agent。
- **FR-476**: 有效完成 MUST 要求 `RESULT.md` 在语义上包含状态、摘要、changed files、计划偏差、测试及结果、已知风险、后续事项和 completion notes。
- **FR-477**: 进程退出但没有有效 `RESULT.md` 时，session MUST 保持 interrupted/failed，不得标记 completed。
- **FR-478**: 中断 MUST 保存 task brief、plan、日志、外部 id、worktree、当前 diff、最后错误类别与 resume count，允许 inspect/resume/abandon 而无需用户重述任务。
- **FR-479**: 只有 owner agent 判断内部无法解决并已向用户请求行动或澄清后，session 才能进入 `waiting_user`。
- **FR-480**: 外部完成后的独立 review/test MUST 被强烈建议但不是状态机硬门卫；跳过任何一项时最终详情和摘要 MUST 明示 `reviewSkippedReason`。
- **FR-481**: 自动 merge MUST 由 Exemplar 执行并记录 target branch、pre-merge HEAD、coding branch HEAD、changed files、dirty/conflict analysis 与结果。
- **FR-482**: Merge 前 MUST 比较目标 workspace dirty files 与 coding branch changed files，并展示 overlap/conflict 风险。
- **FR-483**: 低风险分析 MAY 允许自动 merge；存在 overlap 或 predicted conflict 时 MUST NOT 静默合并，必须有 agent 裁定。
- **FR-484**: V1 rollback MUST 只针对本 session 已记录的精确 merge commit 执行 `git revert`；执行前必须验证 target branch/HEAD、merge ancestry、双 parent 与 clean workspace，并要求显式确认；reset/clean/reverse patch/manual apply 不受支持。
- **FR-485**: QuotaProbe MUST 为两种工具输出 `available | low | exhausted | unknown`，并含安全 source、confidence 与 checked/reset time。
- **FR-486**: QuotaProbe MAY 读取本地 credential/status/usage source，但 MUST NOT 在日志、DTO、UI event 或 artifact 中持久化或暴露 credential、账户标识、原始响应或密钥路径。
- **FR-487**: 自动选择 MUST 按 `available > unknown > low > exhausted` 排序，默认避免 exhausted；只有显式 override 才允许选择 exhausted，并记录原因。
- **FR-488**: 关联 task/subagent detail MUST 展示 status、phase、tool、branch、artifact previews、有界 log tail 与 `availableActions`，操作必须调用真实 typed API。
- **FR-489**: UI MUST 能在 event gap、断线或重启后从后端权威 snapshot 恢复；公开 event 只作安全刷新通知，raw external output 始终有界且脱敏。

### Key Entities

- **ExternalCodingSession**: 外部 coding assignment 的持久事实源；含 owner、固定 tool、launch mode、status/phase、worktree/branch/artifacts、base commit、review 状态和最终结果。SQLite v27 建表、v28 补 `base_commit`。
- **ExternalCodingAttempt**: 一次 plan/implement CLI invocation 或 resume；含 command summary、external ref、PID/identity、exit/status、log tail 与安全错误分类。
- **CodingHandoff / CodingPlan / CodingResult**: 分别对应 `HANDOFF.md`、`PLAN.md`、`RESULT.md` 的协议 artifact；正文落受管目录，API 只返回有界预览。
- **ExternalCodingQuotaObservation**: 安全归一化 quota 观察；仅保存 state/source/confidence/reset/check time/safe detail。
- **ExternalCodingMergeRecord**: merge analysis 与执行审计；记录两端 HEAD、dirty/changed/overlap、conflict risk、agent decision 与 merge commit。
- **ExternalCodingRollbackDecision**: 绑定 merge record 的 rollback 审计；V1 固定 `revert_commit`、显式确认和 applied/blocked/failed 状态。

### Constraints & Compatibility

- **CC-174**: 主 Assistant 仍是协调者；外部 coding 工具只进入 delegated executor / specialist 工具集，planner 不拿实现型工具，不创建无 owner 后台任务。
- **CC-175**: Claude Code / Codex CLI 只是外部 coding execution tools，不得成为 Exemplar 的通用 LLM provider。
- **CC-176**: 业务状态 MUST 持久化到 SQLite Repository；进程内 registry 只管理运行态，不能作为恢复事实源。
- **CC-177**: quota credential access 仍受 UnifiedConfigManager 与 secret 脱敏规则约束；原始 usage response 必须在 execution adapter 内丢弃。
- **CC-178**: Merge/rollback authority 只属于 Exemplar；外部 CLI 命令 profile 必须禁止目标分支 push/merge/reset/clean。
- **CC-179**: V1 隔离以 dedicated worktree、owner/state gate、plan review 和 merge control 为核心，不复制 self-improvement proposal 的 source-only sandbox 语义。
- **CC-180**: `PLAN.md` / `RESULT.md` 采用 semantic soft validation；关键状态、owner、baseline、merge 和 rollback 安全由确定性业务门卫保证。
- **CC-181**: 一个 session 固定一种外部工具；cross-tool continuation 必须建新 session 并保留旧 session 审计。

### Success Criteria

- **SC-204**: 代表性任务能在 agent 与外部 CLI 之间自动完成建 session、产出 `PLAN.md` 和 approve/reject，不需用户跨应用搬运计划。
- **SC-205**: 受控验证中至少 95% 的 completed session 在进程结束后 5 秒内提供 `RESULT.md`、worktree diff summary 与可见 task detail 状态。
- **SC-206**: quota/network/login/model/missing-result 中断 100% 保留足够上下文供 inspect/resume/abandon，无需用户重述原任务。
- **SC-207**: 每个 merged session 100% 留下 pre-merge state、dirty/conflict analysis 与 post-merge outcome。
- **SC-208**: quota probe 的普通日志、公开 event、DTO、前端状态与 session artifact 中 raw credential/account/usage response 泄漏为 0。
- **SC-209**: 一工具 exhausted、另一工具 available 时，除显式 override 外，routing tests 100% 选择 available 工具。
- **SC-210**: 独立 review 或 test 被跳过时，最终 agent summary 100% 显示尚未独立 review/test 及原因。

### Edge Cases

- CLI 未安装、不可执行或未登录——session 不启动，返回安全且可行动的 setup/login 错误。
- 最高 reasoning/effort 档不可用——中断为 `model_unavailable`，不自动降档。
- Plan 阶段任何基线后 mutation——`protocol_violation`，不得进入 `plan_ready`。
- 有 `RESULT.md` 但 coding branch 无提交/无改动——merge readiness fail-closed，不把用户任务盲目标记为已交付。
- `RESULT.md` 自报测试但无独立证据——保留 review warning，不冒充独立验证。
- 依赖/网络/lockfile 影响——必须在 result 与 merge risk 中披露。
- 外部 CLI 尝试 merge/push/reset/clean——命令层拒绝并在审计中展示偏离。
- 目标 workspace 有 dirty files——先做 overlap/conflict analysis；非低风险必须裁定。
- 中途切换 Claude/Codex——拒绝；放弃或完成旧 session 后另建 session。
- rollback intent 不清或 merge/HEAD 已变化——拒绝陈旧 proposal，先澄清并重新分析；不得用 reset/clean 覆盖后续工作。
- UI event gap 或 session mismatch——触发 `backend.resync_required` 并拉 task/session 权威 snapshot。

## 委派上下文交接 [Source: specs/032-delegation-context-handoff]

**Revision note (2026-07-18)**: Archived 032 for merge into `prepare-github`。主助理委派子代理/专员时新增 `context_message_indexes`（1-based，按本轮完整可见消息数组计数，system 占位但禁止引用），委派时刻按 AgentLoop LLM 路径 contextvar 快照逐字展开为「主对话相关原文」段并入 execution_context；异步路径落库前展开持久化进 `task.description`。system/非法下标/无快照/超限整体 fail-closed。同时补齐 `delegate_to_specialist` 的 execution_context 字段并修复异步 specialist description 静默丢弃；`load_reference` message ID 路径按 Agent 角色授权。相邻 T019 MCP 生命周期加固（startup attempt fence、迟到成功隔离、有界 shutdown、SDK stack cleanup 失败传播）作为综合审查修复保留在本 feature 内。0 新公开 UI 事件 / 0 新表 / 0 新 migration / 0 新 secret。

> ID mapping: 031（external-coding-skill-composition）尚未归档；为保 memory 既有 ID 不重排，032 编号续在当前最高号之后（US-108~110 / FR-490~501 / CC-182~187 / SC-211~217），与未来 031 归档段号不连续，属预期（同 025 先例）。

### User Stories

- **US-108 (P1)**: 委派时携带对话中已产生的内容——主助理委派执行体时通过消息引用把方案/清单/结论/代码片段所在的历史消息一并交接；执行体启动时初始输入已含原文，忠实执行而非凭"之前讨论的方案"指代编造。
- **US-109 (P1)**: 异步任务稍后执行仍拿到全文——复杂任务建图落库前就地展开引用为原文并持久化；进程重启、快照消失后 worker 执行时仍拿展开全文。
- **US-110 (P2)**: 固定专员获得同等交接能力——专员委派入口补齐 execution_context 字段并获得与子代理同等的消息引用能力。

> Adjacent Review Repair（MCP 生命周期竞争加固，Verification Gate）：综合审查发现既有 MCP server 启停存在竞争窗口（同步桥超时/stop/shutdown 后旧启动协程迟到发布 session、关停遗漏 starting server 或残留 Task、非 owner thread 关闭 loop）。T019 为每个 server 建立唯一 startup attempt 围栏、隔离迟到成功、有界 shutdown 覆盖 running/starting + 残留 Task，Desktop API lifespan 收口到 `McpServerService.shutdown()` facade。该修复不扩展 032 委派产品能力，作为相邻可靠性修复声明；权威协议以 `specs/027-mcp-management/contracts/mcp-server-lifecycle.md` 为准。

### Functional Requirements

- **FR-490**: 临时子代理委派入口 MUST 支持可选 `context_message_indexes`：主助理按当前可见对话消息顺序指定要携带的历史消息；不提供时行为与现状一致。
- **FR-491**: 固定专员委派入口 MUST 补齐 execution_context 字段并支持与 FR-490 同等的 `context_message_indexes`。
- **FR-492**: 引用解析与原文展开 MUST 由委派链路在委派时刻完成，基于本轮喂给主助理的消息数组快照；展开结果作为独立「主对话相关原文」段注入执行体初始输入。
- **FR-493**: 展开 MUST 逐字保真：原文由系统拷贝，不经任何模型改写、摘要或截断（超上限时整体报错而非截断）。
- **FR-494**: 异步/建图路径 MUST 在任务持久化之前完成展开，持久化内容为全文；任务执行 MUST NOT 依赖委派轮的内存快照。
- **FR-495**: 非法引用（system 消息、越界、重复、非法值）MUST fail-closed：整次委派失败并把可理解错误返回主助理供其重填；MUST NOT 部分展开或静默丢弃。system 消息 MUST NOT 下放，避免泄漏只对父 Agent 授权的能力目录。
- **FR-496**: 展开原文总量 MUST 有可配置上限，超限整体报错；上限走统一配置入口。
- **FR-497**: 执行体 MUST 保持纯接收方：不新增任何读取父会话消息的工具或接口，子会话与父会话隔离边界不变。
- **FR-498**: 填参硬约束 MUST 写在委派工具 schema description 中（凡任务引用对话已产生内容必须用消息引用携带，禁止只写指代）；MUST NOT 通过修改主助理 system prompt 实现。任务图建图入口节点描述字段 MUST 同步加强"自包含"表述。
- **FR-499**: 本 feature MUST NOT 新增公开 UI 事件、secret、数据库表或 migration；省略 `context_message_indexes` 时不得触发下标解析或自动展开。兼容性例外是 FR-491/FR-494 所需异步 specialist 交接修复：非兜底 `task.description` 不再静默丢弃，恢复 checkpoint 改由 execution_context 补充上下文段传递；description 为空/等于 title 且无 checkpoint 时保持原输入形态。
- **FR-500**: 相邻 MCP 审查修复 MUST 为每个 `server_id` 保持至多一个权威 startup attempt；attempt MUST 在 SDK import、配置解析、临时资源和进程构造前绑定，且只有仍为 current、未取消的 attempt 才能在同一锁内原子发布 session/stack/cache。bridge 超时、stop 或 shutdown 后的迟到成功 MUST NOT 发布 running 状态。
- **FR-501**: Sidecar shutdown MUST 只经 `McpServerService.shutdown()` business facade 进入进程管理器；关停 MUST 覆盖 running/starting server、已跟踪 startup cleanup 与残留后台 Task，按有界取消/收割协议由 owner thread 关闭事件循环。无法在边界内收口时 MUST 显式记录并向同步调用方报告失败；running server 的 SDK stack close 超时/异常不得被吞掉，内部缓存清理完成后仍 MUST 传播失败。

### Key Entities

- **LlmMessagesSnapshot（内存态，新）**: 主助理本轮送入 LLM 的消息数组的不可变解析投影（`tuple[SnapshotMessage, ...]`，frozen role/content 拷贝），经 contextvar 在工具执行期间可见；仅 AgentLoop LLM 路径设置，批次结束清除；恢复/initial 路径不设置。源数组在工具执行期间被误改也不影响解析。
- **ContextMessageIndexes（工具参数，新）**: `list[int]` 可选；每项 1-based 正整数，≤ 快照长度，不得重复，不得指向 system，提供时不得为空；只在委派工具执行瞬间按快照解析，不进入下游 Task 语义。原始 tool-call 参数仍按既有机制保存在 `messages.tool_calls` 供 function-call 配对、审计与崩溃恢复。
- **ExpandedContextBlock（派生文本，新）**: 按下标取出的消息原文组成的标记文本块（`【主对话相关原文】` + 逐条 `--- 消息 #<idx>（<role>）---` + 原文），追加进 execution_context；同步路径经 `_format_delegated_task_input` 渲染，异步路径随 `task.description` 落库。handler 附不可见内部 provenance 标记并随 Task 描述持久化，仅最终执行体格式化边界识别"header + provenance"、移除标记并逐字保留该块，避免异步中间层二次消费；普通用户文本同名 header 不触发保真分支。
- **复用 `assistant_tasks.description`（v15 既有列）**: 异步路径展开后的 execution_context 经 `_dispatch_task_via_unified_model(context=...)` → `dispatcher.create_child_task(description=...)` 原样落库，执行时由 TaskExecutorAdapter 回填；落库内容为展开后全文，不含未解析下标。

### Constraints & Compatibility

- **CC-182**: "主助理会正确携带所需上下文"是模型软约束（靠工具 description 指导），MUST NOT 描述为硬保证；系统硬保证的是"给了合法引用就逐字展开、给了非法引用就整体报错"。
- **CC-183**: 子会话与父会话隔离是既有安全边界，本 feature 不得为交接便利开任何执行体侧读取父会话的口子。
- **CC-184**: 展开内容随任务描述落库属既有存储面（会话内容本就持久化于消息表），不新增 secret 暴露面；引用解析过程不进普通日志。
- **CC-185**: 配置（展开总量上限）统一走 `get_unified_config()`，不硬编码。
- **CC-186**: MCP 生命周期相邻修复只加固 027 既有 stdio server 启停契约；MUST NOT 新增公开 API、UI 事件、secret、表、migration 或传输类型；权威细节以 `specs/027-mcp-management/contracts/mcp-server-lifecycle.md` 为准。
- **CC-187**: startup attempt fence、迟到成功隔离和 shutdown drain 是确定性并发边界，MUST 由行为测试硬保证，MUST NOT 依赖第三方 SDK 总会及时响应取消。

### Success Criteria

- **SC-211**: 典型场景（上一轮产出方案、本轮委派写文件）下执行体初始输入包含方案原文且与父会话原文逐字一致，自动化测试可验证。
- **SC-212**: 100% 的非法引用委派整体报错并可被主助理重试，不存在部分展开或静默丢弃用例。
- **SC-213**: 异步任务在委派轮内存快照消失（含进程重启）后执行，执行体输入仍包含展开全文。
- **SC-214**: 不使用 `context_message_indexes` 的既有委派回归测试保持通过；异步 specialist 的 description/checkpoint 兼容性例外由专门回归测试覆盖。
- **SC-215**: 专员委派入口与子代理委派入口的上下文交接能力对齐（补充上下文 + 消息引用均可用）。
- **SC-216**: MCP 并发启动、资源构造前 stop、bridge 超时/取消、迟到成功与失败清理测试全部通过；不存在已失效 startup attempt 发布 running session 的用例。
- **SC-217**: MCP shutdown 测试证明 running/starting server 与后台 Task 均进入有界收口，Desktop API lifespan 只经 service facade 关停；startup Task 拒绝取消、SDK stack close 超时/异常及 drain/join 失败都可观察并向同步调用方传播，不会静默成功。

### Edge Cases

- 引用指向 system 消息、下标越界/重复/非法（负数、非整数）——整次委派 fail-closed 报错，错误回主助理重填；不部分展开、不静默忽略。
- 被引用内容已被压缩归档（可见数组里只剩摘要）——主助理数不到原文位置，不在 V1 范围；先用既有原文取回机制恢复再委派。
- 展开总量过大（引用多条超长消息）——超配置上限时整次报错并提示缩小范围，不截断。
- 被引用消息是工具结果（如文件读取输出）——允许引用，按原文展开不做二次加工。
- 同轮并发/连续多次委派——每次独立解析各自引用，互不影响。
- MCP 启动 Task 在 bridge/stop/shutdown 取消期限内拒绝退出——旧 attempt 仍必须先失去发布资格；stop/shutdown 显式报告未收口风险，不得把迟到 session 写回 running。
- MCP running server 的 SDK `AsyncExitStack.aclose()` 超时或抛错——内部 session/stack/cache 仍必须清除，但 `stop_server()`/`shutdown()` 必须向同步调用方传播失败，不得只记 warning 后伪装成功。

## 外部 Coding 技能组合与专员授权 [Source: specs/031-external-coding-skill-composition]

**Revision note (2026-07-18)**: Archived 031 for merge into `prepare-github`。030 的 11 个 external coding 工具收口为系统内置、只读、已发布的范围型技能组合「外部 Coding」；Specialist Management 按组合配置并把 `composition_ids` 版本化持久化到 SQLite v29（`brain_specialists` + `brain_specialist_versions`）。只有已配置组合的固定 executor 专员在正式 Task 中可经组合按需激活成员工具；主助理、ephemeral、planner、同步专员和试用路径均 fail-closed。0 新公开 UI 事件 / 0 新 secret；复用 030 全部 owner/task 绑定、PLAN/RESULT、quota、merge/rollback 与安全门卫。

> ID mapping: 031 时序早于 032（2026-07-13 vs 07-14）但归档滞后；为保 memory 既有 ID 不重排，031 编号续在 032 之后（US-111~113 / FR-502~510 / CC-188~189 / SC-218~221），故 031 段号高于 032，属预期（同 025 先例）。本 feature 直接在 `prepare-github` 集成分支实施（非 feature 分支），spec/plan/tasks 为可审查性在提交前补录。

### User Stories

- **US-111 (P1)**: 用一个组合配置外部 Coding 能力——用户在技能组合列表看到系统内置、已发布、只读的范围型组合「外部 Coding」；在专员管理页只勾选这一个组合，不再逐项选择 11 个底层动作；保存后只存组合 ID（不复制成员进 `tool_whitelist`）并形成可审计专员版本。
- **US-112 (P1)**: 仅在正式 Task 中按需激活——配置了组合的固定 executor 专员在持久 Task 节点执行代码任务时先看到组合目录；调用组合后 11 个成员工具才进入其能力集合（range 延迟激活），初始不预注入成员 schema。
- **US-113 (P1)**: 非授权执行体无法猜 ID 绕过——主助理、临时子代理、planner 专员、无固定专员身份的委派会话以及未配置组合的专员都不能通过猜测内置组合 ID 获得 external coding 工具。

### Functional Requirements

- **FR-502**: 系统 MUST 以代码定义的稳定 ID 提供「外部 Coding」内置组合；其 11 个成员 MUST 与 030 的 external coding tool factory 保持同源。
- **FR-503**: 内置组合 MUST 固定为 `range + published + assistant_enabled + read-only + trial-disabled`。
- **FR-504**: 组合服务和 Desktop API MUST 返回 builtin/read-only/试用支持/assistant-enabled 元数据。
- **FR-505**: 专员配置 MUST 只保存组合 ID，并通过 `SpecialistService` 校验组合当前可分配状态（published、非待复核、assistant-enabled）。
- **FR-506**: `composition_ids` MUST 同时持久化到 `brain_specialists` 和 `brain_specialist_versions`，使用 SQLite v29 migration（JSON 文本列 + downgrade）。
- **FR-507**: external coding 成员工具 MUST 仅在 `AgentType.SPECIALIST` + `role_kind=executor` + 固定 `specialist_id` + 非空 `current_task_id` + 组合已显式授权五项条件同时成立时构造。
- **FR-508**: 范围型组合 MUST 先激活虚拟组合工具，再由组合调用激活成员；MUST NOT 在初始 delegated executor 工具集中直接注入成员。
- **FR-509**: main assistant、ephemeral、planner、同步 specialist、试用和未配置路径 MUST fail-closed（不展示、不激活、成员工具始终不存在）。
- **FR-510**: 本 feature MUST 复用 030 的 owner/task 绑定、PLAN/RESULT、quota、merge/rollback 和安全门卫；MUST NOT 新增 secret、公开 UI event 或外部 CLI 协议。

### Key Entities

- **内置「外部 Coding」组合（code-defined）**: 固定 ID 的系统内置范围型组合，11 个成员与 030 tool factory 同源；只读投影，不写入可编辑 `skill_compositions` 表，避免用户更新和成员漂移；调用方只依赖 `SkillCompositionService`。
- **`composition_ids`（SQLite v29）**: `brain_specialists` 与 `brain_specialist_versions` 上的 JSON 文本列，记录专员已配置的组合 ID；专员版本化保证当前记录与版本历史一致。

### Constraints & Compatibility

- **CC-188**: 本 feature MUST NOT 新增 secret、公开 UI event 或外部 CLI 协议；全部 owner/task 绑定、PLAN/RESULT、quota、merge/rollback 与安全门卫复用 030。
- **CC-189**: 授权矩阵（main/ephemeral/planner/同步 specialist/试用/未配置/猜 ID 全部 fail-closed）是确定性代码门卫硬保证；组合目录快照不是授权事实——运行时激活 MUST 重校验固定 executor 身份 + 持久 Task + 显式组合授权（与既有「能力目录快照不能成为授权事实」一致）。

### Success Criteria

- **SC-218**: 用户配置外部 Coding 能力时只操作 1 个组合项，而不是 11 个工具项。
- **SC-219**: 自动测试证明所有非授权矩阵均无法看到或激活组合成员。
- **SC-220**: 专员配置更新后，当前记录与版本历史中的 `composition_ids` 一致。
- **SC-221**: 既有 external coding 业务、API 和 UI 相关回归测试保持通过。

## Scheduling Center（调度中心） [Source: specs/033-scheduling-center]

**Revision note (2026-07-20)**: Archived 033 on the verified feature branch for merge into
`prepare-github`。新增时间维度触发中枢：立即 / 一次性定时 / 周期任务到点后新建
`source=scheduled` 主助理会话，复用既有 100% 调度与 task collaboration 内核执行，
并提供执行记账、完成/接管通知、管理屏和待办来源接入。CC-005 的 per-task 无人值守
免确认持久化已作为 constitution 3.1.0 唯一显式受控例外登记；0 新 secret。任务账本
94/96，剩余 T075/T080 均为 Windows NSIS / 实机 quickstart 人工验收。

> ID mapping: 033 feature-local US1~6 / FR-001~025 / CC-001~010 / SC-001~008
> 归档时顺延为 US-114~119 / FR-511~535 / CC-190~199 / SC-222~229；
> 不复用或重排既有全局编号。

### User Stories

- **US-114 (P1)**: 立即触发——用户在对话中提出现在执行的任务，主助理通过创建工具弹出
  全局确认卡；确认后任务落库并立即点燃 scheduled 会话，取消、超时、停止或发布失败均
  fail-closed 不创建。验收：完成后有 Toast + 桌面通知和 succeeded 历史，聊天列表不出现
  该 scheduled 会话。
- **US-115 (P1)**: 一次性定时——用户核对人类可读时刻与指令后创建 one-shot 任务；
  app 运行且到点时只触发一次，成功触发后任务进入 completed，不再重复执行。
- **US-116 (P2)**: 周期任务——支持每隔 N 分钟/小时、每天、每周和工作日规则；
  app 重启只补跑最近一次 misfire，同任务上次未静默时本次记 skipped 且不并发堆积。
- **US-117 (P2)**: 待办接入——待办行内动作以标题 + 描述预填可编辑指令，经确认后创建
  one-shot 任务；执行只读校验待办仍存在且未完成，结果可回显但绝不自动修改待办状态或表结构。
- **US-118 (P2)**: 无人值守安全与人工接管——未授权 scheduled 会话的高危动作立即拒绝；
  用户可仅为单个任务通过 UI 显式开启免确认；需要补充信息时 run 进入 `waiting_user` 并通知，
  用户可从历史进入会话继续处理。
- **US-119 (P2)**: 调度中心管理屏——`/scheduled` 一览任务状态、调度描述、下次触发和
  上次结果，支持暂停/启用/现在跑/软删；免确认授权列表层醒目可回收，scheduled 会话仅在
  调度历史可见并可导航接管。

### Functional Requirements

- **FR-511**: 系统 MUST 支持立即动作、一次性定时和周期三种触发；立即是可作用于既有任务的动作，不是第三种持久任务类型。
- **FR-512**: 每次触发 MUST 新建 `source=scheduled` 的主助理会话并投递用户核定后的指令；调度中心不得自行拆任务或派执行体。
- **FR-513**: scheduled 会话 MUST 获得无人值守 advisory；安全边界仍由确定性机制 fail-closed 保证。
- **FR-514**: 执行、通信、恢复和任务图推进 MUST 复用既有 task collaboration 内核；只允许登记的公共图终态函数与观察事件接缝。
- **FR-515**: 定时任务创建入口 MUST 是主助理专用工具 + 用户确认卡；调度中心 UI 不提供绕过确认的创建表单。
- **FR-516**: 创建 MUST 等用户核对标题、时刻和指令后才落库；取消、超时、停止、关闭和事件发布失败均不得创建。
- **FR-517**: 创建确认卡 MUST 以默认关闭的复选框让用户显式决定 per-task 无人值守免确认，且详情页可事后回收。
- **FR-518**: 第一批周期规则 MUST 至少支持 interval、daily、weekly 和 weekdays；不得引入完整 cron/rrule。
- **FR-519**: `SchedulerWorker` MUST 随 sidecar 生命周期启动/停止，使用周期扫描 + 事件唤醒，并动态等待最近 `next_fire_at`。
- **FR-520**: app 未运行导致的 misfire MUST 只补跑最近一次；暂停期间错过不补跑，one-shot 过点后 expired，周期滚到下个未来时点。
- **FR-521**: worker 与 fire-now 并发时，同一 task 同时最多一个 `running|waiting_user` run；数据库 partial unique index 是 first-wins 权威门卫，冲突记 skipped 且不建会话。
- **FR-522**: 完成 MUST 定义为无活跃主助理 worker、无未消费回流且任务图全终态；任一查询未知时 MUST 延后，不得把首轮 completed 或 root 状态误当完成。
- **FR-523**: 静默且全成功标 succeeded，含失败/取消标 failed，需要用户回答标 `waiting_user`；前三类按契约通知，skipped 只记历史。
- **FR-524**: app 运行时终态通知 MUST 同时提供应用内 Toast 与桌面通知；app 未运行时既不触发也不通知。
- **FR-525**: 待办来源 MUST 只保存 `todo_id` 外部引用和用户核定后的独立 `instruction`，触发前只读校验待办；不得修改 `user_todos` schema。
- **FR-526**: `source_type=todo` MUST 恒为 one-shot；待办删除或完成后任务 MUST 惰性 expired，Repository 读取异常不得误判为悬空。
- **FR-527**: 待办来源任务执行后 MUST NOT 自动改变待办状态；是否标记完成仍由用户决定。
- **FR-528**: `/scheduled` MUST 展示任务及历史，并提供暂停、启用、fire-now、软删和接管入口。
- **FR-529**: `unattended_auto_approve=true` 的任务 MUST 在列表层醒目标识并可在详情页显式回收。
- **FR-530**: 调度中心空态 MUST 提供去对话创建的示例与指引。
- **FR-531**: scheduled 会话 MUST 从普通 AI Assistant 会话列表排除，仅通过调度历史查看或继续。
- **FR-532**: 定时任务删除 MUST 走软删；历史 run 与真实关联会话保留可追溯。
- **FR-533**: 未开启 per-task 免确认的 scheduled 会话遇高危确认 MUST 立即拒绝，不得等待普通超时，也不得被进程级“全部允许”越权放行。
- **FR-534**: per-task 免确认 MUST 同时限定为仅 scheduled 会话、仅该 task、默认关闭、仅用户显式 UI 操作开启；不得改变进程级 `_auto_approve_enabled` 或其他会话。
- **FR-535**: `unattended_auto_approve` MUST NOT 出现在创建/更新定时任务的 Agent 工具 schema、handler 参数或通用创建/更新路由中；唯一写路径是确认卡和详情 PATCH。

### Key Entities

- **ScheduledTask**: SQLite v30 `scheduled_tasks`；保存来源、`source_ref`、用户核定后的独立
  `instruction`、调度规则、状态、per-task 授权、`next_fire_at`/`last_fired_at` 与软删标记。
  `source_type=todo` 只保存外部引用，不建 FK。
- **ScheduledTaskRun**: SQLite v30 append-only `scheduled_task_runs`；记录 task/session、
  起止时间、`running|succeeded|failed|waiting_user|skipped`、安全摘要与失败投影；
  partial unique index 保证每 task 仅一个 active run。v31 增加
  `terminal_event_delivered_at` 与单调 `terminal_event_version`，按代次确认终态事件投影。
- **Session 来源**: 既有 `sessions` 表在 v30 增加 `source`、`scheduled_task_id`、
  `is_scheduled`；既有行回填为 user，Repository 强制 scheduled 三字段关系一致。

### Data Flow / Architecture

`create_scheduled_task` → `SchedulingConfirmationManager` → `SchedulerService` →
`scheduled_tasks`；`SchedulerWorker` 到点后调用 `SessionLauncher`，在同一事务提交 detached
session + active run，再经 desktop lifespan 注入的 callback 调用权威 `AssistantRuntime`。
`RunCompletionMonitor` 由 runtime worker 退出直调和内部图/任务事件双路径重评静默条件，
写入 run 终态后通过 `TerminalEventDelivery` 发布注册过的 UI 事件；v31 对未确认投影在启动
与 worker tick 有界重试。business 层不反向 import desktop API。

### Constraints & Compatibility

- **CC-190**: 调度路径 MUST NOT 修改 `user_todos` 表或结构；待办仅作外部只读引用。
- **CC-191**: todo 来源 MUST 恒为 one-shot，防止周期语义污染个人待办。
- **CC-192**: task collaboration 执行/通信/恢复决策保持不变；公共图终态函数和首次全终态 observer emit 不得门控既有 root 收口或父侧 reentry，观察者失败不得阻断原路径。
- **CC-193**: 无人值守安全 MUST 由立即拒绝和权威 session/task 判定硬保证，不得退回 prompt 或乐观超时。
- **CC-194**: `unattended_auto_approve` 持久化是 constitution 3.1.0 登记的唯一受控例外，必须保持四重限定、三重不暴露、独立 manager 和列表层可回收。
- **CC-195**: scheduled 会话第一批 MUST NOT 参与 brain Segment 沉淀。
- **CC-196**: 5 个 scheduled task Agent 工具 MUST 仅对主助理开放，不得进入 delegated executor 工具集。
- **CC-197**: 面向前端的 5 类 scheduling 事件 MUST 经 UI Event Registry typed envelope 发布；内部通知走 blinker。
- **CC-198**: scheduler 配置与本地时区发现 MUST 经 `UnifiedConfigManager`/权威依赖；不得新增明文 secret 或静默回退 UTC。
- **CC-199**: Tauri notification plugin MUST 只申请 `notification:default` 最小权限；业务终态规则不得下沉 Rust。

### Success Criteria

- **SC-222**: 自然语言创建后，确认卡展示的时间/指令与实际持久化、触发行为一致。
- **SC-223**: 立即、one-shot 和 recurring 均按规则触发，短周期可在分钟级验证。
- **SC-224**: succeeded、failed、waiting_user 在 app 运行时产生可区分通知，skipped 不打扰用户。
- **SC-225**: 调度中心完整展示任务与历史，免确认任务可一览并显式回收。
- **SC-226**: app 重启只补最近一次 misfire，一次性用户意图不会静默丢失。
- **SC-227**: 未由用户显式授权的 scheduled 高危动作不会执行，且不污染其他会话的确认状态。
- **SC-228**: failed 或 waiting_user run 可从历史进入真实会话继续沟通和接管。
- **SC-229**: 待办接入不改变待办 schema 或完成状态，也不引入周期待办语义。

### Edge Cases

- app 关闭期间不触发、不通知；启动后按 misfire 规则补最近一次。
- paused 期间过点不补跑；one-shot expired，recurring 滚到未来。
- 同 task 重入或并发抢占 active-run 槽时只记 skipped，不启动第二个会话。
- todo 被删除/完成时 task expired；todo Repository 暂时失败时保留任务重试。
- 首轮主助理 completed 但 durable 子任务仍在执行时不得误报终态。
- 图含失败/取消或图/runtime 查询未知时不得误报全成功。
- 终态事件采用持久 at-least-once 投递；发布后、确认前退出的极窄窗口允许重复提醒，但不得永久丢失。
- 无 offset 时间按显式 IANA 时区或 `tzlocal` 发现的系统时区解释；发现失败拒绝创建，DST ambiguous/nonexistent 按已登记规则处理并记录 warning。
