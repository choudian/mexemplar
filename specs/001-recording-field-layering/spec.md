# Feature Specification: 录制数据大字段按需读取

**Feature Branch**: `001-recording-field-layering`
**Created**: 2026-04-21
**Status**: Completed
**Input**: 录制数据中单个字段（如 response_body、dom_tree_snapshot、siblings 等）可能非常大（实测单条 HTML 响应达 1.2MB），当前 query_data 工具对所有字段统一截断 12KB。这样做既会浪费上下文，又会让 Agent 误以为自己拿到了完整值。需要在保留 query_data 行数据查询体验的前提下，对大字段做占位替换，并提供分段读取能力，让 Agent 在不撑爆上下文的情况下逐步查看原始内容。

## Clarifications

### Session 2026-04-22

- Q: 哪些 SQL 结果列应触发大字段占位替换？ → A: 任意文本结果列值达到阈值都触发占位（含计算/聚合列）；计算/聚合/歧义来源只影响 `locator` 是否可用（详见 2026-04-23 会话最终澄清）
- Q: `read_field_chunk` 应采用什么定位参数接口？ → A: 接收占位信息中的 `locator` 对象，并额外接收 `field`、`offset`、`length`
- Q: 当查询结果缺少稳定定位字段时，占位对象应如何表达“暂时不能继续读取”？ → A: 仍返回占位对象，但将 `locator` 设为 `null`，并新增 `read_blocked_reason` 表达阻塞原因 *(REFINED 2026-04-24：`read_blocked_reason` 为稳定枚举值，人类可读说明放入可选 `read_blocked_message`)*
- Q: `read_field_chunk` 的成功响应应采用什么结构？ → A: 返回固定结构化对象，包含 `content`、`field`、`locator`、`offset`、`returned_length`、`total_length`、`has_more`、`next_offset`
- Q: 当 `offset` 已到达或超过字段结尾时，`read_field_chunk` 应如何返回？ → A: 返回成功结构，`content` 为空字符串，`returned_length=0`，`has_more=false`，`next_offset=null`
- Q: spec 中”按字符计”应采用什么精确定义？ → A: 按 Python `str` 的 Unicode 码点计数，`len()` 与字符串切片行为即规范
- Q: NULL 或非文本大字段值如何处理？ → A: 仅处理非 NULL 的文本字段；NULL 值和二进制/非文本内容直接透传，不触发占位替换
- Q: read_field_chunk 是否需要性能延迟目标？ → A: 不设硬性延迟目标，该工具为 Agent 低频按需调用，不构成性能瓶颈
- Q: 大字段阈值应设为多少？ → A: 1000 字符（约 1KB），远低于当前 12KB 截断点，确保绝大多数大字段走新机制
- Q: 当 `read_field_chunk` 收到非法范围参数时应如何处理？ → A: 当 `offset < 0` 或 `length <= 0` 时返回明确错误，不执行读取

### Session 2026-04-23

- Q: 运行时配置变更后，旧的 `locator` 是否仍保证可读？ → A: 在取消字段级 hint/allow-list 后，`threshold_chars`、`preview_chars`、`max_chunk_chars` 的运行时变更只影响后续交付大小，不使既有 `locator` 失效；旧 `locator` 是否可读仅取决于源记录/字段仍存在、字段仍为文本列，以及 `network_requests` 的现有过滤边界是否允许读取
- Q: 上下文预算应按什么口径计算？ → A: 按字符计 `preview_chars` / `max_chunk_chars` + 元数据固定小结构，不使用完整 JSON 字节作为硬验收线（详见本会话第 3 条最终澄清）
- Q: spec 是否需要给出复杂 SQL 的支持/不支持示例？ → A: 需要；至少给出一个保留稳定定位字段且仍支持继续读取的 join 示例，以及一个聚合或计算列表达式导致不支持继续读取的示例
- Q: `network_requests` 的过滤/脱敏边界是否只是实现细节？ → A: 不是；它是硬约束，`query_data` 与 `read_field_chunk` 对 `network_requests` 的读取都不得绕过现有过滤/脱敏边界
- Q: 文档和 prompt 从 4 tools 更新到 5 tools 是否属于正式验收范围？ → A: 是；所有面向 Agent 或开发者的活文档、prompt 和配置注释都必须与新的 5 工具工作流保持一致
- Q: blocked / unsupported / error 路径是否需要硬性可观测性要求？ → A: 需要；至少产出可检索的结构化日志，但本期不要求额外的 metrics 或 tracing 指标
- Q: `FR-016` / `SC-005` 中“活文档、prompt、配置注释”是否需要明确清单？ → A: 需要；最小清单至少包括 `docs/ARCHITECTURE.md`、`docs/design/pm_agent_design.md`、`docs/design/programmer_agent_design.md`、`docs/design/recording_tools_redesign_todo.md`、`config.example.comments.md`、`src/business/agents/prompts/pm_prompt.py`、`src/business/agents/prompts/programmer_prompt.py`
- Q: 完整 JSON 预算与 `preview_chars` / `max_chunk_chars` 冲突时谁优先？ → A: `preview_chars` / `max_chunk_chars` 现为唯一硬上限，无独立 JSON 预算（详见本会话第 3 条最终澄清）
- Q: 当字段值仅略高于阈值，但直接回传原文的完整 JSON 可能比占位对象更短时，应如何处理？ → A: 仍必须按阈值规则走占位替换；一旦达到阈值，不因“原文 JSON 恰好更短”而豁免，以保持规则单调且可预测
- Q: 当 join 结果中看似存在稳定定位字段，但字段来源有歧义或需额外推断时，应如何处理？ → A: 保守判定为不支持继续读取；若无法无歧义定位到单条源记录，则不得依赖启发式推断继续读取
- Q: 大字段占位替换与分段读取应限定在 `FR-001` 白名单，还是扩展到所有文本字段？ → A: 扩展到所有文本字段；任何文本结果列值达到阈值（默认 1000 字符）都触发占位+预览替换，取代原 `_MAX_QUERY_CELL_CHARS = 12_000` 的无差别截断路径；`read_field_chunk` 续读是否可用取决于能否明确追回单条源记录，且源表必须由内置 `StableLocatorRule` 覆盖（直接列选择/简单 alias + 字段存在于源表 schema + 结果行保留该表稳定定位字段）。聚合、计算、无稳定定位字段、源表未覆盖等情形仍触发占位但 `locator=null`。`describe_data` 的提示改为基于当前 schema + stable locator 规则自动派生，不再维护 `FR-001` 字段名单
- Q: `read_field_chunk` 在失败路径下应返回什么结构？ → A: 复用成功响应的固定结构并新增 `error` 字段（`{code, message}`）；`error == null` 表示成功，非空表示失败；失败时 `content=""` / `returned_length=0` / `has_more=false` / `next_offset=null` 与“已读完”场景共用同一形状，Agent 仅依靠 `error` 字段是否存在区分成功/失败；`error.code` 同时作为 `SC-006` 结构化日志的检索维度
- Q: `read_field_chunk` 单次返回的 content 长度上限是多少？是否仍维持“完整 JSON 预算”作为硬验收线？ → A: 单段 `content` 硬上限固定为 1000 字符（约 1KB），不再使用“完整 JSON 预算”作为独立验收线。元数据为固定小结构，整体 JSON 自然收敛在约 1.5KB 内。本条覆盖 2026-04-23 早些时候关于“上下文预算按完整 JSON 计算”和“完整 JSON 预算优先于 `max_chunk_chars`”的两条澄清——后者作废，统一以 `max_chunk_chars=1000` 为唯一硬上限
- Q: `SC-001` 是否同步采用与 `SC-002` 一致的“按字符计 + 元数据固定小结构”框架？ → A: 是；`SC-001` 改为“占位对象 `preview` ≤ `preview_chars`（默认 1000 字符），元数据为固定小结构”，不再用 JSON 字节大小作为硬断言；整体 JSON 自然收敛在约 2KB 内
- Q: `read_field_chunk` 的 `length` 参数是必填还是可选？缺省时如何处理？ → A: 可选；缺省时取 `max_chunk_chars`（默认 1000 字符），与单段硬上限对齐；Agent 仍可显式传更小的 `length` 做精细控制

### Session 2026-04-24

- Q: `read_blocked_reason` 应使用人类可读说明还是稳定枚举值？ → A: `read_blocked_reason` 使用稳定枚举值；新增可选 `read_blocked_message` 放人类可读说明，与 `error.code` / `error.message` 模式一致

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent 在 query_data 中识别大字段 (Priority: P1)

Agent 在分析录制数据时，通过 query_data 查询到一条包含超大 response_body 的网络请求记录。系统不再把该字段直接截断成 12KB 原文，而是返回一个简短占位值，明确告诉 Agent 这个字段很大、当前只给了极短预览、如需继续查看应使用分段读取。

**Why this priority**: 这是最高频、最关键的默认路径。只要 query_data 仍然把大字段直接塞进上下文，Agent 就会继续被大字段拖垮。

**Independent Test**: 可通过 query_data 返回包含大字段记录，验证返回值中大字段显示为占位信息（包含大小和继续读取提示），而非 12KB 截断原文。

**Acceptance Scenarios**:

1. **Given** 录制数据中有一条 response_body 为 1.2MB HTML 的网络请求，**When** Agent 通过 query_data 查询该记录，**Then** response_body 字段返回简短占位信息（包含大小和继续读取提示），而非截断的原始 HTML
2. **Given** 录制数据中有一条 dom_tree_snapshot 为 500KB 的操作记录，**When** Agent 通过 query_data 查询该记录，**Then** dom_tree_snapshot 字段被占位替换，其余正常字段保持原样返回
3. **Given** 录制数据中有一条 response_body 仅为 200 字节的网络请求，**When** Agent 通过 query_data 查询该记录，**Then** response_body 字段返回完整原始内容（小字段不触发占位替换）

---

### User Story 2 - Agent 分段读取大字段内容 (Priority: P1)

Agent 在 query_data 结果里看到某个字段被占位替换后，决定继续查看真实内容。Agent 可以使用单独的分段读取工具，按字段、偏移量和长度读取该字段的一小段原文。

**Why this priority**: 这是让 Agent 真正“继续看下去”的关键能力。没有它，占位替换只会把问题从“爆上下文”变成“完全看不到内容”。

**Independent Test**: Agent 对已知的大字段调用分段读取，验证返回指定范围内的原始内容，并附带可继续读取的位置信息。

**Acceptance Scenarios**:

1. **Given** Agent 已知某条 response_body 很大且拥有可定位该记录的标识字段，**When** Agent 请求读取 offset=0 的第一段内容，**Then** 系统返回该范围内的原始文本片段，并附带 total_length、has_more 或 next_offset 等继续读取信息，且这些范围字段统一按字符计
2. **Given** Agent 已读取某字段的第一段内容，**When** Agent 使用下一段 offset 再次读取，**Then** 系统返回后续片段而不是重复前一段
3. **Given** Agent 请求的 length 超过单次允许上限，**When** 系统执行分段读取，**Then** 系统仅返回允许范围内的内容，并明确告知实际返回范围

---

### User Story 3 - Agent 逐段查看完整字段 (Priority: P2)

Agent 可能需要的不只是第一段内容，而是继续查看中间部分、末尾部分，甚至最终遍历完整个字段。系统允许 Agent 通过多次分段读取逐步拿到完整原始值，但不要求一次性把超大字段塞回当前上下文。

**Why this priority**: 如果系统只能返回第一段片段，关键内容一旦不在开头，Agent 仍然会被卡住。必须支持持续向后读取。

**Independent Test**: Agent 对 1MB 以上字段连续发起多次分段读取，验证能逐段读到结尾，且没有单次工具结果超过上下文安全范围。

**Acceptance Scenarios**:

1. **Given** 某条 response_body 超过 1MB，**When** Agent 通过多次分段读取持续向后读取，**Then** 系统最终返回 has_more=false，表示字段内容已经读到结尾
2. **Given** Agent 在多次分段读取过程中需要查看中间区域，**When** Agent 指定新的 offset 请求该区域内容，**Then** 系统返回对应窗口的原始内容
3. **Given** Agent 请求的 offset 已到达或超过字段结尾，**When** 系统执行读取，**Then** 系统返回明确的“无更多内容”成功响应：`content` 为空字符串、`returned_length=0`、`has_more=false`、`next_offset=null`

---

### User Story 4 - 与现有数据发现和查询工具透明集成 (Priority: P2)

Agent 继续沿用现有的 describe_data 和 query_data 工作流。describe_data 负责告诉 Agent 哪些字段可能很大、后续读取要依赖哪些定位字段；query_data 负责正常返回行数据并在必要时对大字段做占位替换；分段读取工具负责按需读取具体内容。

**Why this priority**: 如果集成不清楚，Agent 看到占位信息之后仍然不知道下一步该怎么做，功能就无法闭环。

**Independent Test**: Agent 使用 describe_data 获取字段说明，再用 query_data 查询包含大字段的记录，随后根据占位提示成功调用分段读取工具读取后续内容。

**Acceptance Scenarios**:

1. **Given** Agent 正常使用 query_data 查询，**When** 结果中包含超过阈值的大字段，**Then** 该字段自动替换为占位信息，其余正常字段不受影响
2. **Given** describe_data 向 Agent 展示表结构信息，**When** 某些字段可能很大，**Then** 描述信息中标注这些字段及后续读取所依赖的定位字段
3. **Given** Agent 在查询结果中看到大字段占位信息，**When** Agent 需要继续查看内容，**Then** 可通过固定提示 `read_field_chunk` 请求读取指定记录指定字段的后续片段

---

### Edge Cases

- 当同一查询结果中包含多个大字段时，每个字段独立占位；单个字段的默认占位交付大小需受控，但不要求整条查询结果中所有大字段占位总量都满足同一个固定上限
- 当字段值恰好等于阈值大小时，触发占位替换（>= 阈值即触发）
- 当 query_data 查询结果中未包含后续定位该记录所需的稳定标识字段时，占位信息必须明确提示“继续读取前需要补查定位字段”
- 当 Agent 请求的单次读取长度超过允许上限时，系统仅返回允许范围内的内容，并告知实际返回范围
- 当 Agent 请求的 `offset < 0` 或 `length <= 0` 时，系统返回明确错误，不执行读取，也不做静默纠正
- 当占位对象已经返回、但后续调用 `read_field_chunk` 前 `threshold_chars`、`preview_chars`、`max_chunk_chars` 被运行时调整时，既有 `locator` 不因这些数值配置变化失效；后续读取只重新校验源记录/字段仍存在、字段仍为文本列、定位列合法稳定，以及 `network_requests` 的现有过滤/脱敏边界仍允许读取
- 当字段值刚刚达到或略高于阈值时，即使直接回传原文的完整 JSON 交付可能短于占位对象，系统仍必须按阈值规则返回占位信息
- 当录制数据中某条记录被删除后，Agent 再次分段读取该字段时，系统返回明确的“数据不可用”提示
- 当 Agent 请求的 offset 已达到或超过字段结尾时，系统返回明确的“无更多内容”成功响应，且 `content` 为空字符串、`returned_length=0`、`has_more=false`、`next_offset=null`
- 当 Agent 试图读取字段不存在、字段不是文本列、定位列非法或不稳定、或无法无歧义映射到单条源记录的字段时，系统按固定错误结构返回明确错误，而不是静默失败
- 当 query_data 使用 join，且结果中直接选择内置 `StableLocatorRule` 覆盖源表的大字段，并同时保留能唯一定位单条源记录的稳定定位字段时（例如 `SELECT nr.request_id, nr.response_body AS body, a.action_type ...`），系统仍支持继续分段读取对应源字段
- 当 query_data 的结果中虽然出现看似可用的稳定定位字段，但该字段来源存在歧义、同名列无法无歧义归属，或继续读取依赖启发式推断时，系统必须保守判定为“不支持继续读取”
- 当 query_data 的结果行来自聚合、汇总、计算列或其他无法回溯到单条源记录的结果时（例如 `SELECT recording_id, COUNT(*) ... GROUP BY recording_id` 或 `SELECT response_body || '' AS body ...`），若结果值达到阈值仍触发占位替换，但占位对象 `locator=null` 并明确提示该结果不支持继续分段读取

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须基于当前源表 schema 与内置 `StableLocatorRule`，自动向 describe_data 标注哪些文本字段在值达到阈值时会进入“大字段占位 + 分段读取”工作流，并给出默认稳定定位字段建议；v1 至少必须正确覆盖 `network_requests.response_body`、`actions.dom_tree_snapshot`、`sibling_snapshots.siblings` 这三类已知大字段来源；提示范围不再由可配置字段清单决定
- **FR-002**: query_data 在返回结果时，对于**任意**文本字段值达到阈值的结果列，必须返回占位信息；本特性接管原 `_MAX_QUERY_CELL_CHARS = 12_000` 的无差别截断路径，query_data 不再保留”仅超过 12KB 才截断”的旧行为。占位对象是否允许 `read_field_chunk` 续读的判定规则见 **FR-015**。一旦达到阈值，不因”直接回传原文的完整 JSON 交付恰好更短”而豁免占位替换
- **FR-003**: 占位信息必须以结构化对象形式确定性生成，不使用 LLM，且至少包含以下固定字段：`__large_field__`、`field`、`size_chars`、`preview`、`locator`、`read_hint`。其中：
  - `field` 在可从直接投影推导时表示源字段名，而不是 SQL alias 或展示名；在计算列、聚合列、歧义来源等无法推导源字段名但仍触发占位的场景下，`field` 使用结果列名且 `locator=null`
  - `preview` 为必填字段，表示该字段原始文本按字符截取后的前缀预览，长度必须不超过 `preview_chars`
  - `locator` 在可继续读取时必须至少包含 `table`、`id_field`、`id_value`；当结果行缺少稳定定位字段而无法继续读取时，`locator` 必须为 `null`
  - `read_hint` 的固定值为 `read_field_chunk`
- **FR-003a**: 当结果行缺少稳定定位字段、计算/聚合/歧义来源、源表未被内置 `StableLocatorRule` 覆盖或其他原因导致无法继续调用 `read_field_chunk` 时，占位信息必须包含稳定枚举字段 `read_blocked_reason`，为以下枚举值之一：`missing_locator_field`（结果行缺少稳定定位字段）、`computed_or_aggregated_column`（计算列/聚合列）、`ambiguous_locator_source`（定位字段来源歧义）、`unsupported_source_table`（源表未由内置 `StableLocatorRule` 覆盖）；占位信息可以额外包含 `read_blocked_message` 作为人类可读说明，用于提示 Agent 需先补查定位字段或当前结果不支持继续读取。非文本结果值不触发占位替换
- **FR-004**: 系统必须提供一个单独的分段读取工具 `read_field_chunk`，允许 Agent 传入占位信息中的 `locator` 对象、`field`、`offset`，以及可选的 `length`，对指定记录的指定字段读取原始内容；`offset` 与 `length` 统一按字符计，并遵循本文定义的“字符计数语义”；当 Agent 不传 `length` 时，系统按 `max_chunk_chars`（默认 1000 字符）作为本次返回长度上限；工具执行时必须按当前源表 schema、内置 `StableLocatorRule` 与统一配置重新校验 `locator.table` 与 `field` 是否仍可对单条源记录执行文本分段读取；统一配置仅控制阈值/预览/chunk 上限，不作为字段级可读 allow-list
- **FR-005**: 分段读取工具必须返回固定结构化对象，至少包含 `content`、`field`、`locator`、`offset`、`returned_length`、`total_length`、`has_more`、`next_offset`、`error`；其中 `content` 为本次返回的原始文本片段，`returned_length` 必须严格等于 `len(content)`，其余范围元信息统一按字符计，并遵循本文定义的“字符计数语义”；`error` 字段在成功时为 `null`，失败时为 `{code, message}` 结构（`code` 为可枚举的稳定字符串标识，`message` 为人类可读说明），失败时 `content=""`、`returned_length=0`、`has_more=false`、`next_offset=null`，其余字段在可计算时仍如实回填、否则为 `null`
- **FR-006**: 大字段的“完整访问”定义为可通过多次分段读取逐步拿到完整原始值，而不是要求系统一次性返回超大字段全文
- **FR-007**: 当 Agent 请求的单次读取 `length` 超过 `max_chunk_chars`（默认 1000 字符）时，系统必须将 `content` 实际长度限制在 `max_chunk_chars` 内，并通过 `returned_length` / `next_offset` / `has_more` 如实告知实际返回范围
- **FR-008**: 当 Agent 请求的 offset 已达到或超过字段结尾时，系统必须返回明确的“无更多内容”成功响应：`content` 为空字符串、`returned_length=0`、`has_more=false`、`next_offset=null`
- **FR-009**: 当请求参数非法（如 `offset < 0` 或 `length <= 0`）、定位记录失败、字段不存在、字段不是文本列、定位列非法或不稳定、数据已不可用时，系统必须按 `FR-005` 定义的固定结构返回，并将 `error` 设为非空 `{code, message}`，且不得静默纠正请求参数；`error.code` 必须为以下枚举值之一：`invalid_offset`（`offset < 0`）、`invalid_length`（`length <= 0`）、`unknown_table`（源表未由内置 `StableLocatorRule` 覆盖）、`field_not_found`（字段不存在）、`non_text_field`（字段不是文本列）、`unknown_id_field`（定位列非法或不稳定）、`record_unavailable`（定位失败或数据不可用）、`unsupported_continuation`（计算列/聚合/歧义来源不可续读）、`internal_error`（未预见的内部错误）
- **FR-010**: 未超过阈值的小字段必须保持原有行为，直接返回完整内容，不触发占位替换
- **FR-011**: 大字段阈值、占位预览长度、单次分段读取上限必须通过统一配置管理，支持运行时调整；配置变更对后续工具调用立即生效，但仅影响占位触发阈值、预览长度与单段返回上限，不作为字段级可读 allow-list；先前已返回的 `locator` 是否可继续读取，取决于源记录/字段仍存在、字段仍为文本列、源表仍由内置 `StableLocatorRule` 覆盖，以及 `network_requests` 的过滤边界是否允许读取
- **FR-011a**: `preview_chars` 与 `max_chunk_chars` 是占位预览长度与单次分段读取 `content` 长度的硬上限，默认均为 1000 字符；占位对象与 `read_field_chunk` 响应的元数据为固定小结构（无变长重复字段），默认配置下整体 JSON 预期收敛在约 2KB 量级。2KB 仅作为交付量级说明，不作为独立硬验收线；本期不再以“完整 JSON 预算”作为独立硬验收线
- **FR-012**: describe_data 必须用机器可读字段表达 FR-001 的提示：对可进入续读工作流的字段输出 `large_field=true`、`read_via="read_field_chunk"`、`locator_fields=[...]`；不得只依赖人类可读 `warning`。未被内置 `StableLocatorRule` 覆盖的文本字段不得标注为可续读字段；这不影响 query_data 在该字段达到阈值时返回 `locator=null` 的占位对象
- **FR-013**: query_data 对大字段做占位替换时，不得破坏原有的行列结构，其余正常字段保持原样返回
- **FR-014**: 当 query_data 结果中未包含后续定位该记录所需的稳定标识字段时，占位信息必须提示 Agent 先补查定位字段再继续读取（对应 **FR-003a** 枚举值 `missing_locator_field`）
- **FR-015**: 续读支持的判定规则：分段读取仅支持能够明确定位到单条源记录、且源表由内置 `StableLocatorRule` 覆盖的占位对象。具体场景与 `read_blocked_reason` 枚举见 **FR-003a**。补充示例：`SELECT nr.request_id, nr.response_body AS body, a.action_type ...` 这类 join 结果只要仍直接选择源大字段并保留稳定定位字段且能无歧义归属，仍受支持；聚合/汇总/计算列/未覆盖源表等（如 `SELECT recording_id, COUNT(*) ... GROUP BY recording_id`）达到阈值仍触发占位但 `locator=null`
- **FR-016**: 所有面向 Agent 或开发者的活文档、prompt 和配置注释中，凡列举或解释录制数据工具工作流的内容，都必须更新为包含 `read_field_chunk` 的 5 工具模型，并与本 spec 定义的大字段占位替换 / 分段读取流程保持一致；最小更新清单至少包括 `docs/ARCHITECTURE.md`、`docs/design/pm_agent_design.md`、`docs/design/programmer_agent_design.md`、`docs/design/recording_tools_redesign_todo.md`、`config.example.comments.md`、`src/business/agents/prompts/pm_prompt.py`、`src/business/agents/prompts/programmer_prompt.py`；若本特性导致约束文案变化，还必须同步更新 `docs/PROJECT_CONSTRAINTS.md`

### Key Entities

- **大字段（Large Field）**: query_data 结果列中达到配置阈值（默认 1000 字符）的文本字段值，不受源表或字段名限制；describe_data 基于当前 schema 与内置 `StableLocatorRule` 预告可续读文本字段，并提示常用稳定定位字段，但这类提示不作为 query_data 占位替换的路由条件
- **占位信息（Large Field Placeholder）**: query_data 在遇到大字段时返回的结构化替代对象，包含源字段名、字符数、必填前缀预览、定位信息以及固定的继续读取提示
- **分段读取请求（Chunk Read Request）**: 对某条记录的某个大字段按 offset 和 length 读取原始内容的请求；请求参数由 `locator`、`field`、`offset` 与可选的 `length` 组成；缺省 `length` 时取 `max_chunk_chars`（默认 1000 字符）
- **分段读取响应（Chunk Read Response）**: `read_field_chunk` 的固定响应对象，包含 `content`、`field`、`locator`、`offset`、`returned_length`、`total_length`、`has_more`、`next_offset`、`error`；`error == null` 表示成功，非空 `{code, message}` 表示失败（失败时 content/length/has_more/next_offset 字段按 `FR-009` 规则归零或置 null）
- **稳定定位字段（Stable Locator Field）**: 内置 `StableLocatorRule` 声明的、用于在后续分段读取中唯一定位目标记录的字段，如 `request_id`、`action_id`、`snapshot_id`
- **单条源记录（Single Source Record）**: 可以明确映射回某张源表中一条真实记录的查询结果行，是分段读取的前提条件
- **定位信息（Locator）**: 占位对象中用于指向源记录的结构化定位信息；可继续读取时至少包括 `table`、`id_field`、`id_value`，其中 `id_value` 支持数字或字符串这两类 JSON 标量；当结果暂时无法继续读取时该字段为 `null`
- **稳定定位规则（StableLocatorRule）**: 声明每张源表的稳定定位字段映射规则的数据结构，定义在 `src/recording/filtering/query_projection_analyzer.py`；v1 至少覆盖 `network_requests`（`request_id`）、`actions`（`action_id`）、`sibling_snapshots`（`snapshot_id`）
- **字符计数语义（Character Counting Semantics）**: 本特性中所有”按字符计”的长度、偏移量和大小，统一按 Python `str` 的 Unicode 码点计数；`len()` 的结果和标准字符串切片行为构成规范

### Constraints & Compatibility

- **CC-001**: 本特性不得修改原始录制数据；占位信息和分段读取结果均为查询时派生的交付形式
- **CC-002**: 本特性必须与现有 reference_handler 机制正交——reference_handler 处理会话历史中的 tool result 引用替换，本特性处理录制数据查询中的大字段交付粒度，两者不互相依赖
- **CC-003**: 本特性不得破坏现有 query_data 的 SQL 语义——Agent 编写的 SQL 仍正常执行，变化仅发生在结果交付环节
- **CC-003a**: 对 `network_requests` 的 `query_data` 占位替换与 `read_field_chunk` 读取，必须继续沿用现有过滤 / 脱敏边界，不得通过原始 DuckDB 直读或其他旁路方式绕过现有 SQL rewrite / filtered access 约束
- **CC-004**: 占位信息生成和分段读取元信息计算必须是确定性的，不依赖 LLM 调用
- **CC-005**: 本特性与 noise-filter 正交：noise-filter 决定“哪些数据 Agent 能看到”，本特性决定“看到的数据以什么粒度交付”
- **CC-006**: 本期不引入敏感信息自动识别、自动脱敏、占位符替换或可逆还原机制；本特性仅改变查询结果的交付粒度，不新增数据改写链路
- **CC-007**: 本期不要求结构骨架提取、语义摘要生成或超大字段一次性全文返回；重点是占位替换与分段读取闭环
- **CC-008**: blocked continuation、unsupported continuation 与明确错误返回路径必须产出可检索的结构化日志，至少能区分路径类型与失败原因；本期不要求新增 metrics、tracing 或其他额外可观测性管线

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Agent 查询包含 1MB 以上大字段的记录时，单个大字段默认返回的占位对象 `preview` 长度不超过 `preview_chars`（默认 1000 字符），且元数据为固定小结构（无变长重复字段）；验收以 `preview` 字符上限和固定元数据结构为准，默认配置下整体 JSON 交付预期约为 2KB 量级，相比当前的 12KB 截断交付显著减少
- **SC-002**: Agent 可以通过 query_data + 多次分段读取查看 1MB 以上字段的任意区段，且任一单次 `read_field_chunk` 响应中 `content` 长度不超过 `max_chunk_chars`（默认 1000 字符）；验收以 `content` 字符上限和固定元数据结构为准，默认配置下整体 JSON 交付预期约为 2KB 量级
- **SC-003**: query_data 在执行大字段占位替换时引入的额外延迟不超过 200ms；验收口径为同一进程内、单条包含 1.2MB 大字段记录的 query_data 请求，从原始结果行已取得开始，到占位对象构造并完成工具结果结构化交付为止的增量耗时；不计 GUI、进程启动、人工操作时间，也不包含 `read_field_chunk`
- **SC-004**: 未超过阈值的小字段（< 阈值）行为与本特性引入前完全一致，零回归
- **SC-005**: **FR-016** 所列最小文档清单中，不再保留 recording data tools 仍为”4 tools”或缺少 `read_field_chunk` 工作流说明的陈旧描述；若本特性修改约束文案，`docs/PROJECT_CONSTRAINTS.md` 也必须同步更新
- **SC-006**: blocked continuation、unsupported continuation 与明确错误返回路径在日志中可被结构化检索，且至少能区分路径类型、目标表/字段上下文（若可用）与失败原因；本期不以新增 metrics 或 tracing 作为验收前提

## Assumptions

- 大字段按需读取的范围限定在录制数据的查询交付环节，不影响数据入库和存储
- 阈值默认值设为 1000 字符（约 1KB），取代原 `_MAX_QUERY_CELL_CHARS = 12_000` 的无差别截断；本特性落地后，query_data 的大字段路径由“占位替换 + 分段读取”统一接管，不再保留旧的 12KB 原文截断分支
- 占位信息与分段读取结果为查询时实时生成，不持久化存储——原始数据不变，派生可以随时重建
- 占位预览长度和默认分段长度默认均为 1000 字符，可在统一配置中运行时调整
- describe_data 的大字段提示基于当前 schema 与内置 `StableLocatorRule` 自动生成，不依赖可配置字段名单；query_data 占位仍适用于任意达到阈值的文本结果列
- spec 中所有“按字符计”的要求，统一解释为 Python `str` 的 Unicode 码点语义，而非 UTF-8 字节数或用户可见字形数
- 本特性与 noise-filter 正交：noise-filter 决定“哪些数据 Agent 能看到”，本特性决定“看到的数据以什么粒度交付”
- 本期不新增面向敏感信息的自动处理能力；如需相关治理，留待后续特性单独定义
