# Feature Specification: AgentLoop 多工具调用结果配对修复

**Feature Branch**: `003-fix-agentloop-tool-calls`
**Created**: 2026-04-25
**Status**: Completed
**Input**: User description: "修复 AgentLoop 在模型返回多个 tool_calls 时只执行第一个工具，导致后续 LLM 调用出现未配对 tool result 报错的问题；即使工具绑定设置为串行，也要把同一轮响应里的 tool_calls 按列表顺序执行完并保存每个结果后，再统一交给 LLM。"

## Clarifications

### Session 2026-04-25

- Q: 当同一轮模型响应中同时出现中断型工具与其他工具调用时，系统应如何处理？ → A: 视为模型输出错误，不执行该响应中的工具调用；系统应给模型明确错误提示，要求其重新输出合法工具调用。
- Q: 普通多工具序列中某个工具失败时，后续工具应如何处理？ → A: 首个失败工具之后停止真实执行后续工具；后续未执行工具仍写入明确“未执行/需模型重新规划”的结果，保证消息配对完整。
- Q: 中断型工具混入多工具响应并判定为模型输出错误后，历史应如何保持配对？ → A: 保存该模型响应；不真实执行任何工具；为响应中的每个 tool call 写入配对错误结果，提示模型输出非法并重新输出合法工具调用。
- Q: 会话恢复时待补齐的工具调用当前已无可用 handler，应如何处理？ → A: 当作工具失败处理；为该工具写入配对错误结果，后续未执行工具写入“未执行/需模型重新规划”结果。
- Q: 普通工具返回结果时，系统如何可靠判断该结果属于失败？ → A: 只把未知工具、handler 抛异常、工具返回顶层 JSON 对象且含 `error` 字段或 `success: false` 的标准化错误结构算作失败；不得通过普通文本是否包含“错误/error”推断失败。
- Q: AgentLoop 如何在不执行 handler 的前提下识别中断型工具（用于 FR-006 混合响应拦截）？ → A: 在 `ToolDefinition` 上增加声明式分类字段（`is_interrupting: bool` 或等价的 `kind` 枚举），AgentLoop 在收到工具调用列表后立即按 name → ToolDefinition 查表分类；不得依赖事后 `isinstance(ToolSignal)` 判断，也不得依赖硬编码工具名白名单。
- Q: `not_executed` 与 `invalid_model_output` 配对结果的 content 形态？ → A: 复用 FR-005 定义的标准化错误结构 —— 顶层 JSON 对象，含稳定 `error` 字段（取值 `"not_executed"` 或 `"invalid_model_output"`）与 `message`（人类可读说明），可附加 `upstream_tool_call_id`、`code` 等诊断字段；不得使用纯文本或独立 schema。
- Q: `ToolDefinition.is_interrupting` 与 handler 返回 `ToolSignal` 的一致性约束？ → A: 强一致：`is_interrupting=True` 的 handler 必须返回 `ToolSignal`，`is_interrupting=False` 必须返回 `str`；运行时检测到不一致视为 handler 故障，按 FR-005 失败语义处理（保存标准化错误结构 `{"error": "handler_contract_violation", ...}`，停止后续工具真实执行）。
- Q: 同一轮模型响应包含多个中断型工具（如两个 `talk_to_user`）应如何处理？ → A: 视为非法响应（与 mixed batch 同语义）：保存原响应、不执行任何 handler，为每个 tool call 写入 `invalid_model_output` 配对结果。合法的中断响应必须**有且仅有一个工具调用，且其为中断型**。
- Q: Solo 中断型工具（合法路径）的 handler 抛异常时如何处理 loop 控制流？ → A: 与 FR-005 失败语义统一：保存标准化错误结构 `{"error": "handler_exception", "tool_name": "...", "message": "..."}` 作为该工具的配对结果，**继续 loop**（不终止），让模型基于失败结果重新规划。中断型工具的暂停/完成语义只对成功执行生效；失败路径与普通工具失败一致。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 多工具调用完整配对 (Priority: P1)

当模型在同一轮响应中返回多个工具调用时，Agent 运行循环必须把这些调用都视为同一轮待执行动作，按返回顺序逐个完成并记录结果，然后再进入下一次模型请求。用户不应看到因为缺少后续工具结果而导致的运行失败。

**Why this priority**: 这是当前 bug 的核心路径。只执行第一条工具调用会把会话历史写成不完整状态，后续模型请求可能被拒绝，直接中断 Agent 工作流。

**Independent Test**: 构造一轮模型响应包含两个普通工具调用，验证两个工具都按顺序执行、两个结果都被记录，下一轮交给模型的上下文中不存在未配对的工具调用。

**Acceptance Scenarios**:

1. **Given** 模型返回两个普通工具调用，**When** Agent 运行循环处理该响应，**Then** 系统按列表顺序执行两次工具，并分别记录两个工具结果后再请求模型继续。
2. **Given** 第一个工具执行成功且第二个工具也需要执行，**When** 第一条工具结果已保存，**Then** 系统不得提前把未完成的同轮工具调用交回模型。
3. **Given** 一个普通工具以未知工具、handler 异常或标准化错误结构的形式失败且同轮还有后续工具调用，**When** 系统记录该失败工具结果，**Then** 系统停止真实执行后续工具，为后续工具写入“未执行/需模型重新规划”的结果，并在下一轮让模型基于失败结果重新规划。

---

### User Story 2 - 中断型工具行为可预期 (Priority: P1)

当同一轮响应中出现会暂停或结束 Agent 循环的中断型工具时，系统必须给出一致且可验证的处理规则。中断型工具单独出现时按既有暂停或完成语义处理；中断型工具与任何其他工具同轮出现时，系统必须把该响应判定为模型输出错误，要求模型重新输出合法工具调用。

**Why this priority**: `talk_to_user`、需求提交、代码提交等工具会改变会话状态或交给上层流程。如果它们与其他工具同轮出现，继续执行或部分执行都可能引入半完成状态；明确报错重试能避免副作用和未配对历史。

**Independent Test**: 构造普通工具与中断型工具混合的同轮响应，验证系统保存该模型响应、不执行任何真实工具，并为该响应里的每个 tool call 写入配对错误结果，要求模型重新输出合法工具调用。

**Acceptance Scenarios**:

1. **Given** 同轮响应只包含一个中断型工具，**When** Agent 处理该响应，**Then** 系统按该中断型工具的既有语义暂停或完成会话。
2. **Given** 同轮响应同时包含中断型工具和普通工具，**When** Agent 处理该响应，**Then** 系统保存该模型响应，将整轮响应判定为模型输出错误，不执行其中任何真实工具，并为每个 tool call 写入配对错误结果。
3. **Given** 模型收到错误提示后重新输出一个合法工具调用，**When** Agent 处理新的响应，**Then** 系统按新的合法响应继续执行，且历史中不存在未配对工具调用。

---

### User Story 3 - 会话恢复不重复或遗漏工具 (Priority: P2)

当 Agent 在保存模型响应后、完成所有同轮工具结果前被中断或重启时，系统恢复后必须能识别哪些工具调用仍未完成，并继续补齐结果，而不是只重试第一条或重复已完成的调用。

**Why this priority**: 多工具调用修复后，会话恢复必须跟随同一配对契约，否则崩溃恢复路径仍可能生成不完整历史。

**Independent Test**: 构造会话历史中同一条模型响应含多个工具调用、其中部分已有工具结果，验证恢复时只执行缺失结果的工具调用，并保持原始顺序。

**Acceptance Scenarios**:

1. **Given** 同一轮响应中三个工具调用只有第一条已有结果，**When** Agent 恢复运行，**Then** 系统从第二条开始继续执行并补齐剩余结果。
2. **Given** 所有工具调用都已有结果，**When** Agent 恢复运行，**Then** 系统不重复执行任何工具，并正常进入下一轮模型请求。
3. **Given** 恢复时某个待补齐工具调用当前没有可用 handler，**When** Agent 处理该待恢复调用，**Then** 系统为该工具写入配对错误结果，停止真实执行后续工具，并为后续工具写入“未执行/需模型重新规划”的结果。
4. **Given** 已保存的工具调用记录损坏或缺少必要字段，**When** Agent 尝试恢复，**Then** 系统返回明确错误或记录可诊断日志，而不是静默跳过并继续生成不完整上下文。

### Edge Cases

- 模型在串行工具设置下仍返回多个工具调用。
- 同轮多个工具调用中包含未知工具名。
- 同轮多个工具调用中某个工具执行抛出异常。
- 同轮多个普通工具调用中，前序工具返回标准化错误结构（顶层 JSON 对象含 `error` 字段或 `success: false`），后续工具不得继续真实执行。
- 普通工具返回文本中包含“错误”或“error”等词但不是标准化错误结构时，系统不得仅凭关键词把它判定为失败。
- 同轮工具调用中混有普通工具、中断型工具和需要用户输入的工具，应作为模型输出错误处理。
- 同轮响应包含多个中断型工具（无论是否同一种）也应作为模型输出错误处理；合法中断响应必须有且仅有一个工具调用且为中断型。
- Solo 中断型工具的 handler 抛异常时不触发暂停/完成语义；按 FR-005 失败语义保存错误结果并继续 loop，由模型重新规划。
- 会话恢复时，最后一条消息不是待执行工具调用，但较早的同轮工具调用仍缺结果。注：当前恢复逻辑仅检查最近一条 assistant 消息中的未配对调用（crash 只发生在工具执行中途，assistant 消息始终是最后一条未完成的消息）；若需要搜索全部历史，需额外设计。
- 动态工具列表在恢复前发生变化，导致待恢复工具不再存在时，系统必须按工具失败语义补齐配对结果。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须支持单条模型响应包含多个工具调用，并将这些调用作为同一轮有序工具序列处理。
- **FR-002**: 系统必须按模型返回的工具调用列表顺序执行普通工具调用。
- **FR-003**: 系统必须为每一个已记录的工具调用保存一个对应的工具结果，确保后续模型请求中的会话历史不存在未配对工具调用。
- **FR-004**: 当普通工具执行返回成功结果时，系统必须保存该工具调用对应的结果，并继续处理同轮后续普通工具调用。
- **FR-005**: 当普通工具执行失败时（仅包括未知工具、handler 抛出异常、工具返回顶层 JSON 对象且含 `error` 字段或 `success: false` 的标准化错误结构），系统必须保存该失败工具对应的错误结果，停止真实执行同轮后续工具，并为每个后续未执行工具保存明确“未执行/需模型重新规划”的工具结果；系统不得通过普通文本是否包含“错误”或“error”等关键词推断失败。
- **FR-006**: 当模型在同一响应中返回多于一个工具调用且其中包含至少一个中断型工具时（无论另一个是普通工具还是另一个中断型工具），系统必须保存该模型响应，将该响应判定为模型输出错误，不真实执行该响应中的任何工具调用，并为响应中的每个 tool call 保存配对错误结果，要求模型重新输出合法工具调用。合法的中断响应必须有且仅有一个工具调用，且其为中断型。
- **FR-007**: 中断型工具单独出现且 handler 成功执行时（同轮恰好一个工具调用且为中断型），系统必须保留既有暂停或完成语义。中断型工具与任何其他工具同轮出现时的处理由 FR-006 定义。中断型工具 handler 抛异常时，按 FR-005 失败语义处理（保存 `{"error": "handler_exception", ...}` 配对结果，继续 loop 让模型重新规划）；暂停/完成语义不在失败路径触发。
- **FR-008**: 会话恢复时，系统必须识别同一条模型响应中哪些工具调用已经有结果、哪些仍缺结果，并只补齐缺失结果。
- **FR-009**: 会话恢复不得只取第一条待执行工具调用；多工具响应中的待执行项必须按原始顺序恢复。
- **FR-010**: 会话恢复时，如果待补齐工具调用当前没有可用 handler，系统必须按工具失败语义处理：为该工具保存配对错误结果，停止真实执行同轮后续工具，并为后续未执行工具保存“未执行/需模型重新规划”的工具结果。
- **FR-011**: 系统必须保留单工具调用场景的现有行为，不能让已有 PM、程序员、试用和 assistant 工作流出现可见回归。
- **FR-012**: 系统必须在日志或诊断信息中保留多工具调用数量、执行顺序和恢复缺失结果的关键信息，便于定位同类问题。
- **FR-013**: 系统必须补充覆盖多工具调用完整配对、中断型工具混合报错、工具异常、未知工具、恢复时工具不可用和恢复路径的行为测试。
- **FR-014**: 系统必须通过 `ToolDefinition` 上的声明式分类字段 `is_interrupting: bool` 在执行任何 handler 之前识别中断型工具；不得通过 handler 返回值类型（事后 `isinstance(ToolSignal)`）或硬编码工具名白名单作为识别依据。
- **FR-015**: `not_executed` 与 `invalid_model_output` 配对结果的 content 必须采用与 FR-005 一致的标准化错误结构：顶层 JSON 对象，含稳定 `error` 字段（取值 `"not_executed"` 或 `"invalid_model_output"`）与 `message`（人类可读说明），可附加 `upstream_tool_call_id`、`code` 等诊断字段；不得使用纯文本说明或独立 schema。
- **FR-016**: 系统必须强制 `ToolDefinition.is_interrupting` 与 handler 实际返回类型一致：`is_interrupting=True` 的 handler 必须返回 `ToolSignal`；`is_interrupting=False` 的 handler 必须返回 `str`。运行时检测到不一致视为 handler 故障，按 FR-005 失败语义处理：写入标准化错误结构 `{"error": "handler_contract_violation", "message": "...", "tool_name": "..."}` 作为该工具的配对结果，停止真实执行同轮后续工具，并为后续未执行工具写入 `not_executed` 结果。

### Key Entities *(include if feature involves data)*

- **工具调用序列**: 单条模型响应中返回的一个或多个工具调用，具有稳定顺序和唯一调用标识。
- **工具结果配对**: 每个工具调用标识必须对应一条工具结果记录，供下一轮模型请求验证会话历史完整性；工具结果可以是成功、错误或未执行说明。
- **中断型工具结果**: 会暂停、完成或向上层流程提交状态的工具结果，例如需要用户输入或提交阶段性产物。中断型工具通过 `ToolDefinition` 上的声明式分类字段标记，AgentLoop 在执行前即可识别。
- **待恢复工具调用**: 已经出现在历史模型响应中但尚未拥有对应工具结果的调用。
- **未执行工具结果**: 当前序工具失败导致后续工具不能安全执行时，为后续工具调用写入的配对结果。content 为标准化错误结构：`{"error": "not_executed", "message": "...", "upstream_tool_call_id": "..."}`。
- **模型输出非法错误结果**: 当模型同轮混合中断型工具与其他工具时，为每个 tool call 写入的配对错误结果。content 为标准化错误结构：`{"error": "invalid_model_output", "message": "..."}`，明确说明该响应非法且工具未被执行。
- **标准化错误结构**: 工具结果中可被系统可靠识别为失败的顶层 JSON 对象，必须含 `error` 字段或 `success: false`；可附带 `message`、`code`、`data` 等诊断字段。普通自然语言文本不属于标准化错误结构。

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: 修复必须保持 AgentLoop 不直接感知 UI；上层仍通过现有结果状态接收暂停、完成或错误。
- **CC-002**: 修复必须兼容模型仍只返回单个工具调用的主路径。
- **CC-003**: 修复不得依赖模型或供应商一定遵守串行工具设置；系统自身必须保证历史消息配对完整。
- **CC-004**: 修复不得改变工具 handler 的业务返回协议；普通字符串结果和中断型结果仍按既有语义处理。
- **CC-005**: 修复不得让已完成工具在恢复时重复执行，避免重复写入、重复提交或重复向用户提问。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

Which layers are affected? Check all that apply:

- [ ] **UI** (`src/ui/`) — new widgets, signals, or bridge changes
- [x] **Business** (`src/business/`) — agents, orchestration, services, memory
- [ ] **Execution** (`src/execution/`) — tool execution sandbox
- [x] **Data** (`src/data/`) — models, repositories, migrations, config
- [ ] **Recording** (`src/recording/`) — recorder, filtering, browser extension
- [ ] **Utils** (`src/utils/`) — events, helpers

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: PM / Programmer / Trial / Assistant
- New tools or modified tool handlers? No new user-facing tools; existing tool call handling must accept multi-call responses.
- System prompt changes needed? None expected.
- Orchestrator dispatch changes? None expected unless planning finds an existing upper-layer assumption about single tool results.

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): Existing message history pairing semantics are affected; no new table is expected.
- **DuckDB** (`src/recording/filtering/`): No direct impact.
- **Config** (`src/data/unified_config.py`): No new config key expected.
- **Secrets** (keyring): No impact.

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: None expected.
- Modified event payloads: None expected.
- New event listeners: None expected.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a controlled Agent run where one model response contains two ordinary tool calls, 100% of returned tool calls have matching tool results before the next model request.
- **SC-002**: In a controlled Agent run where one model response contains three ordinary tool calls, observed execution order matches the model-provided order exactly.
- **SC-003**: In a controlled Agent run where the second of three ordinary tool calls returns a top-level JSON object with `error` or `success: false`, the first two calls receive success/error results, the third call receives a not-executed result without running its handler, and the next model request is accepted by message-history validation.
- **SC-008**: In a controlled Agent run where a tool returns plain text containing the word "error" without a standardized error structure, later ordinary tools still execute normally.
- **SC-004**: In a controlled Agent run where one response mixes an ordinary tool with a user-input interrupt tool, the original response is persisted, every tool call in that response receives a paired invalid-output error result without running any handler, and the next accepted model response proceeds without unmatched tool calls.
- **SC-005**: In a recovery test where a multi-tool response has only partial results, the system resumes only missing tool calls and does not repeat completed calls.
- **SC-006**: In a recovery test where the next missing tool call no longer has an available handler, that call receives a paired error result, later calls receive not-executed results, and no later handler is run.
- **SC-007**: Existing single-tool Agent workflows continue to pass their current behavior tests with no user-visible regression.

## Assumptions

- The root cause is a runtime contract gap, not a behavior specific to any single feature or recording-data tool.
- Some model providers or wrappers may return multiple tool calls even when configured for serial tool use.
- The safe default is to preserve provider-facing message validity by ensuring every saved tool call has a corresponding result before the conversation is sent back to the model.
- In v1, no new user-facing configuration is needed; the fix should be deterministic and always enabled.
