# Feature Specification: 修复上下文压缩 tool_call/tool_result 配对断裂

**Feature Branch**: `005-fix-compression-tool-pairing`
**Created**: 2026-04-27
**Status**: Completed
**Input**: 上下文压缩按数量硬切消息，导致 assistant(tool_calls) 被归档而对应 tool result 留在保留区，形成孤立 tool result，API 返回 400 错误。
**Bugfix**: 2026-04-27 — [BUG-ADHOC] 修正文档中关于空压缩区持久化、边界 edge case 和兼容性验证范围的不一致。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 长会话压缩后 Agent 不再崩溃 (Priority: P1)

用户与 assistant 进行长时间对话，涉及大量工具调用（读取文件、搜索记忆等）。当会话消息数达到压缩阈值时，系统自动触发上下文压缩。压缩完成后，Agent 能继续正常工作，不再出现 400 错误导致会话失败。

**Why this priority**: 这是生产环境实际触发的 bug，导致会话不可恢复地失败（用户点击"继续"也会立即再次崩溃）。修复后恢复基本的会话可靠性。

**Independent Test**: 构造一个包含 assistant(tool_calls) + tool result 跨越压缩边界的会话，触发压缩，验证压缩后 Agent 能继续正常调用 LLM。

**Acceptance Scenarios**:

1. **Given** 一个活跃会话积累了超过压缩阈值的消息（含多轮工具调用），**When** 系统触发上下文压缩且切分边界落在某个 assistant(tool_calls) 和其 tool result 之间，**Then** 系统自动将该边界 tool 组整体移入保留区，所有 tool_call 和 tool_result 保持完整配对，LLM API 调用成功
2. **Given** 压缩后生成了新的消息列表，**When** 将消息发送给 LLM，**Then** 不出现 `No tool call found for function call output` 错误

---

### User Story 2 - 多次压缩不累积残留 (Priority: P2)

会话经历多次上下文压缩（第一次压缩后又积累了上百条消息再次触发压缩）。前一次压缩时被拉到保留区的边界 tool 组，在第二次压缩时如果已完全落在压缩区内部，会被正常压缩掉，不会无限累积。

**Why this priority**: 确保 tool 组不会随压缩次数增长而无限膨胀，保证长期运行会话的上下文大小可控。

**Independent Test**: 构造一个经过两次压缩的会话，验证第一次保留的 tool 组在第二次压缩时被正常压缩。

**Acceptance Scenarios**:

1. **Given** 一个会话经历第一次压缩，边界 tool 组被保留，**When** 继续对话积累更多消息后触发第二次压缩，**Then** 第一次保留的 tool 组如果已完全在压缩区内部，会被正常压缩（不重复保留）
2. **Given** 压缩区中有多个 tool 组，**When** 只有最后一个跨越了压缩/保留边界，**Then** 只保留最后一个，其余正常压缩

---

### User Story 3 - 压缩后"继续"能正常恢复 (Priority: P3)

当因任何边缘 case 导致孤立 tool result 残留时，用户点击"继续"恢复会话，系统能自动检测并清理孤立消息，会话能正常运行。

**Why this priority**: 作为兜底安全网，确保即使边界调整有遗漏，恢复路径也能自愈。

**Independent Test**: 模拟一个存在孤立 tool result 的会话状态，触发会话恢复，验证恢复后消息列表无孤立 tool result。

**Acceptance Scenarios**:

1. **Given** 一个因配对问题而 failed 的会话，**When** 用户发送"继续"触发会话恢复（failed → active），**Then** `assemble_context` 检测到孤立 tool result 并自动剔除，后续 LLM 调用成功
2. **Given** 孤立 tool result 被清理后，**When** Agent 继续工作，**Then** 不影响后续正常工具调用

---

### Edge Cases

- ~~压缩区末尾连续多个 tool 组跨越边界（最后一个 assistant 的 tool results 分散在压缩区和保留区）——需将整个 tool 组（含所有 tool results）移入保留区~~
  更正：压缩区末尾可以连续存在多个 tool 组，但真正跨越压缩/保留边界的只会是最后一个；需仅将该最后一个边界 tool 组（含其所有 tool results）移入保留区
- 压缩区调整边界后压缩区为空（只有边界 tool 组和保留区）——跳过 LLM 压缩调用
- 保留区首条消息是 tool result，其对应的 assistant(tool_calls) 在压缩区中——这是核心修复场景
- tool 组中 tool_result 内容已被 reference_handler 替换为指针，移入保留区后指针仍然有效
- 会话恢复（`get_pending_tool_calls`）检测到的未配对 tool_call 与孤立 tool_result 同时存在的场景

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 压缩切分时，必须识别跨越压缩/保留边界的 tool 组（assistant 消息含 tool_calls 在压缩区，但其部分或全部 tool result 在保留区）
- **FR-002**: 跨越边界的 tool 组必须整体移入保留区——包括 assistant(tool_calls) 消息及其所有 tool result 消息，保证配对完整
- **FR-003**: 完全在压缩区内部的 tool 组正常压缩，不做特殊处理——它们内部配对完整，压缩后通过摘要中的 tool_call_id 后处理保留信息
- **FR-004**: 保留区调整后若压缩区为空，必须跳过 LLM 压缩调用，直接构建 `system | [保留区消息]` 的消息列表
- **FR-005**: `assemble_context` 返回前必须校验消息列表中不存在孤立的 tool result（有 tool_call_id 但无对应 tool_call 的 tool 消息），发现时剔除该孤立消息并记录 warning 日志

### Key Entities

- **Tool Group（工具组）**: 由一条 assistant 消息（含 tool_calls 字段）和紧跟其后的所有 tool result 消息组成的原子单元。识别规则：assistant 消息的 tool_calls 中每个 id 必须在后续连续的 tool 消息中找到对应 tool_call_id
- **Boundary Tool Group（边界工具组）**: tool 组中 assistant(tool_calls) 消息位于压缩区，但其部分或全部 tool result 消息位于保留区的 tool 组

### Constraints & Compatibility

- **CC-001**: 修改后 `compress` 方法的返回值（List[Message]）结构必须保持兼容——调用方 `context_manager.assemble_context` 不需要修改其对压缩结果的处理方式
- **CC-002**: ~~持久化行为不变——仍然创建一条 compressed 消息并归档原始消息；移入保留区的 tool 组消息已在 DB 中存在，不需要额外持久化操作~~
  更正：当边界调整后压缩区仍非空时，持久化行为保持不变——仍然创建一条 compressed 消息并归档原始消息；移入保留区的 tool 组消息已在 DB 中存在，不需要额外持久化操作。若边界调整后压缩区为空，则跳过 compressed 消息创建和归档，因为没有消息被实际压缩
- **CC-003**: `_post_process_summary` 的 tool_call_id 替换逻辑保持不变——完全在压缩区内部的 tool 组仍需要此逻辑来保留 tool 信息
- **CC-004**: reference_handler 对大内容 tool result 的替换不受影响——移入保留区的是 DB 中的原始 Message 对象，引用替换在 `assemble_context` 中统一执行
- **CC-005**: 不影响 `get_pending_tool_calls` 的现有行为——它检测的是 assistant 消息中有 tool_calls 但无对应 tool result 的场景，与本次修复方向互补

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [ ] **UI** (`src/ui/`) — 无影响
- [x] **Business** (`src/business/`) — memory 模块（compression_handler, context_manager）
- [ ] **Execution** (`src/execution/`) — 无影响
- [ ] **Data** (`src/data/`) — 无影响
- [ ] **Recording** (`src/recording/`) — 无影响
- [ ] **Utils** (`src/utils/`) — 无影响

### Agent Impact

- 哪些 Agent 受影响: 所有 Agent（PM / Programmer / Trial / Assistant）共享同一个 compression_handler 和 context_manager
- 新工具或修改工具处理器: 无
- 系统提示词需要更改: 无
- 编排器调度更改: 无

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 任何会话经历上下文压缩后，消息列表中不存在孤立的 tool result（100% 无 400 错误）
- **SC-002**: 多次压缩后上下文大小可控——每次压缩只额外保留边界处跨越的 tool 组，不随压缩次数累积
- **SC-003**: 会话恢复（failed → active）后，assemble_context 的兜底校验能检测并清理孤立 tool result，不阻塞恢复流程

## Assumptions

- tool 组的识别基于消息顺序：assistant(tool_calls) 之后连续的 tool 消息即为该组的 tool results
- 一个 assistant 消息的所有 tool results 在消息列表中是连续的（不被其他角色的消息打断），这是 AgentLoop 当前的行为保证
- 完全在压缩区内部的 tool 组配对完整，压缩后通过 `_post_process_summary` 的 tool_call_id 替换保留关键信息，无需特殊处理
- 现有的 14 场景多工具集成测试（`tests/integration/test_agent_loop_multi_tool_calls.py`）覆盖的是 AgentLoop 层面的配对，与压缩层的配对修复互不干扰
