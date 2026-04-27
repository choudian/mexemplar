# Quickstart: 高危操作确认 Toast 化（Auth Toast）

## Scope

Implement and validate the Assistant-only high-risk tool confirmation UX:

- `write_file`
- `edit_file`
- `exec` when not in the existing safe-command allowlist

PM Agent, Trial Agent, `IntentConfirmationUI`, and `ToolExecutionDialog` must remain unchanged.

## Implementation Checklist

1. Add business confirmation metadata and auto-approve helpers in `src/business/agents/tools/builtin_general_tools.py`.
2. Add `src/ui/widgets/auth_toast.py` for the non-modal confirmation surface.
3. Replace `AgentHandlerMixin._on_confirm_action_requested` so it queues auth confirmations and no longer calls `QMessageBox.question`.
4. Keep `AgentBridgeMixin` registration of `_confirm_action_signal` intact.
5. Add a conversation header in `ChatWidget` with a checkable "免确认" Toggle.
6. Reset auto-approve on new chat and synchronize Toggle state with "全部允许".
7. Add QSS for auth toast and Toggle without changing ordinary Toast lifecycle.
8. Add targeted tests before running broader regressions.

## Manual Smoke Flow

1. Start the GUI.
2. Open Assistant chat.
3. Ask Assistant to perform a `write_file` operation.
4. Verify a bottom-right non-modal confirmation surface appears.
5. While the surface is visible, scroll chat history or interact with another visible main-window control.
6. Click "同意" and verify the tool continues.
7. Repeat and click "拒绝"; verify the tool is cancelled.
8. Repeat and click "全部允许"; trigger additional high-risk operations in the same chat and verify no new auth toast appears.
9. Start a new chat and verify the next high-risk operation shows the auth toast again.

## Targeted Validation Commands

```powershell
uv run python -m pytest tests/test_auth_toast_confirmation.py -q
uv run python -m pytest tests/ui/test_auth_toast_surface.py tests/ui/test_chat_widget_auth_toggle.py -q
uv run python -m pytest tests/test_hook_protocol.py tests/ui/test_agent_handler_mixin.py -q
```

## Full Local Gate

```powershell
uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_chat_widget_auth_toggle.py tests/test_hook_protocol.py tests/ui/test_agent_handler_mixin.py -q
uv run black --check src tests
uv run flake8 src tests
```

## Expected Evidence

- Business tests prove accept/reject/timeout/auto-approve each produce exactly one sanitized log event.
- UI tests prove `AuthToastSurface` is non-modal, has no close button, and emits only one terminal decision.
- Queue tests prove 5 concurrent requests are handled FIFO and none are dropped.
- Guard test proves Assistant confirmation no longer calls `QMessageBox.question`.
- Regression tests prove ordinary Toast still works and is not deleted by auth toast lifecycle.
