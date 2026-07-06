# Implementation Plan: 技能商店（skills.sh / GitHub 安装外部技能）

**Branch**: `029-skill-store` | **Date**: 2026-07-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/029-skill-store/`

## Summary

SkillListScreen 加第三个"技能商店"tab（照 027 MCP tab 的"tab 字面量 + 独立组件 + 独立 store"模式）。后端新增 `src/business/skill_store/` 业务模块：skills.sh API client（搜索/精选/详情+文件树/审计）、GitHub 匿名发现（根/skills/* 的 SKILL.md）、SKILL.md frontmatter 解析、安装编排——落为 `BrainSkill(origin='external_import')`（复用既有 `SkillService.create`）+ 附带文件写入受管目录 `<data>/external_skills/<install_id>/`（路径规范化防穿越、大小上限、原子成对）。来源元数据落 v26 新表 `external_skill_installs`（与 brain_skills 一对一，避免动宽表）。`load_skill_methodology` 对 external_import 条目附外部来源警示框架。安装路径零执行由守卫测试焊死。0 新公开事件、0 新 secret、0 新执行通道。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）后端；TypeScript + React 18 前端
**Primary Dependencies**: httpx 0.28（已在依赖树）、既有 SkillService/SkillRepository、Zustand、SafeMarkdown
**Storage**: SQLite v26 migration：`external_skill_installs` 表（install_id/skill_id/source_type/source_ref/source_url/local_dir/installed_at）；文件落 `get_default_data_dir()/external_skills/<install_id>/`
**Testing**: pytest（business/desktop_api/guardrails/data）+ Vitest；网络调用全部 mock（respx 或 monkeypatch httpx）
**Target Platform**: Windows 桌面（Tauri 2 + Python sidecar）
**Project Type**: desktop-app
**Performance Goals**: 搜索响应受外部 API 限制；安装（详情已含文件树时）< 2s 本地落盘
**Constraints**: 安装路径零执行（CC-170 守卫）；匿名访问（CC-172）；0 新事件（CC-173）；受管目录 + 大小上限（CC-174：单文件 ≤ 512KB、单技能总量 ≤ 2MB、文件数 ≤ 40，代码常量）
**Scale/Scope**: 1 新业务模块（约 5 文件）、1 新表、1 typed API 面（4 endpoint）、前端 1 tab + 1 store + 1 弹层

## Constitution Check

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. Layered Boundaries & Event Coordination | 分层与事件？ | UI（SkillStoreTab/skillStoreStore）→ typed API（skill_store router）→ `skill_store` 业务模块 → SkillService/SkillRepository + 新 ExternalSkillInstallRepository。0 新 blinker、0 新公开 UI 事件。 |
| II. Data Boundary & Persistence Discipline | Repository/迁移？ | v26 migration 建 `external_skill_installs`（downgrade drop）；读写走新 Repository；brain_skills 零 schema 改动（软删等生命周期复用既有 SkillService）。文件写盘收敛在业务模块单一 helper（规范化+上限），不碰 DuckDB。 |
| III. Unified Config & Secret Handling | 配置/密钥？ | 0 新配置键、0 secret（CC-172）；上限用模块常量。 |
| IV. Verifiable Delivery | 覆盖？ | 单测：frontmatter 解析、路径穿越拒绝、大小上限、安装原子性、幂等、卸载清理；API contract 测试（mock 网络）；守卫：安装/预览模块零执行 import + methodology 警示框架存在；前端：tab 渲染/搜索/预览确认/已安装态。 |
| V. Living Docs & Spec-Driven Delivery | 活文档？ | ARCHITECTURE.md 增技能商店小节；根/src/frontend AI 镜像各补条目与约束；spec/plan/tasks 在 specs/029-*。 |

**Gate 结论**: 全部通过，无例外。

## Project Structure

### Documentation (this feature)

```text
specs/029-skill-store/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/store-api.md
└── tasks.md
```

### Source Code (repository root)

```text
src/
├── business/skill_store/
│   ├── __init__.py
│   ├── skills_sh_client.py      # 新增：skills.sh /api/v1 搜索/精选/详情/审计（httpx，超时+错误分类）
│   ├── github_discovery.py      # 新增：owner/repo 解析 + SKILL.md 发现 + 文件拉取（匿名 REST）
│   ├── skill_md_parser.py       # 新增：SKILL.md frontmatter(name/description) + body 解析与回退
│   ├── install_service.py       # 新增：预览组装 + 安装编排（SkillService.create + 文件落盘原子成对）+ 卸载
│   └── file_store.py            # 新增：受管目录写盘（路径规范化防穿越、大小/数量上限、整目录清理）
├── business/agents/tools/skill_methodology_tools.py  # 修改：load 输出对 external_import 附来源警示框架
├── data/
│   ├── models_sqlite.py         # 修改：ExternalSkillInstall 模型
│   ├── migrations.py            # 修改：v26（建表 + downgrade）
│   └── repos/external_skill_install_repository.py  # 新增
└── desktop_api/routers/skill_store.py  # 新增：search/discover-github/preview/install/uninstall

frontend/src/
├── api/skillStore.ts            # 新增 typed client
├── state/skillStoreStore.ts     # 新增独立 store（照 mcpStore 模式）
└── screens/skills/
    ├── SkillListScreen.tsx      # 修改：SkillTab 加 "store" 字面量 + 条件渲染
    ├── SkillStoreTab.tsx        # 新增：搜索/精选列表 + GitHub 输入 + 已安装标识
    └── SkillStorePreviewDialog.tsx  # 新增：SKILL.md 全文 + 文件清单 + 审计/无审计警示 + 安装确认

tests/
├── business/skill_store/        # 解析/文件边界/安装编排/幂等/卸载
├── desktop_api/test_skill_store_endpoint.py
└── guardrails/test_skill_store_guardrails.py  # 零执行 import 守卫 + 警示框架守卫

frontend/tests/unit/skill-store.test.tsx
```

**Structure Decision**: 独立 `skill_store` 业务模块（与 mcp/self_improvement 同级），安装最终写入走既有 SkillService 保证方法论生命周期语义单一。

## Complexity Tracking

无例外。
