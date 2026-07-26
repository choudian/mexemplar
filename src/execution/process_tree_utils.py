"""进程树终止公共 helper。

照搬自 ``external_coding_process`` 的私有 helper，供 ``command_runner``（同步 exec）
和 ``external_coding_process``（外部 coding CLI）共用。psutil 递归终止 + terminate→kill
→wait_procs 验证，确保整棵进程树退出——这对 shell 模式尤其关键，shell（bash/cmd）是
中间父进程，只杀直接子会留下孙进程（真实命令）继续跑。
"""

from __future__ import annotations

import subprocess

import psutil


def terminate_process_tree(process: subprocess.Popen[bytes]) -> bool:
    """Stop a spawned process tree and confirm every observed member exited."""
    if process.poll() is not None:
        return True
    try:
        parent = psutil.Process(process.pid)
        descendants = parent.children(recursive=True)
        stopped = terminate_psutil_processes([*descendants, parent])
        try:
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return stopped and process.poll() is not None
    except psutil.NoSuchProcess:
        try:
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return process.poll() is not None
    except psutil.Error:
        try:
            process.terminate()
            process.wait(timeout=2)
            # The parent stopped, but process-tree enumeration failed, so the
            # tree as a whole cannot be certified as gone.
            return False
        except OSError:
            return False
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=2)
                return False
            except (OSError, subprocess.TimeoutExpired):
                return False


def terminate_pid_tree(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        # This path is only used after a restart. If the parent vanished
        # between identity verification and tree enumeration, descendants
        # cannot be proven gone.
        return False
    except psutil.Error:
        return False
    try:
        descendants = process.children(recursive=True)
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        return False
    return terminate_psutil_processes([*descendants, process])


def terminate_psutil_processes(processes: list[psutil.Process]) -> bool:
    """Terminate, then kill, and finally verify a fixed process set is gone."""
    for item in processes:
        try:
            item.terminate()
        except psutil.Error:
            pass
    try:
        _, alive = psutil.wait_procs(processes, timeout=2)
    except psutil.Error:
        return False
    for item in alive:
        try:
            item.kill()
        except psutil.Error:
            pass
    if not alive:
        return True
    try:
        _, still_alive = psutil.wait_procs(alive, timeout=2)
    except psutil.Error:
        return False
    return not still_alive
