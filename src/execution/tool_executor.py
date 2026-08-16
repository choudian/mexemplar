"""
工具执行引擎

使用用户系统 Python 创建的虚拟环境执行工具代码（async def execute(**kwargs)）。
应用本身的 Python（打包在 exe 中）与工具代码的运行环境完全隔离。
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from src.utils.helpers import get_default_data_dir

logger = logging.getLogger(__name__)

_TOOL_TIMEOUT = 120  # 秒，浏览器操作预留充足时间

_TOOL_TMP_DIR_NAME = "tool_tmp"
_TOOL_RUNS_DIR_NAME = "tool_runs"
_TOOL_VENV_DIR_NAME = "tool_venv"
_TOOL_RUNNER_FILENAME = "tool_runner.py"

# pip 包名 → import 名（二者不同时才需要列出）
_PIP_TO_IMPORT = {
    "beautifulsoup4": "bs4",
    "pillow": "PIL",
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "python-dateutil": "dateutil",
    "python-dotenv": "dotenv",
    "pyzmq": "zmq",
    "pyyaml": "yaml",
    "duckduckgo-search": "duckduckgo_search",
}

# 内置工具所需的第三方依赖，应用启动时预装到 tool_venv
BUILTIN_TOOL_DEPS: list[str] = ["duckduckgo-search"]

# 建 venv 和 pip install 都是「写同一个目录」的非幂等操作，必须串行：`python -m venv`
# 并发跑同一目录会互相覆盖，pip 并发装同一 site-packages 会留下半装状态。并发源至少
# 三个——工具执行本身可并发（AgentLoop 最多 4 worker 同时跑），加上启动预热线程。
_VENV_LOCK = threading.RLock()


def ensure_builtin_deps() -> None:
    """预装内置工具依赖到 tool_venv（同步，会阻塞到装完）。失败仅打 warning。

    首启要建 venv + pip install，真机实测约 89 秒。启动路径请用
    ``ensure_builtin_deps_async``，别在 lifespan 里直接调这个。
    """
    try:
        venv_python = _get_venv_python()
    except RuntimeError as e:
        logger.warning(f"[ToolExecutor] 跳过内置依赖预装: {e}")
        return

    ok, err = _ensure_dependencies(venv_python, BUILTIN_TOOL_DEPS)
    if ok:
        logger.info(f"[ToolExecutor] 内置工具依赖就绪: {BUILTIN_TOOL_DEPS}")
    else:
        logger.warning(f"[ToolExecutor] 内置依赖预装失败: {err}")


def ensure_builtin_deps_async() -> threading.Thread:
    """后台预装内置工具依赖，立即返回，不阻塞启动。

    首启建 venv + pip install 实测约 89 秒（真机：13:22:06 建 venv → 13:23:35 就绪），
    同步调用会把 sidecar 的 lifespan 卡住这么久，用户对着空界面干等。

    后台化是安全的：预装只是「预热」，不是可用性前提——``run_tool_code`` 在真正执行
    工具前会自己调 ``_ensure_dependencies``。最坏情况是预热没跑完用户就调了工具，
    那次调用自己装（慢一点），``_VENV_LOCK`` 保证两边不会同时写同一个 venv。

    daemon 线程：装依赖装到一半不该拦着进程退出，下次启动会重来。
    返回线程对象供调用方按需 join（当前无人 join）。
    """
    thread = threading.Thread(
        target=ensure_builtin_deps,
        name="builtin-deps-preinstall",
        daemon=True,
    )
    thread.start()
    return thread


# Runner 脚本：以模块方式加载工具代码，调用 execute()，结果写入 JSON 文件
# 工具代码的 if __name__ == "__main__" 不会被触发（模块名不是 __main__）
_RUNNER_CODE = """\
import asyncio
import importlib.util
import json
import sys

def main():
    tool_path = sys.argv[1]
    params_path = sys.argv[2]
    result_path = sys.argv[3]

    spec = importlib.util.spec_from_file_location("tool_module", tool_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with open(params_path, "r", encoding="utf-8") as f:
        params = json.load(f)

    try:
        result = asyncio.run(mod.execute(**params))
    except Exception as e:
        result = {"success": False, "message": f"{type(e).__name__}: {e}", "data": None}

    if not isinstance(result, dict):
        result = {"success": True, "message": "执行完成", "data": result}

    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

if __name__ == "__main__":
    main()
"""


def _find_system_python() -> str | None:
    """查找系统安装的 Python。"""
    for name in ["python", "python3"]:
        path = shutil.which(name)
        if path:
            return path
    return None


def _get_venv_python() -> str:
    """获取 venv 的 python 路径，不存在则创建。"""
    venv_dir = get_default_data_dir() / _TOOL_VENV_DIR_NAME
    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
    else:
        venv_python = venv_dir / "bin" / "python"

    # 快路径：venv 已就绪时不进锁，避免每次工具执行都排队。
    if venv_python.exists():
        return str(venv_python)

    with _VENV_LOCK:
        # 双重检查：等锁期间可能已被别的线程建好。
        if venv_python.exists():
            return str(venv_python)

        system_python = _find_system_python()
        if not system_python:
            raise RuntimeError(
                "未找到系统 Python。请安装 Python 3.11+ 并确保 python 命令在 PATH 中。"
            )

        logger.info(f"[ToolExecutor] 使用 {system_python} 创建虚拟环境: {venv_dir}")
        venv_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [system_python, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
        return str(venv_python)


def _ensure_runner() -> str:
    """确保 runner 脚本存在并是最新的，返回路径。"""
    runner_path = get_default_data_dir() / _TOOL_RUNNER_FILENAME
    runner_path.parent.mkdir(parents=True, exist_ok=True)
    if not runner_path.exists() or runner_path.read_text(encoding="utf-8") != _RUNNER_CODE:
        runner_path.write_text(_RUNNER_CODE, encoding="utf-8")
    return str(runner_path)


_IMPORT_TO_PIP = {v: k for k, v in _PIP_TO_IMPORT.items()}


def _extract_imports(code: str) -> list[str]:
    """从代码中提取非标准库的顶层 import 名（转为 pip 包名）。"""
    from src.utils.ast_helpers import extract_import_names

    names = extract_import_names(code)
    stdlib = getattr(sys, "stdlib_module_names", frozenset())
    return [_IMPORT_TO_PIP.get(n, n) for n in names if n not in stdlib]


def run_command_in_venv(command: str) -> dict:
    """
    在工具 venv 环境中执行 shell 命令。供业务层 run_command 工具调用。

    LLM 根据错误信息自行决定执行什么命令，如：
    - pip install requests
    - playwright install chromium
    - python -c "import playwright; print(playwright.__version__)"
    """
    if not command.strip():
        return {"success": False, "message": "命令不能为空"}

    # 安全校验：拒绝换行符和 shell 元字符，防止命令拼接注入
    cmd_stripped = command.strip()
    if re.search(r"[\r\n;&|`$]", cmd_stripped):
        return {"success": False, "message": "命令包含不安全字符"}

    # 安全校验：只允许常见安全命令前缀
    if not any(
        cmd_stripped.startswith(p)
        for p in (
            "pip install ",
            "pip3 install ",
            "python -m pip install ",
            "python3 -m pip install ",
            "playwright install ",
        )
    ):
        return {
            "success": False,
            "message": "不支持的命令，仅允许: pip install, playwright install",
        }

    try:
        venv_python = _get_venv_python()
    except RuntimeError as e:
        return {"success": False, "message": str(e)}

    # 替换命令中的 python → venv python
    if cmd_stripped.startswith("python ") or cmd_stripped.startswith("python3 "):
        cmd_stripped = venv_python + cmd_stripped[cmd_stripped.index(" ") :]
    elif cmd_stripped.startswith("pip ") or cmd_stripped.startswith("pip3 "):
        cmd_stripped = f"{venv_python} -m pip{cmd_stripped[4:]}"
    elif cmd_stripped.startswith("playwright "):
        cmd_stripped = f"{venv_python} -m playwright {cmd_stripped[11:]}"

    try:
        proc = subprocess.run(
            cmd_stripped,
            capture_output=True,
            text=True,
            timeout=180,
            shell=True,
        )
        output = proc.stdout.strip()
        error = proc.stderr.strip()
        if proc.returncode != 0:
            return {
                "success": False,
                "message": error or output or f"命令执行失败 (exit code {proc.returncode})",
            }
        return {"success": True, "message": output or "命令执行成功"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "命令执行超时（180秒）"}
    except Exception as e:
        return {"success": False, "message": f"命令执行出错: {e}"}


def _ensure_dependencies(venv_python: str, dependencies: list[str]) -> tuple[bool, str]:
    """
    检查并安装缺失的 pip 依赖到 venv。

    通过 venv 的 python 检查哪些包未安装，只安装缺失的。

    「检查缺失」和「pip install」必须一起串行，否则两个并发调用都查到同一个包缺失，
    各自跑一次 pip install 写同一个 site-packages。
    """
    if not dependencies:
        return True, ""
    with _VENV_LOCK:
        return _ensure_dependencies_locked(venv_python, dependencies)


def _ensure_dependencies_locked(venv_python: str, dependencies: list[str]) -> tuple[bool, str]:
    """``_ensure_dependencies`` 的实际逻辑；调用方必须已持有 ``_VENV_LOCK``。"""
    # 用 venv python 检查哪些包缺失
    pkg_pairs = [[pkg, _PIP_TO_IMPORT.get(pkg, pkg)] for pkg in dependencies]
    check_script = (
        "import importlib.util, json, sys; "
        "pairs = json.loads(sys.argv[1]); "
        "missing = [p for p, i in pairs if importlib.util.find_spec(i) is None]; "
        "print(json.dumps(missing))"
    )

    try:
        proc = subprocess.run(
            [venv_python, "-c", check_script, json.dumps(pkg_pairs)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        missing = json.loads(proc.stdout.strip()) if proc.returncode == 0 else list(dependencies)
    except Exception:
        missing = list(dependencies)

    if not missing:
        return True, ""

    logger.info(f"[ToolExecutor] 安装缺失依赖: {missing}")
    try:
        proc = subprocess.run(
            [venv_python, "-m", "pip", "install", *missing],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            return False, f"依赖安装失败: {proc.stderr.strip()}"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "依赖安装超时（120秒）"
    except Exception as e:
        return False, f"依赖安装出错: {e}"


def _create_tool_run_dir(data_dir: Path) -> Path:
    """创建持久工具输出目录。工具代码的 cwd 会指向这里。"""
    runs_dir = data_dir / _TOOL_RUNS_DIR_NAME
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir = runs_dir / uuid.uuid4().hex
    run_dir.mkdir()
    return run_dir


def _build_tool_run_env(run_dir: Path, data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "MEXEMPLAR_DATA_DIR": str(data_dir),
            "MEXEMPLAR_TOOL_RUN_DIR": str(run_dir),
            "MEXEMPLAR_OUTPUT_DIR": str(run_dir),
        }
    )
    return env


def _collect_output_files(run_dir: Path, *, limit: int = 50) -> list[str]:
    """收集工具输出目录中的相对文件路径，用于把实际落点回传给 Agent。"""
    files: list[str] = []
    try:
        for path in run_dir.rglob("*"):
            if not path.is_file():
                continue
            files.append(path.relative_to(run_dir).as_posix())
            if len(files) >= limit:
                break
    except OSError:
        return files
    return files


def _attach_output_metadata(result: dict, run_dir: Path) -> dict:
    output_files = _collect_output_files(run_dir)
    if output_files:
        result.setdefault("output_dir", str(run_dir))
        result.setdefault("output_files", output_files)
    return result


def run_tool_code(code: str, parameters: dict, dependencies: list[str] | None = None) -> dict:
    """
    在 venv 子进程中执行工具代码，返回标准结果字典。

    工具代码格式：
        async def execute(**kwargs) -> Dict[str, Any]:
            return {"success": True/False, "message": "...", "data": ...}

    Args:
        code: 工具完整 Python 源码
        parameters: 传给 execute() 的参数字典
        dependencies: 需要 pip install 的第三方包名列表

    Returns:
        {"success": bool, "message": str, "data": Any}
    """
    # 1. 获取 venv python
    try:
        venv_python = _get_venv_python()
    except RuntimeError as e:
        return {"success": False, "message": str(e), "data": None}

    # 2. 安装依赖：合并显式声明 + 代码中自动检测的 import
    all_deps = list({*(dependencies or []), *_extract_imports(code)})
    ok, err = _ensure_dependencies(venv_python, all_deps)
    if not ok:
        return {"success": False, "message": err, "data": None}

    # 3. 准备 runner 脚本
    runner_path = _ensure_runner()

    # 4. 写临时文件（每次执行独立目录，支持并发）
    data_dir = get_default_data_dir()
    tmp_dir = data_dir / _TOOL_TMP_DIR_NAME
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_run_dir = Path(tempfile.mkdtemp(dir=tmp_dir))
    output_dir = _create_tool_run_dir(data_dir)

    tool_file = tmp_run_dir / "tool.py"
    params_file = tmp_run_dir / "params.json"
    result_file = tmp_run_dir / "result.json"

    try:
        tool_file.write_text(code, encoding="utf-8")
        params_file.write_text(json.dumps(parameters, ensure_ascii=False), encoding="utf-8")

        # 5. 子进程执行
        try:
            proc = subprocess.run(
                [venv_python, runner_path, str(tool_file), str(params_file), str(result_file)],
                capture_output=True,
                text=True,
                timeout=_TOOL_TIMEOUT,
                cwd=str(output_dir),
                env=_build_tool_run_env(output_dir, data_dir),
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": f"工具执行超时（超过 {_TOOL_TIMEOUT} 秒）",
                "data": None,
            }

        # 6. 读取结果
        if not result_file.exists():
            stderr = proc.stderr.strip() if proc.stderr else "未知错误"
            logger.error(f"[ToolExecutor] 工具执行失败: {stderr}")
            return {"success": False, "message": f"工具执行失败: {stderr}", "data": None}

        result = json.loads(result_file.read_text(encoding="utf-8"))
        if isinstance(result, dict):
            return _attach_output_metadata(result, output_dir)
        return {"success": True, "message": "执行完成", "data": result}

    except Exception as e:
        logger.error(f"[ToolExecutor] 执行出错: {e}")
        return {"success": False, "message": f"执行出错: {type(e).__name__}: {e}", "data": None}

    finally:
        shutil.rmtree(tmp_run_dir, ignore_errors=True)
