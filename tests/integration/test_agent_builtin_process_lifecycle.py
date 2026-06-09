import json
import sys
from pathlib import Path

from src.business.agents.tools import command_tools


def _obj(result: str) -> dict:
    return json.loads(result)


def _python_script(tmp_path: Path, name: str, code: str) -> str:
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f'"{sys.executable}" "{script.name}"'


def test_process_lifecycle_tools_manage_current_session_process(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command = _python_script(
        tmp_path,
        "lifecycle.py",
        "import time\nprint('ready', flush=True)\ntime.sleep(0.2)\n",
    )

    started = _obj(command_tools.exec_handler(command, mode="background", cwd="."))
    process_id = started["payload"]["processId"]
    listed = _obj(command_tools.process_list_handler(status="running"))
    polled = _obj(command_tools.process_poll_handler(process_id))
    waited = _obj(command_tools.process_wait_handler(process_id, timeoutMs=2000))
    logs = _obj(command_tools.process_logs_handler(process_id))
    closed = _obj(command_tools.process_close_handler(process_id))

    assert any(item["processId"] == process_id for item in listed["payload"]["processes"])
    assert polled["payload"]["processId"] == process_id
    assert waited["payload"]["status"] in {"completed", "failed"}
    assert "ready" in logs["payload"]["logs"]
    assert closed["payload"]["status"] == "closed"


def test_process_stop_and_send_input_denial(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command = _python_script(tmp_path, "stop.py", "import time\ntime.sleep(5)\n")
    started = _obj(command_tools.exec_handler(command, mode="background", cwd="."))
    process_id = started["payload"]["processId"]

    stdin_denied = _obj(command_tools.process_send_input_handler(process_id, "q\n"))
    stopped = _obj(command_tools.process_stop_handler(process_id, force=True))
    unavailable = _obj(command_tools.process_poll_handler("proc_old_sidecar"))

    assert stdin_denied["error"]["code"] == "permission_denied"
    assert stopped["payload"]["status"] in {"terminated", "failed"}
    assert unavailable["error"]["code"] == "process_unavailable_after_restart"
