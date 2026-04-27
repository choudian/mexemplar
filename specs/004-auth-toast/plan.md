# Implementation Plan: 高危操作确认 Toast 化（Auth Toast）

**Branch**: `004-auth-toast` | **Date**: 2026-04-27 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-auth-toast/spec.md`

**Note**: This plan is the `/speckit.plan` output for replacing Assistant high-risk tool modal confirmations with non-blocking confirmation toasts.

## Summary

把 Assistant 的高危工具确认从 `QMessageBox.question` 模态弹窗改为主窗口右下角的非阻塞确认浮层。实现上保留现有 `builtin_general_tools` 的 request_id + `threading.Event` 等待模型和 `pyqtSignal` 跨线程通道，在 UI 端新增独立于普通 Toast 的 `AuthToastSurface`/队列管理，并在业务层增加会话级自动放行状态、脱敏结构化决策日志、队列自动放行辅助接口。对话页新增“免确认” Toggle，与浮层的“全部允许”共享同一会话级状态；从任一入口开启自动放行时立即清空当前会话的待展示确认队列；新对话入口除复位外还要收敛并清空旧会话未决确认。

## Technical Context

**Language/Version**: Python 3.11+（项目运行时兼容 Python 3.12）  
**Primary Dependencies**: PyQt6、现有 AgentLoop/ToolDefinition pre_hook、`threading.Event`、项目 logger；不引入新第三方依赖  
**Storage**: N/A；会话级豁免为内存状态，不落 SQLite/DuckDB，不新增迁移  
**Testing**: pytest、pytest-qt/Qt offscreen 习惯、现有 `tests/test_hook_protocol.py` 与 `tests/ui/` 测试风格  
**Target Platform**: Windows 桌面 PyQt6 GUI；保持现有 PowerShell/Windows 运行路径  
**Project Type**: Desktop application with business-layer Agent tooling  
**Performance Goals**: 确认浮层显示期间主窗口交互响应延迟 <= 100ms；Top Toggle/浮层状态同步同帧或下一帧内完成  
**Constraints**: 不改变 Worker 阻塞确认模型；浮层超时不得晚于 `_CONFIRM_TIMEOUT = 120s` 且 UI 关闭与 Worker 超时返回的时间差 <= 1s；不展示完整文件内容/完整工具参数；普通 Toast 与确认浮层生命周期独立；新对话不得保留旧会话未决确认  
**Scale/Scope**: 覆盖 Assistant 的 `write_file` / `edit_file` / `exec` 三类高危工具；压测目标为 5 个并发 Worker 确认请求 FIFO 处理且无丢失

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required | Status |
|-----------|---------------|-------------------|--------|
| I. Layered Boundaries & Event Coordination | Does the design preserve `UI -> business -> execution -> data/driver` direction, and are all cross-module notifications routed through `src/utils/events.py`? | Touched layers: UI (`src/ui/`), business tools (`src/business/agents/tools/builtin_general_tools.py`). No new blinker event; existing `pyqtSignal` is the current synchronous-return confirmation boundary and remains a justified intra UI/Worker bridge. | PASS |
| II. Data Boundary & Persistence Discipline | Are SQLite and DuckDB responsibilities explicit, are Repository boundaries preserved, and do `network_requests` reads keep filtering/desensitization contracts? | No SQLite/DuckDB/Repository work; no recording data access; no migrations. | PASS |
| III. Unified Config & Secret Handling | Do all new settings flow through `UnifiedConfigManager`, and do all secrets stay out of code/config files? | No new persistent config or secrets. Auto-approve scope is session memory only. Structured logs are sanitized and must not include full content. | PASS |
| IV. Verifiable Delivery | Does the plan include automated coverage for deterministic logic plus wiring smoke/guard tests for architecture rewires? | Add behavior tests for confirmation state/result logging, UI queue/toast decisions, new-chat reset, top Toggle sync, and guard tests that Assistant path no longer imports/uses `QMessageBox.question`. | PASS |
| V. Living Docs & Spec-Driven Delivery | Are required active docs identified for update, and are temporary notes confined to `docs/local/`? | Speckit artifacts under `specs/004-auth-toast/`; update `AGENTS.md` active plan pointer. No active architecture docs required unless implementation changes public runtime structure beyond this feature. | PASS |

## Project Structure

### Documentation (this feature)

```text
specs/004-auth-toast/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── auth-confirmation-ui.md
└── tasks.md             # created later by /speckit.tasks
```

### Source Code (repository root)

```text
src/
├── business/
│   └── agents/
│       └── tools/
│           └── builtin_general_tools.py    # confirmation state, auto-approve helpers, sanitized logging
├── ui/
│   ├── main_window.py                       # host state for independent auth toast surface(s)
│   ├── mixins/
│   │   ├── agent_bridge_mixin.py            # keep register_confirm_mechanism wiring
│   │   └── agent_handler_mixin.py           # replace QMessageBox confirmation slot with queue/toast flow
│   ├── resources/
│   │   └── styles.qss                       # auth toast and top toggle styles
│   └── widgets/
│       ├── chat_widget.py                   # conversation header + "免确认" Toggle + new-chat reset signal/callback
│       └── auth_toast.py                    # new non-modal confirmation surface
└── utils/
    └── logger.py                            # existing logging path only; no new event module entry

tests/
├── test_auth_toast_confirmation.py          # business confirmation state/logging/auto-approve behavior
├── test_hook_protocol.py                    # existing hook confirmation regressions remain green
└── ui/
    ├── test_auth_toast_surface.py           # non-modal surface, buttons, timeout, no manual close
    ├── test_chat_widget_auth_toggle.py      # toggle sync/new-chat reset contract
    └── test_agent_handler_mixin.py          # queue handling and QMessageBox guard coverage
```

**Structure Decision**: Keep the synchronous confirmation ownership in `builtin_general_tools` because the Worker already blocks there and the hook protocol tests assert the high-risk tool pre_hook boundary. Add UI-only surface/queue code under `src/ui/` and avoid new data, execution, recording, or cross-module event surfaces.

## Phase 0 Research

Research completed in [research.md](./research.md). No `NEEDS CLARIFICATION` items remain.

Key decisions:
- Preserve the existing `request_id` + `Event` confirmation protocol and extend it with optional decision metadata instead of replacing it with a new async workflow.
- Use a dedicated confirmation toast surface/queue rather than reusing `_active_toast`, because ordinary Toast currently behaves as a single auto-dismiss notification.
- Keep auto-approve state in business-layer tool confirmation helpers so future high-risk requests can bypass UI before signal emission, while UI drains already queued requests when the user clicks "全部允许" or enables the top Toggle.
- Use sanitized summaries generated at pre_hook time for both UI display and structured logs.

## Phase 1 Design

Design artifacts:
- [data-model.md](./data-model.md)
- [contracts/auth-confirmation-ui.md](./contracts/auth-confirmation-ui.md)
- [quickstart.md](./quickstart.md)

Implementation approach:
1. In `builtin_general_tools.py`, introduce a small internal confirmation request record containing `request_id`, `tool_name`, sanitized `summary`, `created_at`, `decision`, and `source`; keep `_pending_confirms` protected by `_confirm_lock`.
2. Change high-risk pre_hooks to call a typed helper such as `_confirm_or_reject(tool_name, summary)` so the UI/logging path gets stable metadata without parsing prose.
3. Add session auto-approve helpers (`set_auto_approve_enabled`, `is_auto_approve_enabled`, `reset_auto_approve`, and a queue-drain helper). When enabled from either the toast or the top Toggle, high-risk pre_hooks return success immediately, already queued requests are drained immediately, and every decision path logs `source` consistently.
4. Replace `AgentHandlerMixin._on_confirm_action_requested` with a non-blocking UI queue. The slot enqueues request ids/messages, displays one `AuthToastSurface` at a time, calls `set_confirm_result` on accept/reject/timeout, and owns the timing assertions/hooks needed to verify UI responsiveness and timeout convergence.
5. Add `AuthToastSurface` as a separate `QFrame`/widget object with three explicit buttons and a single-shot timeout. It must have no close button and must not close from outside-click handling.
6. Update `MainWindow.resizeEvent` so ordinary `_active_toast` and the active auth toast are repositioned independently and do not cover each other.
7. Add a lightweight conversation header in `ChatWidget` with a checkable “免确认” Toggle and expose state-change/new-chat reset signals or callbacks to MainWindow. Enabling the Toggle drains already queued confirmations the same way as “全部允许”. New chat calls `reset_auto_approve`, settles any visible or queued prior-session confirmations by reject/timeout semantics, and updates the toggle off.
8. Add sanitized structured logs for every final decision path: accept, reject, timeout, and auto-approve. Do not log full file content, full replacement text, or full command beyond configured summary.

## Post-Design Constitution Check

| Principle | Result | Evidence |
|-----------|--------|----------|
| I. Layered Boundaries & Event Coordination | PASS | UI owns rendering/queue; business tools own confirmation decision state. Existing `pyqtSignal` bridge stays as the synchronous confirmation exception already present in code; no lower layer imports UI. |
| II. Data Boundary & Persistence Discipline | PASS | No data store access, migration, DuckDB query, or Repository bypass. |
| III. Unified Config & Secret Handling | PASS | No new config or secrets. Logs are explicitly sanitized. |
| IV. Verifiable Delivery | PASS | Planned tests cover deterministic business state, UI queue, timeout, new-chat reset, toggle sync, ordinary Toast coexistence, and a `QMessageBox.question` guard. |
| V. Living Docs & Spec-Driven Delivery | PASS | Speckit artifacts generated under `specs/004-auth-toast/`; `AGENTS.md` active plan pointer updated. |

## Complexity Tracking

No constitution violations or complexity exceptions.

## Validation Commands

```powershell
uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_chat_widget_auth_toggle.py -q
uv run python -m pytest tests/test_hook_protocol.py tests/ui/test_agent_handler_mixin.py -q
uv run black --check src tests
uv run flake8 src tests
```

## Phase 2 Planning Notes

`/speckit.tasks` should decompose implementation in this order:
1. Business confirmation state/logging helpers and tests.
2. UI `AuthToastSurface` component and unit/UI tests.
3. MainWindow/AgentHandler queue integration and regression guard against `QMessageBox.question`.
4. ChatWidget Toggle/new-chat reset integration and tests.
5. Styling, quickstart validation, and targeted regression run.
