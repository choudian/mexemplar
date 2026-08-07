# Specification Quality Checklist: 桌面录制 Phase 1

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-05-01
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — *见下"实施细节豁免"说明*
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders — *Phase 1 启动闸门部分包含技术决策来源标注（CC-002 / FR-009 / FR-010），来源于 brainstorm 决策追溯，不在 Acceptance Scenarios 中*
- [x] All mandatory sections completed (User Scenarios / Requirements / Success Criteria)

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable (5/5 录制成功 / 3/5 试用通过 / 3/5 走捷径 / 门卫不变量 100%)
- [x] Success criteria are technology-agnostic — *SC-005 / SC-006 引用了门卫不变量编号与 byte-equal，但这是用户层面的"不退化"承诺，可由 reviewer 验证而无需读源码*
- [x] All acceptance scenarios are defined (4 个 user story 共 13 条 Given/When/Then)
- [x] Edge cases are identified (9 条覆盖崩溃 / 跨屏 / 快捷键冲突 / vision 失败 / typing 长尾 / 拖拽边界 / 巨型剪贴板 / 三模式互斥 / 浏览器路径回归)
- [x] Scope is clearly bounded (Phase 1 = Windows 单屏 + UIA + pynput hook + 多帧 + clip + 双轨 prompt + e 方案试用；Phase 2 推延项明示)
- [x] Dependencies and assumptions identified (8 条 Assumptions + 7 条 Constraints & Compatibility)

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria — *FR-001 至 FR-027 共 27 条，每条都对应 Acceptance Scenarios 或可独立验证*
- [x] User scenarios cover primary flows — *P1 录制 + 分析、P2 试用、P3 健康反馈*
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification — *见下"实施细节豁免"说明*

## 实施细节豁免（来自 brainstorm 已拍板决策）

本 spec 的 FR / Architecture Impact / CC 章节包含具体技术名词（pynput、UIA、opencv-python、`dataclasses.replace`、表名 `desktop_recordings` / `desktop_actions`、行号 `:176` / `:459` 等）。这些**不属于"实施细节泄漏"**，而是 brainstorm 文档（`docs/local/_archive/design-drafts/2026-04-29-desktop-recording-brainstorm.md` §9.10 + §9.12-§9.15）已经经过 6 轮审查 + 4 轮修订（共 37 处变更）后**最终拍板**的技术决策，纳入 spec 用于：

1. 锁定 Phase 1 启动前置条件（避免实施期间二次决策造成漂移）
2. 守住浏览器路径不退化（门卫不变量 1-7 + prompt 行为级守卫）
3. 让 reviewer 能在没有读 brainstorm 全文的情况下判断实施是否对齐

如需脱开实施细节查看用户视角，仅看 User Scenarios + Success Criteria 即可。

## Notes

- Items 全部通过；未发现需返工的 spec 问题
- 与 brainstorm 文档对齐度 100%（无新增决策、无与 §9.10 冲突）
- 下一步：`/speckit-clarify`（如有进一步澄清需求）或直接 `/speckit-plan`

## 2026-05-05 Reviewer Addendum: Desktop Recording Requirements

**Purpose**: Validate current spec, plan, and tasks quality before implementation.
**Focus**: Requirements completeness, clarity, consistency, and acceptance readiness for the desktop-recording Phase 1 risk surface.
**Audience**: PR reviewer / implementation gate.

## Requirement Completeness

- [ ] CHK001 Are all desktop capture data fields that can enter Agent context explicitly defined with storage, large-field, and readback semantics? [Completeness, Spec §FR-004, Spec §FR-013, Spec §Key Entities, Tasks §T012/T030/T038]
- [ ] CHK002 Are all state transitions for `desktop_recordings.status` documented with UI entry points and downstream reachability constraints? [Completeness, Spec §FR-024, Spec §FR-027, Spec §User Story 4]
- [ ] CHK003 Are all mode-dispatch surfaces covered consistently across the five generic tools and the three desktop-specific tools? [Completeness, Spec §FR-011-FR-015, Plan §Summary, Tasks §T037-T052a]
- [ ] CHK004 Are browser-path non-regression requirements fully represented as requirements, not only as implementation tasks? [Completeness, Spec §CC-002, Spec §CC-003, Spec §SC-005, Spec §SC-006]
- [ ] CHK005 Are all manual e2e funnel requirements defined for both the P1 MVP gate and final Phase 1 gate? [Completeness, Spec §SC-001-SC-004, Tasks §T059a/T088]

## Requirement Clarity

- [ ] CHK006 Is the phrase "按需上传" constrained with exact upload triggers, maximum action count, image sources, and no-runtime-confirmation behavior? [Clarity, Spec §CC-005, Spec §FR-013, Spec §FR-026a]
- [ ] CHK007 Is "立即启动" for desktop recording clarified enough to avoid contradiction with the minimize-complete startup requirement? [Clarity, Spec §FR-022, Tasks §T019/T032]
- [ ] CHK008 Is the `vision_model` missing-state behavior clear across configuration UI, tool injection, PM prompt responsibility, and user notification? [Clarity, Spec §FR-026a, Tasks §T047/T078/T082/T083]
- [ ] CHK009 Are Trial result success, failure, timeout, and stdout-no-JSON outcomes specified with distinguishable user-visible and data-shape criteria? [Clarity, Spec §FR-021a, Spec §SC-003, Tasks §T060-T065/T071/T074]
- [ ] CHK010 Are "走捷径" criteria defined with enough examples, exclusions, and shared detector ownership to avoid reviewer-specific interpretation drift? [Clarity, Spec §SC-004, Tasks §T011a/T011b/T066/T088]

## Requirement Consistency

- [ ] CHK011 Are layer-boundary requirements consistent between spec Architecture Impact, plan Constitution Check, and tasks ownership? [Consistency, Spec §Architecture Impact, Plan §Constitution Check, Tasks §T009/T011c/T030/T075]
- [ ] CHK012 Are `recording.desktop.enable_clip` requirements consistent across config defaults, clip generation, sanity color rules, and tests? [Consistency, Spec §FR-005, Spec §FR-024, Spec §FR-026, Tasks §T003/T017/T028/T076/T083]
- [ ] CHK013 Are clipboard text/image requirements consistent between event capture, action row association, large-field rules, and vision prompt assembly? [Consistency, Spec §FR-004, Spec §FR-013, Spec §Key Entities, Tasks §T012/T015/T025/T030/T038/T042]
- [ ] CHK014 Are crash-recovery exclusions consistent between recording data retention and Trial temporary-directory cleanup? [Consistency, Spec §Edge Cases, Spec §FR-021a, Spec §FR-027, Tasks §T011/T067/T067a]
- [ ] CHK015 Are PM, Programmer, and Trial toolset symmetry requirements consistently stated for browser and desktop modes? [Consistency, Spec §FR-014, Spec §FR-015, Spec §Agent Impact, Tasks §T047a/T052a]

## Scenario Coverage

- [ ] CHK016 Are primary, alternate, exception, recovery, and non-functional scenarios all represented for recording start/stop flows? [Coverage, Spec §User Story 1, Spec §Edge Cases, Spec §FR-022-FR-025]
- [ ] CHK017 Are degraded-start scenarios specified for hook, UIA, clipboard, and hotkey failures with distinct blocking or non-blocking outcomes? [Coverage, Spec §FR-002-FR-004, Spec §FR-023, Tasks §T035]
- [ ] CHK018 Are Agent-analysis failure paths specified for missing `vision_model`, vision timeout, unauthorized access, and partial action failure? [Coverage, Spec §FR-013, Spec §FR-026a, Spec §Edge Cases]
- [ ] CHK019 Are Trial execution failure paths specified for syntax errors, runtime exceptions, timeout, subprocess descendants, and invalid stdout shape? [Coverage, Spec §FR-017a, Spec §FR-021a, Tasks §T046/T057/T060-T065]
- [ ] CHK020 Are cross-mode conflict scenarios specified for browser, desktop, and extension-triggered recordings without relying on database cleanup state? [Coverage, Spec §FR-025, Spec §CC-006, Spec §Edge Cases]

## Acceptance Criteria Quality

- [ ] CHK021 Are all success criteria objectively measurable or explicitly classified as manual judgment where automation is intentionally excluded? [Measurability, Spec §SC-001-SC-008, Plan §Constitution Check IV]
- [ ] CHK022 Is the P1 MVP stop gate measurable enough to decide whether implementation can proceed to Trial and health-feedback work? [Measurability, Tasks §T059a, Spec §SC-001, Spec §SC-002]
- [ ] CHK023 Are browser-path guard requirements traceable to specific invariants and prompt guard criteria rather than generic "no regression" wording? [Measurability, Spec §CC-002, Spec §CC-003, Spec §SC-005, Spec §SC-006]
- [ ] CHK024 Are performance soft targets accompanied by enough observation and reporting requirements to make manual evaluation meaningful? [Measurability, Spec §CC-007, Spec §SC-007, Tasks §T088]
- [ ] CHK025 Is privacy compliance completion expressed as a concrete release gate with owner class, risk text, and artifact location? [Acceptance Criteria, Spec §CC-004, Spec §SC-008, Tasks §T089]

## Non-Functional Requirements

- [ ] CHK026 Are security and privacy assumptions documented for local storage, keyring usage, environment filtering, and vision upload behavior? [Security, Spec §FR-021a, Spec §FR-026a, Spec §CC-004, Spec §CC-005]
- [ ] CHK027 Are observability requirements defined for vision cost audit logs, Trial stdout/stderr persistence, and syntax-gate failure diagnostics? [Observability, Spec §FR-013, Spec §FR-017a, Spec §FR-021a]
- [ ] CHK028 Are reliability tradeoffs around no crash recovery, no hard recording limits, and no resource monitoring explicitly bounded to Phase 1? [Reliability, Spec §FR-027, Spec §CC-008, Spec §Assumptions]
- [ ] CHK029 Are accessibility and localization expectations intentionally excluded or sufficiently specified for the new dialogs, toast text, and floating widget? [Gap, Spec §FR-021, Spec §FR-022, Spec §FR-024, Spec §FR-026a]
- [ ] CHK030 Are Windows-only assumptions explicit enough for unsupported platforms, dependency setup, and installer risk? [Dependency, Spec §CC-001, Plan §Technical Context]

## Dependencies & Assumptions

- [ ] CHK031 Are all external dependencies and their failure modes captured at the requirement level, including UIA, pynput, clipboard listener, vision LLM, sqlglot, and subprocess execution? [Dependency, Spec §FR-002-FR-004, Spec §FR-013, Spec §FR-021a, Spec §CC-002]
- [ ] CHK032 Are configuration and documentation synchronization requirements traceable across spec, plan, and tasks? [Traceability, Spec §FR-026-FR-026a, Plan §Constitution Check III/V, Tasks §T003/T010/T083-T087]
- [ ] CHK033 Are retained artifacts and user cleanup responsibilities specified for both recording data and Trial debug directories? [Assumption, Spec §FR-021a, Spec §FR-027, Spec §Edge Cases]
- [ ] CHK034 Are Phase 2 deferrals documented with clear boundaries that prevent accidental Phase 1 implementation scope creep? [Scope, Spec §Edge Cases, Spec §CC-008, Spec §Assumptions]

## 2026-05-07 Reviewer Addendum: Blueprint-to-Implementation Requirements Gate

**Purpose**: Validate whether the current spec, plan, and tasks are precise enough to guide the remaining implementation and review gates without relying on undocumented reviewer assumptions.
**Focus**: Remaining desktop-recording risk areas after blueprint generation: US1 UI startup/restore flow, US2 tool composition and vision semantics, US3 Trial lifecycle, US4 sanity-state decisions, manual e2e, and release risk gates.
**Audience**: PR reviewer / implementation closeout gate.

## Requirement Completeness

- [ ] CHK035 是否已把 P1 MVP 闸门的进入/退出条件写成完整需求，而不只存在于任务依赖说明中？[Completeness, Spec §SC-001-SC-002, Tasks §T059a, Tasks §Dependencies]
- [ ] CHK036 是否已定义未完成 UI 录制流任务与已完成录制层任务之间的需求边界，避免 reviewer 难以判断 US1 何时可独立交付？[Completeness, Spec §FR-022-FR-025, Tasks §T032-T036b]
- [ ] CHK037 是否已明确桌面专属工具在 PM / Programmer / Trial 三类 Agent 中的注入、缺省和降级需求，而不是只在工具实现任务中体现？[Completeness, Spec §FR-014-FR-015, Spec §FR-026a, Tasks §T047-T047b/T052a]
- [ ] CHK038 是否已完整描述 Trial 事前提示、取消、成功、失败、超时、无有效 JSON 等用户可见结局对应的状态与文案要求？[Completeness, Spec §FR-021-FR-021a, Spec §SC-003, Tasks §T060-T074]

## Requirement Clarity

- [ ] CHK039 `minimize 完成回调后启动` 与 `停止后 restore 主窗` 的先后条件是否以可审查语言定义清楚，包括 geometry/state 的记录和恢复责任？[Clarity, Spec §FR-022, Spec §FR-024, Tasks §T032/T034]
- [ ] CHK040 `UI 禁用 + 程序拒绝双保险` 是否说明了两层失败时的用户可见反馈和后续可恢复状态？[Clarity, Spec §FR-025, Spec §CC-006, Tasks §T036-T036b]
- [ ] CHK041 `analyze_desktop_action` 的 partial failure 字符串拼接、large-field 占位、上传审计日志和无 quota 取舍是否足够清晰，能避免不同 reviewer 对失败返回形态作不同解释？[Clarity, Spec §FR-013, Spec §CC-005, Spec §Assumptions]
- [ ] CHK042 `vision_model` 缺失时的两条用户提示路径是否已用同一套时机、频率和阻塞性术语描述，避免设置页、intent 页和工具注入语义分裂？[Clarity, Spec §FR-026a, Tasks §T047/T078/T082/T083]

## Requirement Consistency

- [ ] CHK043 spec 中的三按钮状态机是否与 tasks 中 US1 基础路径和 US4 增强路径保持一致，且不会把 `继续分析`、`放弃录制`、`重新录制` 的 mode 预选语义混淆？[Consistency, Spec §FR-024, Tasks §T019a/T034/T077/T081]
- [ ] CHK044 Trial 临时目录 7 天清理需求是否与录制数据不清理、不设 quota、不自动处理崩溃孤儿的 Phase 1 边界一致？[Consistency, Spec §FR-021a, Spec §FR-027, Spec §CC-008, Tasks §T011/T067a]
- [ ] CHK045 浏览器路径 byte-equal、prompt legacy 保留、桌面工具替换三组需求是否在 spec、plan、tasks 中使用同一组不变量和相同的 Agent 范围？[Consistency, Spec §CC-002-CC-003, Spec §FR-014-FR-016, Plan §Constitution Check IV, Tasks §T037/T044/T045/T047a]
- [ ] CHK046 高危 API 规则是否在事前提示、捷径判定、共享 detector、manual e2e 四处保持同一枚举、同一排除项和同一人工复核边界？[Consistency, Spec §FR-021, Spec §SC-004, Tasks §T011a/T011b/T066/T073/T088]

## Scenario Coverage

- [ ] CHK047 是否覆盖了录制启动过程中 hook 阻塞失败、UIA 降级、剪贴板降级、热键降级四类场景，并区分阻塞与非阻塞需求？[Coverage, Spec §FR-002-FR-004, Spec §FR-023, Tasks §T035]
- [ ] CHK048 是否覆盖了纯键盘录制、无 action 录制、clip 关闭、clip 编码失败、UIA 分母为 0 等 sanity color 边界需求？[Coverage, Spec §FR-024, Spec §FR-026, Tasks §T076/T079-T081]
- [ ] CHK049 是否覆盖了桌面 fixture 足够弱或缺少剪贴板事件时 PM intent 半集成场景的最低需求，避免 `analyze_desktop_action` 依赖隐含数据前提？[Coverage, Spec §FR-011-FR-013, Spec §SC-002, Tasks §T047b]
- [ ] CHK050 是否覆盖了手工 e2e 过程中性能软目标明显偏离时的记录、归因和是否阻塞发布的判断要求？[Coverage, Spec §CC-007, Spec §SC-007, Tasks §T088]

## Acceptance Criteria Quality

- [ ] CHK051 SC-001 至 SC-004 的 5 场景漏斗是否定义了统一记录格式、最小证据和失败归因字段，便于 reviewer 复核而不依赖口头说明？[Acceptance Criteria, Spec §SC-001-SC-004, Tasks §T088, quickstart.md]
- [ ] CHK052 SC-005 / SC-006 的浏览器路径门卫是否把 baseline 更新规则、允许差异和失败处置写清楚，避免 byte-equal 失败时被临时解释为可接受差异？[Acceptance Criteria, Spec §SC-005-SC-006, Spec §CC-002-CC-003, Tasks §T037/T045]
- [ ] CHK053 SC-008 隐私风险签字是否有明确的 artifact 位置、签字角色和公开发版前的阻塞语义？[Acceptance Criteria, Spec §CC-004, Spec §SC-008, Tasks §T089]
- [ ] CHK054 `试用通过` 的成功定义是否同时约束 exit code、stdout 末行 JSON 和 `ok=True`，并和 UI Toast 的成功/失败标题需求没有冲突？[Acceptance Criteria, Spec §FR-021a, Spec §SC-003, Tasks §T060-T065/T074]

## Dependencies & Assumptions

- [ ] CHK055 是否已把 Windows-only、UIA/pynput/pywin32/opencv/vision provider 等依赖失败的范围写成需求层假设，而不是只写在技术计划中？[Dependency, Spec §CC-001, Spec §Assumptions, Plan §Technical Context]
- [ ] CHK056 是否已明确 provider 维度复用 `analyze_image`、model 维度独立、keyring entry 不分裂三者之间的依赖关系和失败归属？[Dependency, Spec §FR-026a, Plan §Constitution Check III, Tasks §T047a/T083]
- [ ] CHK057 是否已说明 Phase 2 推迟项（UI 播放器、vision 缓存、quota/rate limit、资源配额、弱 UIA 应用）不会成为 Phase 1 验收的隐含条件？[Assumption, Spec §FR-027, Spec §CC-008, Spec §Assumptions]
