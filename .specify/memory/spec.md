# Main Specification Memory

**Purpose**: Consolidated requirements from all merged features. Single source of truth for what the system does.
**Last Updated**: 2026-04-25
**Revision**: 2026-04-26 — Merged `specs/003-fix-agentloop-tool-calls`

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

[Source: specs/001-recording-field-layering]

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

[Source: specs/001-recording-field-layering]

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
