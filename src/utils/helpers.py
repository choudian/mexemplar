"""
通用辅助函数

提供项目级别的通用工具函数，避免在多处重复相同逻辑。
"""

import json
import os
import re
import sys
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Optional

_TEMPLATE_RE = re.compile(r"\{(\w+)\}")


def safe_format_template(template: str, **kwargs: str) -> str:
    """安全的模板字符串替换。

    使用 re.sub 一次性替换 {key} 占位符，
    避免 str.format() 遇到未知花括号时抛出 KeyError。
    未匹配的 {key} 原样保留。替换值中的花括号不会被二次替换。

    注意：不支持 {{ }} 转义语法，模板中的双花括号会被忽略（只匹配 {word}）。

    Args:
        template: 包含 {key} 占位符的模板字符串
        **kwargs: 要替换的键值对

    Returns:
        替换后的字符串
    """

    def replacer(match):
        key = match.group(1)
        return str(kwargs[key]) if key in kwargs else match.group(0)

    return _TEMPLATE_RE.sub(replacer, template)


def is_frozen() -> bool:
    """当前是否运行在 PyInstaller 打包产物中。

    用于区分"资源该从解压目录找"和"开发时仓库根就有"。开发态下
    ``bundled_resource_path`` 总能解析到真实文件，所以只判断文件是否存在
    无法区分两种环境。
    """
    return getattr(sys, "_MEIPASS", None) is not None


def bundled_resource_path(relative_path: str | Path) -> Path:
    """定位随程序打包的只读资源（seed 文件、扩展等）。

    开发时相对仓库根，打包后相对 PyInstaller 的解压目录。这些资源不能用
    ``Path.cwd()`` 拼——装机后 cwd 是安装目录，那里没有源码树，本地开发
    却一切正常，于是问题只在用户机器上出现。

    Args:
        relative_path: 相对仓库根的路径，如 ``src/business/brain/seed/x.md``
    """
    meipass = getattr(sys, "_MEIPASS", None)
    base = Path(meipass) if meipass else Path(__file__).resolve().parents[2]
    return base / relative_path


def get_default_data_dir() -> Path:
    """获取默认数据目录，确保目录存在。

    优先使用 `EXEMPLAR_DATA_DIR` 指定的运行时根目录；未设置时回退到
    项目根目录下的 `data/` 目录。PyInstaller onefile 运行时不使用
    `_MEI...` 临时解压目录，而是优先定位开发仓库，找不到时使用本机
    应用数据目录。如不存在则自动创建。

    Returns:
        data 目录的 Path 对象
    """
    configured_dir = os.environ.get("EXEMPLAR_DATA_DIR", "").strip()
    if configured_dir:
        data_dir = Path(configured_dir).expanduser()
    elif getattr(sys, "frozen", False):
        data_dir = _frozen_data_dir()
    else:
        project_root = Path(__file__).parent.parent.parent
        data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def _frozen_data_dir() -> Path:
    repo_data_dir = _find_repo_data_dir_from_executable()
    if repo_data_dir is not None:
        return repo_data_dir

    # 与 Tauri 壳一致：数据放在程序旁边，装到 E:\mnt\test 时即 E:\mnt\test\data。
    # 正常启动时壳会传 EXEMPLAR_DATA_DIR，这里只覆盖单独运行 sidecar 的情况。
    install_data_dir = _install_dir_data_dir()
    if install_data_dir is not None:
        return install_data_dir

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return Path(local_app_data) / "Mexemplar" / "data"
    return Path.home() / ".mexemplar" / "data"


def _install_dir_data_dir() -> Optional[Path]:
    """exe 同级的 data 目录，不可写时返回 None 由调用方回退。

    装到 Program Files 这类受保护位置且非管理员运行时会写不进去。
    """
    executable = getattr(sys, "executable", "")
    if not executable:
        return None
    candidate = Path(executable).resolve().parent / "data"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError:
        return None
    return candidate


def _find_repo_data_dir_from_executable() -> Optional[Path]:
    executable = getattr(sys, "executable", "")
    if not executable:
        return None

    exe_dir = Path(executable).resolve().parent
    for candidate in (exe_dir, *exe_dir.parents):
        if (
            (candidate / "src-tauri").is_dir()
            and (candidate / "frontend").is_dir()
            and (candidate / "src").is_dir()
        ):
            return candidate / "data"
    return None


def append_jsonl(filepath: Path, record: dict, lock: Optional[threading.Lock] = None) -> None:
    """线程安全地追加一行 JSONL 到队列文件。"""
    line = json.dumps(record, ensure_ascii=False) + "\n"
    ctx = lock or nullcontext()
    with ctx:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line)


_VALID_THINKING_LEVELS = {"off", "low", "medium", "high"}


def normalize_thinking_level(value, *, fallback: str = "off") -> str:
    """将 thinking_level 归一化为 off | low | medium | high，非法值回退。"""
    normalized = str(value).strip().lower() if value is not None else fallback
    if normalized not in _VALID_THINKING_LEVELS:
        return fallback
    return normalized


def positive_int(value, *, default: int, minimum: int = 1) -> int:
    """把配置值归一化为正整数；不可解析或低于 ``minimum`` 时退回默认值。

    配置读取（尤其是测试替身和损坏的持久化值）可能给出 None、空串、MagicMock
    或负数。统一在此兜底，避免每个消费者各自重写 try/except + 下界判断。
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= minimum else default


def walk_exception_chain(
    exc: BaseException,
    *,
    max_depth: int = 20,
):
    """遍历异常链（__cause__ / __context__），yield 每个节点。

    防止循环引用（seen set），限制最大深度。用于在异常链中搜索
    特定标记（类型名、消息文本等），避免各处重复 while + seen 模式。
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and id(current) not in seen and depth < max_depth:
        seen.add(id(current))
        depth += 1
        yield current
        current = current.__cause__ or current.__context__
