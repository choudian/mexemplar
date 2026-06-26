# Feature Specification: Task Graph Scheduling（复杂任务"先分解，再按图执行"纠偏）

**Feature Branch**: `024-task-graph-scheduling`
**Created**: 2026-06-24
**Status**: Completed
**Input**: User description: "docs\superpowers\specs\2026-06-24-task-graph-scheduling-design.md"（024 Task Graph Scheduling 设计草案——对 023-unified-task-collaboration 落地后执行模型偏离的纠偏）

> **Feature Context（业务背景）**：办公助理在 023 落地后，处理复杂任务时偏离了"先分解成带依赖的任务图、再按图执行"的初衷——主助理没有真正分解任务，而是把整句原样一把委派给一个子代理临场发挥；数据库里本有的"依赖边"从未被建立或按序调度；执行变成"派一个→等回流→再决定派下一个"的纯串行 LLM 临场判断。本特性让复杂任务走干净的管线：**识别复杂度 → 分解成带依赖的任务图 → 调度器按依赖自动推进 → 遇高风险节点或失败时停下裁定**，把任务图作为交接物，执行者照图走而非临场发挥。023 投下的持久化、恢复、并发安全地基完整复用，本特性是在其上加两层，不是推倒重来。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 复杂任务被分解成有序任务图并按序执行 (Priority: P1)

操作者给办公助理一个真正复杂的多步任务（例如"整理会议纪要、生成周报、发给团队"）。助理把任务分解成一张带依赖的任务图（纪要整理 → 周报生成 → 发送），无依赖的节点可并行、有依赖的节点按序执行，最终完成整张图而非把整句甩给一个子代理临场发挥。任务图是分解与执行之间的交接物。

**Why this priority**: 这是本特性存在的核心理由——没有它，纠偏就不成立。它把"一把委派/边想边派"纠正为"先出图、按图走"。

**Independent Test**: 给一个多步跨领域的复杂任务，观察助理在执行前产出多个由依赖关系连接的任务节点，并按正确顺序完成全部节点。

**Acceptance Scenarios**:

1. **Given** 一个复杂任务（多步、跨领域/工具族），**When** 助理判定其为复杂，**Then** 在任何执行发生前，先将其分解为多个由依赖关系连接的任务节点。
2. **Given** 一张已分解的任务图，**When** 开始执行，**Then** 任一节点只有在其所有依赖前置节点都完成后才会运行。
3. **Given** 互相无依赖的独立节点，**When** 它们就绪，**Then** 可经由不同执行器并行运行。
4. **Given** 一整张任务图，**When** 全部节点完成，**Then** 助理向操作者汇报最终结果。

---

### User Story 2 - 简单任务继续走快速通道、不建图 (Priority: P1)

1-2 步、单领域的简单任务继续走现有的快速委派路径，不受新图机制影响、不被强行建图。

**Why this priority**: 防止过度工程化与对常见路径的回归——保证简单任务的体验与延迟不变。

**Independent Test**: 给一个简单任务，观察它直接走快速委派、不产出任务图。

**Acceptance Scenarios**:

1. **Given** 一个简单任务（1-2 步、单一领域），**When** 被判定为简单，**Then** 走现有快速委派路径，不构建任务图。

---

### User Story 3 - 高风险步骤执行前暂停等待确认 (Priority: P2)

不可逆/高风险的节点（发邮件、删数据、对外发送等）在分解时被标记；当其依赖前置完成后，助理暂停该分支、在执行前向主助理/操作者裁定——放行 / 调整后放行 / 问用户。

**Why this priority**: 安全与可控——建立在 P1 的图之上，确保危险动作绝不静默执行。

**Acceptance Scenarios**:

1. **Given** 一张含高风险/不可逆节点的任务图，**When** 该节点的依赖前置完成，**Then** 助理在执行它之前暂停并上浮该节点待裁定。
2. **Given** 一个已暂停的高风险节点，**When** 操作者放行，**Then** 执行继续；**When** 操作者调整，**Then** 按调整后的计划继续；**When** 无法自决，**Then** 升级给操作者拍板。

---

### User Story 4 - 节点失败先自愈，兜不住再升级 (Priority: P2)

当一个节点失败时，助理先尝试自愈（重试该节点 / 换执行器 / 调整输入或参数 / 可容忍则跳过 / 改图加删改步骤），只有当确实兜不住（缺关键信息、需用户定方向、反复试均失败、结构性问题）时才升级找操作者拍板。

**Why this priority**: 韧性——把操作者被打断的频率压到最低。

**Acceptance Scenarios**:

1. **Given** 一个节点失败，**When** 存在可行的恢复动作，**Then** 助理在通知操作者之前先尝试自愈。
2. **Given** 反复失败或结构性问题，**When** 助理判断无法自愈，**Then** 连同可选项升级给操作者，而非无限重试或静默失败。

---

### User Story 5 - 中途可见进度、能取消/改主意 (Priority: P3)

操作者能感知整体任务进度，并按需查看某个执行器的子步骤进度（复用 014"点击查看子代理在做什么"的入口，默认界面不展示）；能随时取消或改主意——取消信号顺图传播，改主意按"取消旧图 + 重新分解"处理。

**Why this priority**: 透明与控制——依赖 014 子任务详情入口与 023 取消传播的复用，是体验完善而非核心纠偏。

**Acceptance Scenarios**:

1. **Given** 一张正在运行的任务图，**When** 操作者取消，**Then** 取消顺图传播，运行中的执行被回收、未开始的节点转取消，整图停止。
2. **Given** 一张正在运行的任务图，**When** 操作者改主意（"改成 Y 方案"），**Then** 旧图被取消并重新走分解。
3. **Given** 一个正在运行的节点，**When** 操作者打开子任务详情入口，**Then** 能看到该执行器的子步骤进度（默认任务界面不展示该进度）。

---

### Edge Cases

- 执行器崩溃 / 租约过期 / 被杀（节点执行中途）：该执行器持有的未完成节点自动退回可重派状态，整张图不卡死。
- 单执行器同时在办约束：一个执行器（专员/子 agent）同时只能持有一个未完成节点；需要并行时由多个执行器各跑一个节点，而非一个执行器并行多节点。
- 依赖边成环：建图时直接拒绝（复用现有无环校验）。
- 分解质量问题（节点粒度不当、依赖画错）：建图时无环校验 + 关键裁定兜底 + 分解 prompt 软约束，而非假定 LLM 永远正确。
- 复杂度误判（LLM 软判定）：落库层架构门卫校验"命中超阈值规则的任务必须落库为带依赖边的 DAG、必须由调度器驱动"，不假定 LLM 分类一定正确。
- 高风险节点正处于裁定暂停时操作者取消：按取消传播处理，暂停分支一并停止。
- 简单任务被误判为复杂（或反之）：门卫测试守边界；落库层区分"快捷委派图"与"分解 DAG 图"，避免两条路混线。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 将到达主助理的任务按复杂度至少分三路路由：简单（现有快速委派）、中等（主助理自行分解）、超阈值（委派给固定规划专员）。
- **FR-002**: 对中等与超阈值任务，系统 MUST 在执行前产出一整张任务图结构（节点 + 依赖边）作为分解与执行之间的交接物，且两条分解路 MUST 产出同一种图结构、由下游无差别消费。
- **FR-003**: 任务图 MUST 通过依赖边表达先后；一个节点 MUST NOT 在其所有依赖前置节点完成之前执行（就绪校验在派发/认领层强制兜底）。
- **FR-004**: 系统 MUST 在建图时拒绝会形成环的依赖边。
- **FR-005**: 对超阈值任务，系统 MUST 委派给固定规划专员产出任务图，且规划专员 MUST 只规划不执行（深度封顶，不再向下委派执行）。
- **FR-006**: 系统 MUST 提供一个确定性的调度器，依据依赖完成情况自动推进就绪节点，而不依赖 LLM 临场判断来决定执行顺序。
- **FR-007**: 系统 MUST 强制单执行器同时在办约束：一个执行器（专员/子 agent）同时只持有一个未完成节点。
- **FR-008**: 执行器崩溃/租约过期时，系统 MUST 自动将其持有的未完成节点退回可重派状态，使整图不卡死。
- **FR-009**: 高风险/不可逆节点 MUST 在分解时被标记，且 MUST 在执行前暂停等待裁定。
- **FR-010**: 节点失败时，系统 MUST 提供结构化自愈动作集（重试 / 换执行器 / 调整输入 / 可容忍则跳过 / 改图），且 MUST 仅在自愈无效时才升级操作者。
- **FR-011**: 执行器 MUST 能把多步节点分解成内部 todo 清单，并实时更新其状态。
- **FR-012**: 节点 todo 进度 MUST 对主助理可见（供裁定），且 MUST 对操作者按需可见（经现有子任务详情入口）；MUST NOT 展示在默认任务界面。
  > **机制消解（DEC-E）**：todo 按需可见走 TaskGraphPanel 节点展开（复用 `assistantTaskStore.todosByTaskId` + `GET /tasks/{id}/todos`），而非 014 SubagentDrawer——023 dispatcher 路径下 task executor 不发 `assistant.subagent` 事件，SubagentCard 不出卡片。意图保留（todo 按需可见、默认不展示），机制从 SubagentDrawer 改为 TaskGraphPanel 节点展开。
- **FR-013**: 操作者取消 MUST 顺图传播（回收运行中执行、取消未开始节点）；改主意 MUST 按"取消旧图 + 重新分解"处理。
- **FR-014**: 简单任务 MUST 继续走现有快速委派路径、不构建任务图（无回归）。
- **FR-015**: 主助理 MUST 能基于节点回流结果做结构化裁定——回流包 MUST 在节点完成时附带"下一步建议"（就绪可派节点 / 是否有待裁定节点 / 是否全图完成），在节点失败时附带"可选自愈动作清单"，而非让主助理开放自由发挥。

### Key Entities *(include if feature involves data)*

- **任务图 (Task Graph / DAG)**：分解与执行之间的交接物，由节点和依赖边组成；执行者照图走。
- **任务节点 (Task Node)**：一个执行器的一次连贯执行单元，复用现有任务记录。
- **依赖边 (Dependency Edge)**：节点间先后关系（阻塞=串行前置；非阻塞=可并行），复用现有边类型（激活其闲置枚举值）。
- **规划专员 (Planning Specialist)**：新增固定专员类型，为超阈值任务产出任务图；只规划不执行。
- **DAG 调度器 (DAG Scheduler)**：新增的确定性组件，按依赖就绪自动推进节点，并在需确认/失败时触发裁定与自愈。
- **需确认标记 (Needs-Confirmation Marker)**：标注在高风险/不可逆节点上、强制执行前暂停的标记。
- **节点 Todo (Node Todo)**：执行器对多步节点的内部子步骤清单，复用现有 todo 能力。
- **回流包 (Reentry Briefing)**：节点完成/失败时回流的结构化结果包，承载下一步建议 / 可选自愈动作 / 节点 todo 概览。

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: MUST 完整复用 023 基础设施（持久任务图、durable accepted 即委派即落库、dispatcher 线程池 + TaskAttempt lease/fence、parent reentry、父侧裁定、取消顺图传播），MUST NOT 重写其持久化/恢复/并发安全机制。
- **CC-002**: MUST NOT 强制简单任务建图（避免过度工程化）。
- **CC-003**: 本阶段 MUST NOT 引入任务图的前端可视化编辑（仅消费、不前端编辑图）。
- **CC-004**: MUST NOT 改变现有 UI 事件契约与前端投影方式（如有新裁定/暂停类展示需求，按项目规则在 UI Event Registry 注册公开事件后再消费）。
- **CC-005**: `todo_update` 是副作用工具，MUST NOT 标记 `is_concurrency_safe`、MUST NOT 进入并行执行池。
- **CC-006**: 复杂度分类是 LLM 软判定；凡需硬保证处（如"超阈值必须走规划专员""复杂必须落库为带依赖 DAG"）MUST 由落库层架构门卫校验，MUST NOT 假定 LLM 分类一定正确。
- **CC-007**: 本特性建立在 023 分层越权重构稳定后的地基上；MUST 只消费 023 的稳定接口，两者不冲突。
- **CC-008**: 分解质量约束、阈值规则、自愈动作选择均为模型软约束（advisory），非确定性保证；文档与调用方 MUST 如此描述，需要硬保证时另行增加 schema/业务校验与行为测试（参考 020 的 prompt 软约束经验）。
- **CC-009**: 就绪硬校验、单工作者约束、executor 异常 unassign、回流结构化引导等借鉴自 claude-code（单用户 CLI 场景）的机制，MUST 在 plan 阶段逐个确认对办公助理"多专员 + 持久化"场景的适配点；以 023 已有的 lease/fence/父侧裁定为主保障，借鉴机制为增强。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [ ] **UI** (`frontend/src/`, `src-tauri/`) — 投影不变；todo 进度按需经 014 子任务详情入口查看，不新增 UI 入口。
- [ ] **Desktop API Bridge** (`src/desktop_api/`) — 事件契约不变（仅消费）。
- [x] **Business** (`src/business/`) — agents（主助理 prompt 增复杂度判定与分解决策、新增 `build_task_graph` 工具、`todo_update` 引导放工具描述）、orchestration（新增 DAG 调度器、规划专员招募）、task_collaboration（调度器接入、回流包结构化引导扩展）。
- [ ] **Execution** (`src/execution/`) — 工具执行不变（`todo_update` 已注入，仅增行为引导）。
- [x] **Data** (`src/data/`) — 激活现有 `assistant_task_edges.edge_type='dependency'`；节点"需确认"标记承载字段优先复用现有字段（如 `capability_scope`），是否需轻量 migration 在 plan 阶段定。
- [ ] **Recording** (`src/recording/`) — 不涉及。
- [ ] **Utils** (`src/utils/`) — 复用现有 task collaboration 事件，不新增公开事件类型。

### Agent Impact *(if touching Agent system)*

- 受影响 Agent：**Assistant**（主助理）、**新增规划专员**（固定专员类型）、**执行器**（专员/临时子 agent）。
- 新增/修改工具：主助理新增 `build_task_graph`（输入子任务节点列表 + 依赖关系 + 需确认标记，原子落库成多个 task + edges，返回 graphId）；扩充 `todo_update` 工具 description（教执行器在节点内多步时主动分解 todo）。
- System prompt 变更：主助理 prompt 增复杂度判定与分解决策指令；子 agent 工作规则去掉/弱化与"先 plan 再做"冲突的条款。
- Orchestrator dispatch 变更：复杂任务由新增 DAG 调度器按依赖就绪驱动派发；现有"主助理主动逐步委派"降级为简单任务快捷通道。

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`)：激活现有 `assistant_task_edges` 的 `edge_type='dependency'`（闲置枚举值）；复用 `assistant_tasks`。节点"需确认"标记优先复用现有字段承载，否则加轻量 migration（plan 阶段定）。
- **DuckDB** (`src/recording/filtering/`)：不涉及。
- **Config** (`src/data/unified_config.py`)：复杂度阈值等运行时可调项若需配置化，统一走 `UnifiedConfigManager` 读写（plan 阶段定具体 key）。
- **Secrets**（`UnifiedConfigManager` only）：不涉及新敏感字段。

### Event Impact *(if adding/changing events)*

- 新增事件（`src/utils/events.py`）：本阶段不新增公开 UI 事件类型；DAG 调度器经现有 task collaboration 通道（parent reentry / `reentry_briefing`）驱动推进与裁定通知。
- 修改事件 payload：`reentry_briefing` 扩展承载"下一步建议 / 可选自愈动作清单 / 节点 todo 概览"（内部回流包，非公开 UI 契约）。
- 若裁定/暂停需对前端可见，按项目规则在 `src/desktop_api/ui_events.py` 的 UI Event Registry 注册公开事件 type + payload allowlist 后再消费（plan 阶段定）。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 复杂多步任务（≥3 步、跨 ≥2 领域/工具族）在常规执行段内无需操作者介入即可端到端完成——全部节点按依赖顺序执行完毕。
- **SC-002**: 100% 的高风险/不可逆节点在执行前暂停等待操作者裁定——没有任何危险节点在未确认情况下静默执行。
- **SC-003**: 在存在可行恢复动作的情况下，节点失败的自愈成功率（不升级操作者即解决）占多数。
- **SC-004**: 操作者取消/改主意能在现有取消传播延迟内停下一张运行中的图，无遗留的孤儿执行。
- **SC-005**: 简单任务（1-2 步、单领域）无行为回归——仍走快速委派路径、延迟与体验与改造前一致。
- **SC-006**: 多步节点的执行器对非平凡节点产出并推进内部 todo 清单（不再退回"边想边做"）。
- **SC-007**: 现有 023 稳定路径（durable accepted、崩溃恢复、并发安全、取消传播）在本特性上线后不退化。

## Assumptions

- 023 分层越权重构（项目记忆中记录的在途重构）在 024 开工前稳定；024 只消费 023 的稳定接口。
- 复杂度分类为 LLM 软判定，初始阈值集为：预期步数 ≥3 且跨 ≥2 不同领域/工具族、或主助理自评"无法一次性规划清楚"、或涉及不可逆外部动作且步骤间有依赖；阈值运行时可调。
- "需确认"标记可通过复用现有字段（如 `capability_scope`）承载，plan 阶段确认；轻量 migration 为兜底。
- `todo_update` 能力已注入执行器（设计稿已确认），本特性只补行为引导（主体放工具 description、为辅调子 agent 工作规则、可选回流前 verification nudge）。
- 项目当前为单用户、未发布、无外部消费者（spec/plan 不预留 deprecation 双发兼容范围）。
- 硬保证由落库层架构门卫测试承担；LLM 软判定（复杂度分类、分解质量、自愈动作选择）不被当作确定性保证。
- 本特性遵循 CLAUDE.md 硬规则 6（改静默失败路径必须补测试）：调度、事件、恢复、Repository 等静默失败路径均补门卫与链路测试。
