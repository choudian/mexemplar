# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]  
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]  
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]  
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [e.g., library/cli/web-service/mobile-app/compiler/desktop-app or NEEDS CLARIFICATION]  
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]  
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]  
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. Layered Boundaries & Event Coordination | Does the design preserve `UI -> business -> execution -> data/driver` direction, and are all cross-module notifications routed through `src/utils/events.py`? | List touched layers, new/changed events, and any justified exception |
| II. Data Boundary & Persistence Discipline | Are SQLite and DuckDB responsibilities explicit, are Repository boundaries preserved, and do `network_requests` reads keep filtering/desensitization contracts? | Name touched stores, repositories, migrations, and any approved raw-SQL entry point |
| III. Unified Config & Secret Handling | Do all new settings flow through `UnifiedConfigManager`, and do all secrets stay out of code/config files? | List config keys, template/UI/doc updates, keyring impact, or `N/A` |
| IV. Verifiable Delivery | Does the plan include automated coverage for deterministic logic plus wiring smoke/guard tests for architecture rewires? | Name unit, integration, wiring, and guard tests, or justify omissions |
| V. Living Docs & Spec-Driven Delivery | Are required active docs identified for update, and are temporary notes confined to `docs/local/`? | List docs to update and any `docs/local/` working artifacts |

If any gate fails, record the exception and rationale in **Complexity Tracking** before proceeding.

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
src/
├── business/          # 业务层：编排、Agent、AI、意图、记忆、服务
│   ├── agents/        # Agent 循环、工具、Prompt
│   ├── ai/            # LLM 客户端
│   ├── intent/        # 意图识别
│   ├── memory/        # 会话记忆
│   ├── orchestration/ # 编排引擎（兼容入口 + agent/ 子组件拆分）
│   ├── services/      # 业务 Service
│   └── tool_trial/    # 工具试用
├── data/              # 数据层：配置、Repository、DuckDB/SQLite 管理
│   └── repos/         # 业务数据 Repository
├── execution/         # 执行层：代码执行沙箱等运行时能力
├── recording/         # 录制层：浏览器/桌面录制、过滤、浏览器扩展
│   ├── browser/       # Playwright 录制子组件
│   ├── browser_extension/  # JS 浏览器扩展
│   └── filtering/     # SQL 重写、过滤连接、投影分析
├── ui/                # UI 层：PyQt6 界面
│   ├── mixins/
│   ├── resources/
│   └── widgets/
└── utils/             # 公共工具：事件、AST 辅助等

tests/
├── data/              # 数据层测试
├── e2e/               # 端到端测试
├── fixtures/          # 测试 fixture
├── integration/       # 集成测试
├── recording/         # 录制层测试
│   └── filtering/     # 过滤/分析器测试
└── ui/                # UI 测试
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
