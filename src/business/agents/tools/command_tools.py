"""Command and process lifecycle built-ins."""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from src.business.agents.tools.builtin_config import get_config_int
from src.business.agents.tools.builtin_contracts import (
    OUTCOME_BACKGROUND_STARTED,
    OUTCOME_REJECTED,
    OUTCOME_TIMEOUT,
    ToolOutputReference,
    current_tool_runtime,
    error_json,
    runtime_session_id,
    runtime_workspace_root,
    success_json,
    truncate_with_marker,
)
from src.business.agents.tools.builtin_permissions import (
    build_exec_summary,
    command_path_policy_violation,
    permission_for_path,
)
from src.business.agents.tools.file_tools import _redact_text
from src.data.repos.tool_output_repository import ToolOutputRepository
from src.execution.command_runner import CommandParseError, run_command
from src.execution.process_manager import (
    ProcessLimitExceeded,
    ProcessOperationError,
    get_process_manager,
)

logger = logging.getLogger(__name__)


def _handle_command_start_error(
    exc: Exception,
    *,
    tool: str,
    permission: Any,
    display_path: str,
    error_code: str = "command_start_failed",
    label: str = "Command",
) -> dict[str, Any]:
    """统一的命令启动异常映射：CommandParseError / FileNotFoundError / PermissionError / OSError+。"""
    if isinstance(exc, CommandParseError):
        return error_json(
            tool, "command_rejected", str(exc),
            outcome=OUTCOME_REJECTED, permission=permission,
            payload={"cwd": display_path},
        )
    if isinstance(exc, FileNotFoundError):
        return error_json(
            tool, "command_not_found",
            f"Executable not found: {exc.filename or 'unknown'}",
            outcome=OUTCOME_REJECTED, permission=permission,
            payload={"cwd": display_path, "exitCode": 127},
        )
    if isinstance(exc, PermissionError):
        return error_json(
            tool, "command_not_executable",
            f"Executable could not be started (permission denied): {exc.filename}",
            outcome=OUTCOME_REJECTED, permission=permission,
            payload={"cwd": display_path, "exitCode": 126},
        )
    if isinstance(exc, (OSError, ValueError, subprocess.SubprocessError)):
        logger.warning("[agent_tools] %s start failed", label, exc_info=True)
        return error_json(
            tool, error_code,
            f"{label} could not be started: {type(exc).__name__}: {exc}",
            outcome=OUTCOME_REJECTED, permission=permission,
            payload={"cwd": display_path},
        )
    raise exc  # 未预期异常不吞


def _bounded(text: str, cap: int) -> tuple[str, bool]:
    redacted, _ = _redact_text(text or "")
    return truncate_with_marker(redacted, cap)


def _cwd_check(cwd: str | None):
    return permission_for_path(
        cwd or ".", operation="execute", workspace_root=runtime_workspace_root()
    )


def _raw_reference_for_command(
    *,
    command: str,
    stdout: str,
    stderr: str,
    threshold: int,
    visible_truncated: bool,
) -> tuple[list[dict], list[str]]:
    raw = json.dumps(
        {"commandSummary": build_exec_summary(command), "stdout": stdout, "stderr": stderr},
        ensure_ascii=False,
    )
    if not visible_truncated and len(raw) < threshold:
        return [], []
    max_artifact = get_config_int(
        "get_agent_tools_output_max_artifact_bytes", 10_485_760, maximum=104_857_600
    )
    if len(raw.encode("utf-8")) > max_artifact:
        return [], ["max_artifact_bytes_exceeded"]
    try:
        model = ToolOutputRepository().create_reference(
            session_id=runtime_session_id(),
            tool_name="exec",
            tool_call_id=current_tool_runtime().tool_call_id if current_tool_runtime() else None,
            kind="combined_output",
            data=raw,
            workspace_root=runtime_workspace_root(),
            retention_days=get_config_int("get_agent_tools_output_retention_days", 14, maximum=90),
            content_type="application/json",
            redaction_profile="visible_summary_redacted",
        )
    except Exception:
        logger.warning("[agent_tools] command raw output reference creation failed", exc_info=True)
        return [], ["raw_reference_create_failed"]
    return [
        ToolOutputReference(
            reference_id=model.reference_id,
            kind=model.kind,
            size_bytes=model.size_bytes,
            content_type=model.content_type,
            sha256=model.sha256,
            expires_at=model.expires_at.isoformat() if model.expires_at else None,
        ).to_dict()
    ], ["raw_output_reference_created"]


def exec_handler(
    command: str,
    cwd: str = ".",
    timeoutMs: int | None = None,
    timeout: int | None = None,
    mode: str = "sync",
    stdin: str | None = None,
    allowStdin: bool = False,
) -> str:
    tool = "exec"
    check = _cwd_check(cwd)
    path_check = command_path_policy_violation(
        command,
        workspace_root=runtime_workspace_root(),
        base_dir=check.classification.resolved,
    )
    if path_check is not None:
        return error_json(
            tool,
            path_check.error_code or "command_rejected",
            path_check.message or "Command path arguments outside the workspace are denied.",
            outcome=OUTCOME_REJECTED,
            permission=path_check.decision,
            payload={"cwd": check.classification.display_path},
        )
    timeout_default = get_config_int("get_agent_tools_process_default_timeout_ms", 30_000)
    timeout_max = get_config_int("get_agent_tools_process_max_timeout_ms", 600_000)
    if timeoutMs is None and timeout is not None:
        timeoutMs = int(timeout) * 1000
    timeout_ms = max(1, min(int(timeoutMs or timeout_default), timeout_max))
    log_cap = get_config_int("get_agent_tools_process_log_tail_chars", 4000, maximum=50_000)
    mode_value = str(mode or "sync").lower()
    if mode_value == "background":
        manager = get_process_manager()
        try:
            record, duplicate = manager.start(
                session_id=runtime_session_id(),
                command=command,
                cwd=check.classification.resolved,
                cwd_display=check.classification.display_path,
                command_summary=build_exec_summary(command),
                allow_stdin=bool(allowStdin),
                max_processes=get_config_int(
                    "get_agent_tools_process_max_background_processes",
                    16,
                ),
            )
        except ProcessLimitExceeded as exc:
            return error_json(
                tool,
                "process_limit_reached",
                str(exc),
                outcome=OUTCOME_REJECTED,
                permission=check.decision,
                payload={"cwd": check.classification.display_path},
            )
        except (CommandParseError, FileNotFoundError, PermissionError, OSError, ValueError, subprocess.SubprocessError) as exc:
            return _handle_command_start_error(
                exc, tool=tool, permission=check.decision,
                display_path=check.classification.display_path,
                error_code="process_start_failed", label="Background process",
            )
        payload = manager.poll(record.process_id) or {}
        payload["duplicate"] = duplicate
        payload["logTail"] = manager.logs(record.process_id, tail_chars=log_cap) or ""
        return success_json(
            tool, payload, permission=check.decision, outcome=OUTCOME_BACKGROUND_STARTED
        )

    try:
        result = run_command(
            command,
            cwd=check.classification.resolved,
            timeout_ms=timeout_ms,
            stdin=stdin,
        )
    except (CommandParseError, FileNotFoundError, PermissionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        return _handle_command_start_error(
            exc, tool=tool, permission=check.decision,
            display_path=check.classification.display_path,
            error_code="command_start_failed", label="Command",
        )
    stdout, stdout_truncated = _bounded(result.stdout, log_cap)
    stderr, stderr_truncated = _bounded(result.stderr, log_cap)
    references, warnings = _raw_reference_for_command(
        command=command,
        stdout=result.stdout,
        stderr=result.stderr,
        threshold=get_config_int(
            "get_agent_tools_output_raw_reference_threshold_chars",
            20_000,
            minimum=get_config_int("get_agent_tools_output_visible_char_cap", 12_000),
        ),
        visible_truncated=stdout_truncated or stderr_truncated,
    )
    payload = {
        "status": result.status,
        "exitCode": result.exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "durationMs": result.duration_ms,
        "cwd": check.classification.display_path,
    }
    if result.timed_out:
        return error_json(
            tool,
            "command_timeout",
            f"Command timed out after {timeout_ms}ms.",
            outcome=OUTCOME_TIMEOUT,
            permission=check.decision,
            payload=payload,
            details={"timeoutMs": timeout_ms},
            references=references,
            warnings=warnings or None,
        )
    return success_json(
        tool,
        payload,
        permission=check.decision,
        references=references,
        warnings=warnings or None,
        limits={
            "truncated": stdout_truncated or stderr_truncated,
            "visibleChars": len(stdout) + len(stderr),
            "capName": "agent_tools.process.log_tail_chars",
        },
    )


def process_list_handler(status: str | None = None) -> str:
    manager = get_process_manager()
    records = manager.list(session_id=runtime_session_id(), status=status)
    return success_json("process_list", {"processes": records, "count": len(records)})


def _process_missing(tool: str, process_id: str) -> str:
    code = (
        "process_unavailable_after_restart"
        if str(process_id).startswith("proc_")
        else "process_not_found"
    )
    message = (
        "Process id belongs to a previous sidecar process session."
        if code == "process_unavailable_after_restart"
        else "Process was not found."
    )
    return error_json(
        tool, code, message, outcome=OUTCOME_REJECTED, payload={"processId": process_id}
    )


def _process_for_current_session(tool: str, process_id: str):
    record = get_process_manager().get(process_id)
    if record is None:
        return None, _process_missing(tool, process_id)
    if record.session_id != runtime_session_id():
        return None, error_json(
            tool,
            "permission_denied",
            "Process belongs to a different Agent session.",
            outcome=OUTCOME_REJECTED,
            payload={"processId": process_id},
        )
    return record, None


def process_poll_handler(processId: str) -> str:
    _, rejected = _process_for_current_session("process_poll", processId)
    if rejected is not None:
        return rejected
    payload = get_process_manager().poll(processId)
    return success_json("process_poll", payload)


def process_logs_handler(
    processId: str,
    stream: str = "combined",
    tailChars: int | None = None,
    extractionGoal: str | None = None,
) -> str:
    _, rejected = _process_for_current_session("process_logs", processId)
    if rejected is not None:
        return rejected
    configured_cap = get_config_int(
        "get_agent_tools_process_log_tail_chars",
        4000,
        maximum=50_000,
    )
    cap = max(1, min(int(tailChars or configured_cap), configured_cap))
    logs = get_process_manager().logs(processId, stream=stream, tail_chars=int(cap))
    text, truncated = _bounded(logs, int(cap))
    return success_json(
        "process_logs",
        {"processId": processId, "stream": stream, "logs": text},
        limits={
            "truncated": truncated,
            "visibleChars": len(text),
            "capName": "agent_tools.process.log_tail_chars",
        },
    )


def process_wait_handler(
    processId: str,
    timeoutMs: int | None = None,
    extractionGoal: str | None = None,
) -> str:
    _, rejected = _process_for_current_session("process_wait", processId)
    if rejected is not None:
        return rejected
    default_timeout = get_config_int("get_agent_tools_process_default_timeout_ms", 30_000)
    max_timeout = get_config_int("get_agent_tools_process_max_timeout_ms", 600_000)
    timeout = max(1, min(int(timeoutMs or default_timeout), max_timeout))
    payload = get_process_manager().wait(processId, timeout_ms=int(timeout))
    return success_json("process_wait", payload)


def wait_for_process_event_handler(
    processId: str,
    sinceCursor: int | None = None,
    timeoutMs: int | None = None,
) -> str:
    """022 process-event-push: block until next event or timeout."""
    _, rejected = _process_for_current_session("wait_for_process_event", processId)
    if rejected is not None:
        return rejected
    default_timeout = get_config_int("get_agent_tools_process_default_timeout_ms", 30_000)
    max_timeout = get_config_int("get_agent_tools_process_max_timeout_ms", 600_000)
    timeout = max(1, min(int(timeoutMs or default_timeout), max_timeout))
    try:
        payload = get_process_manager().wait_for_event(
            processId, since_cursor=sinceCursor, timeout_ms=int(timeout)
        )
    except Exception:
        logger.warning(
            "[agent_tools] wait_for_process_event internal failure: process_id=%s",
            processId,
            exc_info=True,
        )
        return error_json(
            "wait_for_process_event",
            "internal_error",
            "Internal error while waiting for process event.",
            outcome=OUTCOME_REJECTED,
            payload={"processId": processId},
        )
    if payload is None:
        return _process_missing("wait_for_process_event", processId)
    payload = {"processId": processId, **payload}
    return success_json("wait_for_process_event", payload)


def process_stop_handler(processId: str, force: bool = False) -> str:
    _, rejected = _process_for_current_session("process_stop", processId)
    if rejected is not None:
        return rejected
    try:
        payload = get_process_manager().stop(processId, force=force)
    except ProcessOperationError:
        logger.warning(
            "[agent_tools] background process stop failed: process_id=%s",
            processId,
            exc_info=True,
        )
        return error_json(
            "process_stop",
            "process_stop_failed",
            "Background process could not be stopped.",
            outcome=OUTCOME_REJECTED,
            payload={"processId": processId},
        )
    return success_json("process_stop", payload)


def process_send_input_handler(processId: str, text: str) -> str:
    _, rejected = _process_for_current_session("process_send_input", processId)
    if rejected is not None:
        return rejected
    bounded_text = str(text)
    if len(bounded_text) > 64_000:
        return error_json(
            "process_send_input",
            "permission_denied",
            "Process input exceeds the 64000 character limit.",
            outcome=OUTCOME_REJECTED,
            payload={"processId": processId},
        )
    try:
        ok = get_process_manager().send_input(processId, bounded_text)
    except ProcessOperationError:
        logger.warning(
            "[agent_tools] background process stdin failed: process_id=%s",
            processId,
            exc_info=True,
        )
        return error_json(
            "process_send_input",
            "process_input_failed",
            "Process input could not be delivered.",
            outcome=OUTCOME_REJECTED,
            payload={"processId": processId},
        )
    if ok is False:
        return error_json(
            "process_send_input",
            "permission_denied",
            "Process stdin is not enabled or process is not running.",
            outcome=OUTCOME_REJECTED,
            payload={"processId": processId},
        )
    return success_json(
        "process_send_input",
        {"processId": processId, "sentChars": len(bounded_text)},
    )


def process_close_handler(processId: str) -> str:
    _, rejected = _process_for_current_session("process_close", processId)
    if rejected is not None:
        return rejected
    payload = get_process_manager().close(processId)
    if payload.get("status") == "running":
        return error_json(
            "process_close",
            "permission_denied",
            "Running process records must be stopped or completed before close.",
            outcome=OUTCOME_REJECTED,
            payload=payload,
        )
    return success_json("process_close", payload)
