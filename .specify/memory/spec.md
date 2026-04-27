# Main Specification Memory

**Purpose**: Consolidated requirements from all merged features. Single source of truth for what the system does.
**Last Updated**: 2026-04-27
**Revision**: 2026-04-27 — Merged `specs/002-tool-hook-system`

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
