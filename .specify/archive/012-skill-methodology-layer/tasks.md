# Tasks: Skill Methodology Layer

**Input**: Design documents from `specs/012-skill-methodology-layer/`
**Prerequisites**: plan.md ✅, spec.md ✅, data-model.md ✅, contracts/rest-api.md ✅, quickstart.md ✅

**Bugfix**: 2026-05-28 — ANALYZE-001 Updated from analysis patch: fixed config/table naming inconsistencies, tightened verification coverage, and corrected task statistics.

**Bugfix**: 2026-05-28 — ANALYZE-002 Updated from analysis follow-up: added config template coverage and audit change-reason verification.

---

## Phase 1: Setup（共享基础设施）

**Purpose**: 创建 seed 文件与配置占位符，不阻塞任何业务逻辑

- [X] T001 [P] 创建 seed 文件 `src/business/brain/seed/how_to_create_skill_methodology.md`（含判重义务、load 节制义务、素材 zone 限制、字段必填说明、**FR-026 SHOULD 引导**——工具产出新 active / 新版本方法论后向用户回复"已新增 / 更新方法论 X"作为可见反馈；FR-026 / FR-027 / SC-024d 必填）
- [X] T002 [P] 在 `src/data/unified_config.py` 添加 `brain.skill.token_budget.warn_threshold`（默认 4096）/ `brain.skill.token_budget.danger_threshold`（默认 8192）/ `brain.skill.seed_file_path` 三项配置占位符；同步更新 `config.example.json` 与 `config.example.comments.md` 的默认值 / 注释模板；阈值必须由后端 `get_unified_config()` 读取后通过装备端点 DTO 下发给前端，前端不得硬编码（Constitution III / plan.md Constitution Check III）

---

## Phase 2: Foundational（阻塞所有 US 的基础层）

**Purpose**: 数据层 + 事件层 + Bootstrap，所有 User Story 均依赖此 phase 完成

**⚠️ CRITICAL**: 所有 US 实现必须等此 phase 完成后才能开始

- [X] T003 [P] 在 `src/utils/events.py` 新增 blinker 事件 `brain_skill_changed` / `brain_skill_equipment_changed` / `brain_skill_supersede_completed`（plan.md 事件契约 / FR-032）
- [X] T004 [P] 在 `src/desktop_api/ui_events.py` 新增 UI Event Registry 条目：(1) `skill.changed`（payload 含 reason / skillId / chainRootId / newSkillId / callerType / callerId / bootstrapFallbackUsed / bootstrapFallbackInfo，**不含** body_markdown，对齐 contracts/events.md §2.1）；(2) `skill.equipment.changed`（payload 含 changeType / entityType / entityId / skillId / unequippedReason，对齐 contracts/events.md §2.2）；(3) 同步把 `skills.changed` 改名为 `tools.changed`（FR-003 / CC-006）；(4) **扩展既有 `assistant.confirmation` UI Event 的 `actionType` 枚举集**，新增 `skill.edit_protected` / `skill.soft_delete` 两值（contracts/events.md §2.4 / FR-027a / FR-020）；(5) **扩展既有 `backend.resync_required` UI Event 的 `domains` 枚举值**，新增 `"skill"` 域（contracts/events.md §2.5）
- [X] T005 [P] 在 `src/data/models_sqlite.py` 新增 ORM 模型 `BrainSkill` / `BrainSkillSourceSegment` / `BrainSkillEquipment`，含封闭枚举（`origin` 5 值 / `status` / `equipment_status` / `unequipped_reason`）和字段类型约束（FR-006a / FR-014b / SC-025）
- [X] T006 在 `src/data/migrations.py` 实现 `migrate_to_v12()`：创建 `brain_skills` / `brain_skill_source_segments` / `brain_skill_equipment` 三张表 + 全部索引 + UNIQUE PARTIAL INDEX + CHECK 约束；migration 在 data 层内部直接插入 bootstrap 行与 assistant 本体装备行，不反向 import business service（data-model.md v12 / FR-027b / SC-023；依赖 T007–T009）
- [X] T007 [P] 实现 `src/data/repos/skill_repository.py`（`SkillRepository`）：CRUD + `chain_root_id` 冗余查询 + same-name active 检查 + 链遍历 + 按 origin 筛选；Repository 不暴露 `delete_*` 方法（CC-001 / FR-007 / SC-008）
- [X] T008 [P] 实现 `src/data/repos/skill_equipment_repository.py`（`SkillEquipmentRepository`）：装备状态机（active / unequipped）+ 新建而非复用历史行 + 双向历史查询 + unique partial index 约束；不暴露物理 DELETE（FR-014b / SC-026）
- [X] T009 实现 `src/business/brain/skill_bootstrap_service.py`（`SkillBootstrapService`）：`load_seed_or_fallback()`（含 fallback 逻辑 + `_FALLBACK_BODY` 常量，常量正文必须符合 FR-027b 最小内容约束——含"seed 加载失败 + 联系开发者修复 + 在 SkillScreen 上手动编辑此方法论"提示，以及最小判重义务说明保证 assistant fallback 状态下仍有创建指引底线）/ `bootstrap_missing_skill()` / `ensure_bootstrap_skill()`（应用启动自愈：链上无 user_edit 且当前 active 是 fallback body 时用真实 seed 自动 supersede；已有 user_edit 则跳过尊重用户修订）（FR-027 / FR-027b / SC-023；依赖 T007）
- [X] T010 [P] 在 `src/desktop_api/schemas.py` 新增 `SkillSummary` / `SkillDetail` / `SkillVersionNode` / `SkillEquipmentItem` / `SkillEquipmentAuditRow` / `EquipmentUpdateRequest` / `BootstrapStatusResponse` / `TokenBudgetThresholds` DTO（contracts/rest-api.md §1-§4 契约；`SkillEquipmentAuditRow` 对应 `/api/skills/methodology/{id}/audit-equipment` 的 rows 形态；`TokenBudgetThresholds` 由装备端点返回 warn/danger 阈值）
- [X] T011 验证 `src/data/migrations.py::run_migrations()` 调用链含 `migrate_to_v12()`；若缺失则在 `run_migrations()` 末尾插入调用；新增 `tests/data/test_migrations.py::test_v12_invoked_in_run_migrations` 断言用例（保证未来回归不会漏接 v12）
- [X] T011a 在 data 层定义固定 bootstrap 常量 `BOOTSTRAP_HOW_TO_SKILL_ID = "bootstrap.how_to_create_skill_methodology"`，由 migration 自包含写入"如何创建方法论" skill 行与 assistant 本体（entity_type=`'assistant'`, entity_id=`'_assistant'`）装备行；`SkillBootstrapService.bootstrap_missing_skill()` 复用同一 data-owned 常量处理启动期缺行修复。fallback 路径（FR-027b）保证 fallback 版本也立刻可被 assistant 本体 load。本任务绕过 P3 才上线的 `SkillEquipmentService.default_equip_all` 编排层，但严格维持 FR-014a "system_bootstrap 例外仅装 assistant 本体"不变量与 FR-025 默认装备约定；P3 T040 上线后 default_equip_all 不再为 system_bootstrap 链根方法论的 bootstrap 初装做事情（已由本任务在 migration 期完成），新建 specialist 默认全装备路径仍按 FR-014a 例外正确剔除该方法论。新增 `tests/business/brain/test_skill_bootstrap_service.py::test_bootstrap_equips_to_assistant_only` 与 `tests/guardrails/test_skill_system_bootstrap_protection.py::test_bootstrap_initial_equipment_skips_specialists`（FR-014a / FR-025 / FR-027 / SC-013；依赖 T008 / T009）

**Checkpoint**: 数据层、事件层、bootstrap（含 assistant 本体首装）完备 → 所有 User Story 可并行展开

---

## Phase 3: User Story 1 — 术语腾位（Priority: P1）🎯 MVP

**Goal**: 把 "Skill" 词位让给方法论；现有三屏（Teaching / List / Composition）文案、路由标签、对外通知整体改为 Tool 系列

**Independent Test**: 打开 UI，导航文案全部为 Tool 系列；访问旧 `/skills` 路径自动 redirect；SSE 事件流 type 只有 `tools.changed`，不再出现 `skills.changed`；`uv run pytest tests/guardrails/test_skill_tools_terminology_rename.py -v` 全部通过

- [X] T012 [P] [US1] 将 `src/utils/events.py` 中现有 `skills_changed` blinker 事件改名为 `tools_changed`，并同步更新所有 emit 调用点（`src/business/` 下的全部引用）（FR-003 / CC-006）
- [X] T013 [P] [US1] 更新 `src/desktop_api/` 与 `src/business/` 下所有 `emit('skills.changed', ...)` 调用点为 `emit('tools.changed', ...)`（Registry 改名本身已在 T004 完成）（FR-003 / SC-012）
- [X] T014 [P] [US1] 更新 `frontend/src/app/routes.tsx`：(1) 把 Skill Teaching / Skill List / Skill Composition 三条 label / shortLabel 改为 Tool Teaching / Tool List / Tool Composition；(2) **新增 `/tools/list` / `/tools/teaching` / `/tools/compositions` 三条新路径**（按 plan.md 路由策略，组件复用 `frontend/src/screens/skills/`、`teaching/`、`compositions/`）；(3) 添加一次性改名提示的逻辑触发点（FR-001 / FR-004）
- [X] T015 [P] [US1] 更新 `frontend/src/screens/skills/`、`frontend/src/screens/teaching/`、`frontend/src/screens/compositions/` 下所有面向用户的文案（屏内标题、按钮文本、空态文案）改为 Tool 系列；**同步更新 `frontend/tests/e2e/` 下原 Skill 三屏 e2e 测试文件**（如 `skill-list.spec.ts` / `skill-teaching.spec.ts` / `skill-composition.spec.ts` 或同等命名）中所有硬编码 Skill 文案断言为对应 Tool 文案，文件可视情况一并重命名为 `tool-*.spec.ts`，避免 P1 完成时 T070(v) e2e 回归套件因文案不匹配先红（FR-001 / CC-005 / SC-007）
- [X] T016 [P] [US1] 在 `frontend/src/app/routes.tsx` 添加 redirect 规则（按 plan.md 路由策略；优先级 `/skills/methodology` > `/skills/*`）：(a) `/skills` 与 `/skills?category=...` → `/tools/list`；(b) `/skills/teaching` 与子路径 → `/tools/teaching`；(c) `/skills/compositions` 与子路径 → `/tools/compositions`；(d) `/skills/methodology` 与子路径**不**走 redirect，由 T033 注册的方法论路由捕获（FR-002 / SC-011）
- [X] T017 [P] [US1] 更新 `frontend/src/app/NavRail.tsx`：导航标签改为 Tool 系列；添加一次性 "已将 Skill 重命名为 Tool" toast 组件（带 localStorage/settingsStore 持久化关闭状态）（FR-001 / FR-004 / SC-001）
- [X] T018 [US1] 新增守卫测试 `tests/guardrails/test_skill_tools_terminology_rename.py`：(a) 断言 `src/utils/events.py` 不再存在 `skills_changed` 符号导出；(b) 断言 `UI_EVENT_REGISTRY` 不再含 `"skills.changed"` key，新含 `"tools.changed"` / `"skill.changed"` / `"skill.equipment.changed"`；(c) 断言 emit 调用点都已切换；(d) 断言旧 `/skills*` 路由（除 `/skills/methodology`）100% redirect 到对应 `/tools/*`；(e) **新增断言**：扫描 `frontend/src/screens/SkillMethodologyScreen/` 目录所有文件，"Skill" 词均指方法论（不出现"Skill Teaching / List / Composition"等 Tool 三屏遗留词；FR-005）（SC-001 / SC-011 / SC-012 / FR-005）

**Checkpoint**: P1 独立可交付 — 命名整顿完毕，不依赖方法论资产存在

---

## Phase 4: User Story 2 — 通过 assistant 创建方法论 + 编辑闭环（Priority: P2）

**Goal**: 方法论资产层从 0 到 1；用户可通过对话请求 assistant 调工具入库 active；可在 SkillScreen 编辑（等价 supersede）或软删除

**Independent Test**: 对 assistant 说"做成方法论"→ SkillScreen 出现 active 卡片（≤30s）；编辑保存后无弹窗即生成 v2；受保护方法论保存触发高危确认；软删除走高危确认；`uv run pytest tests/guardrails/test_skill_no_physical_delete.py tests/guardrails/test_skill_origin_closed_enum.py -v` 通过

### 业务层与 Agent

- [X] T019 [P] [US2] 实现 `src/business/brain/skill_service.py`（`SkillService`）：create（same-name active 检查 + 素材 zone 校验）/ supersede（单事务：旧→superseded + 新→active + 装备关系切换）/ user_edit 接力 / soft_delete（含 FR-027a 受保护拒绝 + FR-020 高危确认占位）/ system_bootstrap 链根例外判定 / `force_soft_delete`（P2 阶段**完整实现**——同事务内通过 `SkillEquipmentRepository`（T008）把该 skill 上所有 `status='active'` 装备关系标 `status='unequipped'` / `unequipped_reason='force_remove_on_soft_delete'` / `unequipped_at=now`，再把 skill 行落 `soft_deleted`；崩溃整体回滚，避免 FR-020 明令禁止的"已落 soft_deleted 但装备未裁剪"中间态。本任务绕过 P3 才上线的 `SkillEquipmentService` 编排层，模式与 T011a / T019a 一致；P3 T041 上线后把直调 Repository 的内联裁剪替换为 `SkillEquipmentService.force_unequip_all_for_skill()` 调用，等价语义不变）（依赖 T007 / T008 / T009）
- [X] T019a [US2] 在 `SkillService.create()` 与 `SkillService.supersede()` / `SkillService.user_edit_supersede()` 写入新 active skill 行之后**同事务内**直接通过 `SkillEquipmentRepository`（T008，绕过 P3 才上线的 `SkillEquipmentService.default_equip_all` 编排层）执行 FR-014a 默认全装备传播：(a) 新建模式 → 对当时所有 active specialist + assistant 本体新增 `status='active'` 装备关系行；(b) supersede 模式 → FR-011 已在 T019 完成"旧 active 装备行标 unequipped reason=`supersede_transfer` + 新版本插入对应 active 行"切版本，T019a 仅追加"未装备旧版本的现有 specialist + (assistant 本体若未装备) 也按 FR-014a 追加 active 行"合并语义；(c) 用户曾主动卸下（reason=`user_unequip`）的装备关系**不**自动复装；(d) **system_bootstrap 例外按链根 origin 判定**——本路径计算时如新 skill 的链根 origin = `system_bootstrap`，则默认装备范围剔除所有 specialist，仅装备到 assistant 本体（与 T011a bootstrap 期同语义；P2 阶段 assistant 调工具产出的 origin = `assistant_tool_call` 不触发本例外）；(e) 崩溃整体回滚。P3 T040 `default_equip_all` 上线后本任务的内联实现可被替换为对 service 的单次调用并删除冗余路径，等价语义不变（FR-014a / FR-023 / SC-013；依赖 T008 / T019）
- [X] T020 [P] [US2] 实现 `src/business/brain/skill_reference_counter.py`（`SkillReferenceCounterService`）：`process_reply_metadata(skills_referenced: list[str])`——chain_root 归一化 +1 / 去重 / soft_deleted 静默跳过 / 格式错误静默跳过（FR-041 / SC-016；依赖 T007）
- [X] T021 [US2] 实现 `src/business/agents/tools/skill_methodology_tools.py`：`create_skill_methodology` 工具定义 + handler（新建/supersede 两种模式；≥1 素材 archive/failure zone 校验；trigger_conditions ≥1 条校验；同名 active 拒绝（新建模式）；直接 active 入库；仅 assistant 本体默认装备给自己）；`load_skill_methodology` 工具定义 + **P2 阶段 placeholder handler**（P2 仅 assistant 本体调用以查看自己装备的"如何创建方法论"内置方法论作为创建指引；handler 实现 FR-017a 完整契约——返回 SKILL.md 形态 / loaded_count +1 / 装备清单检查 / 拒绝 superseded / soft_deleted；P2 不向 specialist 默认装备本工具，**P3 T044/T045 阶段才向所有装备者放开**——并非永久限制，注意 `# TODO(P3)` 标注引导）（FR-021–FR-025 / FR-017a / SC-009 / SC-010；依赖 T019）
- [X] T022 [P] [US2] 在 `src/business/agents/tools/assistant_tools.py` 的 `reply_to_user` 工具 schema 新增 `skills_referenced: list[str]` 字段；在 reply 落库路径调 `SkillReferenceCounterService.process_reply_metadata()`。**说明**：`reply_to_user` schema 由 assistant 调度层本体与 specialist 共享同一文件入口（已是项目既有模式），单文件修改即同时覆盖 specialist 与 assistant 本体两类装备者的 reply 元数据契约——不需要拆分多文件任务（FR-041 / SC-016）
- [X] T023 [US2] 在 `src/business/brain/context_builder.py` 为 assistant 调度层本体角色注入装备清单条目段（id + name + description + trigger_conditions YAML list，**不含** body_markdown；只注入 active 方法论；按装备顺序）；同时在 `src/business/agents/prompts/assistant_prompt.py` 末段追加 **FR-026 SHOULD 引导文本**："工具产出新 active / 新版本方法论后，向用户回复'已新增 / 更新方法论 X'作为可见反馈"——落点放 prompt 文件以与 010 已有 SHOULD 引导模式对齐；本段 SHOULD 引导仅作 LLM 行为引导，不要求自动化测试断言具体输出（与 FR-026 备注一致）（FR-017 / FR-026 SHOULD / SC-018；P2 阶段 assistant 本体已通过 T011a 装备 "如何创建方法论"）

### Desktop API 层

- [X] T024 [P] [US2] 实现 `src/desktop_api/routers/skills_methodology.py`（P2 端点）：`GET /api/skills/methodology`（list + sort + filter）/ `GET /api/skills/methodology/{id}`（detail）/ `PUT /api/skills/methodology/{id}`（用户编辑 → supersede 接力；当链根 origin = `system_bootstrap` 时**必须复用项目高危同步确认协议** `request_id + threading.Event + emit(request_id, message)`（CLAUDE.md 第 9 条 / 004 高危确认浮层同协议），service emit `assistant.confirmation` UI Event（actionType = `skill.edit_protected`）后**阻塞等待**用户决策；用户拒绝即取消、用户确认才走 supersede）/ `POST /api/skills/methodology/{id}/soft-delete`（同样走 `request_id + threading.Event + emit` 同步确认协议；service emit `assistant.confirmation`（actionType = `skill.soft_delete`，payload 含装备者名单 + 数量）后阻塞；用户确认后调用 `SkillService.force_soft_delete()`（T019）在**单事务内**完成装备关系裁剪 + 方法论落 soft_deleted——P2 阶段装备关系来自 T019a / T011a 桥接路径，T019 已完整裁剪不留中间态，**无 no-op**）/ `GET /api/skills/methodology/bootstrap-status`（contracts/rest-api.md §2 / FR-027a / FR-020 / SC-005 / SC-021；依赖 T010 / T019）
- [X] T025 [US2] 在 `src/desktop_api/app.py`（或对应路由注册文件）挂载 `skills_methodology.py` 路由

### 前端状态层

- [X] T026 [P] [US2] 实现 `frontend/src/state/skillMethodologyStore.ts`（Zustand store）：active list / sort key / filter state / edit draft / 未读 badge 计数；监听 `skill.changed` 事件被动刷新（FR-032 / FR-033）
- [X] T027 [P] [US2] 实现 `frontend/src/api/skillsMethodology.ts` API client：list / detail / edit / softDelete / bootstrapStatus（对应 T024 端点）

### 前端 UI 组件

- [X] T028 [P] [US2] 实现 `frontend/src/components/SkillCard.tsx`：方法论卡片（名称 + 描述 + 三项计数（被加载次数 / 装备者数量 / 被引用执行次数）+ is_protected badge + version 显示）（FR-029a / SC-015）
- [X] T029 [US2] 实现 `frontend/src/screens/SkillMethodologyScreen/SkillActiveList.tsx`：active 列表（4 种排序切换 + 2 类筛选叠加 + SkillCard 网格；排序为前端本地排序，不 round-trip）；默认排序键"最近变更时间倒序"的时间字段 MUST 取 **当前 active 版本的 `created_at`**（即 FR-029b 定义），不消费装备关系变更时间、`load_skill_methodology` 调用时间或 `skills_referenced` 触发的"最近一次被引用执行时间"——后者是与本键独立的 30 天筛选用时间字段（FR-029a / FR-029b / SC-015）
- [X] T030 [US2] 实现 `frontend/src/screens/SkillMethodologyScreen/SkillEditor.tsx`：五字段编辑器（name / description / trigger_conditions list editor / required_tools list editor / body_markdown textarea）；字段必填校验；name 撞名检查；**系统字段（status / version / chain refs / 三项计数 / origin / 最近变更时间）以只读形式渲染（或仅在审计视图展示），编辑器表单不含可写入这些字段的控件**（FR-031 / FR-024a / SC-022）
- [X] T031 [US2] 实现 `frontend/src/screens/SkillMethodologyScreen/SkillDangerConfirm.tsx`：FR-027a 编辑高危确认浮层（含受保护提示）+ FR-020 软删除高危确认浮层（含受影响装备者名单，specialist + assistant 本体）；沿用 `request_id + threading.Event + emit` 同步协议（FR-027a / FR-020 / SC-021 / SC-005）
- [X] T032 [US2] 实现 `frontend/src/screens/SkillMethodologyScreen/SkillMethodologyScreen.tsx`：双视图 shell（active 列表视图 + 审计视图占位 toggle）；集成 SkillActiveList + SkillEditor + SkillDangerConfirm（FR-029）
- [X] T033 [US2] 在 `frontend/src/app/routes.tsx` 新增 `/skills/methodology` 路由（方法论 SkillScreen；按 plan.md 路由策略，匹配优先级高于 T016 的 `/skills/*` redirect）；在 `frontend/src/app/NavRail.tsx` **将第 8 屏入口"方法论 / Skill" + 未读 badge 插入到"专员管理"之后**（保持"大脑管理 / 专员管理 / 方法论"三个大脑层资产屏视觉相邻；plan.md 二选一已收敛到此顺位）（FR-033 / plan.md 与现有屏幕的关系）
- [X] T033a [P] [US2] 在 `frontend/src/app/AppShell.tsx`（或对应根组件）启动后调用一次 `GET /api/skills/methodology/bootstrap-status`；当 `fallback_used = true` 时通过既有 toast 系统展示 non-blocking 提示（含 seed_file_path 与"请检查 seed 文件或在 SkillScreen 编辑修复"建议）；订阅 `skill.changed` with `reason = bootstrap_fallback_used` 事件并触发同等 toast；正常 seed 路径不触发（FR-027b / SC-023g）

### 测试（P2 守卫 + 业务层 + Repository + API + 集成）

- [X] T034 [P] [US2] 新增守卫测试 `tests/guardrails/test_skill_no_physical_delete.py`（skill 行三路径阻断：API / Repository / 直连 SQL）、`tests/guardrails/test_skill_origin_closed_enum.py`（5 合法值 + 非法值拒绝 + external_import 本期禁用；断言 FR-042/FR-043 本期只是 origin 锚点，不存在可调用导入 endpoint / DTO，desktop_api 写入 `external_import` 被拒）、`tests/guardrails/test_skill_no_duplicate_name_active.py`（新建模式同名拒绝 / supersede 同名允许 / 编辑改名撞名拒绝）、`tests/guardrails/test_skill_tool_authorization.py`（未在工具白名单内的 specialist 调 `create_skill_methodology` 100% 被工具层鉴权拒绝并返回"无权限"错误；assistant 调度层本体作为默认白名单持有者调用成功；用户在 SpecialistScreen 主动授权某 specialist 后该 specialist 调用成功）（SC-008 / SC-009 / SC-019 / SC-025 / FR-042 / FR-043）
- [X] T035 [P] [US2] 新增守卫测试 `tests/guardrails/test_skill_trigger_conditions_required.py`（空 list / 全空白 string list 拒绝 / required_tools 0 条允许）、`tests/guardrails/test_skill_seed_fail_open.py`（seed 缺失 / 空 / IO 异常三场景 fallback + 自愈逻辑）、`tests/guardrails/test_skill_reference_chain_root_normalize.py`（superseded skill_id 归一化 +1 / soft_deleted 静默跳过 / 同轮去重）、`tests/guardrails/test_skill_load_count_path.py`（工具成功 +1 / 失败不 +1 / 人翻看不 +1）（SC-022 / SC-023 / SC-016 / SC-017）
- [X] T035a [P] [US2] 新增守卫测试 `tests/guardrails/test_skill_sort_filter_semantics.py`，覆盖 SC-015 (a)(b)(c) 后端语义不变量：(a) `/api/skills/methodology` list 端点返回的"排序键集合"与"卡片显示字段集"对齐——4 种排序键（`recently_changed` / `loaded_count` / `referenced_count` / `equipped_count`）皆可在 API 层独立查询，且每张卡片返回三项计数（被加载次数 / 装备者数量 / 被引用执行次数）+ 时间字段全部齐备；(b) **FR-029b 不变量**——构造 skill v1 + v2 supersede 链后，"最近变更时间" = v2 active 版本的 `created_at`；该时间**不**因下列事件刷新：装备关系新增/卸下（FR-014 / FR-014b）、`load_skill_methodology` 工具被调用（loaded_count +1）、reply 元数据 `skills_referenced` 触发的 referenced_count +1；(c) 30 天未引用筛选用的"最近一次被引用执行时间"是与 FR-029b "最近变更时间"独立的字段——构造 `referenced_count` 在 35 天前最后一次 +1 + 今天发生一次内容 supersede 的场景，断言 skill 被"最近 30 天未被引用过"筛选命中（与"最近变更时间"是今天无关）（FR-029a / FR-029b / SC-015）
> **编号说明**：T036 编号空缺，无任务遗失——早期草稿合并到 T034 / T035 后未顺延以避免破坏 SC 映射引用稳定。后续不要把 T037 起的编号下移。

- [X] T037 [P] [US2] 新增 Repository 测试 `tests/data/test_skill_repository.py`（CRUD + chain_root 查询 + same-name active 检查 + 物理 DELETE 被阻断）
- [X] T038 [US2] 新增 Desktop API 测试 `tests/desktop_api/test_skill_methodology_api.py`（P2 端点 list / detail / edit / soft-delete / bootstrap-status 契约）；其中至少一条用例显式断言 **`equipped_count` 口径** = active specialists 装备该 skill 数 + (assistant 本体是否装备 ? 1 : 0)（FR-040 / SC-013 口径校验，覆盖"system_bootstrap 默认只装 assistant 本体的方法论 equipped_count 应为 1 而非 0"）；另一条用例断言 `skill.changed` UI Event payload **不含** `body_markdown` 字段（CC-004）
- [X] T039 [US2] 新增集成冒烟测试 `tests/integration/test_skill_create_flow.py`（P2 端到端：create_skill_methodology 工具 → active 入库 → API list 出现 → user edit → v2 active；显式断言 create→SkillScreen 可见链路在测试时钟/可控 fake LLM 下 ≤30s，编辑保存后 SkillScreen / 版本链 / 受影响装备者视图刷新链路 ≤3s；构造 create 工具失败路径并断言 UI/API 返回明确错误提示而非静默卡住）（SC-002 / SC-003）

**Checkpoint**: P2 独立可交付 — 方法论资产层完整生命周期；内部装备关系桥接已覆盖创建 / 编辑 / 软删除事务，仍缺 P3 的用户可配置装备管理 UI 与 specialist 派活注入

---

## Phase 5: User Story 3 — 装备方法论给 specialist（Priority: P3）

**Goal**: specialist + assistant 本体可装备 active 方法论；派活时 system prompt 注入装备清单条目；`load_skill_methodology` 工具全面可用；token 计量条实时更新

**Independent Test**: SpecialistScreen 能看到 AssistantEquipmentCard + EquipmentPanel；保存后 Foo 的 system prompt 含装备清单条目（无正文）；soft delete 被装备方法论触发阻断弹窗；`uv run pytest tests/guardrails/test_skill_no_body_in_system_prompt.py tests/guardrails/test_skill_dispatch_no_methodology_signal.py -v` 通过

### 业务层

- [X] T040 [P] [US3] 实现 `src/business/brain/skill_equipment_service.py`（`SkillEquipmentService`）：equip / unequip（标 unequipped 不删行）/ 调序 / default_equip_all（新建 specialist 触发；新方法论 active 触发；`system_bootstrap` 例外规则按 **链根 origin** 判定——链根 origin = `system_bootstrap` 的方法论默认快照剔除所有 specialist，仅装备到 assistant 本体；用户**主动**装备过的 `system_bootstrap` 方法论在后续 supersede 时按 FR-011 跟新到新版本、**不**被本例外撤销）/ **supersede 路径同事务内合并三段语义**：(a) 已装备旧版本者切到新版本（FR-011：旧 active 行标 unequipped reason=`supersede_transfer` + 新版本插入对应 active 行）；(b) 未装备旧版本的现有 specialist + assistant 本体按 FR-014a 默认全装备规则追加 active 行（链根 origin = `system_bootstrap` 仅 (b) 段限制为 assistant 本体）；(c) 用户曾主动卸下（reason=`user_unequip`）的关系**不**在 supersede 路径自动复装（与 FR-014a "卸下的关系在该方法论下一次 supersede / 编辑接力时不自动复装"一致）；(d) 崩溃整体回滚 / **FR-018 非 active 装备拒绝**——equip 入参 skill 状态非 `active`（`superseded` / `soft_deleted`）时拒绝并返回错误，由 Service 在写入前校验。本任务上线时 MUST 将 P2 T019a 的内联默认装备传播路径改接为对本 service 的单次调用（或删除重复内联路径），避免 default_equip_all 双实现漂移；T011a bootstrap 期首装保留为迁移特例。等价语义不变（FR-014 / FR-014a / FR-014b / FR-011 / FR-018 / SC-013 / SC-026；依赖 T008 / T019）
- [X] T041 [US3] 把 `src/business/brain/skill_service.py::force_soft_delete` 中 P2 阶段直调 `SkillEquipmentRepository` 的内联裁剪路径**替换**为对 `SkillEquipmentService.force_unequip_all_for_skill()` 的编排层调用（等价语义不变：同事务内标 `unequipped` reason=`force_remove_on_soft_delete` + 方法论落 `soft_deleted`）。本任务是 T019 桥接代码的清理与归位，不引入新行为，与 T019a / T011a 在 P3 上线后回归编排层的同一模式（FR-012 / FR-020 / SC-005；依赖 T040）
- [X] T042 [US3] 更新 `src/business/brain/context_builder.py`：为所有装备者（specialist + assistant 本体）按装备顺序注入装备清单条目段（id + name + description + trigger_conditions YAML list，**不含** body_markdown）；specialist 走已有 `context_builder` 注入路径；同时把本轮 system prompt 装备段快照与后续 `load_skill_methodology` tool result 接入既有调试视图 / agent trace DTO，确保 SC-004 的"可在调试视图查到"有实现落点（FR-017 / SC-004 / SC-018；依赖 T040）
- [X] T043 [US3] 更新 `src/business/brain/specialist_service.py`：新建 specialist 时调 `SkillEquipmentService.default_equip_all(specialist_id)`（FR-014a / SC-013；依赖 T040）
- [X] T044 [US3] 验证 `src/business/agents/tools/skill_methodology_tools.py::load_skill_methodology` handler（T021 已实现 FR-017a 完整契约：装备清单检查 / 拒绝 superseded / soft_deleted / loaded_count +1 / 返回 SKILL.md 形态文本 / 无调用次数硬上限）在 T045 工具注册放开后对 **specialist 装备者**与 **assistant 本体**两类调用方语义同等生效。**本任务无 handler 代码新增**，仅含：(a) 移除 T021 在文件顶部留的 `# TODO(P3)` 标注；(b) 新增装备者类型覆盖单元测试 `tests/business/brain/test_skill_methodology_tools.py::test_load_for_specialist_and_assistant` 断言两类调用方均能成功 load 自己装备的方法论、跨装备者越权调用被拒（FR-017a / FR-017b / SC-024；依赖 T040 / T045）
- [X] T045 [US3] 在工具注册层（`src/business/agents/tools/assistant_tools.py` 或对应框架级工具注册点）把 `load_skill_methodology` 注册为**框架级工具**——工具层默认放行所有装备者调用，**不**写入任何 specialist 或 assistant 的 `tool_whitelist`（与 contracts/tools.md L168 约束对齐：load_skill_methodology 只读、无写入风险，与既有"框架基础工具"模式一致）（FR-017a / FR-025）

### Desktop API 层

- [X] T046 [P] [US3] 在 `src/desktop_api/routers/skills_methodology.py` 添加装备管理端点：`GET /api/specialists/{id}/equipment`（含 missing_required_tools / token_budget_estimate / token_budget_thresholds，其中 thresholds 来自 `get_unified_config()`）/ `PUT /api/specialists/{id}/equipment`（multi-select diff 更新 + 单事务；`_assistant` 特殊标识符处理）；同时补全 soft-delete 端点的装备裁剪集成（contracts/rest-api.md §3；依赖 T040 / T041）
- [X] T047 [US3] 验证装备端点已注册并更新 Desktop API 测试覆盖（`tests/desktop_api/test_skill_methodology_api.py` P3 端点）

### 前端 UI 组件

- [X] T048 [P] [US3] 实现 `frontend/src/components/TokenBudgetMeter.tsx`：token 计量条（装备条目数 + 本地估算 token 数 `ceil(chars/4*1.2)` + 阈值染色）；warn/danger 阈值从 `skillMethodologyStore` 中的装备端点 DTO 读取（默认值只存在后端统一配置与测试 fixture，前端组件不得硬编码 4096/8192）；随勾选/卸下/调序实时更新（不 round-trip）；不阻断保存（FR-016a / SC-020）
- [X] T049 [P] [US3] 实现 `frontend/src/screens/SpecialistScreen/EquipmentPanel.tsx`：方法论装备面板（active 方法论多选 + 拖拽调序 + missing_required_tools 黄色警告 + TokenBudgetMeter）（FR-015 / FR-016 / SC-020；依赖 T048）
- [X] T050 [P] [US3] 实现 `frontend/src/screens/SpecialistScreen/AssistantEquipmentCard.tsx`：assistant 本体装备入口卡片（不可删除不可重命名；点入 EquipmentPanel；`GET /api/specialists/_assistant/equipment`）（FR-015a / SC-013）
- [X] T051 [US3] 更新 `frontend/src/screens/SpecialistScreen/SpecialistScreen.tsx`：顶部插入 AssistantEquipmentCard；每个 specialist 详情页新增 EquipmentPanel tab 与现有白名单面板并列；监听 `skill.equipment.changed` 事件被动刷新（FR-015a / FR-032）
- [X] T052 [US3] 更新 `frontend/src/state/skillMethodologyStore.ts`：添加 equipment CRUD 状态（active_equipment by entity）与 token_budget_thresholds 状态；监听 `skill.equipment.changed` 事件更新装备清单；token 估算值本地计算，阈值来自装备端点 DTO

### 测试（P3 守卫 + 业务 + Repository + 集成）

- [X] T053 [P] [US3] 补全守卫测试 `tests/guardrails/test_skill_no_physical_delete.py`（装备关系行三路径阻断）、新增 `tests/guardrails/test_skill_system_bootstrap_protection.py`（链根传播 + FR-014a 例外）、`tests/guardrails/test_skill_no_body_in_system_prompt.py`（system prompt 不含 body_markdown）、`tests/guardrails/test_skill_load_tool_no_call_limit.py`（单轮多次 load 不被工具层拒绝）、`tests/guardrails/test_skill_dispatch_no_methodology_signal.py`（派活决策路径不读方法论）（SC-008 / SC-013 / SC-014 / SC-018 / SC-024 / SC-026）
- [X] T054 [P] [US3] 新增业务层测试 `tests/business/brain/test_skill_equipment_service.py`（equip / unequip / default_equip_all / system_bootstrap 例外 / supersede 切版本 / **FR-018 非 active 装备拒绝**——构造 status=`superseded` 与 status=`soft_deleted` 两类 skill 各一例，断言 equip 调用被拒并返回错误，不写入装备关系行）；新增 Repository 测试 `tests/data/test_skill_equipment_repository.py`（状态机 / unique partial index / 历史留行 / 双向查询）
- [X] T055 [US3] 新增集成冒烟测试 `tests/integration/test_skill_equip_dispatch_flow.py`（P3 端到端：方法论 active → 自动装备 specialist → specialist 收到 system prompt 装备段 → load_skill_methodology → loaded_count +1；断言调试视图 / agent trace 中可查到该轮 system prompt 装备段快照与 messages 序列中的 `load_skill_methodology` tool result）；新增**CC-003 子断言** `test_equip_change_during_dispatch_does_not_interrupt`：构造 specialist 正在执行一轮派活的中间态（mock agent loop 持有当前轮 system prompt 快照），主线程同步修改该 specialist 装备关系（equip / unequip 各一条），断言 (a) 本轮 agent loop 不抛异常 / 不重建 system prompt；(b) 本轮调用 load_skill_methodology 仍按"派活那一刻冻结的装备清单"鉴权；(c) 下一轮 dispatch 才看到新装备状态（CC-003 / SC-004 / Edge Case "强制移除时受影响专员正在被派活"）

**Checkpoint**: P3 独立可交付 — 方法论资产"派得上用场"

---

## Phase 6: User Story 4 — 方法论修订与溯源（Priority: P4）

**Goal**: supersede 并发 first-writer-wins；版本链回看（完整正文 + diff）；装备关系双向历史审计；素材降权显示

**Independent Test**: assistant 调工具 supersede 后所有装备者 100% 指向新版本（单事务）；审计视图展示完整版本链 + diff；`uv run pytest tests/integration/test_skill_supersede_transaction.py -v` 通过（含并发场景）

### 业务层

- [X] T056 [US4] 实现 `src/business/brain/skill_service.py` 中并发 first-writer-wins 接力逻辑（FR-011a）：后到 supersede 以"当前 active"为新基线接力，最终形成单向无分叉链（X → v_a → v_b → …）；每步单事务；**使用 SQLite `BEGIN IMMEDIATE` 排它锁机制**实现（research.md D10：SQLite 不支持 `SELECT FOR UPDATE`，等价路径为 `BEGIN IMMEDIATE` 在事务起始即获取写锁，并发后到者 `SQLITE_BUSY` → 重试时基线已变 → 自然接力）（FR-011a / SC-006）

### Desktop API 层

- [X] T057 [P] [US4] 在 `src/desktop_api/routers/skills_methodology.py` 添加版本链历史端点 `GET /api/skills/methodology/{id}/history`：返回 chain 所有节点（含完整正文 + `diff_from_previous` unified diff text + `change_reason` 变更原因）（contracts/rest-api.md §1.3 / FR-034 / FR-039）
- [X] T058 [P] [US4] 在 `src/desktop_api/routers/skills_methodology.py` 添加装备审计端点 `GET /api/skills/methodology/{id}/audit-equipment`：返回双向装备历史（含 equipped_at / unequipped_at / unequipped_reason）（contracts/rest-api.md §1.4 / FR-034）

### 前端 UI 组件

- [X] T059 [P] [US4] 实现 `frontend/src/components/SkillDiffView.tsx`：版本间 diff 高亮对比（unified diff 渲染 + 完整正文 / diff 展示切换）（FR-039）
- [X] T060 [P] [US4] 实现 `frontend/src/screens/SkillMethodologyScreen/SkillAuditView.tsx`：版本链时间轴（倒序；每节点含完整正文 + SkillDiffView + origin + 操作者 + 时间 + `change_reason` 变更原因）+ 装备关系历史轨迹（含 unequipped_reason 筛选 tag）+ specialist 反向视图入口（FR-034 / FR-039）
- [X] T061 [US4] 将 SkillAuditView 接入 `frontend/src/screens/SkillMethodologyScreen/SkillMethodologyScreen.tsx` 双视图 toggle（替换 P2 阶段的占位）
- [X] T062 [US4] 在 SkillEditor.tsx / SkillAuditView.tsx 的素材来源列表实现降权显示：segment_status = soft_deleted 时灰显 + 显示 "来源已删除" + 保留 segment_id 与 summary 快照（FR-038 / US4 Acceptance Scenario 2）

### 测试（P4 集成）

- [X] T063 [US4] 新增集成测试 `tests/integration/test_skill_supersede_transaction.py`：(a) FR-011 单事务切换（装备关系全部指向新版本，崩溃回滚）；(b) FR-011a first-writer-wins 并发场景（两路并发 supersede → 单向链 X→v_a→v_b，装备最终全指向 v_b）；(c) **FR-041a 统计沿链继承**：supersede 接力后新版本的 `loaded_count` / `referenced_count` / `last_referenced_at` 完整继承自旧版本基线值，并在此基础上继续累计（构造 v1 有非零计数 → supersede 出 v2 → 断言 v2 计数 = v1 旧值 → 再 +1 → 断言 v2 计数 = v1 旧值 + 1）；(d) history / audit 查询返回每个版本节点的 `change_reason`，且用户编辑 / assistant 工具 supersede 两类来源均可回看原因文本（SC-006 / FR-011 / FR-011a / FR-034 / FR-041a）

**Checkpoint**: P4 独立可交付 — 方法论资产生命周期全闭环

---

## Phase 7: Polish & 跨切面事项

**Purpose**: 文档同步 + 前端测试 + 最终验证

- [X] T064 [P] 更新 `docs/ARCHITECTURE.md`：方法论资产层描述、v12 表结构、`skill.*` 事件契约、`load_skill_methodology` 工具 result 进 messages 模式（plan.md Constitution Check V）
- [X] T065 [P] 更新 `docs/PROJECT_CONSTRAINTS.md`：方法论数据安全边界（永不物理删除 + 装备关系同等）、`brain.skill.*` 配置占位符、`skills.* → tools.*` 改名约定（plan.md Constitution Check V）
- [X] T066 [P] 同步更新 `frontend/AGENTS.md` + `frontend/CLAUDE.md` + `frontend/GEMINI.md`（三文件内容保持一致）：SkillMethodologyScreen 新增、Tool 改名、TokenBudgetMeter 约束、装备清单注入不含正文（CLAUDE.md §必须遵守的全局硬规则 / AI 入口同步规则）
- [X] T067 [P] 同步更新 `src/AGENTS.md` + `src/CLAUDE.md` + `src/GEMINI.md`（三文件内容保持一致）：SkillService / SkillEquipmentService / SkillBootstrapService 三项约束 + `load_skill_methodology` 默认全装备约束 + 派活不读方法论约束（CLAUDE.md §AI 入口同步规则）
- [X] T068 [P] 更新根目录 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` Recent Changes 区段：添加 012 feature 条目（v12 tables / skill.* 事件 / SkillScreen / Tool 改名 / 装备清单注入）（CLAUDE.md §AI 入口同步规则）
- [X] T069 [P] 新增前端单元测试：`frontend/tests/unit/skill-methodology-store.test.tsx`（store CRUD + sort/filter + 未读 badge + token_budget_thresholds 从 API DTO 入 store）+ `frontend/tests/unit/token-budget-meter.test.tsx`（估算公式 + 使用 mock thresholds 的阈值染色，断言组件不内置 4096/8192 常量）+ `frontend/tests/unit/skill-editor.test.tsx`（字段校验 + 撞名阻断 + list editor 交互）
- [X] T070 新增前端 E2E 测试 `frontend/tests/e2e/skill-methodology.spec.ts`：覆盖 4 个 user story 主要冒烟路径（P1 导航文案 / P2 创建+编辑 / P3 装备+计量条 / P4 版本链审计，含版本节点 `change_reason` 展示）；**含 Edge Cases 中前端可验证子集**：(i) 同名 active 撞名时编辑器保存被阻断并显示已占用 id 链接（FR-024a / FR-031）；(ii) token 计量条三段染色阈值使用测试后端 / mock API 下发的 4096 黄 / 8192 红，随勾选实时变化（FR-016a / SC-020）；(iii) 受 FR-027a 保护的方法论卡片**不显示**"软删除"按钮（FR-027a / spec User Story 2 Acceptance 6）；(iv) SpecialistScreen 不存在"对某 specialist 直接下创建方法论指令"入口（FR-022 / CC-002 UI 层兜底）；(v) **Tool 三屏（Teaching / List / Composition）现有 e2e 回归套件 100% 通过**——本任务 MUST 显式跑既有 `frontend/tests/e2e/tool-*.spec.ts`（或同等命名的旧 Skill e2e 套件，已经过 P1 文案改名）确认录制/编辑/list/composition 业务行为不因命名整顿回归（FR-001 / CC-005 / SC-007）
- [X] T071 按 `specs/012-skill-methodology-layer/quickstart.md` 验证脚本逐节手动验证（P1→P4），修复发现的回归问题

---

## Phase 8: 工具池重构（Scope Amendment 2026-06-01）

**Purpose**: 将内置工具并入工具列表"已掌握"分类，移除 BrainScreen 中的独立工具池面板（详见 spec.md §Scope Amendment）

- [X] T072 [P] 提取公开常量：新建 `src/business/brain/builtin_tools.py`，将 `specialist_service.py` 中的私有 `_BUILTIN_TOOL_CATALOG` 提取为公开 `BUILTIN_TOOL_CATALOG`；`specialist_service.py` 改为 import 引用
- [X] T073 后端：`skills_service.py` 新增 `_builtin_summaries()` 静态方法，`get_category("published")` 与 `get_all_categories()` 在已掌握列表头部追加内置工具条目（`is_builtin: True`）；`src/desktop_api/schemas.py` 的 `ToolSummary` 新增 `is_builtin: bool = False` 字段（不加则 FastAPI 序列化过滤该字段，前端永远收到 `undefined`）
- [X] T074 [P] 前端：`frontend/src/api/skills.ts` 的 `SkillSummary` 新增 `is_builtin?: boolean`；`SkillCards.tsx` published 视图中 `is_builtin` 为 true 的卡片显示"内置" badge、隐藏删除和试用按钮、不显示成功次数；用户自建已掌握卡片保持原有操作
- [X] T075 [P] 前端：`BrainScreen.tsx` 移除 `SkillPoolPanel` import 与渲染，移除 `skillPool / loadingSkillPool / removeSkill / pendingSkillRemoval / clearPendingSkillRemoval` state 绑定与 `loadSkillPool` useEffect 调用（`brainStore` 中对应状态保留供 `SpecialistScreen` 复用）；修复 `SpecialistScreen` 搜索框在无数据时高度撑满的 CSS 问题（`.specialist-list-pane .brain-search { flex: none }`）
- [X] T076 [P] 文档：`docs/ARCHITECTURE.md` 路由表移除 `/brain` 的"skill-pool 管理"、补充 `brainStore` 的 skill-pool 状态供 `SpecialistScreen` 复用说明

---

## 依赖关系与执行顺序

### Phase 依赖

- **Phase 1 (Setup)**: 无依赖，立即可开始（T001-T002 可并行）
- **Phase 2 (Foundational)**: 依赖 Phase 1 完成；T006 依赖 T007/T008/T009；T007/T008 可并行；T009 依赖 T007；T011a 依赖 T008 / T009 **BLOCKS 所有 US**
- **Phase 3-6 (US1-US4)**: 依赖 Phase 2 全部完成；US1 与 US2/US3/US4 可并行进行（若有人力）
- **Phase 7 (Polish)**: 依赖所需 US 完成

### US 内依赖

- Phase 2 内：T005 → T006 / T007 → T009 → T006 → T011 → T011a（依赖 T008 / T009）
- Phase 3 (US1)：T012/T013/T014/T015/T016/T017 可并行；T018 (守卫测试) 依赖 T012-T017 完成
- Phase 4 (US2)：T019/T020/T022/T026/T027/T028 可并行；T019a 依赖 T008 / T019；T021 依赖 T019；T023 依赖 T019；T024 依赖 T010/T019；T029/T030 依赖 T028；T032 依赖 T029/T030/T031；T033 依赖 T032；T033a 依赖 T024（bootstrap-status 端点）+ T026（store）；T035a 依赖 T019（SkillService）+ T020（SkillReferenceCounterService）+ T024（list 端点）
- Phase 5 (US3)：T040 依赖 T008/T019；T041 依赖 T040；T042/T043/T044 依赖 T040；T048/T049/T050 可并行；T051 依赖 T049/T050；T052 依赖 T049
- Phase 6 (US4)：T056 依赖 T019；T057/T058 可并行（依赖 T056）；T059/T060 可并行；T061 依赖 T060

### 并行示例（Phase 2 Foundational）

```
同时启动（无依赖）：
  T003: 新增 blinker 事件（src/utils/events.py）
  T004: 新增 UI Event Registry 条目（src/desktop_api/ui_events.py）
  T005: 新增 ORM 模型（src/data/models_sqlite.py）
  T010: 新增 DTO schemas（src/desktop_api/schemas.py）

T005 完成后并行：
  T007: SkillRepository（依赖 T005 ORM 模型）
  T008: SkillEquipmentRepository（依赖 T005 ORM 模型）

T007 完成后：
  T009: SkillBootstrapService（依赖 T007）

T007/T008/T009 完成后：
  T006: migrate_to_v12（依赖 T007/T008/T009）
  T011: 验证 migration 接线
  T011a: bootstrap 期为 assistant 本体首装"如何创建方法论"（依赖 T008/T009）
```

---

## 实现策略

### MVP 优先（仅 US1）

1. 完成 Phase 1 + Phase 2（Foundation）
2. 完成 Phase 3（US1 术语腾位）
3. **STOP AND VALIDATE**：SC-001 / SC-007 / SC-011 / SC-012 通过
4. 可独立发布版本

### 增量交付

1. Setup + Foundational → 基础就绪
2. US1 → 术语整顿完毕（独立发布）
3. US2 → 方法论可创建 + 编辑（独立发布）
4. US3 → 方法论可装备 + 派活生效（独立发布）
5. US4 → 修订 + 溯源全闭环（最终发布）

---

## 统计

| 维度 | 数值 |
|------|------|
| 总任务数 | 79（追加 T011a bootstrap 期 assistant 本体首装 + T019a P2 阶段新建期默认全装备桥接，弥合 P2/P3 边界；T036 编号空缺不计入任务数；T072–T076 工具池重构补入） |
| Phase 1 (Setup) | 2 |
| Phase 2 (Foundational) | 10 |
| Phase 3 (US1) | 7 |
| Phase 4 (US2) | 23 |
| Phase 5 (US3) | 16 |
| Phase 6 (US4) | 8 |
| Phase 7 (Polish) | 8 |
| Phase 8 (工具池重构) | 5 |
| 可并行任务 [P] | 47（Phase 1: 2 / Phase 2: 6 / US1: 6 / US2: 12 / US3: 7 / US4: 4 / Polish: 6 / 工具池重构: 4） |
| 守卫测试任务 | 14 个文件（T018/T034/T035/T035a/T053 覆盖；含 SC-015 后端语义 + SC-009 工具白名单鉴权两个新文件） |
| 集成测试任务 | 3 个文件（T039/T055/T063） |
| 前端测试任务 | 4 个文件（T069/T070） |

### SC 覆盖映射

| SC | 任务 |
|----|------|
| SC-001,011,012 | T018 |
| SC-002 端到端 ≤30s | T039（集成冒烟 + 30s 计时 + 失败提示）|
| SC-003 编辑后 ≤3s 一致状态 | T039（集成计时）/ T026（store 被动刷新）|
| SC-004,018 | T042/T053/T055（含调试视图 / trace 可观测断言） |
| SC-005,020,021 | T024/T031/T041/T053 |
| SC-006 | T040/T056/T063 |
| SC-007 Tool 业务不回归 | T015/T070(v) |
| SC-008,026 | T034/T053 |
| SC-009 工具白名单鉴权 | T021/T034（含 `test_skill_tool_authorization.py`） |
| SC-010 | T021/T035 |
| SC-013 | T011a/T019a（P2 桥接）/T040/T043/T053；口径校验 T038 |
| SC-014 | T053 |
| SC-015 4 种排序 + FR-029b 后端语义 | T029（前端实现）/T035a（后端守卫）/T069（前端单元） |
| SC-016 | T020/T035 |
| SC-017 | T021/T035 |
| SC-019 | T034 |
| SC-022 | T021/T035 |
| SC-023 | T009/T035；前端 toast T033a |
| SC-024 | T044/T053 |
| SC-025 | T034 |
| FR-005 词义守卫 | T018(e) |
| FR-018 非 active 装备拒绝 | T040/T054 |
| FR-022 UI 入口阻断 | T070(iv)（**约定为唯一路径**——SpecialistScreen 无"对 specialist 直接下创建方法论指令"入口；后端无独立守卫，因为 spec.md FR-022 / CC-002 已把"必经 assistant 对话路径"约束固化在 UI 层 + 工具白名单层，结合 T034 工具白名单鉴权天然兜底）|
| FR-026 LLM 引导（SHOULD） | T023（assistant prompt 末段 SHOULD 段）/T001（seed 正文）|
| FR-027a 高危确认协议 | T024 |
| FR-027b 前端 toast | T033a |
| FR-029b 最近变更时间定义 | T029/T035a |
| FR-034 审计视图变更原因 | T057/T060/T063/T070 |
| FR-040 装备者数量口径 | T038 |
| FR-041a 沿链继承 | T063(c) |
