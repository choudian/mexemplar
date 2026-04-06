"""
工具模块

提供日志等通用工具。

配置相关：
- 请使用 src.data.unified_config.get_unified_config() 获取全局配置实例
- 配置数据类已移动到 src.data.config_models
"""

from .logger import setup_logger, get_logger

__all__ = [
    "setup_logger",
    "get_logger",
]
