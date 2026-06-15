"""022 process-event-push: 工具层(wait_for_process_event_handler)单测.

覆盖任务 T010 / T022 / 集成测中工具入口的归属/钳位/cursor 返回。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


from src.business.agents.tools import command_tools
from src.business.agents.tools.builtin_contracts import use_tool_runtime
from src.execution.process_manager import get_process_manager


def _obj(result: str) -> dict:
    return json.loads(result)


def _python_script(tmp_path: Path, name: str, code: str) -> str:
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f'"{sys.executable}" "{script.name}"'


def _start_in_session(tmp_path: Path, code: str, session_id: str) -> str:
    """Start a process via exec_handler under a specific runtime session id."""
    command = _python_script(tmp_path, f"start-{session_id}.py", code)
    with use_tool_runtime(
        session_id=session_id,
        tool_call_id="call-022",
        tool_name="exec",
        workspace_root=tmp_path,
    ):
        result = _obj(command_tools.exec_handler(command, mode="background", cwd="."))
    return result["payload"]["processId"]


def test_process_missing_returns_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with use_tool_runtime(
        session_id="owner-022",
        tool_call_id="call-1",
        tool_name="wait_for_process_event",
        workspace_root=tmp_path,
    ):
        result = _obj(
            command_tools.wait_for_process_event_handler("proc_does_not_exist", timeoutMs=100)
        )
    assert result["outcome"] == "rejected"
    assert result["error"]["code"] in {
        "process_not_found",
        "process_unavailable_after_restart",
    }


def test_permission_denied_for_other_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pid = _start_in_session(
        tmp_path,
        "import time; time.sleep(5)\n",
        session_id="owner-022",
    )
    try:
        with use_tool_runtime(
            session_id="attacker-022",
            tool_call_id="call-2",
            tool_name="wait_for_process_event",
            workspace_root=tmp_path,
        ):
            result = _obj(command_tools.wait_for_process_event_handler(pid, timeoutMs=100))
        assert result["outcome"] == "rejected"
        assert result["error"]["code"] == "permission_denied"
    finally:
        get_process_manager().stop(pid, force=True)


def test_default_timeout_used_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    pm = get_process_manager()

    def stub(process_id, *, since_cursor, timeout_ms):
        captured["timeout_ms"] = timeout_ms
        captured["since_cursor"] = since_cursor
        return {
            "events": [],
            "cursor": 0,
            "status": "completed",
            "exitCode": 0,
            "cursorTooOld": False,
        }

    monkeypatch.setattr(pm, "wait_for_event", stub)

    pid = _start_in_session(
        tmp_path,
        "import sys; sys.exit(0)\n",
        session_id="owner-default",
    )
    with use_tool_runtime(
        session_id="owner-default",
        tool_call_id="call-default",
        tool_name="wait_for_process_event",
        workspace_root=tmp_path,
    ):
        _obj(command_tools.wait_for_process_event_handler(pid))

    # default_timeout_ms config default is 30_000.
    assert captured["timeout_ms"] == 30_000
    assert captured["since_cursor"] is None


def test_timeout_ms_clamped_to_max(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    captured = {}

    pm = get_process_manager()

    def stub(process_id, *, since_cursor, timeout_ms):
        captured["timeout_ms"] = timeout_ms
        return {
            "events": [],
            "cursor": 0,
            "status": "completed",
            "exitCode": 0,
            "cursorTooOld": False,
        }

    monkeypatch.setattr(pm, "wait_for_event", stub)

    pid = _start_in_session(
        tmp_path,
        "import sys; sys.exit(0)\n",
        session_id="owner-clamp",
    )
    with use_tool_runtime(
        session_id="owner-clamp",
        tool_call_id="call-clamp",
        tool_name="wait_for_process_event",
        workspace_root=tmp_path,
    ):
        _obj(command_tools.wait_for_process_event_handler(pid, timeoutMs=10_000_000))
    # max_timeout_ms config default is 600_000.
    assert captured["timeout_ms"] == 600_000


def test_handler_returns_cursor_field_even_on_cursor_too_old(tmp_path, monkeypatch):
    """T022: handler MUST keep cursor field present when cursorTooOld=true."""
    monkeypatch.chdir(tmp_path)
    pid = _start_in_session(
        tmp_path,
        "import time; time.sleep(5)\n",
        session_id="owner-cto",
    )
    try:
        # Force a tiny event buffer + tiny chunk threshold so the deque
        # overflows quickly and old cursors get evicted.
        pm = get_process_manager()
        monkeypatch.setattr(pm, "_load_event_config", lambda: (3, 10000, 80))
        # Generate many emits manually.
        record = pm.get(pid)
        from collections import deque

        record.events = deque(maxlen=3)
        with pm._lock:
            for i in range(8):
                pm._emit_event_locked(record, "log_chunked", {"totalChars": i, "deltaChars": 1})
        with use_tool_runtime(
            session_id="owner-cto",
            tool_call_id="call-cto",
            tool_name="wait_for_process_event",
            workspace_root=tmp_path,
        ):
            result = _obj(
                command_tools.wait_for_process_event_handler(pid, sinceCursor=1, timeoutMs=300)
            )
        assert result["outcome"] == "success"
        payload = result["payload"]
        assert payload["cursorTooOld"] is True
        assert "cursor" in payload and payload["cursor"] >= record.events[-1].sequence
        assert payload["processId"] == pid
    finally:
        get_process_manager().stop(pid, force=True)


def test_handler_returns_internal_error_on_manager_exception(tmp_path, monkeypatch):
    """U2: ProcessManager internal exception maps to tool_internal_error."""
    monkeypatch.chdir(tmp_path)
    pid = _start_in_session(
        tmp_path,
        "import time; time.sleep(5)\n",
        session_id="owner-int",
    )
    try:
        pm = get_process_manager()

        def boom(*args, **kwargs):
            raise RuntimeError("simulated internal failure")

        monkeypatch.setattr(pm, "wait_for_event", boom)
        with use_tool_runtime(
            session_id="owner-int",
            tool_call_id="call-int",
            tool_name="wait_for_process_event",
            workspace_root=tmp_path,
        ):
            result = _obj(command_tools.wait_for_process_event_handler(pid, timeoutMs=100))
        assert result["outcome"] == "rejected"
        assert result["error"]["code"] == "internal_error"
    finally:
        # bypass the monkeypatched wait by stopping via direct call.
        # but stop also goes through ProcessManager; use a fresh instance attribute.
        get_process_manager().stop(pid, force=True)
