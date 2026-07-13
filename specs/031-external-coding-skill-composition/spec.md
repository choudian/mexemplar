# Feature Specification: 外部 Coding 内置技能组合与专员授权

**Feature Branch**: `prepare-github`
**Created**: 2026-07-13
**Status**: Completed
**Related Feature**: `030-external-coding-sessions`
**Input**: 用户要求把既有 11 个 external coding 工具收口为系统内置的范围型技能组合，并在固定专员上按组合配置。

## 问题背景

030 已经提供完整的外部 Coding session 能力，但将 11 个底层动作直接视为普通 coding 工具，会让专员配置暴露过多实现细节，也容易把“有一个业务能力”误配成“勾选若干零散动作”。用户需要的授权单位是“外部 Coding”能力包：管理员只给固定专员配置一个组合，执行时仍按范围型组合的延迟激活协议获取成员工具。

## User Scenarios & Testing

### User Story 1 - 用一个组合配置外部 Coding 能力 (Priority: P1)

用户在技能组合列表看到系统内置、已发布、只读的“外部 Coding”范围型组合；在专员管理页只需勾选这一个组合，不再逐项选择 11 个底层动作。

**Independent Test**: 打开技能组合与专员管理接口，验证组合元数据、11 个成员、只读状态和单一组合勾选项；保存后配置进入专员当前记录与版本记录。

**Acceptance Scenarios**:

1. **Given** 系统启动, **When** 查询技能组合, **Then** 返回固定 ID 的“外部 Coding”，其状态为 published、模式为 range、成员数为 11，且标记 builtin/read-only/not-trialable。
2. **Given** 用户查看或编辑该组合, **When** 尝试修改、发布或试用, **Then** 系统拒绝变更，成员集合不能被用户漂移。
3. **Given** 用户编辑固定专员, **When** 勾选“外部 Coding”并保存, **Then** 只保存组合 ID，不把成员复制进 `tool_whitelist`，并形成可审计的专员版本。
4. **Given** 组合未发布、待复核或 `assistant_enabled=false`, **When** 用户配置专员, **Then** UI 不作为新分配项展示且业务层拒绝保存；已分配的陈旧项仍可见并可移除。

---

### User Story 2 - 仅在正式 Task 中按需激活 (Priority: P1)

配置了组合的固定执行型专员，在持久 Task 节点执行代码任务时先看到组合目录；调用组合后，11 个成员工具才进入其能力集合。

**Independent Test**: 用带组合配置、`role_kind=executor` 和非空 `current_task_id` 的固定专员运行工具工厂，验证初始无成员 schema、组合激活后成员出现。

**Acceptance Scenarios**:

1. **Given** 固定 executor 专员已显式配置组合且正在执行持久 Task, **When** 查询并激活“外部 Coding”, **Then** 11 个成员工具按原有 owner-bound session 契约可用。
2. **Given** 专员尚未激活组合, **When** 构建初始工具目录, **Then** 不预注入 11 个成员 schema。
3. **Given** 组合被配置, **When** 专员执行非正式同步委派（无 `current_task_id`）, **Then** 组合和成员均不可用。

---

### User Story 3 - 非授权执行体无法猜 ID 绕过 (Priority: P1)

主助理、临时子代理、规划专员、无固定专员身份的执行会话以及未配置专员都不能通过猜测内置组合 ID 获得 external coding 工具。

**Independent Test**: 分别向各类非授权工具工厂注入固定组合 ID，验证目录不泄漏组合、详情查询不可用且成员工具始终不存在。

**Acceptance Scenarios**:

1. **Given** main assistant 或 ephemeral subagent, **When** 注入或猜测组合 ID, **Then** 不展示、不激活组合。
2. **Given** planner specialist 或没有持久 specialist identity 的 delegated session, **When** 注入组合 ID, **Then** fail-closed。
3. **Given** 固定 executor specialist 未配置组合, **When** 执行正式 Task, **Then** 不获得组合或成员工具。

## Functional Requirements

- **FR-001**: 系统 MUST 以代码定义的稳定 ID 提供“外部 Coding”内置组合；其 11 个成员 MUST 与 030 的 external coding tool factory 保持同源。
- **FR-002**: 内置组合 MUST 固定为 `range + published + assistant_enabled + read-only + trial-disabled`。
- **FR-003**: 组合服务和 Desktop API MUST 返回内置/只读/试用支持/assistant-enabled 元数据。
- **FR-004**: 专员配置 MUST 只保存组合 ID，并通过 `SpecialistService` 校验组合当前可分配状态。
- **FR-005**: `composition_ids` MUST 同时持久化到 `brain_specialists` 和 `brain_specialist_versions`，使用 SQLite v29 migration。
- **FR-006**: external coding 成员工具 MUST 仅在 `AgentType.SPECIALIST`、`role_kind=executor`、固定 `specialist_id`、非空 `current_task_id`、组合已显式授权五项条件同时成立时构造。
- **FR-007**: 范围型组合 MUST 先激活虚拟组合工具，再由组合调用激活成员；不得在初始 delegated executor 工具集中直接注入成员。
- **FR-008**: main assistant、ephemeral、planner、同步 specialist、试用和未配置路径 MUST fail-closed。
- **FR-009**: 本 feature MUST 复用 030 的 owner/task 绑定、PLAN/RESULT、quota、merge/rollback 和安全门卫，不新增 secret、公开 UI event 或外部 CLI 协议。

## Success Criteria

- **SC-001**: 用户配置外部 Coding 能力时只操作 1 个组合项，而不是 11 个工具项。
- **SC-002**: 自动测试证明所有非授权矩阵均无法看到或激活组合成员。
- **SC-003**: 专员配置更新后，当前记录与版本历史中的 `composition_ids` 一致。
- **SC-004**: 既有 external coding 业务、API 和 UI 相关回归测试保持通过。

## Delivery Note

本 follow-up 最初来自 `docs/local/todo` 与用户澄清，实施在正式 Spec Kit artifact 之前开始。为满足可审查性要求，本目录在提交前补录完整约束、计划与任务；这是一次流程时序例外，不改变运行时边界。
