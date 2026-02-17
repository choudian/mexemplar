"""
调试日志工具模块

提供统一的调试日志记录功能，可以通过配置开关控制
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
import os


# 全局调试日志开关（可以通过环境变量或配置控制）
_DEBUG_LOG_ENABLED = os.getenv("MEXEMPLAR_DEBUG_LOG", "false").lower() == "true"

# 调试日志文件路径（默认在项目根目录的 .cursor/debug.log）
_project_root: Optional[Path] = None
_debug_log_path: Optional[Path] = None


def set_project_root(root: Path):
    """设置项目根目录（用于计算调试日志路径）"""
    global _project_root, _debug_log_path
    _project_root = root
    _debug_log_path = root / ".cursor" / "debug.log"


def set_debug_log_enabled(enabled: bool):
    """设置调试日志开关"""
    global _DEBUG_LOG_ENABLED
    _DEBUG_LOG_ENABLED = enabled


def _get_debug_log_path() -> Path:
    """获取调试日志文件路径"""
    if _debug_log_path:
        return _debug_log_path

    # 如果未设置项目根目录，尝试从当前文件位置推断
    if _project_root:
        return _project_root / ".cursor" / "debug.log"

    # 默认：从当前工作目录查找项目根（包含 src 目录的父目录）
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / "src").exists():
            return parent / ".cursor" / "debug.log"

    # 最后回退到当前目录
    return Path(".cursor") / "debug.log"


def debug_log(
    location: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    session_id: str = "debug-session",
    run_id: str = "run1",
    hypothesis_id: Optional[str] = None,
):
    """
    记录调试日志到 .cursor/debug.log

    Args:
        location: 代码位置（格式：文件名:行号）
        message: 日志消息
        data: 附加数据（字典）
        session_id: 会话ID
        run_id: 运行ID
        hypothesis_id: 假设ID（可选）
    """
    if not _DEBUG_LOG_ENABLED:
        return

    try:
        log_path = _get_debug_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)

        log_entry = {
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": time.time() * 1000,  # 毫秒时间戳（与现有日志格式一致）
            "sessionId": session_id,
            "runId": run_id,
        }

        if hypothesis_id:
            log_entry["hypothesisId"] = hypothesis_id

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        # 静默失败，不影响主程序
        pass
