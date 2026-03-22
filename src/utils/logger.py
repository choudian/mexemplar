"""
日志系统模块

提供统一的日志配置和管理
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler


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
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(log_level)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        # 文件处理器
        if file_output:
            if log_dir is None:
                # 使用默认路径：data/logs
                project_root = Path(__file__).parent.parent.parent
                log_dir = project_root / "data" / "logs"

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


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称，如果为None则使用根记录器

    Returns:
        日志记录器
    """
    if name is None:
        name = "mexemplar"

    logger = logging.getLogger(name)

    # 如果还没有配置，使用默认配置
    if not logger.handlers and not logging.getLogger().handlers:
        setup_logger(name)

    return logger


# 初始化根日志记录器
_root_logger = setup_logger("mexemplar")
