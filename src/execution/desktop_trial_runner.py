from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.execution.desktop_trial_models import TrialResult

WHITELISTED_ENV_VARS = {
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "PYTHONPATH",
    "PYTHONHOME",
    "LANG",
    "LC_ALL",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
}
SENSITIVE_PATTERNS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "KEYRING")
TRIAL_TIMEOUT_SECONDS = 120

_WRAPPER_SUFFIX = r"""
async def _main():
    try:
        result = await execute()
        if not isinstance(result, dict):
            return {"ok": False, "summary": "execute() 返回非 dict: " + type(result).__name__, "details": None}
        if "ok" not in result or "summary" not in result:
            return {"ok": False, "summary": "execute() 返回缺少 ok 或 summary 字段", "details": result}
        return result
    except Exception as exc:
        return {
            "ok": False,
            "summary": type(exc).__name__ + ": " + str(exc),
            "details": {"traceback": traceback.format_exc()},
        }

if __name__ == "__main__":
    try:
        payload = asyncio.run(_main())
    except Exception as exc:
        payload = {
            "ok": False,
            "summary": type(exc).__name__ + ": " + str(exc),
            "details": {"traceback": traceback.format_exc()},
        }
    print(json.dumps(payload, ensure_ascii=False))
"""

_WRAPPER_PREFIX = "import asyncio\nimport json\nimport traceback\n\n"


def build_whitelisted_env(parent_env: dict[str, str] | None = None) -> dict[str, str]:
    source = parent_env or os.environ
    result: dict[str, str] = {}
    for key, value in source.items():
        key_upper = key.upper()
        if key_upper not in WHITELISTED_ENV_VARS:
            continue
        if any(pattern in key_upper for pattern in SENSITIVE_PATTERNS):
            continue
        result[key] = value
    return result


def _stderr_tail(stderr_text: str) -> str:
    tail = "\n".join(stderr_text.splitlines()[-5:])[:200]
    return tail or "(无 stderr 输出)"


def parse_trial_stdout(stdout_bytes: bytes, stderr_bytes: bytes, exit_code: int) -> dict[str, Any]:
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    lines = [line.strip() for line in stdout_text.splitlines() if line.strip()]
    if lines:
        try:
            parsed = json.loads(lines[-1])
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and "ok" in parsed and "summary" in parsed:
            return parsed
    return {
        "ok": False,
        "summary": _stderr_tail(stderr_text),
        "details": {"_fallback": "stdout_no_json", "exit_code": exit_code},
    }


def _trial_root() -> Path:
    from src.utils.helpers import get_default_data_dir

    return get_default_data_dir() / "trials"


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def run_desktop_trial(code: str, trial_id: str) -> TrialResult:
    trial_dir = _trial_root() / trial_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = trial_dir / "stdout.log"
    stderr_path = trial_dir / "stderr.log"
    wrapper_code = _WRAPPER_PREFIX + code + "\n" + _WRAPPER_SUFFIX
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", wrapper_code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(trial_dir),
        env=build_whitelisted_env(),
        creationflags=creationflags,
    )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = proc.communicate(timeout=TRIAL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.terminate()
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                timeout=5,
                capture_output=True,
                check=False,
            )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_bytes, stderr_bytes = proc.communicate()

    _write_bytes(stdout_path, stdout_bytes)
    _write_bytes(stderr_path, stderr_bytes)

    if timed_out:
        return TrialResult(
            ok=False,
            summary="代码执行超过 120 秒已被终止",
            details={"timed_out": True},
            exit_code=proc.returncode,
            timed_out=True,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            trial_id=trial_id,
        )

    parsed = parse_trial_stdout(stdout_bytes, stderr_bytes, proc.returncode or 0)
    return TrialResult(
        ok=bool(parsed.get("ok")),
        summary=str(parsed.get("summary", "")),
        details=parsed.get("details"),
        exit_code=proc.returncode,
        timed_out=False,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        trial_id=trial_id,
    )
