# Implementation Plan: Assistant Brain Redesign

**Branch**: `010-assistant-brain-redesign` | **Date**: 2026-05-20 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `specs/010-assistant-brain-redesign/spec.md`
**Critique Fix**: 2026-05-20 — Applied E11/E10/E12/E13/P7/X3 updates before `/speckit.tasks`.

---

## Summary

将主助理从"单 Agent + 单段记忆摘要"重构为拥有 **6 个认知分区**（热区/持久区/归档区/潜意识区/失败区/猜测区）的大脑架构，同时把助理工作方式从"自己执行"改为"100% 调度"（任务派给临时 subagent 或固定专员）。实现路径：新增 `BrainBackgroundWorker`（daemon thread 复用现有 worker 模式）、`BrainContextBuilder`（在 assistant 后台工作线程内同步构建多分区上下文并发出 ready 事件）、v11 migration（一次建全所有表）、两个新前端路由（`/brain`、`/brain/specialists`）。按 5 个用户故事增量交付，每阶段独立可验证。

---

## Technical Context

**Language/Version**: Python 3.12（运行时）、TypeScript 5+、React 18、Rust stable  
**Primary Dependencies**: FastAPI、SQLAlchemy、blinker、LangChain（ChatAnthropic / ChatOpenAI）、Tauri 2、Zustand、Vite、pytest、Vitest、Playwright  
**Storage**: SQLite（业务数据，SQLAlchemy + 自定义 migration v11）；DuckDB 不受影响（仅录制）  
**Testing**: pytest（后端单元/集成/门卫）、Vitest + React Testing Library（前端单元）、Playwright（E2E）  
**Target Platform**: Windows 桌面应用（Tauri 2 + Python FastAPI sidecar）  
**Project Type**: Desktop app（Tauri shell + Python sidecar + React UI）  
**Performance Goals**: 大脑上下文构建在 assistant 后台工作线程内完成，不阻塞 UI；沉淀分析后台执行，不影响对话流；首轮回复在上下文就绪后发出（后端 worker 阻塞，前端不感知）  
**Constraints**: CC-003（不引入新中间件）、CC-008（所有数值为占位符）、CC-001（复用现有 AgentLoop kernel）  
**Scale/Scope**: 单用户、单大脑；现有代码库约 60+ Python 文件，5 个前端路由屏幕

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门卫问题 | 证据 |
|------|---------|------|
| **I. 分层边界与事件协调** | 是否保持 `UI → business → data` 方向？跨模块通知是否走 `events.py`？ | **通过**。新增层次：`BrainScreen → /api/brain/ → BrainService → BrainRepository`。新 blinker 事件全部在 `events.py` 定义（`brain_zone_changed`, `brain_specialist_changed`, `segment_boundary_triggered`, `segment_idle_trigger`, `brain_specialist_recruited`, `brain_context_ready`）。`desktop_api` 只做 DTO / event stream adapter，不直接访问 Repository。无上调依赖。 |
| **II. 数据边界与持久化纪律** | SQLite/DuckDB 职责是否清晰？Repository 边界是否保留？ | **通过**。6 个分区表全部在 SQLite，由新建 `BrainRepository`（和各分区专属子 Repository）访问；业务代码不直接写 SQL；DuckDB 完全不受影响。v11 migration 一次建全所有表。现有 `assistant_summaries` / `assistant_profile` 表保留（向后兼容过渡期）。 |
| **III. 统一配置与密钥安全** | 新配置是否走 `UnifiedConfigManager`？密钥安全？ | **通过**。所有新阈值（`brain.*` config keys）通过 `get_unified_config()` 读取，均为占位符（CC-008）。无新密钥字段。详见 `data-model.md` 配置占位符表。 |
| **IV. 可验证交付** | 确定性逻辑是否有自动化测试？架构接线替换是否有冒烟/门卫测试？ | **通过**。规划测试：Segment 状态机单元测试、BrainRepository CRUD 单元测试、蒸馏流集成测试（mock LLM）、上下文注入集成测试、专员招募逻辑单元测试。门卫测试：PM/Programmer/Trial Agent 未被修改、旧 `assistant_memory` 路径已被替换。每个 Phase 有独立验收场景。 |
| **V. 活文档与规格驱动交付** | 活文档是否识别待更新？临时材料是否在 `docs/local/`？ | **通过**。需更新：`docs/ARCHITECTURE.md`（新 brain service 层、新 DB 表、新前端路由）、`docs/PROJECT_CONSTRAINTS.md`（brain.* 配置占位符、大脑分区数据安全边界）、`frontend/AGENTS.md`（新路由/store 说明）、`src/AGENTS.md`（brain service/repository 说明）。设计稿已在 `docs/design/`（只读参考，非活文档）。 |

所有门卫通过，无需填写 Complexity Tracking。

---

## Project Structure

### Documentation (this feature)

```text
specs/010-assistant-brain-redesign/
├── plan.md              # 本文件（/speckit.plan 输出）
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出（见下文）
├── contracts/
│   ├── rest-api.md      # Phase 1：REST API 契约
│   └── events.md        # Phase 1：blinker + SSE 事件契约
└── tasks.md             # Phase 2 输出（/speckit.tasks 命令生成）
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── app/
│   │   └── routes.tsx           # 新增 brain / brain/specialists 路由
│   ├── api/
│   │   └── brain.ts             # 新增：大脑管理 API client
│   ├── components/
│   │   └── BrainToast.tsx       # 新增：专员招募非模态 toast
│   ├── screens/
│   │   ├── BrainScreen/         # 新增：大脑管理模块（分区列表/条目编辑删除/技能池；不替代现有技能列表/组合屏）
│   │   └── SpecialistScreen/    # 新增：专员管理模块（列表/创建/编辑/删除/白名单）
│   └── state/
│       ├── brainStore.ts        # 新增：分区条目 + segment 列表状态
│       └── specialistStore.ts   # 新增：专员列表状态
└── tests/
    ├── unit/
    │   └── brain/               # 新增：brainStore / specialistStore 单元测试
    └── e2e/
        └── brain.spec.ts        # 新增：大脑管理 E2E 冒烟测试

src/
├── business/
│   ├── agents/
│   │   ├── config.py            # 新增 AgentType.EPHEMERAL_SUBAGENT / SPECIALIST
│   │   ├── prompts/
│   │   │   └── assistant_prompt.py   # 重构：多分区注入（持久区全量 + 热区 top-N + 潜意识区 top-N + 专员列表）
│   │   └── tools/
│   │       └── assistant_tools.py    # 新增工具：reply_to_user, delegate_to_subagent, delegate_to_specialist,
│   │                                  #   create_specialist, retrieve_archive, retrieve_failure_zone,
│   │                                  #   invalidate_memory_entry
│   ├── brain/                   # 新增目录：大脑业务逻辑
│   │   ├── __init__.py
│   │   ├── background_worker.py      # BrainBackgroundWorker（daemon thread）
│   │   ├── context_builder.py        # BrainContextBuilder（assistant worker 内同步上下文构建）
│   │   ├── distillation_service.py   # 沉淀 LLM 调用 + Segment 状态机
│   │   ├── decay_router.py           # 热区衰减路由器（event→archive, insight→persistent）
│   │   ├── specialist_service.py     # 专员 CRUD + 招募逻辑
│   │   └── retrieval_service.py      # 归档区/失败区显式检索
│   └── orchestration/
│       └── agent/
│           ├── orchestrator.py       # 扩展：ephemeral subagent / specialist dispatch 执行路径
│           └── assistant_prompt_builder.py  # 重构：从 BrainContextBuilder 读取多分区上下文
├── data/
│   ├── migrations.py            # 新增 migrate_to_v11()
│   ├── models_sqlite.py         # 新增 6 张表的 ORM 模型
│   └── repos/
│       ├── brain_repository.py       # 新增：MemoryEntry / Segment CRUD
│       └── specialist_repository.py  # 新增：Specialist + SpecialistVersion CRUD
├── desktop_api/
│   └── routers/
│       └── brain.py             # 新增：/api/brain/* 路由（zone 管理 / segment 重试 / 专员 / 技能池）
└── utils/
    └── events.py                # 新增 6 个 brain_* 事件

tests/
├── business/
│   └── brain/                   # 新增：大脑业务层测试
│       ├── test_segment_state_machine.py
│       ├── test_distillation_service.py
│       ├── test_decay_router.py
│       ├── test_specialist_service.py
│       └── test_context_builder.py
├── data/
│   └── test_brain_repository.py      # 新增：Repository CRUD 测试
├── desktop_api/
│   └── test_brain_api.py             # 新增：API 契约测试
├── guardrails/
│   └── test_brain_guardrails.py      # 新增：PM/Programmer/Trial 未被修改；旧 memory 路径已隔离
└── integration/
    └── test_brain_distillation.py    # 新增：沉淀链路冒烟测试（mock LLM）
```

**Structure Decision**: 新增 `src/business/brain/` 独立子包承载所有大脑业务逻辑，避免把脑相关代码散落进现有 `agents/` / `memory/` / `services/` 目录；`src/data/repos/` 新增两个 repository 类；前端新增两个 screen 目录和两个 store，完全对称现有 5 个屏幕的组织方式。

---

## 与现有技能/组合屏幕的关系

本 feature 不替换现有 `frontend/src/screens/skills/` 与 `frontend/src/screens/compositions/`。短期边界如下：

- 现有技能列表屏继续管理用户已教学、可复用的技能资产。
- 现有技能组合屏继续管理用户手动组合出的能力集合。
- `/brain` 内的技能池面板只管理"主助理当前可授予专员的能力白名单"，其数据来源可复用现有技能资产，但 UI 目标是约束专员工具权限，而不是重新实现技能教学/列表。
- `/brain/specialists` 只管理固定专员：命名执行体、角色定义、工具白名单和版本历史。专员可以引用技能池能力，但不是技能组合的同义词。

`/speckit.tasks` 生成任务时不得为技能教学、技能列表或技能组合创建重复屏幕；如需能力选择器，应优先复用现有组件/数据接口。

---

## 分阶段交付计划

### Phase P1：跨对话延续的工作记忆（P1 User Story）

**目标**: 基础大脑架构 + 热区 + P1 持久区 + Segment 沉淀 + 冷启动破冰  
**范围**: v11 migration（全部表 + `assistant_profile` 数据回填至持久区）、BrainRepository、Segment 状态机、单次 LLM 沉淀（P1 schema 只请求并持久化热区 + 持久区；破冰答案和稳定事实直接路由到持久区）、BrainContextBuilder（热区 top-N + 持久区全量注入）、更新 assistant_prompt（真实热区 + 真实持久区注入，不只是框架）、前端空闲计时器 + segment-idle API，以及新建/切换会话、窗口关闭等显式 Segment boundary API  
**验证**: SC-001（重开对话引用上次脉络）、SC-005（冷启动至多 2 个问题）、SC-011（Profile 数据在持久区）

---

### Phase P2：永久身份与历史档案（P2 User Story）

**目标**: 长期经验持久化 + 归档区 + 显式归档检索工具  
**范围**: 在 P1 持久区基础上扩展稳定长期经验的沉淀规则；激活归档区写入与归档分层（unit→日/周/月）；`retrieve_archive` 工具；注入排序复合评分（relevance/新近度主排序 + 效果比加权项；`referenced_count` 计量在 P3 到位）。Profile 数据迁入不属于 P2，它已在 P1 的 v11 migration 回填完成。  
**验证**: SC-003（新对话无需手动步骤即可获得大脑条目）、归档检索验收场景（提到旧事时可回查到对应摘要）

---

### Phase P3：100% 调度与可复用专员（P3 User Story）

**目标**: 任务派发框架 + 临时 subagent + 固定专员 + `reply_to_user` 工具  
**范围**: 重构助理系统 prompt（100% 调度规则）；新增 `reply_to_user`、`delegate_to_subagent`、`delegate_to_specialist`、`create_specialist` 工具；SpecialistService；SpecialistRepository；专员管理 API；前端 SpecialistScreen；`memory_entries_referenced` 计量  
**验证**: SC-002（标注任务样本中的派发正确率与零直接执行）、SC-004（所有自动产物有 reason）

---

### Phase P4：避坑、人格感知与自我校准（P4 User Story）

**目标**: 失败区 + 潜意识区 + 猜测区 + 相关检索工具  
**范围**: 沉淀激活失败区 + 潜意识区写入；`retrieve_failure_zone` 工具；`invalidate_memory_entry` 工具；猜测生成 worker（周期性后台 LLM，读取跨 Segment 记忆并写入猜测区）；猜测验证 worker（后台 LLM 评估）；潜意识区注入（top-N 复合评分）；反馈信号消费  
**验证**: SC-008（猜测条目携带验证状态）、SC-009（无硬删除）

---

### Phase P5：自动招人与大脑管理模块（P5 User Story）

**目标**: 自动招募专员 + 大脑管理 UI + 完整反馈信号闭环  
**范围**: 专员招募扫描（BrainBackgroundWorker 周期任务）；招募完成 toast 通知；前端 BrainScreen（6 分区查看/编辑/删除/演化链）；技能池管理面板（管理专员可用能力白名单，复用/引用现有技能资产，不重复实现技能列表/技能组合屏）；`feedback_signals` 完整消费路径；门卫测试补全  
**验证**: SC-006（大脑管理模块可见/可编辑所有条目）、SC-007（自动专员在一个招募周期内出现）、SC-010（无确认弹窗）

---

## Complexity Tracking

> 所有 Constitution Check 门卫通过，无违规例外记录。
