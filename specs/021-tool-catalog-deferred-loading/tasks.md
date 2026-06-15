# Tasks: 工具目录渐进式延迟加载

**Input**: Design documents from `specs/021-tool-catalog-deferred-loading/`

## Phase 1: Setup

- [X] T001 固化 021 spec/plan/research/data-model/contracts/quickstart 到 `specs/021-tool-catalog-deferred-loading/`

## Phase 2: Foundational

- [X] T002 [P] 在 `src/data/config_models.py`、`src/data/unified_config.py`、`config.example.json`、`config.example.comments.md` 增加 `agent_tools.discovery.*` 配置和边界
- [X] T003 [P] 在 `tests/data/test_unified_config.py` 添加发现配置默认值、上界、非法值和 default<=max 回归测试
- [X] T004 在 `src/business/agents/tools/capability_catalog.py` 实现共享目录模型、Prompt 渲染、确定性搜索排序和分页
- [X] T005 [P] 在 `tests/business/agents/test_capability_catalog.py` 添加阈值、隐藏名称、排序、分页、描述截断和 100 项遍历测试

## Phase 3: User Story 1 - 有界 Agent Prompt (P1)

- [X] T006 [US1] 在 `src/business/orchestration/agent/assistant_prompt_builder.py` 接入授权目录构建与模式日志
- [X] T007 [US1] 在 `src/business/agents/prompts/assistant_prompt.py` 支持共享能力目录区段并保留旧 `tools` 调用兼容
- [X] T008 [US1] 在 `src/business/orchestration/agent/orchestrator.py` 将临时子代理和固定专员接入同一目录策略
- [X] T009 [US1] 在 `tests/integration/test_agent_orchestrator_architecture.py` 覆盖三类 Agent 的 full/deferred/授权隔离接线

## Phase 4: User Story 2 - 完整目录发现 (P1)

- [X] T010 [US2] 在 `src/business/agents/tools/dynamic_tool_manager.py` 扩展 `search_tools` schema、全目录重校验、类型过滤和分页 JSON 契约
- [X] T011 [US2] 在 `tests/test_skill_composition_regressions.py` 覆盖旧 query 调用、空查询浏览、组合授权、重名 selector 和分页
- [X] T012 [US2] 在 `tests/integration/test_agent_loop_parallel_tools.py` 保持 search/get detail 并发安全声明回归

## Phase 5: User Story 3 - 动态失效与运行时配置 (P2)

- [X] T013 [US3] 在 `tests/test_skill_composition_regressions.py` 覆盖搜索与详情的发布状态/授权重校验和激活失效
- [X] T014 [US3] 在 `tests/integration/test_agent_orchestrator_architecture.py` 覆盖运行时阈值变更下一次 Prompt 生效

## Phase 6: Polish

- [X] T015 [P] 更新 `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md` 和 `src/AGENTS.md` / `CLAUDE.md` / `GEMINI.md`
- [X] T016 更新 `docs/local/todo/agent-tool-patterns.md`、`docs/local/todo/todo.md` 并新增 `_archive/completed-summaries/todo-tool-catalog-deferred-loading.md`
- [X] T017 运行 quickstart 中的 pytest、Black check 和 Flake8，修复所有相关失败
- [X] T018 将本文件全部任务标记完成并核对 `git diff --check`

## Dependencies

- T002/T003 与 T004/T005 可并行，完成后解锁三类 Agent 接线。
- T006-T009 完成后可独立验收有界 Prompt。
- T010-T012 完成后可独立验收目录浏览与搜索。
- T013-T014 依赖前两条路径完成。
- 文档和最终验证依赖全部行为实现。

## Validation Notes

- 功能相关测试、Black check、Flake8 和 `git diff --check` 均通过。
- 全量测试结果为 1474 passed、3 skipped、5 failed；5 个失败已在未修改的主工作树复现，分别是既有 debug client 测试对象缺少 `audit_source`、两个 migration 版本断言仍期待 13、两个 Settings `FakeConfig` 缺少语义摘要密钥 getter，与本功能无关。
