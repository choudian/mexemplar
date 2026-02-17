"""
工具模块

提供配置数据类、日志等通用工具

注意:
- ConfigManager 已被 UnifiedConfigManager 替代
- 配置数据类已移动到 src.data.config_models
- 请使用 src.data.unified_config.get_unified_config() 获取全局配置实例
"""

# 为了向后兼容，重定向到新位置
from src.data.config_models import AppConfig
from .logger import setup_logger, get_logger

__all__ = [
    "AppConfig",
    "setup_logger",
    "get_logger",
]
