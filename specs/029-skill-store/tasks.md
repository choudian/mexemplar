# Tasks: 技能商店（skills.sh / GitHub 安装外部技能）

**Input**: Design documents from `/specs/029-skill-store/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/store-api.md, quickstart.md

**Tests**: Included — Constitution IV。网络调用一律 mock，不依赖真实外部服务。

**Organization**: 按 user story 分阶段；US1（skills.sh 安装闭环）即 MVP。

## Project Paths

- Python 源码 `src/`，测试 `tests/`；前端 `frontend/src/`，单测 `frontend/tests/unit/`
- 验证：`uv run pytest … -q`、`uv run black/flake8`、`cd frontend && npm run lint && npx vitest run`

---

## Phase 1: Foundational（阻塞所有 user story）

- [X] T001 src/data/models_sqlite.py 增 ExternalSkillInstall 模型（install_id/skill_id UNIQUE/source_type CHECK/source_ref/source_url/local_dir/installed_at/uninstalled_at）
- [X] T002 src/data/migrations.py 增 migrate_to_v26（CREATE TABLE + UNIQUE(skill_id) + ix source 复合索引）与 downgrade_v26（DROP TABLE），注册 _MIGRATIONS
- [X] T003 新建 src/data/repos/external_skill_install_repository.py：create/get_active_by_source(source_type, source_ref)/get_by_install_id/list_active/mark_uninstalled
- [X] T004 [P] 新建 src/business/skill_store/skill_md_parser.py：极简 frontmatter 解析（---包围 key:value，仅取 name/description）+ 回退（slug 作名、正文首段截 200 字作描述）+ body 提取
- [X] T005 [P] 新建 src/business/skill_store/file_store.py：受管目录写盘（临时目录写全→rename 原子成对；相对路径规范化拒绝 ../ 绝对路径 盘符；单文件≤512KB/总量≤2MB/文件数≤40 常量；UTF-8 文本 only）+ remove_install_dir 清理
- [X] T006 [P] tests/data/test_external_skill_install_migration.py：v26 建表/幂等/downgrade；tests/business/skill_store/test_skill_md_parser.py：完整 frontmatter/缺 name/缺 description/无 frontmatter 回退；tests/business/skill_store/test_file_store.py：正常落盘、路径穿越拒绝零残留、超限拒绝、清理

**Checkpoint**: 数据层 + 解析 + 文件边界就绪

---

## Phase 2: User Story 1 - 从 skills.sh 搜索并安装 (P1) 🎯 MVP

- [X] T007 [US1] 新建 src/business/skill_store/skills_sh_client.py：search(q)/curated()/detail(source_ref)→含文件树/audit(source_ref)→失败降级 "unavailable"；httpx 超时 10s、错误分类为用户可理解消息（FR-448）
- [X] T008 [US1] 新建 src/business/skill_store/install_service.py：preview(source_type, source_ref)（组装全文/文件清单/审计，零持久化；超限返回 installable=false）+ install()（file_store 落盘→SkillService.create(origin='external_import', trigger_conditions=[description])→伴生表；失败逆序清理；同 source 活跃安装幂等返回；重名自动加来源后缀重试一次）+ uninstall(install_id)（SkillService 软删 + mark_uninstalled + 目录清理）+ list_installed()
- [X] T009 [US1] 新建 src/desktop_api/routers/skill_store.py：GET /api/skill-store/search、POST /preview、POST /install、GET /installed、POST /{install_id}/uninstall（契约按 contracts/store-api.md；search 外部失败降级 sourceAvailable=false）并注册进 app
- [X] T010 [P] [US1] tests/business/skill_store/test_install_service.py（mock client + in_memory_db）：安装三件套原子成对、失败逆序清理零残留、幂等同 installId、重名后缀重试、卸载清理闭环、preview 零持久化
- [X] T011 [P] [US1] tests/desktop_api/test_skill_store_endpoint.py：契约 6 条行为约束（mock 网络）
- [X] T012 [P] [US1] tests/guardrails/test_skill_store_guardrails.py：零执行守卫（skill_store 模块源码不 import src.execution/不引用 exec 工具/subprocess）+ install/preview 路径静态断言
- [X] T013 [US1] 修改 src/business/agents/tools/skill_methodology_tools.py：load 渲染对 origin='external_import' 条目注入来源警示头（D6）；tests/guardrails 增警示框架存在断言
- [X] T014 [US1] 新建 frontend/src/api/skillStore.ts（search/discoverGithub/preview/install/installed/uninstall typed client）+ frontend/src/state/skillStoreStore.ts（结果/精选/已装列表/预览态/pending 态；照 mcpStore 模式）
- [X] T015 [US1] 修改 frontend/src/screens/skills/SkillListScreen.tsx：SkillTab 加 "store" 字面量 + tab 按钮 + 条件渲染 SkillStoreTab；新建 SkillStoreTab.tsx（防抖搜索框 + 精选/结果列表卡片含已安装徽章）+ SkillStorePreviewDialog.tsx（SafeMarkdown 全文 + 文件清单 + 审计区/无审计警示 + 安装按钮 pending disable）
- [X] T016 [US1] frontend/tests/unit/skill-store.test.tsx：tab 渲染、搜索出结果、打开预览显示全文与审计、确认安装调 install、已安装徽章、外部不可达提示

**Checkpoint**: US1 独立可验收——skills.sh 端到端安装闭环

---

## Phase 3: User Story 2 - GitHub 直装 (P2)

- [X] T017 [US2] 新建 src/business/skill_store/github_discovery.py：owner/repo 与 URL 解析（非法 422 语义）、发现根 SKILL.md 与 skills/*/SKILL.md（匿名 REST 一层枚举）、按发现路径拉取技能目录文件（走 file_store 同一上限）；preview/install 复用 install_service（source_type='github'，audit 恒 "unaudited"）
- [X] T018 [US2] skill_store router 增 POST /api/skill-store/discover-github；tests/desktop_api 补 discover 契约（发现多技能/无技能/非法输入 422）
- [X] T019 [P] [US2] tests/business/skill_store/test_github_discovery.py（mock httpx）：URL/owner-repo 解析、根与子目录发现、限额/404 错误分类
- [X] T020 [US2] SkillStoreTab 增"从 GitHub 安装"折叠输入区（输入→发现列表→进同一预览弹层，弹层显示未审计警示）；frontend 单测补 GitHub 流用例

**Checkpoint**: US2 独立可验收

---

## Phase 4: User Story 3 - 已安装管理 (P3)

- [X] T021 [US3] 方法论详情（SkillMethodologyScreen 或其详情组件）对 external_import 条目显示来源徽章 + 原始链接 + 卸载入口（调 uninstall API）；frontend 单测补断言
- [X] T022 [P] [US3] tests/business/skill_store 补卸载后重装为新条目（旧条目在软删历史）用例

**Checkpoint**: US3 独立可验收

---

## Phase 5: Polish & Cross-Cutting

- [X] T023 [P] 活文档：docs/ARCHITECTURE.md 增技能商店小节；根/src/frontend AI 入口镜像各补 029 条目与约束（零执行安装、受管目录、外部来源警示 advisory 定位）
- [X] T024 全量验证：uv run pytest tests/business/skill_store tests/desktop_api tests/data tests/guardrails -q；cd frontend && npm run lint && npx vitest run；black/flake8 改动文件

---

## Dependencies & Execution Order

- Phase 1（T001→T002→T003；T004/T005/T006 并行）阻塞全部
- US1：T007→T008→T009 串行；T010/T011/T012 并行；T013 独立；T014→T015→T016 前端串行
- US2 依赖 US1 的 install_service/preview 弹层
- US3 依赖 US1 的 installed/uninstall API
- Polish 最后

## Implementation Strategy

MVP = Phase 1 + US1。US2/US3 增量交付。
