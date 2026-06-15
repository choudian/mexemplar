# Feature Specification: 大脑记忆质量提示词升级

**Feature Branch**: `020-brain-memory-quality`  
**Created**: 2026-06-15  
**Status**: migrated  
**Input**: Reverse-engineered from uncommitted changes to `src/business/brain/distillation_service.py` and `src/business/brain/prediction_service.py`.

## Migration Note

本规格在实现之后补录，用于恢复缺失的 Spec Kit 过程文档。它描述当前代码已经表达的行为，
不把提示词中的软约束误写成程序级硬保证。

## User Scenarios & Testing

### User Story 1 - 只沉淀未来有用的记忆 (Priority: P1)

作为使用办公助理的用户，我希望大脑只保存未来对话中真正有决策价值、能减少重复询问或避免
重蹈覆辙的信息，而不是把聊天过程、通用知识和宽泛印象都当成记忆。

**Why this priority**: 低质量记忆会直接污染后续上下文，造成错误决策和无效 token 消耗。

**Independent Test**: 检查各 phase 的 Segment 沉淀 system prompt，确认它包含价值判断、
自包含、一条一事、宁缺毋滥、反例和空数组许可，并仍要求调用既有结构化输出工具。

**Acceptance Scenarios**:

1. **Given** 一段只包含闲聊且没有长期价值的对话，**When** 模型执行 Segment 沉淀，
   **Then** prompt 明确允许所有已激活分区返回空数组，不要求为填满分区而提取内容。
2. **Given** 一段包含具体技术决策和原因的对话，**When** 模型判断是否提取，
   **Then** prompt 要求生成脱离原对话仍可理解、每条只表达一件事的记忆。
3. **Given** 对话只描述了讨论过程、通用知识或缺少证据的宽泛印象，**When** 模型提取记忆，
   **Then** prompt 将这些模式列为应避免的低质量输出。
4. **Given** 当前 phase 为 P1、P2 或 P4，**When** 构建沉淀 prompt，
   **Then** 只展示该 phase 已激活分区的规则，并保留既有 phase-aware schema 契约。

---

### User Story 2 - 用跨对话证据归纳潜意识模式 (Priority: P2)

作为使用办公助理的用户，我希望潜意识区只记录在多个对话中反复出现、能够帮助助理预判我
如何取舍的行为模式，而不是根据一次事件给我贴标签。

**Why this priority**: 潜意识条目属于推断性信息，证据不足会放大误判并降低用户信任。

**Independent Test**: 检查周期性潜意识沉淀 system prompt，确认它区分单次事件、明确偏好、
宽泛人格判断和跨对话模式，并要求输出具体模式及证据来源。

**Acceptance Scenarios**:

1. **Given** 某行为只出现一次，**When** 周期性潜意识沉淀运行，
   **Then** prompt 明确说明该信息不构成模式。
2. **Given** 至少两段不同对话表现出相同决策倾向，**When** 模型归纳潜意识条目，
   **Then** prompt 允许输出具体模式，并要求 `reason` 指向支撑判断的记忆来源。
3. **Given** 没有足够证据形成模式，**When** 模型生成结构化结果，
   **Then** prompt 允许 `subconscious_zone` 为空，不要求凑足条目。

---

### User Story 3 - 生成并验证可证伪的行为预测 (Priority: P3)

作为使用办公助理的用户，我希望猜测区只生成具体、带验证时机且可被未来事件证实或证伪的
行为预测，并使用一致的状态语义完成自动验证。

**Why this priority**: 不可证伪的人格判断无法用于系统自校准，却仍会消耗 LLM 调用并形成误导。

**Independent Test**: 检查预测生成和验证 prompt，确认生成规则包含具体行动、时间窗、至少两条
记忆证据和空结果许可；验证规则明确 `hit / partial / miss / expired` 的含义。

**Acceptance Scenarios**:

1. **Given** 只有宽泛人格描述或单条记忆，**When** 生成预测，
   **Then** prompt 要求不生成缺少足够依据的猜测。
2. **Given** 多条记忆支持一个具体未来行动，**When** 生成预测，
   **Then** 输出仍包含 `content`、`verification_checkpoint` 和 `reason`。
3. **Given** 预测到达验证点，**When** worker 使用沉淀记忆进行评估，
   **Then** prompt 要求以 `hit`、`partial`、`miss` 或 `expired` 开头并给出简要理由。

### Edge Cases

- 所有候选信息都不值得保存时，结构化输出允许为空，但既有 all-empty 重试机制仍保持不变。
- 近期用户反馈信号仅作为提取指导，不能被逐条复制成新的记忆。
- P1/P2 prompt 不应提前暴露 P4 的潜意识区和失败区规则。
- “至少两条证据”目前由 LLM prompt 约束，输出 schema 和业务代码未执行确定性计数校验。
- 验证响应解析仍依赖既有前缀解析逻辑，本改动不改变失败重试或 `expired` 回退行为。

## Requirements

### Functional Requirements

- **FR-001**: Segment 沉淀 prompt MUST 提供明确的记忆价值判断标准。
- **FR-002**: Segment 沉淀 prompt MUST 要求记忆自包含且一条只表达一个事实或判断。
- **FR-003**: Segment 沉淀 prompt MUST 明确排除聊天过程摘要、通用知识、无证据宽泛印象和
  把单次事件误判为稳定偏好等常见低质量输出。
- **FR-004**: 各认知分区 MUST 有可操作的判断问题、适用内容和正反例说明。
- **FR-005**: Prompt MUST 明确允许没有合格内容时返回空数组，不得要求模型填满分区。
- **FR-006**: 用户反馈信号 MUST 被描述为参考信息，不得要求模型逐条转换为记忆。
- **FR-007**: 潜意识沉淀 prompt MUST 把跨对话重复证据作为模式判断依据，并要求输出说明
  支撑该模式的记忆来源。
- **FR-008**: 预测生成 prompt MUST 要求猜测具体、可证伪、有验证时机，并由至少两条记忆支撑。
- **FR-009**: 预测验证 prompt MUST 明确定义 `hit`、`partial`、`miss` 和 `expired` 的判定语义。
- **FR-010**: 既有工具 schema、phase 激活范围、Repository 写入、worker 调度、重试和解析行为
  MUST 保持兼容。

### Constraints & Compatibility

- **CC-001**: 本改动仅修改 business 层 LLM prompt，不新增或修改 SQLite、DuckDB、Repository、
  migration、配置、secret、API、事件或前端契约。
- **CC-002**: `distillation_output`、`subconscious_distillation_output` 和
  `prediction_generation_output` 的结构化工具名称及 schema 保持不变。
- **CC-003**: Prompt 约束属于模型指导，不得在规格中宣称为确定性运行时保证。
- **CC-004**: 现有 all-empty 重试、prediction 验证重试和失败回退语义保持不变。

## Architecture Impact

### Layer Impact

- [ ] **UI** (`frontend/src/`, `src-tauri/`)
- [ ] **Desktop API Bridge** (`src/desktop_api/`)
- [x] **Business** (`src/business/`) — 调整 brain distillation/prediction prompt
- [ ] **Execution** (`src/execution/`)
- [ ] **Data** (`src/data/`)
- [ ] **Recording** (`src/recording/`)
- [ ] **Utils** (`src/utils/`)

### Agent Impact

- Affected runtime: Brain background LLM jobs, not user-facing PM / Programmer / Trial / Assistant tools.
- New or modified tools: None; existing structured output tools remain unchanged.
- System prompt changes: Brain distillation, subconscious distillation, prediction generation and verification prompts.
- Orchestrator dispatch changes: None.

### Data Store Impact

- **SQLite**: N/A.
- **DuckDB**: N/A.
- **Config**: N/A.
- **Secrets**: N/A.

### Event Impact

- New events: None.
- Modified payloads or listeners: None.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Prompt regression tests can assert all three Segment phases retain their correct active-zone guidance
  and structured output instruction.
- **SC-002**: Prompt 回归测试可断言低价值提取反例、空结果许可和反馈信号边界存在。
- **SC-003**: 潜意识 prompt 回归测试可断言重复证据规则和证据来源要求存在。
- **SC-004**: Prediction prompt 回归测试可断言证据数量指导、可证伪性、验证点和四种验证状态存在。
- **SC-005**: Existing brain distillation and prediction worker tests continue to pass without schema or persistence changes.

## Assumptions

- LLM 会把提示词中的规则作为软约束执行；本 feature 不引入第二次模型评审或规则引擎。
- 当前结构化 tool schema 足以保持输出形状，质量提升主要来自更清晰的判断标准和示例。
- 提示词语言继续使用中文，与现有 brain prompt 和产品用户语言一致。
- 提示词效果的离线样本评测不在本次已实现范围内，可作为后续质量评估工作。
