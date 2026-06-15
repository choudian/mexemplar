# Feature Specification: 工具目录渐进式延迟加载

**Feature Branch**: `021-tool-catalog-deferred-loading`  
**Created**: 2026-06-15  
**Status**: Implemented  
**Input**: 用户要求实现工具目录延迟加载的完整版，覆盖主助理、临时子代理和固定专员，并补齐分页浏览、授权隔离、统一配置、观测和完整测试。

## User Scenarios & Testing

### User Story 1 - 大技能池保持有限上下文 (Priority: P1)

当可用技能和技能组合持续增长时，主助理、临时子代理和固定专员仍能在有限的系统提示词中工作，不会每轮重复携带完整能力目录。

**Why this priority**: 这是降低每轮 token 消耗并避免技能池扩张拖累 Agent 稳定性的核心价值。

**Independent Test**: 为任一 Agent 配置超过阈值的授权目录，验证系统提示词不再包含完整名称和描述，但明确给出能力数量和发现方式。

**Acceptance Scenarios**:

1. **Given** 授权后的能力目录未超过条目数和字符数阈值，**When** 构建 Agent 提示词，**Then** 系统继续完整展示当前可用能力摘要。
2. **Given** 授权后的能力目录超过任一阈值，**When** 构建 Agent 提示词，**Then** 系统只展示目录统计和按需搜索说明，不泄漏隐藏条目的名称或描述。
3. **Given** 不同 Agent 拥有不同授权范围，**When** 判断完整或延迟模式，**Then** 每个 Agent 只基于自身授权后的目录计算阈值。

---

### User Story 2 - 大目录仍可完整发现能力 (Priority: P1)

Agent 在延迟模式下可以浏览或搜索全部已授权能力，稳定分页，并使用返回的明确选择器加载详情和激活调用定义。

**Why this priority**: 只隐藏目录而不补齐发现能力会让长尾技能事实上不可用。

**Independent Test**: 构造 100 个授权能力，通过无关键词浏览和关键词搜索分页遍历全部结果，再加载其中任一能力详情。

**Acceptance Scenarios**:

1. **Given** Agent 不知道准确关键词，**When** 调用空查询浏览，**Then** 返回第一页授权能力、总数和下一页偏移量。
2. **Given** Agent 提供关键词和能力类型，**When** 搜索目录，**Then** 结果按匹配质量和稳定次序返回。
3. **Given** 结果超过单页上限，**When** 使用下一页偏移继续请求，**Then** 不重复、不遗漏地遍历授权目录。
4. **Given** 技能与技能组合重名，**When** 查看搜索结果，**Then** 每项都提供可直接传给详情工具的无歧义选择器。

---

### User Story 3 - 目录变更和异常安全降级 (Priority: P2)

技能发布状态、组合可用性、会话白名单或配置发生变化后，后续 Prompt 和搜索调用立即采用最新事实；旧的已激活定义不能绕过权限或可用性校验。

**Why this priority**: 延迟加载不能削弱现有动态工具权限和失效保护。

**Independent Test**: 在同一管理器生命周期中撤销能力授权或发布状态，验证搜索、详情和下一轮激活定义均拒绝旧能力。

**Acceptance Scenarios**:

1. **Given** 能力在 Prompt 构建后被停用，**When** Agent 再搜索或加载详情，**Then** 该能力不再可见且无法激活。
2. **Given** 运行时修改发现阈值，**When** 下一次构建 Prompt，**Then** 新阈值立即生效而无需重启。
3. **Given** 配置值无效，**When** 读取发现策略，**Then** 系统使用有界默认值并保持可用。

### Edge Cases

- 目录为空时继续明确提示没有用户自定义能力，不强制调用搜索。
- 条目数或字符数恰好等于阈值时仍使用完整目录；只有严格超过阈值才延迟。
- 组合仅在已发布、启用、无需复核且全部成员均获授权时计入目录和搜索结果。
- offset 超过总数时返回空 items、正确 total，且没有 nextOffset。
- 描述为空或超长时返回稳定的空描述或有界截断，不让单项结果突破输出预算。
- 搜索参数类型或范围无效时返回清晰、可恢复的工具错误，不修改激活状态。

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 对授权过滤后的用户技能和技能组合目录同时应用条目数阈值与渲染字符数阈值。
- **FR-002**: 当目录不超过两个阈值时，系统 MUST 保持现有完整摘要注入行为。
- **FR-003**: 当目录超过任一阈值时，系统 MUST 切换为延迟模式，仅注入能力统计和 `search_tools` / `get_tool_detail` 使用说明。
- **FR-004**: 延迟模式提示 MUST NOT 包含被隐藏能力的名称、描述、适用场景或成员名称。
- **FR-005**: 策略 MUST 覆盖主助理、临时子代理和固定专员，并保持各自既有授权范围。
- **FR-006**: `search_tools` MUST 支持可选关键词、能力类型过滤、offset/limit 分页和无关键词目录浏览。
- **FR-007**: 搜索结果 MUST 返回 total、当前分页信息、nextOffset 以及每项的类型、名称、无歧义选择器和有界描述。
- **FR-008**: 搜索排序 MUST 确定且可复现，优先级依次为名称精确匹配、名称前缀、名称包含、描述或适用场景包含，同级稳定排序。
- **FR-009**: 搜索和详情加载 MUST 在调用时重新校验发布状态、组合可用性和授权范围。
- **FR-010**: `get_tool_detail` 激活后的 FC schema MUST 继续按现有动态工具刷新机制在下一轮生效，并保留 LRU 上限。
- **FR-011**: 新发现策略参数 MUST 通过统一配置管理并支持运行时覆盖，但本功能 MUST NOT 新增 Settings UI 控件。
- **FR-012**: 系统 MUST 记录不含能力名称、描述或 secret 的模式选择日志，至少包含 Agent 类型、授权条目数、目录字符数和 full/deferred 模式。
- **FR-013**: 现有只传 `query` 的 `search_tools` 调用 MUST 保持兼容。
- **FR-014**: 系统 MUST 支持至少 100 个授权能力的分页无遗漏遍历，并保持延迟模式 Prompt 长度有界。

### Key Entities

- **Authorized Capability Catalog**: 某一 Agent 当前获准使用的技能与技能组合集合，已经过发布、组合状态、成员完整性和会话白名单过滤。
- **Discovery Policy**: 决定完整目录或延迟目录模式的阈值与搜索输出限制。
- **Discovery Result Page**: 一次浏览或搜索返回的稳定分页结果，包含总数、游标和无歧义能力选择器。

### Constraints & Compatibility

- **CC-001**: UI、desktop API、SQLite schema、DuckDB 和公开 UI Event Registry 均不变。
- **CC-002**: 配置只能经 `get_unified_config()` / `UnifiedConfigManager` 读取，默认值同步到配置模型和示例模板。
- **CC-003**: 搜索与详情不得扩大 Agent 既有授权范围；组合必须保留成员授权子集规则。
- **CC-004**: `get_tool_detail` 仍为非并发安全工具；`search_tools` 只有在共享 Repository/Service 会话访问受保护时保持并发安全。
- **CC-005**: 不新增数据库迁移、secret、前端持久化状态或跨模块事件。

## Architecture Impact

### Layer Impact

- [ ] **UI** (`frontend/src/`, `src-tauri/`)
- [ ] **Desktop API Bridge** (`src/desktop_api/`)
- [x] **Business** (`src/business/`)
- [ ] **Execution** (`src/execution/`)
- [x] **Data** (`src/data/`)
- [ ] **Recording** (`src/recording/`)
- [ ] **Utils** (`src/utils/`)

### Agent Impact

- Which Agent(s) are affected: Assistant、临时子代理、固定专员
- New tools or modified tool handlers? 扩展 `search_tools` 的参数和返回契约；`get_tool_detail` 行为保持兼容。
- System prompt changes needed? 三类 Agent 统一使用完整/延迟目录策略。
- Orchestrator dispatch changes? 委派语义不变，仅改变授权能力目录提示的构建方式。

### Data Store Impact

- **SQLite**: 无 schema、Repository 或迁移变化。
- **DuckDB**: 无变化。
- **Config**: 新增 `agent_tools.discovery.*` 非敏感参数并同步三处配置入口。
- **Secrets**: 无新增 secret。

## Success Criteria

### Measurable Outcomes

- **SC-001**: 授权目录达到 100 项时，三类 Agent 的目录提示不包含任一隐藏能力名称，且目录区段不超过 1000 字符。
- **SC-002**: 100 项目录可通过连续分页遍历 100%，无重复、无遗漏。
- **SC-003**: 阈值边界、授权过滤、排序、分页、失效重校验和动态激活均有自动化行为测试。
- **SC-004**: 小目录现有完整摘要行为和仅传 `query` 的旧搜索调用保持通过。
- **SC-005**: 新增配置运行时覆盖在下一次 Prompt 构建或搜索调用中生效，无需重启或数据迁移。

## Assumptions

- 默认完整目录阈值为 20 项和 6000 字符。
- 默认搜索页大小为 10，最大页大小为 25，单项描述最多 500 字符。
- offset 分页足以满足当前本地单用户目录规模，不引入持久游标。
- 模式判断与搜索调用读取的是当前运行时配置；正在进行的单次模型调用不会被中途改写。
- Settings UI 不暴露工程调优参数，未来若需要用户可调将另行更新约束。
