# Implementation Plan: Skill Methodology Layer

**Branch**: `012-skill-methodology-layer` | **Date**: 2026-05-27 | **Spec**: [spec.md](./spec.md) | **Status**: Completed
**Input**: Feature specification from `specs/012-skill-methodology-layer/spec.md`

**Bugfix**: 2026-05-28 — ANALYZE-001 Updated from analysis patch: unified v12 table naming with data-model/tasks and clarified token budget thresholds flow through UnifiedConfig.

**Bugfix**: 2026-05-28 — ANALYZE-002 Updated from analysis follow-up: added config template coverage, aligned P2 equipment bridge scope, removed repository naming drift, and included audit change reasons.

---

## Summary

为助理大脑（010 上线）新增一层**方法论资产**：与 specialist 平级、可被 assistant 本体与 specialist 装备的"做某件事时遵循的步骤"。同时把现有 UI 上的"工具技能"术语整体改名为 "Tool"，把 "Skill" 词位让给方法论。

实现路径：(1) 新增大脑 SQLite 表 `brain_skills` / `brain_skill_source_segments` / `brain_skill_equipment`（v12 migration，与 data-model.md 保持一致）；(2) 业务层新增 `SkillService`（生命周期、supersede、强制裁剪、`system_bootstrap` 例外、装备者数量口径）、`SkillEquipmentService`（N:M 装备 + 状态机留行）、`SkillReferenceCounterService`（`skills_referenced` 同构 reply 元数据计数 + supersede 链根归一化）、`SkillBootstrapService`（seed 文件读取 + fail-open fallback）；(3) Agent 工具新增 `create_skill_methodology` / `load_skill_methodology`，前者默认仅装备给 assistant 本体；(4) Assistant / specialist system prompt 在派活时按装备顺序注入"轻量清单条目"（id + name + description + trigger_conditions list，**不含正文**），正文走 `load_skill_methodology` 工具按需拉入 messages 序列；(5) 前端新增 SkillScreen（双视图：active 列表 + 审计视图 + 编辑器）、SpecialistScreen 顶部 Assistant 本体装备卡片、各装备面板 token 计量条、SkillScreen 卡片三项计数 + 4 种排序 + 2 类筛选；(6) UI 文案/路由/事件名整体 `skills.*` → `tools.*` 改名，无 deprecation 窗口；新增 `skill.*` 事件契约面向新方法论资产；(7) 守卫测试覆盖 26 项 SC（含装备关系永不物理删除、`origin` 封闭枚举三层校验、`system_bootstrap` 链根例外、supersede 链根 asset id 归一化、token 计量条阈值、seed fail-open 三场景等）。

按 P1（命名腾位）→ P2（创建 + 编辑闭环）→ P3（装备给 specialist）→ P4（修订与溯源）四个用户故事增量交付，每阶段独立可验证。

---

## Technical Context

**Language/Version**: Python 3.12（运行时）、TypeScript 5+、React 18、Rust stable
**Primary Dependencies**: FastAPI、SQLAlchemy（自定义 migration）、blinker、LangChain（assistant 现有模型池）、Tauri 2、Zustand、Vite、pytest、Vitest、Playwright
**Storage**: SQLite 大脑命名空间（`brain_skills` / `brain_skill_source_segments` / `brain_skill_equipment`）；DuckDB 不涉及；Seed 文件作为静态资源随包发布（`src/business/brain/seed/how_to_create_skill_methodology.md`）
**Testing**: pytest（业务层 / Repository / 集成 / 守卫）、Vitest + React Testing Library（前端单元）、Playwright（前端 E2E）
**Target Platform**: Windows 桌面应用（Tauri 2 + Python FastAPI sidecar）
**Project Type**: Desktop app（Tauri shell + Python sidecar + React UI）
**Performance Goals**: 装备清单条目注入到 system prompt 的总 token 量随当前装备者实际装备数线性增长，方法论正文一律不进 system prompt；`load_skill_methodology` 工具 result 进入 messages 序列后由 010 既有压缩机制兜底；SkillScreen 三项计数 + 4 种排序前端基于已下发数据本地排序，不要求每次切排序回 backend round-trip
**Constraints**:
- **CC-001 / FR-014b**: 方法论行与装备关系行**永不物理删除**——所有删除路径走 status 字段
- **CC-002**: 100% 调度约束保留——不引入"skill 工匠"专员，所有创建路径必经 assistant 对话
- **CC-003**: 装备关系修改对正在执行的派单轮不生效，最快下一轮派单生效
- **CC-004**: 面向前端的事件必须经 UI Event Registry 注册；payload 不含方法论正文全文
- **CC-006**: `skills.*` → `tools.*` 改名为直接切换无 deprecation 窗口（依据：本产品单用户未发布无外部脚本消费者）
- 单事务原子性：supersede / 强制软删除 / 用户编辑接力的"旧版本→superseded + 新版本→active + 装备关系切换 + 装备关系旧行标 `unequipped` + 装备关系新行插入"必须全部在同一 SQLAlchemy 事务内完成；崩溃整体回滚
**Scale/Scope**: 单用户、单大脑；预期 active 方法论数量量级在 10² 内（用户手编 + assistant 提炼）；每个装备者（assistant 本体 + 当前已建 specialist）默认全装备；装备关系总行数约为"装备者数 × 方法论数"（含历史 unequipped 留行），仍在 SQLite 可承受范围

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门卫问题 | 证据 |
|------|---------|------|
| **I. 分层边界与事件协调** | 是否保持 `UI → business → execution → data` 方向？跨模块通知是否走 `events.py`？ | **通过**。新增链路：`SkillScreen → /api/skills/methodology/* → SkillService → SkillRepository → SQLite`；`SpecialistScreen 装备面板 → /api/specialists/{id}/equipment → SkillEquipmentService`。新 blinker 事件全部在 `src/utils/events.py` 集中定义（`brain_skill_changed` / `brain_skill_equipment_changed` / `brain_skill_supersede_completed`）。面向前端的事件按 UI Event Registry 公开契约新增 `skill.changed` / `skill.equipment.changed`，并把现有 `skills.changed` 改名为 `tools.changed`。`desktop_api/routers/skills.py`（Tool 视角）保留，对应 Tool 域；新增 `desktop_api/routers/skills_methodology.py`（方法论域）作为 Skill 视角入口。`desktop_api` 仅做 DTO/event 适配，不直接读写 SQLite。无上调依赖。 |
| **II. 数据边界与持久化纪律** | SQLite/DuckDB 职责是否清晰？Repository 边界是否保留？`network_requests` 读取边界是否守住？ | **通过**。所有方法论数据走 SQLite（大脑命名空间）；DuckDB 完全不涉及（`network_requests` 边界无变化）。新增 `SkillRepository` + `SkillEquipmentRepository`；业务代码不直接拼 SQL。v12 migration 一次性建全三张表 + 索引 + unique partial index（"每对 (装备者, skill) 至多 1 行 active 装备"）+ CHECK 约束（`status` / `origin` / 装备关系 `status` 三处封闭枚举）。Bootstrap"如何创建方法论"由 migration 末尾的"读取 seed 文件 + fail-open fallback"步骤插入。Schema 与 010 v11 同风格。 |
| **III. 统一配置与密钥安全** | 新配置是否走 `UnifiedConfigManager`？密钥安全？ | **通过**。新增配置占位符：`brain.skill.token_budget.warn_threshold`（默认 4096）、`brain.skill.token_budget.danger_threshold`（默认 8192）、`brain.skill.seed_file_path`（默认 `src/business/brain/seed/how_to_create_skill_methodology.md`）。阈值由后端通过 `get_unified_config()` 读取，并随装备端点 DTO 下发给前端；前端只消费 DTO，不硬编码阈值。配置默认值同步到 `src/data/unified_config.py`，配置模板同步到 `config.example.json` / `config.example.comments.md`。无新密钥字段。 |
| **IV. 可验证交付** | 确定性逻辑是否有自动化测试？架构接线替换是否有冒烟/门卫测试？ | **通过**。规划测试矩阵 26 项 SC 全部映射到 `tests/guardrails/test_skill_*` 守卫测试 + `tests/business/test_skill_*` 单元 + `tests/integration/test_skill_*` 集成 + `frontend/tests/unit/skillStore.test.ts` + `frontend/tests/e2e/skill-methodology.spec.ts`。重点门卫：(a) 物理 DELETE 阻断三路径（SC-008、SC-026）；(b) `origin` 封闭枚举三层校验（SC-025）；(c) 装备清单注入 system prompt 时 100% 不含正文（SC-018）；(d) supersede 链根归一化（SC-016）；(e) 派活决策路径不读方法论（SC-014）。 |
| **V. 活文档与规格驱动交付** | 活文档是否识别待更新？临时材料是否在 `docs/local/`？ | **通过**。需更新：`docs/ARCHITECTURE.md`（方法论资产层、v12 表、`skill.*` 事件、`load_skill_methodology` 工具 result 进 messages 的模式）；`docs/PROJECT_CONSTRAINTS.md`（方法论资产数据安全边界 + `brain.skill.*` 配置占位符 + `skills.* → tools.*` 改名）；`frontend/AGENTS.md` 镜像（SkillScreen 新增、Tool 改名、token 计量条约束）；`src/AGENTS.md` 镜像（`SkillService` / `SkillEquipmentService` / `SkillBootstrapService` 三项约束 + `load_skill_methodology` 工具默认全装备约束）。脑暴文档 `docs/local/todo/*-skill-methodology-layer.md` 已 gitignore 不入版本库，是本地状态。 |

所有门卫通过，无需填写 Complexity Tracking。

---

## Project Structure

### Documentation (this feature)

```text
specs/012-skill-methodology-layer/
├── plan.md              # 本文件（/speckit-plan 输出）
├── research.md          # Phase 0 输出（NEEDS CLARIFICATION 解析 + 技术选型）
├── data-model.md        # Phase 1 输出（三张表 + 状态机 + 索引）
├── quickstart.md        # Phase 1 输出（4 个 user story 验收脚本）
├── contracts/
│   ├── rest-api.md      # Phase 1：方法论 REST API + 装备 REST API 契约
│   ├── tools.md         # Phase 1：create_skill_methodology / load_skill_methodology 工具 schema
│   ├── events.md        # Phase 1：blinker + UI Event Registry 事件契约
│   └── reply-metadata.md # Phase 1：skills_referenced 元数据 schema（复用 memory_entries_referenced 同构契约）
└── tasks.md             # Phase 2 输出（/speckit-tasks 命令生成，不由 /speckit-plan 创建）
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── app/
│   │   ├── routes.tsx                    # 改：skills→tools 文案；新增 /skills 方法论路由（与原 /skills 旧路径以 redirect 兼容）
│   │   └── NavRail.tsx                   # 改：badge 复用现有未读提示；新增 Skill 方法论入口未读 badge
│   ├── api/
│   │   ├── skills.ts                     # 改：保留旧 /api/skills（Tool 域）路径与 DTO，文案改 Tool；新增 skillsMethodology client
│   │   └── skillsMethodology.ts          # 新增：方法论 REST API client（list / detail / edit / soft_delete / equip）
│   ├── components/
│   │   ├── SkillCard.tsx                 # 新增：方法论卡片（三项计数 + 同名标签 N/A 因业务层已阻断）
│   │   ├── TokenBudgetMeter.tsx          # 新增：装备面板 token 计量条（健康/警示/危险三段染色 + 本地估算）
│   │   └── SkillDiffView.tsx             # 新增：版本链 diff 高亮对比（FR-039）
│   ├── screens/
│   │   ├── skills/                       # 现有"Tool" 屏（原 Skill List）；文案改 Tool；行为保留
│   │   │   └── *.tsx
│   │   ├── teaching/                     # 现有 Tool Teaching；文案改 Tool
│   │   ├── compositions/                 # 现有 Tool Composition；文案改 Tool
│   │   ├── SkillMethodologyScreen/       # 新增：方法论 SkillScreen（双视图 active 列表 + 审计 + 编辑器）
│   │   │   ├── SkillMethodologyScreen.tsx
│   │   │   ├── SkillActiveList.tsx       # 4 种排序 + 2 类筛选 + 三项计数显示
│   │   │   ├── SkillAuditView.tsx        # 装备关系历史轨迹 + 版本链
│   │   │   ├── SkillEditor.tsx           # 五字段编辑器（trigger/required tools 用 list editor）
│   │   │   └── SkillDangerConfirm.tsx    # FR-027a 编辑高危确认浮层 + FR-020 软删除高危确认浮层
│   │   └── SpecialistScreen/
│   │       ├── SpecialistScreen.tsx      # 改：顶部固定"Assistant 本体"装备卡片
│   │       ├── EquipmentPanel.tsx        # 新增：装备方法论面板（多选 + 排序 + token 计量条 + 所需工具警告）
│   │       └── AssistantEquipmentCard.tsx # 新增：assistant 本体装备入口
│   └── state/
│       ├── skillsStore.ts                # 改：保留 Tool 域字段；命名空间隔离
│       └── skillMethodologyStore.ts      # 新增：方法论列表 / 排序键 / 筛选 / 编辑草稿 / 装备关系
└── tests/
    ├── unit/
    │   ├── skill-methodology-store.test.tsx
    │   ├── token-budget-meter.test.tsx
    │   └── skill-editor.test.tsx
    └── e2e/
        └── skill-methodology.spec.ts     # 4 个 user story E2E 冒烟

src/
├── business/
│   ├── agents/
│   │   ├── prompts/
│   │   │   ├── assistant_prompt.py       # 改：装备者 system prompt 注入装备清单条目段（id + name + description + trigger_conditions list，YAML list 形态）
│   │   │   └── specialist_prompt_builder.py  # 改：同上
│   │   └── tools/
│   │       ├── assistant_tools.py        # 改：reply_to_user 工具 schema 新增 skills_referenced 字段
│   │       └── skill_methodology_tools.py # 新增：create_skill_methodology + load_skill_methodology 工具定义 + handler
│   ├── brain/
│   │   ├── seed/
│   │   │   └── how_to_create_skill_methodology.md  # FR-027 seed 文件（含判重义务 + load 节制义务 + 素材 zone 限制 + 字段必填说明）
│   │   ├── skill_service.py              # 新增：SkillService（CRUD + 状态机 + supersede + 强制裁剪 + system_bootstrap 例外）
│   │   ├── skill_equipment_service.py    # 新增：装备 N:M + 状态机留行 + 默认全装备传播 + 装备者数量口径
│   │   ├── skill_reference_counter.py    # 新增：reply 元数据 skills_referenced +1 + supersede 链根归一化
│   │   ├── skill_bootstrap_service.py    # 新增：seed 文件读取 + fail-open fallback + auto-supersede 修复路径
│   │   ├── context_builder.py            # 改：把装备清单条目段注入装备者 system prompt（FR-017）
│   │   └── specialist_service.py         # 改：新建 specialist 时通过 SkillEquipmentService 默认全装备
├── data/
│   ├── migrations.py                     # 新增 migrate_to_v12()
│   ├── models_sqlite.py                  # 新增三张表的 ORM 模型 + 封闭枚举（origin / status / equipment status）
│   └── repos/
│       ├── skill_repository.py           # 新增：Skill + SkillVersion CRUD + 链根 origin 查询 + 同名 active 检查
│       └── skill_equipment_repository.py # 新增：装备关系状态机 + unique partial index + 双向历史查询
├── desktop_api/
│   ├── routers/
│   │   └── skills_methodology.py         # 新增：/api/skills/methodology/* + /api/specialists/{id}/equipment 路由
│   ├── ui_events.py                      # 改：skills.changed → tools.changed；新增 skill.changed / skill.equipment.changed
│   └── schemas.py                        # 新增：SkillSummary / SkillDetail / SkillEquipmentItem / TokenBudgetThresholds DTO
└── utils/
    └── events.py                         # 新增 brain_skill_changed / brain_skill_equipment_changed / brain_skill_supersede_completed

tests/
├── business/
│   └── brain/
│       ├── test_skill_service.py
│       ├── test_skill_equipment_service.py
│       ├── test_skill_reference_counter.py
│       └── test_skill_bootstrap_service.py
├── data/
│   ├── test_skill_repository.py
│   └── test_skill_equipment_repository.py
├── desktop_api/
│   └── test_skill_methodology_api.py
├── guardrails/
│   ├── test_skill_no_physical_delete.py            # SC-008 + SC-026
│   ├── test_skill_origin_closed_enum.py            # SC-025 三层校验
│   ├── test_skill_system_bootstrap_protection.py   # SC-013 / FR-027a 链根传播 / FR-014a 例外
│   ├── test_skill_no_body_in_system_prompt.py      # SC-018
│   ├── test_skill_dispatch_no_methodology_signal.py # SC-014（派活不读方法论）
│   ├── test_skill_no_duplicate_name_active.py      # SC-019 唯一硬约束
│   ├── test_skill_trigger_conditions_required.py   # SC-022
│   ├── test_skill_load_tool_no_call_limit.py       # SC-024
│   ├── test_skill_reference_chain_root_normalize.py # SC-016
│   ├── test_skill_load_count_path.py               # SC-017
│   ├── test_skill_seed_fail_open.py                # SC-023 三场景
│   └── test_skill_tools_terminology_rename.py      # SC-001 / SC-011 / SC-012
└── integration/
    ├── test_skill_create_flow.py                   # P2 端到端冒烟
    ├── test_skill_equip_dispatch_flow.py           # P3 端到端冒烟
    └── test_skill_supersede_transaction.py         # P4 + FR-011 / FR-011a 单事务 + first-writer-wins
```

**Structure Decision**: 新增 `src/business/brain/skill_*.py` 三个 service + 一个 seed 目录承载所有方法论业务逻辑，复用 010 已有的 `src/business/brain/` 目录结构（与 `specialist_service.py` / `context_builder.py` 并列），不在 `src/business/services/` 下增加新文件以避免脑相关代码散落。前端新增 `screens/SkillMethodologyScreen/` 与 010 的 `BrainScreen/` / `SpecialistScreen/` 对称组织。守卫测试集中放 `tests/guardrails/`，按 SC 编号一一对应。

---

## 与现有屏幕的关系

本 feature 是 010 完成后的演进，与既有屏幕的边界如下：

- **现有"Skill"三屏（Teaching / List / Composition）改名为 Tool**：屏幕代码仍住在 `frontend/src/screens/skills/`、`teaching/`、`compositions/` 目录（不重命名目录以减少 diff 噪音和 PR 风险），所有面向用户的导航文案、屏内标题、按钮、空态、提示都改为 Tool 系列。
- **前端路由策略**（FR-002 / SC-011 / spec User Story 1 与 User Story 2 共存的唯一一致路由表）：
  - Tool 三屏新路径：`/tools/list`（原 Skill List）、`/tools/teaching`（原 Skill Teaching）、`/tools/compositions`（原 Skill Composition）
  - 旧路径 redirect：`/skills`、`/skills?category=...`、`/skills/teaching`、`/skills/compositions` 等所有 `/skills` 前缀且**非** `/skills/methodology` 子路径 → 通过 `routes.tsx` 内 redirect 到对应的 `/tools/*` 新路径（FR-002 / SC-011）
  - 方法论 SkillScreen 新路径：`/skills/methodology`（独立子路径，与 Tool 三屏 redirect 不冲突；spec User Story 1 末段"Skill"词位让给方法论的物理实现）
  - 路由 redirect 顺序：`routes.tsx` 内匹配优先级 `/skills/methodology` > `/skills/*` redirect to `/tools/*`
- **新方法论 SkillScreen 入口**：在 NavRail 新增"方法论"入口（label "方法论 / Skill"，shortLabel "方法论"），不挤掉现有的"AI 助手 / 教学 / 工具 / 组合 / 大脑管理 / 专员管理 / 应用设置"7 屏，而是作为第 8 屏插入"专员管理"之后或并列于"大脑管理"。
- **SpecialistScreen 增强**：保留现有专员管理能力（列表/新建/编辑/版本历史/白名单），顶部插入 Assistant 本体装备卡片；每个 specialist 的详情页新增"装备方法论"面板（与白名单面板并列），不改原有面板。
- **大脑管理 BrainScreen**：不接入方法论资产；分区列表与方法论资产分离展示，避免用户混淆"分区条目"与"方法论"两种资产形态。
- **现有 `skills.*` UI 事件**：整体改名为 `tools.*`，前端 store / 后端 emit / UI Event Registry 三处一次性切换；不留双发兼容层。

---

## 分阶段交付计划

### Phase P1：术语腾位（"Skill" 三屏改名为 Tool）

**目标**: 把"Skill" 词位让给方法论，避免后续 P2 引入方法论时与现有"Skill 三屏"撞名。

**范围**:
- 前端：`routes.tsx` 三屏的 label / shortLabel 改 Tool；`SkillListScreen` / `TeachingScreen` / `CompositionListScreen` 屏内标题、按钮、空态文案改 Tool；NavRail badge label 改 Tool；一次性"已改名"提示组件 + 持久化（localStorage 或 settingsStore）
- 后端 / desktop API：`skills.changed` UI 事件改 `tools.changed`；events.py blinker `skills_changed` 改 `tools_changed`；emit 调用点同步切换；UI Event Registry 一次性下线 `skills.changed`，无双发窗口
- 路由兼容：`/skills` 旧路径 redirect 到新位置（如果有用户书签依赖）；redirect 在 `routes.tsx` 处理，不引入新的 router
- 守卫测试：`test_skill_tools_terminology_rename.py` 断言旧名 100% 下线、新名 100% 上线

**验证**: SC-001（30 秒内识别改名）、SC-007（业务功能不回归）、SC-011（旧 `/skills` 类路由 100% redirect 不返回 404）、SC-012（旧 `skills.*` 通知名 100% 下线）

**独立可交付**：P1 完成时即可发布版本——它不依赖方法论资产存在，纯粹是文案 + 事件 + 路由整顿。

---

### Phase P2：通过 assistant 创建方法论 + 编辑闭环

**目标**: 方法论资产层从 0 到 1，用户可在对话里说"把刚才那套做成方法论"，assistant 直接调工具入库 active；可在 SkillScreen 上编辑、软删除。

**范围**:
- 数据层：v12 migration（三张表 + 索引 + unique partial index + CHECK 约束）；`SkillRepository`（包含版本链查询 / 链根遍历）；~~`SkillVersionRepository`~~（ANALYZE-002：版本链职责收敛到 `SkillRepository`，避免新增未规划仓储）
- 业务层：`SkillService`（状态机、`origin` 封闭枚举、同名 active 拒绝、supersede + 装备关系切换单事务、强制软删除流程在 P2 通过 `SkillEquipmentRepository` 桥接完整裁剪，P3 再归位到 `SkillEquipmentService` 编排层）；`SkillBootstrapService`（seed 文件读取 + fail-open fallback + 应用启动时插入"如何创建方法论"）；`SkillReferenceCounterService`（reply 元数据 `skills_referenced` 字段 +1 + 链根归一化）
- Agent 工具：`create_skill_methodology`（新建 + supersede 两种模式 + ≥1 条素材来源约束 + ≥1 条 trigger_conditions 约束 + 同名 active 拒绝 + supersede 路径不查重）；默认仅装备给 assistant 本体；`load_skill_methodology` 工具实现完整 FR-017a 契约，P2 阶段默认装备仅限 assistant 本体（仅用于查看自己装备的"如何创建方法论"内置方法论作为创建指引；P3 T044/T045 才向所有装备者放开默认装备）；assistant_tools.py 的 `reply_to_user` schema 新增 `skills_referenced` 字段
- API: `/api/skills/methodology/list`（active 列表 + 排序 + 筛选）、`/api/skills/methodology/{id}`（detail）、`/api/skills/methodology/{id}/edit`（用户编辑 → supersede 接力，普通方法论无 UI 确认，`system_bootstrap` 链根需高危确认）、`/api/skills/methodology/{id}/soft-delete`（走高危确认 + 装备关系裁剪单事务；P2 阶段装备关系来自 bootstrap 首装与新 active 默认装备桥接路径，裁剪不得 no-op）
- 前端：SkillMethodologyScreen（active 列表 4 种排序 + 2 类筛选 + 三项计数；编辑器五字段 + list editor for trigger / required tools；FR-027a 编辑高危确认浮层）；NavRail 未读 badge；非模态浮层"已新增方法论 X"
- 事件：blinker `brain_skill_changed`；UI Event Registry `skill.changed`（payload 不含正文全文）
- 守卫测试：`test_skill_no_physical_delete.py`（部分覆盖方法论行；装备关系行测试在 P3）、`test_skill_origin_closed_enum.py`、`test_skill_no_duplicate_name_active.py`、`test_skill_trigger_conditions_required.py`、`test_skill_seed_fail_open.py`、`test_skill_reference_chain_root_normalize.py`、`test_skill_load_count_path.py`

**验证**: SC-002（30 秒端到端）、SC-003（编辑后 3 秒一致状态）、SC-008（物理删除阻断）、SC-009（未授权 specialist 调用工具被拒）、SC-010（无素材或非允许 zone 被拒）、SC-019（业务层不做语义判重，唯一硬约束 = 同名）、SC-021（编辑保存普通方法论无 UI 确认 / 受保护方法论触发确认）、SC-022（trigger ≥1 条）、SC-023（seed fail-open 三场景）、SC-025（origin 三层校验）

**独立可交付**：P2 完成时已具备方法论资产的完整生命周期能力，并具备内部装备关系桥接以保证创建 / 编辑 / 软删除事务正确；仅缺用户可配置装备管理 UI、specialist 全量装备面板与派活时 specialist 装备清单注入。

---

### Phase P3：装备方法论给 specialist（含 assistant 本体）

**目标**: 用户可在 SpecialistScreen 把方法论装备给 specialist 或 assistant 本体；派活时按装备顺序注入装备清单条目；具体方法论正文按需通过 `load_skill_methodology` 拉入 messages 序列。

**范围**:
- 数据层：`SkillEquipmentRepository`（装备关系状态机 + status 字段 + unique partial index 约束 + 双向历史查询）
- 业务层：`SkillEquipmentService`（多选装备 / 调整顺序 / 卸下 = 标 unequipped 不删行 / 默认全装备传播规则含 `system_bootstrap` 例外 / supersede 时装备关系单事务切换）；`SkillService.force_soft_delete` 在 P3 接入装备关系单事务裁剪
- Agent prompt 改造：assistant_prompt / specialist_prompt_builder 在派活时按装备顺序注入"装备清单条目段"（id + name + description + trigger_conditions list YAML form，**不含正文**）；assistant 本体作为一种装备者按相同协议处理（在自身角色 prompt 之外追加装备清单段）
- Agent 工具：`load_skill_methodology` 工具默认装备给所有装备者（specialist + assistant 本体）；工具 result = SKILL.md form text（YAML frontmatter + Markdown body）；调用方传入的 skill_id 不在装备清单 / skill 已 soft_deleted / superseded 时拒绝；每次成功 +1 被加载次数；**不**设单轮调用次数硬上限
- 派活路径：编排器派活决策本身不变（继承 010），即不读方法论装备关系或 trigger_conditions——守卫测试断言这一点
- API: `/api/specialists/{id}/equipment`（GET 当前装备清单 + 历史轨迹 / PUT 多选装备 + 顺序 / DELETE 单条卸下）；`/api/specialists/_assistant/equipment`（assistant 本体专用入口，路由处理 `_assistant` 特殊标识符）；`/api/skills/methodology/{id}/soft-delete` 接入装备关系裁剪
- 前端：SpecialistScreen 顶部 Assistant 本体装备卡片；每个 specialist 详情页"装备方法论"面板；TokenBudgetMeter 实时计量（前端本地估算公式：装备清单段总字符数 ÷ 4 ≈ token 数，乘以 1.2 安全系数；阈值来自装备端点 DTO，不在前端硬编码）；所需工具警告（不阻断保存）
- 事件：`brain_skill_equipment_changed`；UI Event Registry `skill.equipment.changed`
- 守卫测试：`test_skill_no_physical_delete.py`（装备关系行）、`test_skill_system_bootstrap_protection.py`（含链根传播 + FR-014a 例外）、`test_skill_no_body_in_system_prompt.py`、`test_skill_load_tool_no_call_limit.py`、`test_skill_dispatch_no_methodology_signal.py`

**验证**: SC-004（system prompt 含装备清单条目；不含正文）、SC-005（软删除被引用方法论触发阻断弹窗）、SC-006（supersede 后所有装备者 100% 指向新版本，单事务）、SC-013（默认全装备 + system_bootstrap 例外）、SC-014（派活决策不读方法论）、SC-015（4 种排序 + 卡片三项计数）、SC-017（被加载次数 +1 路径）、SC-018（正文不在 system prompt）、SC-020（token 计量条实时更新）、SC-024（无调用次数硬上限）、SC-026（装备关系永不物理删除）

**独立可交付**：P3 完成时方法论资产已"派得上用场"。

---

### Phase P4：修订与溯源闭环

**目标**: 方法论可被 supersede 修订；版本链回看；素材来源降权显示；并发 supersede first-writer-wins；溯源审计视图完整。

**范围**:
- 业务层：`SkillService.supersede` 接入并发 first-writer-wins 接力（FR-011a）；版本链查询（链根/链尾/全链节点）；正文 diff 计算（后端返回每节点正文 + 与上一版的 diff 高亮信息）
- 用户编辑接力：`SkillService.user_edit` 已在 P2 入库为 supersede 接力的一种 origin (`user_edit`)；P4 补足"链根 origin 判定继承保护"逻辑（FR-027a 沿链传播）
- 装备关系审计：`SkillEquipmentRepository` 双向历史查询（"该方法论曾被哪些装备者装备又卸下""该装备者历史装备组合"）
- API: `/api/skills/methodology/{id}/history`（版本链节点列表 + 每节点完整正文 / diff 数据 / `change_reason`）；`/api/skills/methodology/{id}/audit-equipment`（装备关系历史轨迹，含装备 / 卸下来源与原因）
- 前端：SkillAuditView（按时间倒序展示版本链 + 每次变更原因 + 装备关系变更轨迹 + 卸下来源标签筛选）；SkillDiffView（相邻两版 diff 高亮，完整正文 + diff 两种展示切换）；素材来源降权样式（segment 已 soft_deleted 时灰显并显示快照）
- 守卫测试：`test_skill_supersede_transaction.py` 集成测试（FR-011 单事务 + FR-011a first-writer-wins 单向链）

**验证**: 用户故事 4 Acceptance Scenarios 1-3 + Edge Case "并发 supersede 接力"

**独立可交付**：P4 完成时方法论资产生命周期全闭环。

---

## Complexity Tracking

> 所有 Constitution Check 门卫通过，无违规例外记录。

---

## 关键技术决策（详见 research.md）

1. **token 计量条公式**: 前端本地估算 `tokens = ceil(装备清单段总字符数 / 4 * 1.2)`；阈值默认值由 UnifiedConfig 提供：4096（警示） / 8192（危险），经装备端点 DTO 下发给前端；阈值与公式由 plan 阶段固定，未来调整另起 feature
2. **seed 文件路径**: `src/business/brain/seed/how_to_create_skill_methodology.md`；fail-open fallback 文本硬编码在 `SkillBootstrapService._FALLBACK_BODY` 常量
3. **supersede 链根归一化算法**: `SkillRepository.resolve_chain_root(skill_id) → root_skill_id`，按 `superseded_by` 反向遍历至无 `superseded_by` 指向自己的节点；缓存 chain root id 减少重复查询
4. **装备清单段 YAML 渲染**: trigger_conditions 以 YAML list 原生形态嵌入 system prompt 中"装备方法论清单"段，每条方法论一个块（YAML 二级 key），不再拼成单串
5. **`load_skill_methodology` 工具 result form**: SKILL.md 标准格式 = `---\nname: ...\ndescription: ...\nwhen_to_use: <trigger_conditions 拼接成单串>\nallowed-tools: [...]\n---\n\n<body markdown>`；trigger_conditions list → 单串转换由工具 handler 在 result 生成时完成
6. **`/skills` 路由 redirect 策略**: 前端 `routes.tsx` 顶部判断旧 URL 关键词（`/skills`、`?category=...`）转到新路径；不在 backend 层处理
7. **`skills_referenced` 元数据嵌入位置**: 复用 010 已有的 `reply_to_user` 工具 schema，新增 `skills_referenced: list[str]` 字段；handler 在调 BrainRepository 之外再调 SkillReferenceCounterService 批量 +1
8. **Tool 改名最小 diff 边界**: 文件路径与目录名保留 `skills` 词不变（避免大量 import path 改动），只改文案 + 事件名 + 路由 label

---

## Open Questions（需要在 Phase 0 research 中解决）

无 NEEDS CLARIFICATION 项——spec.md 已经过 27 轮澄清，所有关键决策已落正文。research.md 仅作技术选型与公式细化的载体。
