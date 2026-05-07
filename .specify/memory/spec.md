# Main Specification Memory

**Purpose**: Consolidated requirements from all merged features. Single source of truth for what the system does.
**Last Updated**: 2026-05-07
**Revision**: 2026-05-07 — Merged `specs/007-desktop-recording`

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
### US-011: 单次确认改为非阻塞浮层 (Priority: P1)

Assistant Agent 触发高危工具时，主窗口右下角出现非阻塞浮层，显示工具名与关键参数摘要，提供"全部允许 / 同意 / 拒绝"三按钮。用户可正常浏览聊天记录、滚动页面、打开侧边栏。 [Source: specs/004-auth-toast]

### US-012: 会话级"全部允许"快捷通道 (Priority: P2)

浮层"全部允许"按钮一键开启会话级豁免：本次会话内后续所有 Assistant 高危工具请求自动放行。新建对话时自动复位。 [Source: specs/004-auth-toast]

### US-013: 顶栏 Toggle 与浮层状态双向同步 (Priority: P3)

对话窗口顶栏提供"免确认" Toggle，与浮层"全部允许"共享同一会话级状态，任一入口变化后另一处可视状态立刻同步。新对话时一并复位。 [Source: specs/004-auth-toast]

### US-014: AI 回复消息以富文本展示 Markdown (Priority: P1)

AI 回复包含标题、列表、代码块、加粗、链接、图片、表格等 Markdown 元素时，聊天气泡将 AI 回复渲染为富文本结构。用户消息保持纯文本。Markdown 链接/图片不触发外部导航。 [Source: specs/006-chat-ui-polish]

### US-015: 压缩后的旧聊天记录仍可回看 (Priority: P2)

长会话触发上下文压缩后，被归档的早期用户消息与助手回复仍按原时间顺序出现在同一聊天时间线中。不显示归档/压缩分区标签。工具调用/结果/压缩摘要不作为普通聊天记录展示。初始展示最近 10 条，滚动向上分页加载。 [Source: specs/006-chat-ui-polish]

### US-016: 新对话/欢迎界面不展示"免确认"Toggle (Priority: P3)

"免确认" Toggle 仅在当前对话已启动过 Agent 会话后可见。欢迎界面、新对话起始态、清空后的会话不展示。 [Source: specs/006-chat-ui-polish]

### US-017: 录制桌面操作并产出可分析数据 (Priority: P1)

用户在录制页选择桌面模式后，应用最小化主窗并在 minimize 完成后启动全局键鼠 hook、UIA 查询、剪贴板订阅和帧缓冲。停止录制后主窗恢复，sanity check 对话框展示健康统计，用户可继续进入 intent 分析。 [Source: specs/007-desktop-recording]

### US-018: Agent 使用桌面录制数据生成方案 (Priority: P1)

PM / Programmer / Trial 在桌面 mode 下使用 5 个通用录制数据工具的 mode dispatch 和 3 个桌面专属工具分析 `desktop_recordings` / `desktop_actions`，同时浏览器路径工具和 prompt 保持不退化。 [Source: specs/007-desktop-recording]

### US-019: 桌面 Programmer 代码进入隔离 Trial 子进程 (Priority: P2)

Programmer 输出的 `async def execute() -> dict` 先经过 `ast.parse` syntax gate 和最多 2 次自动反馈重试，再由 execution 层子进程在 `data/trials/<trial_id>/` 隔离 cwd、env 白名单和 120s 超时兜底下试用执行。 [Source: specs/007-desktop-recording]

### US-020: 桌面录制健康反馈与早期止损 (Priority: P3)

录制停止后，用户通过 sanity check 颜色、动作总数、UIA 命中率、clip 成功率和三按钮状态机决定继续分析、放弃录制或重新录制；`vision_model` 缺失时以设置区说明和一次性 toast 透明提示降级。 [Source: specs/007-desktop-recording]

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
- **FR-116**: `recording.desktop.vision_model` 未配置时 MUST 不注入 `analyze_desktop_action`，并在设置页说明和桌面 intent 页一次性 toast 中提示降级；provider 和 API key 沿用 `analyze_image` 现有 provider/keyring entry。
- **FR-117**: Phase 1 MUST 不引入录制数据 retention、cleanup、compress 或 disk quota；放弃录制为软删除状态，Trial 调试目录 7 天 startup cleanup 与录制数据保留边界分开。

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
会话级自动放行状态。字段：`enabled`（bool，默认 False）、`source`（最近变更来源）。生命周期等于一次对话；新对话复位。不持久化到 config/DB/keyring。

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
运行时配置 namespace `recording.desktop.*`。字段：`enable_clip`（bool，默认 true）、`vision_model`（str | None，无默认）。provider 和 API key 沿用 `analyze_image` 当前 provider/keyring entry。

### HighRiskApiDetection [Source: specs/007-desktop-recording]
桌面 Trial 事前提示与"走捷径"判定共用的静态检测结果。命中规则覆盖 `subprocess`、`os.startfile`、`webbrowser`、Win32 协议 URL（排除 Windows 盘符路径）、pywin32 高级 API、pywinauto 控件级 API；纯 pyautogui 坐标点击不算捷径。

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
