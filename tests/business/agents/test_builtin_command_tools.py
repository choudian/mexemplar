import json
import sys
from pathlib import Path

from src.business.agents.tools import command_tools
from src.business.agents.tools.builtin_contracts import use_tool_runtime
from src.business.agents.tools.builtin_permissions import is_safe_exec_command
from src.business.agents.tools.output_governance import (
    get_tool_output_health_counters,
    load_tool_output_handler,
)
from src.data.repos.tool_output_repository import ToolOutputRepository
from src.execution.process_manager import get_process_manager
from src.utils.agent_tool_health import reset_agent_tool_health_for_tests


def _obj(result: str) -> dict:
    return json.loads(result)


def _python_script(tmp_path: Path, name: str, code: str) -> str:
    script = tmp_path / name
    script.write_text(code, encoding="utf-8")
    return f'"{sys.executable}" "{script.name}"'


def test_exec_returns_bounded_success_and_failure_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    command = _python_script(tmp_path, "success.py", "print('ok')\n")
    result = _obj(command_tools.exec_handler(command, cwd="."))

    assert result["outcome"] == "success"
    assert result["payload"]["exitCode"] == 0
    assert "ok" in result["payload"]["stdout"]
    assert result["payload"]["cwd"] == "."


def test_exec_timeout_is_stable_outcome(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = _obj(
        command_tools.exec_handler(
            _python_script(tmp_path, "timeout.py", "import time\ntime.sleep(1)\n"),
            cwd=".",
            timeoutMs=50,
        )
    )

    assert result["outcome"] == "timeout"
    assert result["error"]["code"] == "command_timeout"


def test_exec_rejects_external_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    command = _python_script(tmp_path, "external-cwd.py", "print('no')\n")
    result = _obj(command_tools.exec_handler(command, cwd=str(tmp_path.parent)))

    assert result["outcome"] == "rejected"
    assert result["error"]["code"] == "command_rejected"


def test_exec_rejects_path_reader_command_targeting_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-command-read.txt"
    outside.write_text("secret\n", encoding="utf-8")
    try:
        result = _obj(command_tools.exec_handler("cat ../outside-command-read.txt", cwd="."))
    finally:
        outside.unlink(missing_ok=True)

    assert result["outcome"] == "rejected"
    assert result["error"]["code"] == "command_rejected"


def test_exec_rejects_shell_syntax_inline_code_and_parent_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-command-write.txt"
    cases = [
        "echo ok\nwhoami",
        f'echo unsafe > "{outside}"',
        f'"{sys.executable}" -c "print(1)"',
        "git -C .. status",
    ]

    for command in cases:
        result = _obj(command_tools.exec_handler(command, cwd="."))
        assert result["outcome"] == "rejected"
        assert result["error"]["code"] == "command_rejected"
    assert not outside.exists()
    assert is_safe_exec_command("echo ok\nwhoami") is False


def test_exec_large_output_creates_recoverable_raw_reference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path / "data",
    )

    command = _python_script(tmp_path, "large.py", "print('x' * 100000)\n")
    result = _obj(command_tools.exec_handler(command, cwd="."))

    assert result["outcome"] == "success"
    assert result["limits"]["truncated"] is True
    assert len(json.dumps(result, ensure_ascii=False)) < 12000
    reference_id = result["references"][0]["referenceId"]
    assert ToolOutputRepository().load_authorized_bytes(
        reference_id,
        session_id="_default_agent_session",
        workspace_root=tmp_path,
    )
    loaded = _obj(
        load_tool_output_handler(
            reference_id,
            sessionId="_default_agent_session",
            workspaceRoot=str(tmp_path),
            maxBytes=50000,
        )
    )
    assert reference_id.startswith("out_")
    assert loaded["outcome"] == "success"
    assert "x" * 1000 in loaded["payload"]["content"]


def test_process_cleanup_records_health_counters(tmp_path, monkeypatch):
    reset_agent_tool_health_for_tests()
    monkeypatch.chdir(tmp_path)
    command = _python_script(tmp_path, "cleanup.py", "import time\ntime.sleep(5)\n")

    started = _obj(command_tools.exec_handler(command, cwd=".", mode="background"))
    process_id = started["payload"]["processId"]
    try:
        cleanup = get_process_manager().cleanup()
        counters = get_tool_output_health_counters()

        assert cleanup["stopped"] >= 1
        assert counters["process_cleanup_stopped"] >= 1
    finally:
        command_tools.process_stop_handler(process_id, force=True)


def test_background_process_lifecycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command = _python_script(
        tmp_path,
        "background.py",
        "import time\nprint('start', flush=True)\ntime.sleep(0.1)\nprint('done', flush=True)\n",
    )

    started = _obj(command_tools.exec_handler(command, cwd=".", mode="background"))
    duplicate = _obj(command_tools.exec_handler(command, cwd=".", mode="background"))
    process_id = started["payload"]["processId"]
    waited = _obj(command_tools.process_wait_handler(process_id, timeoutMs=2000))
    logs = _obj(command_tools.process_logs_handler(process_id, tailChars=4000))
    closed = _obj(command_tools.process_close_handler(process_id))
    missing = _obj(command_tools.process_poll_handler("proc_previous_session"))

    assert started["outcome"] == "background_started"
    assert duplicate["payload"]["duplicate"] is True
    assert waited["payload"]["status"] in {"completed", "failed"}
    assert "start" in logs["payload"]["logs"]
    assert closed["payload"]["status"] == "closed"
    assert missing["error"]["code"] == "process_unavailable_after_restart"


def test_process_lifecycle_rejects_different_session_access(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command = _python_script(tmp_path, "session.py", "import time\ntime.sleep(1)\n")
    with use_tool_runtime(
        session_id="session-a",
        tool_call_id="call-a",
        tool_name="exec",
        workspace_root=tmp_path,
    ):
        started = _obj(command_tools.exec_handler(command, cwd=".", mode="background"))
    process_id = started["payload"]["processId"]
    try:
        with use_tool_runtime(
            session_id="session-b",
            tool_call_id="call-b",
            tool_name="process_poll",
            workspace_root=tmp_path,
        ):
            denied = _obj(command_tools.process_poll_handler(process_id))

        assert denied["outcome"] == "rejected"
        assert denied["error"]["code"] == "permission_denied"
    finally:
        with use_tool_runtime(
            session_id="session-a",
            tool_call_id="call-c",
            tool_name="process_stop",
            workspace_root=tmp_path,
        ):
            command_tools.process_stop_handler(process_id, force=True)


def test_process_limits_and_visible_cwd_are_enforced(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    command = _python_script(tmp_path, "limit.py", "import time\ntime.sleep(2)\n")
    monkeypatch.setattr(
        command_tools,
        "get_config_int",
        lambda getter, default, **kwargs: {
            "get_agent_tools_process_max_background_processes": 1,
            "get_agent_tools_process_log_tail_chars": 8,
            "get_agent_tools_process_default_timeout_ms": 10,
            "get_agent_tools_process_max_timeout_ms": 20,
        }.get(getter, default),
    )

    started = _obj(command_tools.exec_handler(command, cwd=".", mode="background"))
    second_command = _python_script(tmp_path, "limit-2.py", "import time\ntime.sleep(2)\n")
    rejected = _obj(command_tools.exec_handler(second_command, cwd=".", mode="background"))
    process_id = started["payload"]["processId"]
    try:
        logs = _obj(command_tools.process_logs_handler(process_id, tailChars=1000))
        waited = _obj(command_tools.process_wait_handler(process_id, timeoutMs=1000))

        assert started["payload"]["cwd"] == "."
        assert rejected["error"]["code"] == "process_limit_reached"
        assert logs["limits"]["visibleChars"] <= 8
        assert waited["payload"]["status"] == "running"
    finally:
        command_tools.process_stop_handler(process_id, force=True)
