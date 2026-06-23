# Implementation Plan: 统一任务模型 + 多范式协作

**Branch**: `023-unified-task-collaboration` | **Date**: 2026-06-17 | **Spec**: [spec.md](spec.md)  
**Input**: Feature specification from `specs/023-unified-task-collaboration/spec.md`

## Summary

把 Assistant 现有的隐式子会话委派、子任务卡片和同步等待路径收口为 SQLite 持久化的一等 Task 图。新增 Task / TaskAttempt / 父侧裁定 / 看板认领 / 会议通道 / Todo 私人清单模型，并在业务层提供异步 dispatch、结果回流重入、容量=1 执行者锁、崩溃恢复、顺图停止/取消和三种协作范式切换。前端只通过 typed API 与公开 UI event 展示权威快照和增量，不直接触达 Repository；Tauri 层不承载业务规则。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）、TypeScript + React 18/Vite、Rust stable/Tauri 2  
**Primary Dependencies**: FastAPI sidecar、SQLAlchemy、SQLite、blinker、LangChain-compatible AgentLoop、Zustand、Vitest、Playwright  
**Storage**: SQLite v15 migration for assistant task collaboration tables plus v16 active-attempt partial unique indexes; no DuckDB or recording schema changes  
**Testing**: pytest、Vitest/React Testing Library、Playwright smoke where UI shell changes are needed、Black、Flake8  
**Target Platform**: 单用户 Windows 桌面应用，本地 Tauri shell + Python sidecar  
**Project Type**: Tauri + React desktop app with Python business/data backend  
**Performance Goals**: controlled executor tests show independent tasks complete in <=70% of serial baseline or within max(child duration)+20% overhead; task graph snapshot for 200 nodes returns in <=500ms locally; UI receives task state event within 1s of business state commit in controlled tests  
**Constraints**: preserve `UI -> desktop_api -> business -> data` layering; all public events go through UI Event Registry; capacity=1 per executor; no user-facing pending answer persistence; no plaintext secret in DTO/event/log; no shared SQLAlchemy Session across worker threads  
**Scale/Scope**: Assistant only; per user request graph target <=200 tasks, <=20 active attempts, <=2-party meeting channels, Todo scoped to one assigned task; PM/Programmer/Trial excluded from task state machine

## Constitution Check

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. Layered Boundaries & Event Coordination | Does the design preserve dependency direction and route notifications through `src/utils/events.py`? | UI uses typed clients and event stream only; desktop API calls `TaskCollaborationService`; business emits new blinker events; data layer remains Repository-only. No Tauri business logic. |
| II. Data Boundary & Persistence Discipline | Are SQLite/DuckDB responsibilities explicit and Repository boundaries preserved? | New SQLite tables and repositories under `src/data/repos/`; no DuckDB changes; business code never writes SQL directly; migration v15 owns schema and v16 adds DB-level active-attempt capacity fences. |
| III. Unified Config & Secret Handling | Do settings and secrets flow through `UnifiedConfigManager`? | New tuning keys under `assistant_tasks.*` are read by getters on `UnifiedConfigManager`; no new secret fields; public DTO/events use sanitized projections only. |
| IV. Verifiable Delivery | Does the plan include tests for deterministic logic and rewiring? | Repository/state-machine tests, crash recovery tests, event registry/projector tests, API contract tests, frontend store/component tests, guardrail tests for old transition-derived UI and direct Repository access. |
| V. Living Docs & Spec-Driven Delivery | Are active docs identified? | Update `docs/ARCHITECTURE.md`, `docs/PROJECT_CONSTRAINTS.md`, root/module AI entry mirrors if the implementation changes live constraints. Spec artifacts live under `specs/023-unified-task-collaboration/`. |

Post-design re-check: PASS. The design adds complexity because it replaces an unsafe implicit runtime model with durable orchestration state; no constitution exception is required.

## Project Structure

### Documentation

```text
specs/023-unified-task-collaboration/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── assistant-task-collaboration.md
└── tasks.md              # Created by /speckit.tasks, not this command
```

### Source Code

```text
frontend/
├── src/
│   ├── api/
│   │   └── assistantTasks.ts          # typed task graph / board / meeting / todo clients
│   ├── screens/assistant/
│   │   ├── TaskGraphPanel.tsx
│   │   ├── TaskBoardPanel.tsx
│   │   ├── MeetingChannelDrawer.tsx
│   │   └── TodoChecklistPanel.tsx
│   └── state/
│       ├── assistantTaskStore.ts
│       └── assistantStore.ts          # resync wiring and stop/continue handoff
└── tests/
    ├── unit/
    │   ├── assistant-task-store.test.ts
    │   └── assistant-task-panels.test.tsx
    └── e2e/
        └── assistant-task-graph.spec.ts

src/
├── business/
│   ├── task_collaboration/
│   │   ├── models.py                  # enums/dataclasses, no ORM
│   │   ├── service.py                 # authoritative task graph facade
│   │   ├── dispatcher.py              # async dispatch, parking, re-entry
│   │   ├── recovery.py                # TaskAttempt lease/fence recovery
│   │   ├── adjudication.py            # parent-side accept/return/abandon
│   │   ├── board.py                   # open task claim/release/fallback
│   │   ├── meetings.py                # supervised message-only channel
│   │   └── todos.py                   # private checklist service
│   ├── agents/
│   │   ├── tools/assistant_tools.py   # delegate/ask_parent/meeting/todo tool handlers
│   │   └── prompts/assistant_prompt.py
│   └── orchestration/agent/
│       ├── orchestrator.py            # dispatch entry points and specialist/subagent integration
│       └── assistant_task_worker.py   # renamed legacy background queue if still needed
├── data/
│   ├── models_sqlite.py               # ORM models
│   ├── migrations.py                  # v15/v16 migrations
│   ├── unified_config.py              # assistant_tasks.* getters
│   └── repos/
│       ├── assistant_task_repository.py
│       ├── assistant_task_attempt_repository.py
│       ├── assistant_task_adjudication_repository.py
│       ├── assistant_task_board_repository.py
│       ├── assistant_meeting_repository.py
│       └── assistant_todo_repository.py
├── desktop_api/
│   ├── routers/assistant_tasks.py
│   ├── schemas.py
│   ├── ui_events.py
│   └── ui_event_projector.py
└── utils/
    └── events.py                      # internal blinker task events

tests/
├── data/
│   ├── test_assistant_task_migration.py
│   └── test_assistant_task_repositories.py
├── business/agents/
│   ├── test_task_dispatch_async.py
│   ├── test_task_adjudication.py
│   ├── test_task_recovery.py
│   ├── test_task_board_claims.py
│   ├── test_task_meetings.py
│   └── test_task_todos.py
├── desktop_api/
│   ├── test_assistant_task_api.py
│   └── test_assistant_task_events.py
├── integration/
│   ├── test_assistant_task_graph_smoke.py
│   └── test_assistant_task_cutover.py
└── guardrails/
    ├── test_assistant_task_boundaries.py
    └── test_assistant_task_transition_source.py
```

**Structure Decision**: Implement a dedicated `business/task_collaboration` layer instead of placing task state in routers, React stores, or `AgentLoop`. The layer owns deterministic task semantics; Orchestrator and tool handlers become adapters. Existing `workflow_transitions` remain useful for Debug Inspector/audit, but task UI and recovery must read the new repositories.

## Migration and Cutover

SQLite v15/v16 is a one-way local schema upgrade for a single-user, unpublished feature branch. v15 MUST create the assistant task collaboration tables without changing DuckDB or recording data; v16 MUST add partial unique indexes that enforce at most one active TaskAttempt per Task and per executor.

- `pending_assistant_tasks` is not the new Task model. It remains a legacy background queue for `codify_tool` / `fix_tool_bug` until implementation explicitly renames it to `assistant_background_jobs` with a compatibility repository. The unified Task model MUST use new `assistant_tasks*` tables.
- Existing `workflow_transitions` remain debug/audit records. They are not a sufficient business source after cutover.
- Default MVP cutover mode is **Clean-start guard**: if any legacy active/suspended delegation exists at startup, expose it through legacy observability only and block new unified task dispatch until the legacy run is completed or failed.
- **Backfill** is allowed only if an implementation task explicitly opts in before schema work: convert `assistant_delegation_started` rows plus child session status into `assistant_tasks` rows, with `suspended/waiting_system` for active/suspended child sessions and pending adjudication if no safe checkpoint exists.
- No double-write: once unified dispatch is enabled, Assistant task UI/API reads only task collaboration repositories and snapshot endpoints; legacy transition writes may continue only as Debug Inspector breadcrumbs.
- The implementation MUST include a migration/cutover guard test proving routers and React stores do not derive task truth from `workflow_transitions`.

## Dispatch and Concurrency Model

- The main Assistant is a graph coordinator, not a work executor. User work TaskAttempt rows may only execute under `ephemeral_subagent` or `specialist`; pure dialogue/clarification remains outside the TaskAttempt executor pool.
- Dispatch is controlled by `TaskDispatcher`, which owns scheduling, parking, and parent re-entry. Tool handlers return accepted `taskId` / `graphId` after durable enqueue and do not block on child completion.
- Workers are bounded by `assistant_tasks.dispatch.max_workers`; every worker opens its own Repository / SQLAlchemy session scope. No mutable activation cache, shared SQLAlchemy session, process registry, or tool output state may be shared across worker threads without an explicit lock or independent session.
- Executor capacity=1 is DB-backed: claim/start uses conditional Repository updates and active-attempt indexes, not only in-process locks.
- Result回流 wakes the parent coordinator through business service re-entry after the child Task reaches pending adjudication or terminal state; it must preserve AgentLoop tool-call/tool-result pairing.

## Checkpoint and Idempotency Protocol

- Every side-effecting task step MUST record an `AssistantTaskOperation` with a stable operation key before execution and mark completion after success.
- Recovery may auto-resume only when the latest checkpoint proves all prior side effects are complete or safe to retry.
- Non-idempotent or unknown side effects MUST NOT be retried automatically after crash/restart; they create a parent-side adjudication with a safe explanation.
- Late attempt results are accepted as idempotent no-ops only when their fence token is stale; they must not update Task state or emit success UI events.
- High-risk confirmation, user clarification, and capability grants keep their existing fail-closed protocols and must not be bypassed by checkpoint replay.

## Stop, Cancel, and Replan Ordering

- Stop is non-terminal and applies to the current user request graph only. It changes active tasks to `suspended/user_stop` at safe points and can be superseded only by explicit continue or terminal cancel.
- Cancel is terminal. A cancel at graph version N wins over replan operations at version <=N, and cancelled downstream tasks cannot be revived by late planning.
- Late success from a cancelled task is ignored and recorded as a rejected late result.
- Replan must create new tasks or edges at a newer graph version and must check ancestor cancel state before activation.

## Privacy, Retention, and Brain Boundary

- Task descriptions, meeting messages, Todo text, adjudication summaries, and result previews are persisted with the assistant session and exposed only through sanitized DTO/UI event projections.
- Todo entries are never distilled into brain memory.
- Meeting/task content is not injected into brain memory directly; only ordinary assistant messages and their existing metadata paths may influence memory.
- Task collaboration rows follow assistant session archive/delete visibility: archived or deleted sessions are soft-hidden from normal task APIs and UI resync; authorized debug/audit paths may still read safe projections.
- Task collaboration services do not introduce physical delete methods. If an existing session retention path later owns physical cleanup, it must go through repositories and preserve brain "no physical delete" constraints. Exception: Todo `replace_for_executor` physically deletes superseded Todo rows — Todos are per-task executor checklists that never enter brain distillation (FR-021), so batch replacement of a single task's checklist is safe and the no-physical-delete rule above is scoped to brain-eligible data.

## UI Event Contract Sync

- Every new public event type MUST be registered in `src/desktop_api/ui_events.py`, projected through `src/desktop_api/ui_event_projector.py`, and mirrored in frontend event contracts in `frontend/src/api/uiEvents.ts`.
- Backend registry tests and frontend event validator/type tests MUST be updated in the same implementation slice as `assistant.task_graph.changed`, `assistant.task_board.changed`, `assistant.meeting.changed`, and `assistant.todo.changed`.
- Event payload examples in `contracts/assistant-task-collaboration.md` are the allowlist source for public task collaboration event fields; frontend stores must not branch on internal blinker event names or `workflow_transitions`.

## Observability and Failure Bridge

- Structured debug-safe logs/counters MUST cover: `task_created`, `attempt_started`, `attempt_fenced`, `late_result_rejected`, `claim_conflict`, `adjudication_decided`, `graph_stopped`, `graph_cancelled`, `root_graph_failed`.
- Only a root graph terminal failure that reaches the user creates or updates `assistant_run_failures`. Partial task failures stay in the graph/adjudication layer.
- Successful replan/continue of a graph-local failure must not create duplicate assistant failure cards and should resolve any graph-local failure display.
- Local release gate: any nonzero duplicate side effect, permanent `running` task after recovery, or unsafe recovery auto-replay in controlled smoke tests blocks enabling unified dispatch by default.
- Local rollback posture: because this is a single-user desktop schema migration, rollback means restoring the pre-upgrade app data backup or disabling unified task dispatch behind config if implemented; down-migration is not required unless implementation introduces a user-visible release channel.

## Phase Plan

`/speckit.tasks` MUST preserve these phase headings and dependencies. P3/P4 tasks may be generated for visibility, but they MUST depend on P1/P2 gate tests and should not be implemented before those gates pass.

1. **P1 durable task foundation (MVP gate A)**: migration/cutover mode, repositories, service, task graph snapshot, task/attempt state machine, async delegation acceptance result, crash recovery fences, existing subagent observability cutover. Gate: graph snapshot, crash recovery, late-result rejection, and old transition cutover tests pass.
2. **P2 adjudication and stop/cancel (MVP gate B)**: parent-side adjudication queue, accept/return/abandon transitions, task-level vs run-level failure bridge, stop/continue over current request graph, cascading cancel with graph version fences. Gate: stop current request graph, cancel/replan race, and root failure bridge tests pass.
3. **P3 collaboration paradigms**: directed delegation and board share one assignment model; atomic board claim/lease; fallback temporary executor; supervised meeting channels with budget and message-only permission boundary; `ask_parent`, persisted agent-to-agent question routing, and capability request flow. Starts only after MVP gates A/B pass.
4. **P4 private Todo**: per-executor checklist model, agent tool, UI panel, persistence across restart, no task graph/court-adjudication coupling. Starts only after task graph display projection is stable.
5. **Cutover and guards**: remove UI dependence on transition-derived subagent list; keep legacy transition writes only as debug/audit breadcrumbs; add guard tests that new task UI/API does not read Repository from router/UI.

## Complexity Tracking

No constitution violations.
