"""
工具执行引擎

使用用户系统 Python 创建的虚拟环境执行工具代码（async def execute(**kwargs)）。
应用本身的 Python（打包在 exe 中）与工具代码的运行环境完全隔离。
"""

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_TOOL_TIMEOUT = 120  # 秒，浏览器操作预留充足时间

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_DATA_DIR = _PROJECT_ROOT / "data"
_VENV_DIR = _DATA_DIR / "tool_venv"
_RUNNER_PATH = _DATA_DIR / "tool_runner.py"

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


def ensure_builtin_deps() -> None:
    """应用启动时预装内置工具依赖到 tool_venv。失败仅打 warning，不阻塞启动。"""
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
    if sys.platform == "win32":
        venv_python = _VENV_DIR / "Scripts" / "python.exe"
    else:
        venv_python = _VENV_DIR / "bin" / "python"

    if venv_python.exists():
        return str(venv_python)

    system_python = _find_system_python()
    if not system_python:
        raise RuntimeError("未找到系统 Python。请安装 Python 3.11+ 并确保 python 命令在 PATH 中。")

    logger.info(f"[ToolExecutor] 使用 {system_python} 创建虚拟环境: {_VENV_DIR}")
    _VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [system_python, "-m", "venv", str(_VENV_DIR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return str(venv_python)


def _ensure_runner() -> str:
    """确保 runner 脚本存在并是最新的，返回路径。"""
    _RUNNER_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _RUNNER_PATH.exists() or _RUNNER_PATH.read_text(encoding="utf-8") != _RUNNER_CODE:
        _RUNNER_PATH.write_text(_RUNNER_CODE, encoding="utf-8")
    return str(_RUNNER_PATH)


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
    """
    if not dependencies:
        return True, ""

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
    tmp_dir = _DATA_DIR / "tool_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(dir=tmp_dir))

    tool_file = run_dir / "tool.py"
    params_file = run_dir / "params.json"
    result_file = run_dir / "result.json"

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
            return result
        return {"success": True, "message": "执行完成", "data": result}

    except Exception as e:
        logger.error(f"[ToolExecutor] 执行出错: {e}")
        return {"success": False, "message": f"执行出错: {type(e).__name__}: {e}", "data": None}

    finally:
        shutil.rmtree(run_dir, ignore_errors=True)
