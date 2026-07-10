"""CLI command adapters for Claude Code and Codex CLI."""

from __future__ import annotations

import logging
from pathlib import Path

from src.data.unified_config import UnifiedConfigManager, get_unified_config
from src.execution.external_coding_process import (
    ExternalCodingProcessRunner,
    ExternalProcessSnapshot,
)

from .models import (
    AttemptStatus,
    CodingPhase,
    ErrorCategory,
    ExternalCodingTool,
    LaunchMode,
    ProcessStartResult,
)


class ExternalCodingAdapter:
    def start(
        self,
        *,
        tool: ExternalCodingTool,
        phase: CodingPhase,
        prompt_path: Path,
        worktree_path: Path,
        artifact_dir: Path,
        log_path: Path,
        launch_mode: LaunchMode,
        external_session_ref: str | None,
    ) -> ProcessStartResult:
        raise NotImplementedError

    def poll(self, *, pid: int | None, log_path: Path) -> ProcessStartResult:
        raise NotImplementedError

    def stop(self, *, pid: int | None, log_path: Path, reason: str) -> bool:
        raise NotImplementedError


class CliExternalCodingAdapter(ExternalCodingAdapter):
    _log = logging.getLogger(__name__)

    def __init__(
        self,
        *,
        config: UnifiedConfigManager | None = None,
        runner: ExternalCodingProcessRunner | None = None,
    ) -> None:
        self._config = config or get_unified_config()
        self._runner = runner or ExternalCodingProcessRunner()

    def start(
        self,
        *,
        tool: ExternalCodingTool,
        phase: CodingPhase,
        prompt_path: Path,
        worktree_path: Path,
        artifact_dir: Path,
        log_path: Path,
        launch_mode: LaunchMode,
        external_session_ref: str | None,
    ) -> ProcessStartResult:
        command = self._build_command(
            tool,
            phase,
            prompt_path,
            artifact_dir=artifact_dir,
            launch_mode=launch_mode,
            external_session_ref=external_session_ref,
        )
        timeout_seconds = (
            self._config.get_external_coding_plan_timeout_seconds()
            if phase == CodingPhase.PLAN
            else self._config.get_external_coding_run_timeout_seconds()
        )
        max_log_bytes = min(
            max(self._config.get_external_coding_log_tail_chars() * 4, 16_000),
            1_000_000,
        )
        try:
            started = self._runner.start(
                command=command,
                cwd=worktree_path,
                log_path=log_path,
                timeout_seconds=timeout_seconds,
                max_log_bytes=max_log_bytes,
                interactive=launch_mode == LaunchMode.INTERACTIVE,
            )
        except FileNotFoundError:
            return ProcessStartResult(
                status=AttemptStatus.FAILED,
                command_summary=command[0],
                error_category=ErrorCategory.LOGIN_REQUIRED,
                error_message=f"{tool.value} command is not available or not on PATH",
            )
        except Exception as exc:
            self._log.error("Failed to start external coding process (%s)", type(exc).__name__)
            return ProcessStartResult(
                status=AttemptStatus.FAILED,
                command_summary=command[0],
                error_category=ErrorCategory.PROCESS_ERROR,
                error_message="failed to start external coding process",
            )
        return ProcessStartResult(
            status=AttemptStatus.RUNNING,
            command_summary=started.command_summary,
            pid=started.pid,
            log_path=str(log_path),
        )

    def poll(self, *, pid: int | None, log_path: Path) -> ProcessStartResult:
        snapshot = self._runner.poll(pid=pid, log_path=log_path)
        return self._snapshot_to_result(snapshot, log_path=log_path)

    def stop(self, *, pid: int | None, log_path: Path, reason: str) -> bool:
        return self._runner.stop(pid=pid, log_path=log_path, reason=reason)

    def _build_command(
        self,
        tool: ExternalCodingTool,
        phase: CodingPhase,
        prompt_path: Path,
        *,
        artifact_dir: Path | None = None,
        launch_mode: LaunchMode = LaunchMode.HEADLESS,
        external_session_ref: str | None = None,
    ) -> list[str]:
        del phase
        if tool == ExternalCodingTool.CLAUDE_CODE:
            command = self._config.get_external_coding_claude_command()
            effort = self._config.get_external_coding_claude_effort()
            args = [command]
            if external_session_ref:
                args.extend(["--resume", external_session_ref])
            if launch_mode == LaunchMode.HEADLESS:
                args.extend(
                    [
                        "-p",
                        f"@{prompt_path}",
                        "--output-format",
                        "stream-json",
                    ]
                )
            else:
                args.append(f"@{prompt_path}")
            args.extend(
                [
                    "--effort",
                    effort,
                    "--safe-mode",
                    "--permission-mode",
                    "auto",
                    "--disallowedTools",
                    (
                        "Bash(git push *),Bash(git reset --hard *),"
                        "Bash(git clean *),Bash(git merge *),Bash(git rebase *),"
                        "Bash(git branch -D *)"
                    ),
                ]
            )
            if artifact_dir is not None:
                args.extend(["--add-dir", str(artifact_dir.resolve())])
            return args
        command = self._config.get_external_coding_codex_command()
        effort = self._config.get_external_coding_codex_reasoning_effort()
        args = [command]
        if launch_mode == LaunchMode.HEADLESS:
            args.append("exec")
            if external_session_ref:
                args.extend(["resume", external_session_ref])
        elif external_session_ref:
            args.extend(["resume", external_session_ref])
        args.extend(
            [
                "--sandbox",
                "workspace-write",
                "--ignore-user-config",
                "-c",
                f'model_reasoning_effort="{effort}"',
            ]
        )
        if launch_mode == LaunchMode.HEADLESS:
            args.insert(2 if not external_session_ref else 4, "--json")
        if artifact_dir is not None:
            args.extend(["--add-dir", str(artifact_dir.resolve())])
        args.append(f"@{prompt_path}")
        return args

    @staticmethod
    def _snapshot_to_result(
        snapshot: ExternalProcessSnapshot, *, log_path: Path
    ) -> ProcessStartResult:
        try:
            status = AttemptStatus(snapshot.status)
        except ValueError:
            status = AttemptStatus.FAILED
        error_category = None
        if snapshot.error_category:
            try:
                error_category = ErrorCategory(snapshot.error_category)
            except ValueError:
                error_category = ErrorCategory.UNKNOWN
        return ProcessStartResult(
            status=status,
            command_summary="managed external coding process",
            pid=snapshot.pid,
            exit_code=snapshot.exit_code,
            external_session_ref=snapshot.external_session_ref,
            log_path=str(log_path),
            log_tail=snapshot.log_tail,
            error_category=error_category,
            error_message=snapshot.error_message,
        )
