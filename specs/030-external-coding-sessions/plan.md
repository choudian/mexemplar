# Implementation Plan: 外部 Coding Session（Claude Code / Codex CLI）

**Branch**: `030-external-coding-sessions` | **Date**: 2026-07-09 | **Spec**: [spec.md](./spec.md)
**Revision**: 2026-07-10 — Finalized implemented V1 rollback boundary and archived project memory.
**Input**: Feature specification from `specs/030-external-coding-sessions/spec.md`

## Summary

把 Claude Code 和 Codex CLI 接入 Exemplar 作为 owner-bound 的外部代码执行工具。Agent 通过新工具创建 coding session；系统为每次 session 创建独立 git worktree 与 `data/coding_sessions/<id>/` artifact 目录，先要求外部工具产出 `PLAN.md`，由派活 agent 审核后才进入实现。实现完成依赖 `RESULT.md`、worktree diff 和测试/风险摘要；Exemplar 负责状态机、可恢复 attempt、quota-aware 选择、合并前 dirty/conflict 分析、自动 merge 审计和回滚建议。

技术上新增 `src/business/external_coding/` 业务模块、`src/execution/external_coding_process.py` 进程适配、SQLite v27 持久化与 v28 worktree 基线、Desktop API typed endpoints、task detail UI 展示，以及 agent tool factory。外部 CLI 原始输出只进入有界 artifact/log tail；公开 DTO/UI event 只暴露脱敏状态和摘要。

## Technical Context

**Language/Version**: Python 3.12 runtime / Python 3.11+ compatible code, React 18 + TypeScript, FastAPI, SQLite, git CLI, local Claude Code/Codex CLI executables  
**Primary Dependencies**: SQLAlchemy ORM, FastAPI/Pydantic, blinker event registry, existing AgentLoop `ToolDefinition`, Zustand/Vite frontend, subprocess/process helpers, git command line  
**Storage**: SQLite business tables plus filesystem artifacts under `data/coding_sessions/<codingSessionId>/`; no DuckDB change  
**Testing**: `uv run pytest` for business/data/API/guardrails; Vitest/RTL for frontend task card/API parser changes; external CLI covered through fake adapters by default  
**Target Platform**: Windows-first Tauri desktop app with local Python sidecar; command construction remains path-safe for local CLI invocation  
**Project Type**: Desktop app with Python business/backend bridge and React frontend  
**Performance Goals**: Session status/event projection visible within 5 seconds after process completion in normal sidecar runtime; API snapshot reads bounded to recent session summaries/log tail  
**Constraints**: No secret raw values in logs/DTO/UI events/artifacts; no unowned external coding session; plan phase write detection; fixed external tool per session; Exemplar-only merge/rollback authority  
**Scale/Scope**: V1 supports Claude Code and Codex CLI only; multiple active sessions across task graph nodes; artifact logs are bounded and summarized

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. Layered Boundaries & Event Coordination | Does the design preserve `UI -> business -> execution -> data/driver` direction, and are all cross-module notifications routed through `src/utils/events.py`? | PASS. UI calls Desktop API only; Desktop API calls `ExternalCodingSessionService`; business uses repositories and execution adapter; execution launches CLI only; internal `external_coding_session_changed` event is defined in `src/utils/events.py` and projected through UI Event Registry. |
| II. Data Boundary & Persistence Discipline | Are SQLite and DuckDB responsibilities explicit, are Repository boundaries preserved, and do `network_requests` reads keep filtering/desensitization contracts? | PASS. New SQLite v27 tables accessed only through `ExternalCodingSessionRepository`; no DuckDB or `network_requests` access. |
| III. Unified Config & Secret Handling | Do all settings and secrets flow through `UnifiedConfigManager`, with masked DTO/UI output and redacted ordinary logs? | PASS. Tool command paths, defaults, quota probe toggles and timeout/log limits use unified config getters/defaults. Quota probes may read local credentials/status, but only normalized status/confidence/source/reset time is persisted or exposed. |
| IV. Verifiable Delivery | Does the plan include automated coverage for deterministic logic plus wiring smoke/guard tests for architecture rewires? | PASS. Tests cover repository/state machine, semantic artifact validation, tool owner guard, quota redaction, API contracts, UI event allowlist, task detail rendering and merge dirty/conflict analysis. |
| V. Living Docs & Spec-Driven Delivery | Are required active docs identified for update, and are temporary notes confined to `docs/local/`? | PASS. Spec artifacts live under `specs/030-external-coding-sessions/`; root AI entry mirrors updated. If implementation changes runtime overview/constraints, update `docs/ARCHITECTURE.md` and `docs/PROJECT_CONSTRAINTS.md`. |

Post-design re-check: PASS. No constitution exception is required.

## Project Structure

### Documentation (this feature)

```text
specs/030-external-coding-sessions/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── external-coding-api.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code

```text
src/
├── business/
│   ├── agents/
│   │   └── tools/
│   │       └── external_coding_tools.py
│   └── external_coding/
│       ├── __init__.py
│       ├── artifacts.py
│       ├── cli_adapters.py
│       ├── git_ops.py
│       ├── models.py
│       ├── quota_probe.py
│       ├── service.py
│       └── validators.py
├── data/
│   ├── migrations.py
│   ├── models_sqlite.py
│   ├── unified_config.py
│   └── repos/
│       └── external_coding_session_repository.py
├── desktop_api/
│   ├── app.py
│   ├── routers/
│   │   └── external_coding_sessions.py
│   ├── schemas.py
│   ├── ui_event_projector.py
│   └── ui_events.py
├── execution/
│   └── external_coding_process.py
└── utils/
    └── events.py

frontend/
├── src/
│   ├── api/
│   │   ├── assistantTasks.ts
│   │   ├── externalCodingSessions.ts
│   │   ├── uiEventParser.ts
│   │   └── uiEventTypes.ts
│   ├── screens/assistant/
│   │   └── TaskNodeCard.tsx
│   └── state/
│       ├── assistantTaskStore.ts
│       └── externalCodingSessionStore.ts
└── tests/unit/
    └── externalCodingSessions.test.tsx

tests/
├── business/external_coding/
├── data/
├── desktop_api/
├── guardrails/
└── integration/
```

**Structure Decision**: 新能力独立成 `business/external_coding`，避免把外部 CLI 编排塞进 task collaboration 或 agent loop。Task collaboration 只通过 owner/taskId 和 snapshot 附加摘要感知 session；外部进程启动在 execution 层；SQLite 持久化和文件 artifact 由业务 service 协调。

## Complexity Tracking

无 constitution 例外。

## Phase 0 Research

See [research.md](./research.md).

## Phase 1 Design

See [data-model.md](./data-model.md), [contracts/external-coding-api.md](./contracts/external-coding-api.md), and [quickstart.md](./quickstart.md).

## Implementation Notes

- `codingSessionId` 由 repository 生成，默认前缀 `ecs`；worktree 使用 `.worktrees/coding/<id>`，branch 使用 `coding/<id>`。
- `PLAN.md` / `RESULT.md` 是 Markdown soft template；validator 检查最低语义覆盖，不锁死标题。
- Session lifetime 固定 `tool`；quota/model failure 只中断，不自动切换工具或降级 reasoning。
- Headless attempt 默认使用最高 effort/reasoning。Claude Code adapter 默认 `--effort max`；Codex CLI adapter 默认通过 config override 请求 `model_reasoning_effort="xhigh"`，若 CLI 拒绝该档则分类为 `model_unavailable`。
- Interactive supervised mode 只记录 launch intent/status，完成仍以 artifact 和 service inspect 为准，不解析终端屏幕。
- Merge 只由 Exemplar 执行：先记录 target dirty set、coding branch diff、overlap/conflict prediction，再由 agent 或用户确认风险。
- Rollback V1 只对本 session 记录的精确 merge commit 执行确认后的 `git revert`；执行前重验 target branch/HEAD、ancestry、双 parent 与 clean workspace，拒绝 reset/clean/reverse patch/manual apply。
