import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil
import pytest

from src.business.external_coding.cli_adapters import CliExternalCodingAdapter
from src.business.external_coding.models import (
    AttemptStatus,
    CodingPhase,
    ExternalCodingTool,
    LaunchMode,
    ProcessStartResult,
)
from src.execution.external_coding_process import (
    ExternalCodingProcessRunner,
    ExternalProcessSnapshot,
    ExternalProcessStartError,
    ExternalProcessTerminationOutcome,
    ProcessIdentity,
    _ManagedProcess,
    _dangerous_git_action,
    _resolve_executable,
    _safe_command_summary,
    _status_path,
    _terminate_process,
)
from src.execution import external_coding_process


class FakeConfig:
    def get_external_coding_claude_command(self):
        return "claude"

    def get_external_coding_codex_command(self):
        return "codex"

    def get_external_coding_claude_effort(self):
        return "max"

    def get_external_coding_codex_reasoning_effort(self):
        return "xhigh"

    def get_external_coding_plan_timeout_seconds(self):
        return 30

    def get_external_coding_run_timeout_seconds(self):
        return 60

    def get_external_coding_log_tail_chars(self):
        return 1000


def _prompt(tmp_path: Path, text: str = "请先写 PLAN.md\nsecret_token=abc") -> Path:
    path = tmp_path / "HANDOFF.md"
    path.write_text(text, encoding="utf-8")
    return path


def _register_test_managed(managed: _ManagedProcess) -> None:
    ExternalCodingProcessRunner._retain_managed(managed)


def _remove_test_managed(managed: _ManagedProcess) -> None:
    ExternalCodingProcessRunner._remove_managed(managed)


def _managed_for(pid: int, log_path: Path, create_time: float | None = None):
    return ExternalCodingProcessRunner._lookup_managed(
        pid=pid,
        process_create_time=create_time,
        status_path=_status_path(log_path),
    )


def _registry_has_pid(pid: int) -> bool:
    return any(
        managed.process.pid == pid for managed in ExternalCodingProcessRunner._registry.values()
    )


def test_terminal_process_result_rejects_unconfirmed_ownership() -> None:
    with pytest.raises(ValueError, match="cannot retain unconfirmed ownership"):
        ProcessStartResult(
            status=AttemptStatus.FAILED,
            command_summary="codex exec <prompt>",
            termination_unconfirmed=True,
        )


def test_running_process_types_require_unconfirmed_ownership() -> None:
    with pytest.raises(ValueError, match="running process results must retain"):
        ProcessStartResult(
            status=AttemptStatus.RUNNING,
            command_summary="codex exec <prompt>",
            pid=42120,
        )
    with pytest.raises(ValueError, match="running process snapshots must retain"):
        ExternalProcessSnapshot(
            status="running",
            pid=42120,
        )


def test_process_types_reject_creation_time_without_pid() -> None:
    with pytest.raises(ValueError, match="creation time requires a PID"):
        ProcessStartResult(
            status=AttemptStatus.FAILED,
            command_summary="codex exec <prompt>",
            process_create_time=100.0,
        )
    with pytest.raises(ValueError, match="creation time requires a PID"):
        ExternalProcessSnapshot(
            status="failed",
            process_create_time=100.0,
        )


def test_claude_headless_command_uses_print_stream_json_and_max_effort(tmp_path) -> None:
    adapter = CliExternalCodingAdapter(config=FakeConfig())
    artifact_dir = tmp_path / "artifacts"

    command = adapter._build_command(
        ExternalCodingTool.CLAUDE_CODE,
        CodingPhase.PLAN,
        _prompt(tmp_path),
        artifact_dir=artifact_dir,
    )

    assert command[:2] == ["claude", "-p"]
    assert "--output-format" in command
    assert "stream-json" in command
    assert "--verbose" in command
    assert command[command.index("--effort") + 1] == "max"
    assert "--safe-mode" in command
    assert "--disallowedTools" in command
    assert command[command.index("--add-dir") + 1] == str(artifact_dir.resolve())


def test_codex_headless_command_uses_json_and_xhigh_reasoning(tmp_path) -> None:
    adapter = CliExternalCodingAdapter(config=FakeConfig())
    artifact_dir = tmp_path / "artifacts"

    command = adapter._build_command(
        ExternalCodingTool.CODEX_CLI,
        CodingPhase.IMPLEMENT,
        _prompt(tmp_path),
        artifact_dir=artifact_dir,
    )

    assert command[:3] == ["codex", "exec", "--json"]
    assert 'model_reasoning_effort="xhigh"' in command
    assert command[command.index("--sandbox") + 1] == "workspace-write"
    assert "--ignore-user-config" in command
    assert command[command.index("--add-dir") + 1] == str(artifact_dir.resolve())
    assert command[command.index("-o") + 1] == str((artifact_dir / "RESULT.md").resolve())

    plan_command = adapter._build_command(
        ExternalCodingTool.CODEX_CLI,
        CodingPhase.PLAN,
        _prompt(tmp_path),
        artifact_dir=artifact_dir,
    )
    assert plan_command[plan_command.index("-o") + 1] == str((artifact_dir / "PLAN.md").resolve())


def test_resume_commands_reuse_external_session_reference(tmp_path) -> None:
    adapter = CliExternalCodingAdapter(config=FakeConfig())
    prompt = _prompt(tmp_path)
    artifact_dir = tmp_path / "artifacts"

    claude = adapter._build_command(
        ExternalCodingTool.CLAUDE_CODE,
        CodingPhase.IMPLEMENT,
        prompt,
        external_session_ref="claude-session-1",
    )
    codex = adapter._build_command(
        ExternalCodingTool.CODEX_CLI,
        CodingPhase.IMPLEMENT,
        prompt,
        artifact_dir=artifact_dir,
        external_session_ref="codex-thread-1",
    )

    assert claude[:4] == ["claude", "--resume", "claude-session-1", "-p"]
    assert codex[:3] == ["codex", "exec", "--json"]
    assert codex.index("--sandbox") < codex.index("resume")
    assert codex.index("--add-dir") < codex.index("resume")
    assert codex.index("-o") < codex.index("resume")
    assert codex[-3:-1] == ["resume", "codex-thread-1"]


def test_interactive_commands_use_real_tui_instead_of_headless_exec(tmp_path) -> None:
    adapter = CliExternalCodingAdapter(config=FakeConfig())
    prompt = _prompt(tmp_path)

    claude = adapter._build_command(
        ExternalCodingTool.CLAUDE_CODE,
        CodingPhase.PLAN,
        prompt,
        launch_mode=LaunchMode.INTERACTIVE,
    )
    codex = adapter._build_command(
        ExternalCodingTool.CODEX_CLI,
        CodingPhase.PLAN,
        prompt,
        launch_mode=LaunchMode.INTERACTIVE,
    )

    assert "-p" not in claude
    assert f"@{prompt}" in claude
    assert "exec" not in codex
    assert "--json" not in codex
    assert codex[-1].startswith(f"Follow the instructions in this file: {prompt}.")


def test_process_command_summary_does_not_persist_prompt_or_secret() -> None:
    summary = _safe_command_summary(
        ["claude", "-p", "做这个任务\nsecret_token=abc", "--output-format", "stream-json"]
    )

    assert "<prompt>" in summary
    assert "secret_token" not in summary

    codex_summary = _safe_command_summary(
        ["codex", "exec", "--json", "@E:/private/user/prompts/implement-1.md"]
    )
    assert "private" not in codex_summary
    assert "<path>" in codex_summary

    instructed_summary = _safe_command_summary(
        [
            "codex",
            "exec",
            "--json",
            "Follow the instructions in this file: E:/private/user/prompts/implement-1.md",
        ]
    )
    assert "private" not in instructed_summary
    assert "<path>" in instructed_summary

    posix_summary = _safe_command_summary(
        [
            "codex",
            "exec",
            "--json",
            "Follow the instructions in this file: /private/user/prompts/implement-1.md",
        ]
    )
    assert "private" not in posix_summary
    assert "<path>" in posix_summary


@pytest.mark.parametrize(
    "configured_command",
    [r"C:\Users\private-user\bin\claude.exe", "/home/private-user/bin/claude"],
)
@pytest.mark.parametrize("failure_kind", ["missing", "survived", "other"])
def test_adapter_redacts_absolute_command_on_every_start_failure(
    tmp_path, configured_command, failure_kind
) -> None:
    class AbsoluteCommandConfig(FakeConfig):
        def get_external_coding_claude_command(self):
            return configured_command

    class RaisingRunner:
        def start(self, **_kwargs):
            if failure_kind == "missing":
                raise FileNotFoundError("missing")
            if failure_kind == "survived":
                raise ExternalProcessStartError(
                    identity=ProcessIdentity(pid=49101, create_time=100.0)
                )
            raise RuntimeError("boom")

    adapter = CliExternalCodingAdapter(config=AbsoluteCommandConfig(), runner=RaisingRunner())

    result = adapter.start(
        tool=ExternalCodingTool.CLAUDE_CODE,
        phase=CodingPhase.PLAN,
        prompt_path=_prompt(tmp_path),
        worktree_path=tmp_path,
        artifact_dir=tmp_path / "artifacts",
        log_path=tmp_path / "start.log",
        launch_mode=LaunchMode.HEADLESS,
        external_session_ref=None,
    )

    assert result.command_summary is not None
    assert result.command_summary.startswith("<path>")
    assert "private-user" not in result.command_summary
    assert result.status == (
        AttemptStatus.RUNNING if failure_kind == "survived" else AttemptStatus.FAILED
    )


def test_process_executable_resolution_preserves_argv(monkeypatch) -> None:
    monkeypatch.setattr(
        external_coding_process.shutil,
        "which",
        lambda command: "E:/tools/codex.CMD" if command == "codex" else None,
    )

    assert _resolve_executable(["codex", "exec", "do work"])[0] == "E:/tools/codex.CMD"
    assert _resolve_executable(["missing-cli", "--version"])[0] == "missing-cli"


def test_process_runner_passes_resolved_argv_to_popen_without_a_shell(
    tmp_path, monkeypatch
) -> None:
    captured = {}

    class FakeProcess:
        pid = 48201

        def poll(self):
            return None

    class FakeMonitor:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

    def _popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(
        external_coding_process.shutil,
        "which",
        lambda command: "E:/tools/codex.CMD" if command == "codex" else None,
    )
    monkeypatch.setattr(external_coding_process.subprocess, "Popen", _popen)
    monkeypatch.setattr(external_coding_process, "_process_create_time", lambda _pid: 10.0)
    monkeypatch.setattr(external_coding_process, "_write_status", lambda *_args: None)
    monkeypatch.setattr(external_coding_process.threading, "Thread", FakeMonitor)
    runner = ExternalCodingProcessRunner()

    try:
        started = runner.start(
            command=["codex", "exec", "do work"],
            cwd=tmp_path,
            log_path=tmp_path / "resolved.log",
            timeout_seconds=10,
            max_log_bytes=2048,
        )

        assert started.pid == 48201
        assert captured["command"] == ["E:/tools/codex.CMD", "exec", "do work"]
        assert captured["kwargs"].get("shell", False) is False
        assert captured["kwargs"]["cwd"] == str(tmp_path)
    finally:
        managed = _managed_for(48201, tmp_path / "resolved.log", 10.0)
        if managed is not None:
            _remove_test_managed(managed)


@pytest.mark.parametrize("failure_point", ["status", "thread"])
def test_process_runner_stops_spawned_process_when_initialization_fails(
    tmp_path, monkeypatch, failure_point
) -> None:
    class FakeProcess:
        pid = 48202 if failure_point == "status" else 48203

        def __init__(self):
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

    class FakeMonitor:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            if failure_point == "thread":
                raise RuntimeError("thread start failed")

    process = FakeProcess()
    monkeypatch.setattr(
        external_coding_process.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(external_coding_process, "_process_create_time", lambda _pid: 10.0)
    monkeypatch.setattr(
        external_coding_process,
        "_terminate_process",
        lambda spawned: (setattr(spawned, "stopped", True), True)[1],
    )
    monkeypatch.setattr(external_coding_process.threading, "Thread", FakeMonitor)
    if failure_point == "status":
        monkeypatch.setattr(
            external_coding_process,
            "_write_status",
            lambda *_args: (_ for _ in ()).throw(OSError("status write failed")),
        )
    else:
        monkeypatch.setattr(external_coding_process, "_write_status", lambda *_args: None)
    runner = ExternalCodingProcessRunner()

    with pytest.raises((OSError, RuntimeError)):
        runner.start(
            command=[sys.executable, "--version"],
            cwd=tmp_path,
            log_path=tmp_path / f"{failure_point}.log",
            timeout_seconds=10,
            max_log_bytes=2048,
        )

    assert process.stopped is True
    assert not _registry_has_pid(process.pid)


def test_process_runner_retains_and_later_stops_unconfirmed_startup_process(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 48204

        def __init__(self):
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

    class FailingMonitor:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    process = FakeProcess()
    terminate_calls = 0

    def _terminate(spawned):
        nonlocal terminate_calls
        terminate_calls += 1
        if terminate_calls == 1:
            return False
        spawned.stopped = True
        return True

    monkeypatch.setattr(
        external_coding_process.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(external_coding_process, "_process_create_time", lambda _pid: 10.0)
    monkeypatch.setattr(external_coding_process, "_terminate_process", _terminate)
    monkeypatch.setattr(external_coding_process.threading, "Thread", FailingMonitor)
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "survived.log"

    try:
        with pytest.raises(ExternalProcessStartError) as caught:
            runner.start(
                command=[sys.executable, "--version"],
                cwd=tmp_path,
                log_path=log_path,
                timeout_seconds=10,
                max_log_bytes=2048,
            )

        assert caught.value.pid == process.pid
        managed = _managed_for(process.pid, log_path, 10.0)
        assert managed is not None
        assert managed.monitor is None
        assert managed.termination_unconfirmed is True
        snapshot = runner.poll(pid=process.pid, log_path=log_path)
        assert snapshot.status == "running"
        assert snapshot.error_message == ("external coding process tree termination is unconfirmed")

        _remove_test_managed(managed)
        restarted_snapshot = ExternalCodingProcessRunner().poll(
            pid=None,
            log_path=log_path,
        )
        assert restarted_snapshot.status == "running"
        assert restarted_snapshot.pid == process.pid
        assert restarted_snapshot.error_message == (
            "external coding process tree termination is unconfirmed"
        )
        _register_test_managed(managed)

        outcome = runner.stop(pid=process.pid, log_path=log_path, reason="test cleanup")
        assert outcome == ExternalProcessTerminationOutcome.CONFIRMED_STOPPED
        assert not _registry_has_pid(process.pid)
    finally:
        _remove_test_managed(managed)


def test_process_tree_termination_confirms_child_exit(tmp_path) -> None:
    child_pid_path = tmp_path / "child.pid"
    parent_script = (
        "import pathlib,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid),encoding='utf-8'); "
        "time.sleep(30)"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", parent_script, str(child_pid_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    child_pid = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not child_pid_path.exists():
            time.sleep(0.02)
        assert child_pid_path.exists()
        child_pid = int(child_pid_path.read_text(encoding="utf-8"))

        assert _terminate_process(process) is True
        assert process.poll() is not None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and psutil.pid_exists(child_pid):
            time.sleep(0.02)
        assert not psutil.pid_exists(child_pid)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        if child_pid is not None:
            try:
                child = psutil.Process(child_pid)
                child.kill()
                child.wait(timeout=2)
            except psutil.Error:
                pass


def test_process_status_metadata_lives_outside_writable_session_artifacts(tmp_path) -> None:
    log_path = tmp_path / "ecs-1" / "logs" / "plan-0.log"

    status_path = _status_path(log_path)

    assert status_path == tmp_path / ".control" / "ecs-1" / "plan-0.log.status.json"
    assert log_path.parent.parent not in status_path.parents


def _wait_for_process(
    runner,
    *,
    pid: int,
    process_create_time: float | None,
    log_path: Path,
    timeout: float = 5.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = runner.poll(
            pid=pid,
            process_create_time=process_create_time,
            log_path=log_path,
        )
        if snapshot.status != "running":
            return snapshot
        time.sleep(0.02)
    raise AssertionError("managed process did not finish")


def test_managed_runner_persists_exit_session_ref_and_bounded_redacted_log(tmp_path) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "managed.log"
    script = (
        "import json; "
        "print(json.dumps({'type':'thread.started','thread_id':'thread-123'})); "
        "print('api_key=super-secret-value'); "
        "print(json.dumps({'ANTHROPIC_API_KEY':'json-secret','email':'owner@example.com'})); "
        "print('x' * 20000)"
    )

    started = runner.start(
        command=[sys.executable, "-c", script],
        cwd=tmp_path,
        log_path=log_path,
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    snapshot = _wait_for_process(
        runner,
        pid=started.pid,
        process_create_time=started.process_create_time,
        log_path=log_path,
    )

    assert snapshot.status == "succeeded"
    assert snapshot.exit_code == 0
    assert snapshot.external_session_ref == "thread-123"
    assert log_path.stat().st_size <= 2048
    safe_log = log_path.read_text(encoding="utf-8")
    assert "super-secret-value" not in safe_log
    assert "json-secret" not in safe_log
    assert "owner@example.com" not in safe_log
    status = json.loads(log_path.with_suffix(".log.status.json").read_text(encoding="utf-8"))
    assert status["processCreateTime"] > 0


def test_managed_runner_times_out_and_stops_process(tmp_path) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "timeout.log"
    started = runner.start(
        command=[sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        log_path=log_path,
        timeout_seconds=1,
        max_log_bytes=2048,
    )

    snapshot = _wait_for_process(
        runner,
        pid=started.pid,
        process_create_time=started.process_create_time,
        log_path=log_path,
    )

    assert snapshot.status == "interrupted"
    assert snapshot.error_category == "process_error"
    assert snapshot.error_message == "external coding process timed out"


def test_poll_rereads_terminal_status_after_monitor_finishes(tmp_path, monkeypatch) -> None:
    class ExitedProcess:
        pid = 4249

        def poll(self):
            return 1

    class FinishedMonitor:
        def join(self, timeout):
            return None

        def is_alive(self):
            return False

    log_path = tmp_path / "monitor-finished-race.log"
    managed = _ManagedProcess(
        process=ExitedProcess(),
        process_create_time=100.0,
        interactive=False,
        log_path=log_path,
        status_path=log_path.with_suffix(".log.status.json"),
        timeout_seconds=5,
        max_log_bytes=2048,
        monitor=FinishedMonitor(),
    )
    payloads = iter(
        [
            {"status": "running", "pid": 4249, "processCreateTime": 100.0},
            {
                "status": "interrupted",
                "pid": 4249,
                "processCreateTime": 100.0,
                "exitCode": 1,
                "errorCategory": "process_error",
                "errorMessage": "external coding process timed out",
            },
        ]
    )
    monkeypatch.setattr(
        external_coding_process,
        "_read_status",
        lambda _path: next(payloads),
    )
    _register_test_managed(managed)

    try:
        snapshot = ExternalCodingProcessRunner().poll(
            pid=managed.process.pid,
            log_path=log_path,
        )

        assert snapshot.status == "interrupted"
        assert snapshot.error_message == "external coding process timed out"
    finally:
        _remove_test_managed(managed)


def test_interactive_monitor_records_real_process_completion(tmp_path) -> None:
    class FakeInteractiveProcess:
        pid = 4243

        def __init__(self) -> None:
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count == 1 else 0

        def wait(self, timeout):
            return 0

    log_path = tmp_path / "interactive.log"
    managed = _ManagedProcess(
        process=FakeInteractiveProcess(),
        process_create_time=100.0,
        interactive=True,
        log_path=log_path,
        status_path=log_path.with_suffix(".log.status.json"),
        timeout_seconds=5,
        max_log_bytes=2048,
    )

    ExternalCodingProcessRunner._monitor_interactive(managed)

    status = json.loads(managed.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "succeeded"
    assert status["exitCode"] == 0


def test_monitor_keeps_running_ownership_when_tree_termination_is_unconfirmed(
    tmp_path, monkeypatch
) -> None:
    class FakeInteractiveProcess:
        pid = 4244

        def poll(self):
            return None

    log_path = tmp_path / "interactive-unconfirmed.log"
    managed = _ManagedProcess(
        process=FakeInteractiveProcess(),
        process_create_time=100.0,
        interactive=True,
        log_path=log_path,
        status_path=log_path.with_suffix(".log.status.json"),
        timeout_seconds=5,
        max_log_bytes=2048,
        stop_reason="stop requested",
    )
    _register_test_managed(managed)
    monkeypatch.setattr(external_coding_process, "_terminate_process", lambda _process: False)

    try:
        ExternalCodingProcessRunner._monitor_interactive(managed)

        status = json.loads(managed.status_path.read_text(encoding="utf-8"))
        assert status["status"] == "running"
        assert status["terminationUnconfirmed"] is True
        assert _registry_has_pid(managed.process.pid)
    finally:
        _remove_test_managed(managed)


def test_managed_runner_blocks_dangerous_git_attempt(tmp_path) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "danger.log"
    script = (
        "import json,time; "
        "print(json.dumps({'type':'item.started','item':"
        "{'type':'command_execution','command':'git push origin main'}}), flush=True); "
        "time.sleep(30)"
    )
    started = runner.start(
        command=[sys.executable, "-c", script],
        cwd=tmp_path,
        log_path=log_path,
        timeout_seconds=10,
        max_log_bytes=2048,
    )

    snapshot = _wait_for_process(
        runner,
        pid=started.pid,
        process_create_time=started.process_create_time,
        log_path=log_path,
    )

    assert snapshot.status == "interrupted"
    assert snapshot.error_category == "protocol_violation"
    assert snapshot.error_message == "blocked high-risk git operation: git push"


def test_dangerous_git_audit_catches_wrapped_and_optioned_commands() -> None:
    assert _dangerous_git_action("powershell -Command git -C repo push origin main") == "git push"
    assert (
        _dangerous_git_action('cmd /c "C:\\Program Files\\Git\\bin\\git.exe" reset HEAD --hard')
        == "git reset --hard"
    )
    assert _dangerous_git_action("git status") is None


def test_runner_never_stops_reused_unmanaged_pid(tmp_path, monkeypatch) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "reused.log"
    status_path = log_path.with_suffix(".log.status.json")
    status_path.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": 4242,
                "processCreateTime": 100.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        external_coding_process,
        "_process_create_time",
        lambda _pid: 200.0,
    )

    def fail_if_called(_pid: int) -> bool:
        raise AssertionError("a reused PID must never be terminated")

    monkeypatch.setattr(
        external_coding_process,
        "_terminate_pid_tree",
        fail_if_called,
    )

    assert (
        runner.stop(pid=4242, log_path=log_path, reason="abandoned")
        == ExternalProcessTerminationOutcome.UNCONFIRMED
    )
    snapshot = runner.poll(pid=4242, log_path=log_path)
    assert snapshot.status == "failed"
    assert snapshot.error_category == "process_error"


def test_restarted_runner_retries_verified_live_unconfirmed_process(tmp_path, monkeypatch) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "retry-unconfirmed.log"
    status_path = log_path.with_suffix(".log.status.json")
    status_path.write_text(
        json.dumps(
            {
                "status": "running",
                "pid": 4245,
                "processCreateTime": 100.0,
                "terminationUnconfirmed": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        external_coding_process,
        "_process_create_time",
        lambda _pid: 100.0,
    )
    terminated = []
    monkeypatch.setattr(
        external_coding_process,
        "_terminate_pid_tree",
        lambda pid: (terminated.append(pid), True)[1],
    )

    outcome = runner.stop(
        pid=4245,
        log_path=log_path,
        reason="retry after restart",
        process_create_time=100.0,
        termination_unconfirmed=True,
    )

    assert outcome == ExternalProcessTerminationOutcome.CONFIRMED_STOPPED
    assert terminated == [4245]
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "interrupted"
    assert status["processCreateTime"] == 100.0
    assert "terminationUnconfirmed" not in status


def test_restarted_runner_keeps_unconfirmed_ownership_when_parent_disappeared(
    tmp_path, monkeypatch
) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "parent-gone.log"
    log_path.with_suffix(".log.status.json").write_text(
        json.dumps(
            {
                "status": "running",
                "pid": 4246,
                "processCreateTime": 100.0,
                "terminationUnconfirmed": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        external_coding_process,
        "_process_create_time",
        lambda _pid: None,
    )

    snapshot = runner.poll(
        pid=4246,
        log_path=log_path,
        process_create_time=100.0,
        termination_unconfirmed=True,
    )
    outcome = runner.stop(
        pid=4246,
        log_path=log_path,
        reason="retry after restart",
        process_create_time=100.0,
        termination_unconfirmed=True,
    )

    assert snapshot.status == "running"
    assert snapshot.termination_unconfirmed is True
    assert outcome == ExternalProcessTerminationOutcome.UNCONFIRMED


def test_restarted_runner_rejects_terminal_status_without_durable_create_time(
    tmp_path,
) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "missing-create-time.log"
    _status_path(log_path).write_text(
        json.dumps(
            {
                "status": "succeeded",
                "pid": 4254,
                "processCreateTime": 100.0,
                "exitCode": 0,
            }
        ),
        encoding="utf-8",
    )

    snapshot = runner.poll(
        pid=4254,
        log_path=log_path,
        process_create_time=None,
        termination_unconfirmed=True,
    )
    outcome = runner.stop(
        pid=4254,
        log_path=log_path,
        reason="missing durable identity",
        process_create_time=None,
        termination_unconfirmed=True,
    )

    assert snapshot.status == "running"
    assert snapshot.termination_unconfirmed is True
    assert snapshot.process_create_time is None
    assert snapshot.error_message == (
        "external coding process status identity could not be verified"
    )
    assert outcome == ExternalProcessTerminationOutcome.UNCONFIRMED


def test_guarded_monitor_converts_unexpected_failure_to_safe_terminal_status(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 4247

        def __init__(self):
            self.stopped = False

        def poll(self):
            return 1 if self.stopped else None

    process = FakeProcess()
    log_path = tmp_path / "monitor-failure.log"
    managed = _ManagedProcess(
        process=process,
        process_create_time=100.0,
        interactive=False,
        log_path=log_path,
        status_path=log_path.with_suffix(".log.status.json"),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(managed)
    monkeypatch.setattr(
        ExternalCodingProcessRunner,
        "_monitor",
        classmethod(
            lambda _cls, _managed: (_ for _ in ()).throw(OSError("raw secret must not escape"))
        ),
    )
    monkeypatch.setattr(
        external_coding_process,
        "_terminate_process",
        lambda spawned: (setattr(spawned, "stopped", True), True)[1],
    )

    ExternalCodingProcessRunner._run_monitor_guarded(managed)

    status = json.loads(managed.status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["errorMessage"] == "external coding process monitor failed"
    assert "secret" not in status["errorMessage"]
    assert not _registry_has_pid(process.pid)


def test_guarded_monitor_retains_registry_when_recovery_and_marker_write_fail(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 4248

        def poll(self):
            return None

    process = FakeProcess()
    log_path = tmp_path / "monitor-recovery-failure.log"
    managed = _ManagedProcess(
        process=process,
        process_create_time=100.0,
        interactive=False,
        log_path=log_path,
        status_path=log_path.with_suffix(".log.status.json"),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(managed)
    monkeypatch.setattr(
        ExternalCodingProcessRunner,
        "_monitor",
        classmethod(lambda _cls, _managed: (_ for _ in ()).throw(RuntimeError("monitor failed"))),
    )
    monkeypatch.setattr(
        external_coding_process,
        "_terminate_process",
        lambda _process: False,
    )
    monkeypatch.setattr(
        external_coding_process,
        "_write_status",
        lambda *_args: (_ for _ in ()).throw(OSError("status write failed")),
    )

    try:
        ExternalCodingProcessRunner._run_monitor_guarded(managed)

        assert managed.termination_unconfirmed is True
        assert _managed_for(process.pid, log_path, 100.0) is managed
    finally:
        _remove_test_managed(managed)


def test_poll_retries_recovery_marker_and_releases_stopped_registry_owner(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 4249

        def __init__(self) -> None:
            self.stopped = False

        def poll(self):
            return 1 if self.stopped else None

    process = FakeProcess()
    log_path = tmp_path / "monitor-recovery-retry.log"
    managed = _ManagedProcess(
        process=process,
        process_create_time=100.0,
        interactive=False,
        log_path=log_path,
        status_path=_status_path(log_path),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(managed)
    monkeypatch.setattr(
        ExternalCodingProcessRunner,
        "_monitor",
        classmethod(lambda _cls, _managed: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    monkeypatch.setattr(
        external_coding_process,
        "_terminate_process",
        lambda spawned: (setattr(spawned, "stopped", True), True)[1],
    )
    real_write_status = external_coding_process._write_status
    write_calls = 0

    def _fail_twice(path, payload):
        nonlocal write_calls
        write_calls += 1
        if write_calls <= 2:
            raise OSError("status write failed")
        real_write_status(path, payload)

    monkeypatch.setattr(external_coding_process, "_write_status", _fail_twice)

    try:
        ExternalCodingProcessRunner._run_monitor_guarded(managed)
        assert _managed_for(process.pid, log_path, 100.0) is managed

        retry_failed = ExternalCodingProcessRunner().poll(
            pid=process.pid,
            process_create_time=100.0,
            log_path=log_path,
        )
        assert retry_failed.status == "running"
        assert retry_failed.termination_unconfirmed is True
        assert retry_failed.error_message == (
            "external coding recovered terminal status could not be persisted"
        )
        assert _managed_for(process.pid, log_path, 100.0) is managed

        snapshot = ExternalCodingProcessRunner().poll(
            pid=process.pid,
            process_create_time=100.0,
            log_path=log_path,
        )

        assert snapshot.status == "failed"
        assert snapshot.error_message == "external coding process monitor failed"
        assert _managed_for(process.pid, log_path, 100.0) is None
        assert json.loads(_status_path(log_path).read_text(encoding="utf-8"))["status"] == (
            "failed"
        )

        replacement_log = tmp_path / "monitor-recovery-replacement.log"
        replacement = _ManagedProcess(
            process=FakeProcess(),
            process_create_time=200.0,
            interactive=False,
            log_path=replacement_log,
            status_path=_status_path(replacement_log),
            timeout_seconds=5,
            max_log_bytes=2048,
        )
        assert ExternalCodingProcessRunner._register_managed(replacement) is True
        _remove_test_managed(replacement)
    finally:
        _remove_test_managed(managed)


def test_process_runner_pid_reuse_conflict_never_overwrites_existing_owner(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 4250

        def __init__(self, *, stopped: bool = False) -> None:
            self.stopped = stopped

        def poll(self):
            return 0 if self.stopped else None

    old_process = FakeProcess(stopped=True)
    old_log = tmp_path / "old-owner.log"
    old_managed = _ManagedProcess(
        process=old_process,
        process_create_time=100.0,
        interactive=False,
        log_path=old_log,
        status_path=_status_path(old_log),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(old_managed)
    new_process = FakeProcess()
    monkeypatch.setattr(
        external_coding_process.subprocess,
        "Popen",
        lambda *_args, **_kwargs: new_process,
    )
    monkeypatch.setattr(external_coding_process, "_process_create_time", lambda _pid: 200.0)
    monkeypatch.setattr(
        external_coding_process,
        "_terminate_process",
        lambda process: (setattr(process, "stopped", True), True)[1],
    )
    new_log = tmp_path / "new-owner.log"

    try:
        with pytest.raises(RuntimeError, match="PID is already owned"):
            ExternalCodingProcessRunner().start(
                command=[sys.executable, "--version"],
                cwd=tmp_path,
                log_path=new_log,
                timeout_seconds=5,
                max_log_bytes=2048,
            )

        assert new_process.stopped is True
        assert _managed_for(old_process.pid, old_log, 100.0) is old_managed
        assert _managed_for(new_process.pid, new_log, 200.0) is None
    finally:
        _remove_test_managed(old_managed)


def test_pid_collision_with_failed_compensation_retains_isolated_owners(
    tmp_path, monkeypatch
) -> None:
    class FakeProcess:
        pid = 4255

        def __init__(self) -> None:
            self.stopped = False

        def poll(self):
            return 0 if self.stopped else None

    old_process = FakeProcess()
    old_log = tmp_path / "collision-old.log"
    old_managed = _ManagedProcess(
        process=old_process,
        process_create_time=100.0,
        interactive=False,
        log_path=old_log,
        status_path=_status_path(old_log),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(old_managed)
    new_process = FakeProcess()
    new_log = tmp_path / "collision-new.log"
    terminate_calls = 0

    def _terminate(spawned):
        nonlocal terminate_calls
        terminate_calls += 1
        if terminate_calls == 1:
            return False
        spawned.stopped = True
        return True

    monkeypatch.setattr(
        external_coding_process.subprocess,
        "Popen",
        lambda *_args, **_kwargs: new_process,
    )
    monkeypatch.setattr(external_coding_process, "_process_create_time", lambda _pid: 200.0)
    monkeypatch.setattr(external_coding_process, "_terminate_process", _terminate)

    new_managed = None
    try:
        with pytest.raises(ExternalProcessStartError) as caught:
            ExternalCodingProcessRunner().start(
                command=[sys.executable, "--version"],
                cwd=tmp_path,
                log_path=new_log,
                timeout_seconds=5,
                max_log_bytes=2048,
            )

        assert caught.value.identity == ProcessIdentity(pid=4255, create_time=200.0)
        new_managed = _managed_for(4255, new_log, 200.0)
        assert _managed_for(4255, old_log, 100.0) is old_managed
        assert new_managed is not None
        assert new_managed is not old_managed
        assert new_managed.termination_unconfirmed is True

        ExternalCodingProcessRunner._remove_managed(old_managed)
        assert _managed_for(4255, new_log, 200.0) is new_managed

        outcome = ExternalCodingProcessRunner().stop(
            pid=4255,
            process_create_time=200.0,
            log_path=new_log,
            reason="collision cleanup",
            termination_unconfirmed=True,
        )
        assert outcome == ExternalProcessTerminationOutcome.CONFIRMED_STOPPED
        assert new_process.stopped is True
        assert old_process.stopped is False
        assert _managed_for(4255, new_log, 200.0) is None
    finally:
        _remove_test_managed(old_managed)
        if new_managed is not None:
            _remove_test_managed(new_managed)


def test_output_reader_cancellation_unblocks_a_full_queue() -> None:
    output_queue = external_coding_process.queue.Queue(maxsize=1)
    cancel = external_coding_process.threading.Event()
    reader = external_coding_process.threading.Thread(
        target=external_coding_process._read_stream,
        args=(io.BytesIO(b"x" * 1_000_000), output_queue, cancel),
        daemon=True,
    )
    reader.start()

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and output_queue.empty():
        time.sleep(0.01)
    assert not output_queue.empty()
    assert reader.is_alive()

    cancel.set()
    reader.join(timeout=2)

    assert not reader.is_alive()


def test_output_reader_failure_enters_guarded_process_tree_recovery(tmp_path, monkeypatch) -> None:
    class BrokenStream:
        def read(self, _size):
            raise OSError("raw stream failure")

    class FakeProcess:
        pid = 4256
        stdout = BrokenStream()

        def __init__(self) -> None:
            self.stopped = False

        def poll(self):
            return 1 if self.stopped else None

    process = FakeProcess()
    log_path = tmp_path / "reader-failure.log"
    managed = _ManagedProcess(
        process=process,
        process_create_time=100.0,
        interactive=False,
        log_path=log_path,
        status_path=_status_path(log_path),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(managed)
    monkeypatch.setattr(
        external_coding_process,
        "_terminate_process",
        lambda spawned: (setattr(spawned, "stopped", True), True)[1],
    )

    try:
        ExternalCodingProcessRunner._run_monitor_guarded(managed)

        status = json.loads(_status_path(log_path).read_text(encoding="utf-8"))
        assert process.stopped is True
        assert status["status"] == "failed"
        assert status["errorMessage"] == "external coding process monitor failed"
        assert "raw stream failure" not in json.dumps(status)
        assert managed.output_reader is not None
        assert not managed.output_reader.is_alive()
        assert _managed_for(process.pid, log_path, 100.0) is None
    finally:
        _remove_test_managed(managed)


def test_process_exit_waits_for_reader_failure_signal_before_success(tmp_path) -> None:
    release_read = threading.Event()

    class DelayedBrokenStream:
        def read(self, _size):
            assert release_read.wait(timeout=2)
            raise OSError("late raw stream failure")

    class ExitedProcess:
        pid = 4257
        stdout = DelayedBrokenStream()

        def poll(self):
            return 0

        def wait(self, timeout):
            return 0

    process = ExitedProcess()
    log_path = tmp_path / "late-reader-failure.log"
    managed = _ManagedProcess(
        process=process,
        process_create_time=100.0,
        interactive=False,
        log_path=log_path,
        status_path=_status_path(log_path),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(managed)
    release_timer = threading.Timer(0.25, release_read.set)
    release_timer.start()

    try:
        ExternalCodingProcessRunner._run_monitor_guarded(managed)

        status = json.loads(_status_path(log_path).read_text(encoding="utf-8"))
        assert status["status"] == "failed"
        assert status["errorMessage"] == "external coding process monitor failed"
        assert "late raw stream failure" not in json.dumps(status)
        assert managed.output_reader is not None
        assert not managed.output_reader.is_alive()
    finally:
        release_read.set()
        release_timer.cancel()
        _remove_test_managed(managed)


def test_old_monitor_cas_removal_cannot_delete_reused_pid_owner(tmp_path) -> None:
    class FakeProcess:
        pid = 4251

        def poll(self):
            return None

    old_log = tmp_path / "old-cas.log"
    new_log = tmp_path / "new-cas.log"
    old_managed = _ManagedProcess(
        process=FakeProcess(),
        process_create_time=100.0,
        interactive=False,
        log_path=old_log,
        status_path=_status_path(old_log),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    new_managed = _ManagedProcess(
        process=FakeProcess(),
        process_create_time=200.0,
        interactive=False,
        log_path=new_log,
        status_path=_status_path(new_log),
        timeout_seconds=5,
        max_log_bytes=2048,
    )
    _register_test_managed(old_managed)
    _register_test_managed(new_managed)

    try:
        ExternalCodingProcessRunner._remove_managed(old_managed)

        assert _managed_for(4251, old_log, 100.0) is None
        assert _managed_for(4251, new_log, 200.0) is new_managed
    finally:
        _remove_test_managed(old_managed)
        _remove_test_managed(new_managed)


@pytest.mark.parametrize(
    ("payload_pid", "payload_create_time"),
    [(4253, 100.0), (4252, 200.0)],
)
def test_terminal_status_identity_conflict_stays_running_and_unconfirmed(
    tmp_path, payload_pid, payload_create_time
) -> None:
    runner = ExternalCodingProcessRunner()
    log_path = tmp_path / "terminal-identity-conflict.log"
    _status_path(log_path).write_text(
        json.dumps(
            {
                "status": "succeeded",
                "pid": payload_pid,
                "processCreateTime": payload_create_time,
                "exitCode": 0,
            }
        ),
        encoding="utf-8",
    )

    snapshot = runner.poll(
        pid=4252,
        log_path=log_path,
        process_create_time=100.0,
        termination_unconfirmed=True,
    )
    outcome = runner.stop(
        pid=4252,
        log_path=log_path,
        reason="identity conflict",
        process_create_time=100.0,
        termination_unconfirmed=True,
    )

    assert snapshot.status == "running"
    assert snapshot.termination_unconfirmed is True
    assert snapshot.error_message == (
        "external coding process status identity could not be verified"
    )
    assert outcome == ExternalProcessTerminationOutcome.UNCONFIRMED
