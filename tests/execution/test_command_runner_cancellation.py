from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import psutil

from src.business.agents.run_context import CancelReason, CancelToken
from src.execution.command_runner import run_command


def _wait_for_file(path: Path, timeout: float = 10) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


def test_user_cancel_terminates_entire_sync_command_tree(tmp_path):
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    pid_file = tmp_path / "child.pid"
    child.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    parent.write_text(
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, 'child.py'])\n"
        "pathlib.Path('child.pid').write_text(str(child.pid), encoding='utf-8')\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    token = CancelToken()

    def cancel() -> None:
        assert _wait_for_file(pid_file)
        token.cancel(CancelReason.USER_CANCEL)

    canceller = threading.Thread(target=cancel, daemon=True)
    canceller.start()
    result = run_command(
        f'"{sys.executable}" "{parent.name}"',
        cwd=tmp_path,
        timeout_ms=30_000,
        cancel_token=token,
    )
    canceller.join(timeout=2)
    child_pid = int(pid_file.read_text(encoding="utf-8"))

    assert result.status == "interrupted"
    assert result.interrupted is True
    assert psutil.pid_exists(child_pid) is False
