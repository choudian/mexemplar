"""022 process-event-push: 端到端行为契约测试.

覆盖任务 T011 / T016 / T023:走工具入口起真子进程,验证 wait → logs → wait
整链路;不直接调 ProcessManager。
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


def _runtime(tmp_path, session_id: str):
    return use_tool_runtime(
        session_id=session_id,
        tool_call_id="call-022-integ",
        tool_name="wait_for_process_event",
        workspace_root=tmp_path,
    )


def test_state_changed_end_to_end(tmp_path, monkeypatch):
    """T011: 工具入口起真进程 → 拿到 state_changed: failed, exitCode=1."""
    monkeypatch.chdir(tmp_path)
    cmd = _python_script(tmp_path, "fail.py", "import sys; sys.exit(1)\n")
    with _runtime(tmp_path, "integ-state"):
        started = _obj(command_tools.exec_handler(cmd, mode="background", cwd="."))
        pid = started["payload"]["processId"]
        result = _obj(command_tools.wait_for_process_event_handler(pid, timeoutMs=5000))
    assert result["outcome"] == "success"
    payload = result["payload"]
    assert payload["processId"] == pid
    sc = [e for e in payload["events"] if e["type"] == "state_changed"]
    assert sc, f"expected state_changed, got: {payload['events']}"
    assert sc[-1]["status"] == "failed"
    assert sc[-1]["exitCode"] == 1
    assert payload["status"] == "failed"
    assert payload["exitCode"] == 1
    assert payload["cursorTooOld"] is False


def test_log_chunked_end_to_end(tmp_path, monkeypatch):
    """T016: 工具入口起真进程,验证 wait → log_chunked → logs(取原文)→ wait 链路."""
    monkeypatch.chdir(tmp_path)
    pm = get_process_manager()
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 10000, 100))
    cmd = _python_script(
        tmp_path,
        "chunked.py",
        (
            "import sys, time\n"
            "for i in range(20):\n"
            "    sys.stdout.write('chunk-%02d-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n' % i)\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.01)\n"
            "time.sleep(0.5)\n"
        ),
    )
    with _runtime(tmp_path, "integ-log"):
        started = _obj(command_tools.exec_handler(cmd, mode="background", cwd="."))
        pid = started["payload"]["processId"]
        try:
            wait_result = _obj(command_tools.wait_for_process_event_handler(pid, timeoutMs=4000))
            chunked = [e for e in wait_result["payload"]["events"] if e["type"] == "log_chunked"]
            assert chunked, f"expected log_chunked, got: {wait_result['payload']['events']}"
            assert chunked[0]["deltaChars"] > 0
            assert chunked[0]["totalChars"] >= chunked[0]["deltaChars"]
            # Read actual log content via process_logs (separate tool).
            logs_result = _obj(command_tools.process_logs_handler(pid, tailChars=500))
            assert "chunk-00" in logs_result["payload"]["logs"]
            # No log content leaked into log_chunked payload.
            for c in chunked:
                for v in c.values():
                    assert "chunk-" not in str(v)
        finally:
            pm.stop(pid, force=True)


def test_full_lifecycle_log_then_state_change(tmp_path, monkeypatch):
    """T023: 覆盖 spec '典型一次交互' 七步——log_chunked → process_logs → state_changed."""
    monkeypatch.chdir(tmp_path)
    pm = get_process_manager()
    monkeypatch.setattr(pm, "_load_event_config", lambda: (64, 10000, 100))
    cmd = _python_script(
        tmp_path,
        "full.py",
        (
            "import sys, time\n"
            # Burst of output to trigger log_chunked.
            "for i in range(20):\n"
            "    sys.stdout.write(('payload-%02d-' % i) + 'b'*120 + '\\n')\n"
            "    sys.stdout.flush()\n"
            "    time.sleep(0.005)\n"
            "time.sleep(0.2)\n"
            "sys.exit(2)\n"
        ),
    )
    with _runtime(tmp_path, "integ-full"):
        started = _obj(command_tools.exec_handler(cmd, mode="background", cwd="."))
        pid = started["payload"]["processId"]
        # Step 1: wait → expect log_chunked.
        first = _obj(command_tools.wait_for_process_event_handler(pid, timeoutMs=3000))
        first_events = first["payload"]["events"]
        chunked = [e for e in first_events if e["type"] == "log_chunked"]
        assert chunked, f"first wait should see log_chunked, got: {first_events}"
        cursor = first["payload"]["cursor"]
        # Step 2: read logs.
        logs = _obj(command_tools.process_logs_handler(pid, tailChars=2000))
        assert "payload-" in logs["payload"]["logs"]
        # Step 3: loop wait until we see state_changed (may drain log_chunked
        # events first if reader is still flushing).
        state_change = None
        last_cursor = cursor
        for _ in range(20):
            poll_result = _obj(
                command_tools.wait_for_process_event_handler(
                    pid, sinceCursor=last_cursor, timeoutMs=2000
                )
            )
            events = poll_result["payload"]["events"]
            last_cursor = poll_result["payload"]["cursor"]
            for e in events:
                if e["type"] == "state_changed":
                    state_change = e
                    break
            if state_change is not None:
                break
            if poll_result["payload"]["status"] != "running":
                # Terminal already reached but no state_changed in this batch
                # (we missed the transition emit because process ended before
                # the first wait observed running). Force a final refresh.
                break
        assert state_change is not None, "expected state_changed within poll budget"
        assert state_change["status"] == "failed"
        assert state_change["exitCode"] == 2
        # Cursor must monotonically advance.
        assert last_cursor > cursor
