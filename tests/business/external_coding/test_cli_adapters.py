import json
import sys
import time
from pathlib import Path

from src.business.external_coding.cli_adapters import CliExternalCodingAdapter
from src.business.external_coding.models import CodingPhase, ExternalCodingTool, LaunchMode
from src.execution.external_coding_process import (
    ExternalCodingProcessRunner,
    _ManagedProcess,
    _dangerous_git_action,
    _safe_command_summary,
    _status_path,
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


def test_resume_commands_reuse_external_session_reference(tmp_path) -> None:
    adapter = CliExternalCodingAdapter(config=FakeConfig())
    prompt = _prompt(tmp_path)

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
        external_session_ref="codex-thread-1",
    )

    assert claude[:4] == ["claude", "--resume", "claude-session-1", "-p"]
    assert codex[:5] == ["codex", "exec", "resume", "codex-thread-1", "--json"]


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
    assert f"@{prompt}" in codex


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


def test_process_status_metadata_lives_outside_writable_session_artifacts(tmp_path) -> None:
    log_path = tmp_path / "ecs-1" / "logs" / "plan-0.log"

    status_path = _status_path(log_path)

    assert status_path == tmp_path / ".control" / "ecs-1" / "plan-0.log.status.json"
    assert log_path.parent.parent not in status_path.parents


def _wait_for_process(runner, *, pid: int, log_path: Path, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = runner.poll(pid=pid, log_path=log_path)
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
    snapshot = _wait_for_process(runner, pid=started.pid, log_path=log_path)

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

    snapshot = _wait_for_process(runner, pid=started.pid, log_path=log_path)

    assert snapshot.status == "interrupted"
    assert snapshot.error_category == "process_error"
    assert snapshot.error_message == "external coding process timed out"


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

    snapshot = _wait_for_process(runner, pid=started.pid, log_path=log_path)

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

    assert runner.stop(pid=4242, log_path=log_path, reason="abandoned") is False
    snapshot = runner.poll(pid=4242, log_path=log_path)
    assert snapshot.status == "failed"
    assert snapshot.error_category == "process_error"
