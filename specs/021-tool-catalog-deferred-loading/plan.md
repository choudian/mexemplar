# Implementation Plan: 工具目录渐进式延迟加载

**Branch**: `021-tool-catalog-deferred-loading` | **Date**: 2026-06-15 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/021-tool-catalog-deferred-loading/spec.md`

## Summary

在现有动态 FC schema 激活机制之上增加授权能力目录策略。小目录继续完整注入摘要；大目录只注入统计和发现说明，由增强后的 `search_tools` 提供授权范围内的稳定浏览、搜索与分页，再通过 `get_tool_detail` 激活调用定义。共享纯业务模型覆盖主助理、临时子代理和固定专员，配置通过 `UnifiedConfigManager` 管理且不开放 Settings UI。

## Technical Context

**Language/Version**: Python 3.11+，运行时 3.12  
**Primary Dependencies**: SQLAlchemy、LangChain Agent function calling、现有 AgentLoop/Orchestrator  
**Storage**: 现有 SQLite 只读目录查询；无 schema 或迁移  
**Testing**: pytest、Black、Flake8  
**Target Platform**: Windows 桌面应用 Python sidecar  
**Project Type**: Tauri + React 桌面应用的 Python Agent 业务层  
**Performance Goals**: 100+ 授权能力时目录区段保持在 1000 字符内；25 项搜索页在本地目录查询中稳定返回  
**Constraints**: 不扩大授权，不新增 UI/API/event，不改变动态激活 LRU 和工具并发语义  
**Scale/Scope**: 主助理、临时子代理、固定专员；用户技能与技能组合

## Constitution Check

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. Layered Boundaries & Event Coordination | 保持依赖方向且无新跨模块通知 | 仅 `business -> data config/repository`；无新事件 |
| II. Data Boundary & Persistence Discipline | 保持 Repository 边界 | 目录读取继续经 ToolRepository/SkillCompositionService；无 SQL、迁移或 DuckDB 变化 |
| III. Unified Config & Secret Handling | 新参数统一配置 | `agent_tools.discovery.*` 只经 UnifiedConfigManager；无 secret、DTO 或 Settings UI |
| IV. Verifiable Delivery | 确定性逻辑和接线有测试 | 纯策略单测、动态管理器搜索契约测试、三类 Agent Prompt 接线集成测试、配置测试 |
| V. Living Docs & Spec-Driven Delivery | 活文档同步 | 更新 ARCHITECTURE、PROJECT_CONSTRAINTS、模块 AI 入口镜像和 TODO 归档 |

Post-design re-check: 全部通过，无需例外。

## Project Structure

### Documentation

```text
specs/021-tool-catalog-deferred-loading/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── search-tools.md
└── tasks.md
```

### Source Code

```text
src/
├── business/
│   ├── agents/tools/
│   │   ├── capability_catalog.py
│   │   └── dynamic_tool_manager.py
│   └── orchestration/agent/
│       ├── assistant_prompt_builder.py
│       └── orchestrator.py
└── data/
    ├── config_models.py
    └── unified_config.py

tests/
├── business/agents/test_capability_catalog.py
├── data/test_unified_config.py
├── integration/test_agent_orchestrator_architecture.py
└── test_skill_composition_regressions.py
```

**Structure Decision**: 新增一个无持久化依赖的业务策略模块；Prompt Builder 负责从 Repository/Service 获取并授权过滤目录，DynamicToolManager 负责调用时重校验，二者复用相同目录模型、排序、分页和渲染规则。

## Design

1. `CapabilityCatalogItem` 规范化技能与组合为 `kind/name/selector/description/search_text`。
2. `CapabilityDiscoveryPolicy` 每次从统一配置读取阈值，避免运行时配置被实例缓存。
3. `render_capability_catalog()` 先生成完整目录并计算实际字符数；仅当条目数和字符数均未超限时返回 full，否则返回不含条目名称的 deferred 区段。
4. `search_capability_catalog()` 在完整授权集合上执行类型过滤、确定性相关度排序和 offset 分页，返回结构化 JSON 所需数据。
5. `AssistantPromptBuilder` 新增可复用目录构建方法，供主助理与 Orchestrator 委派路径调用。
6. `DynamicToolManager` 在每次搜索时重新读取全部当前可用能力并应用既有 `_is_allowed_*`，因此不依赖 Prompt 快照。

## Complexity Tracking

无宪法例外。
