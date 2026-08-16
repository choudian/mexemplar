"""
日志系统模块

提供统一的日志配置和管理
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler

from src.utils.helpers import get_default_data_dir


def _force_utf8_stream(stream) -> None:
    """把标准流切成 UTF-8 + errors=replace。

    Windows 上子进程的 ``sys.stdout`` 默认用系统 ANSI 代码页（中文机器是 GBK）：
    日志里的中文在 Tauri 侧全成乱码，emoji 更是直接让 ``StreamHandler.emit`` 抛
    ``UnicodeEncodeError`` 打断 logging（真机 sidecar 启动时 3 次
    ``--- Logging error ---``，丢了录制恢复的三条日志）。文件 handler 一直显式
    ``encoding="utf-8"``，这里对齐。

    ``errors="replace"`` 是第二道保险：万一仍有编不出的字符，替换成占位符而不是
    抛异常——日志编码问题不该打断业务流程。

    流不支持 ``reconfigure``（被替换成非 TextIOWrapper，如测试期的 capture 对象）
    或已分离时静默跳过：日志配置失败不能中断启动。
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        pass


def setup_logger(
    name: str = "mexemplar",
    log_dir: Optional[str] = None,
    log_level: int = logging.INFO,
    console_output: bool = True,
    file_output: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    设置日志记录器

    Args:
        name: 日志记录器名称
        log_dir: 日志文件目录，如果为None则使用默认路径
        log_level: 日志级别
        console_output: 是否输出到控制台
        file_output: 是否输出到文件
        max_bytes: 日志文件最大大小（字节）
        backup_count: 备份文件数量

    Returns:
        配置好的日志记录器
    """
    # 首先配置根logger以捕获所有模块的日志
    root_logger = logging.getLogger()
    # 始终更新根logger级别（确保 --log-level DEBUG 等参数能生效）
    root_logger.setLevel(log_level)

    if not root_logger.handlers:
        # 日志格式
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )

        # 控制台处理器
        if console_output:
            # sidecar 的 stdout/stderr 由 Tauri 收走转发，必须先固定成 UTF-8，
            # 否则中文乱码 + emoji 抛 UnicodeEncodeError。stderr 一并处理：
            # uvicorn 往 stderr 写日志，同样可能带非 ASCII。
            _force_utf8_stream(sys.stdout)
            _force_utf8_stream(sys.stderr)
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # 文件处理器
        if file_output:
            if log_dir is None:
                # 使用统一 data 目录，Tauri sidecar 会通过 EXEMPLAR_DATA_DIR 指定运行期根目录。
                log_dir = get_default_data_dir() / "logs"

            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)

            log_file = log_dir / "mexemplar.log"
            file_handler = RotatingFileHandler(
                log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
    else:
        # handlers 已存在，更新它们的级别
        for handler in root_logger.handlers:
            handler.setLevel(log_level)

    # 配置指定的logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # 不再为这个logger添加处理器,让日志传播到根logger

    return logger


# 初始化根日志记录器
setup_logger("mexemplar")
