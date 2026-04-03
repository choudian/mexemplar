"""
网络请求智能分析的数据模型
"""

from dataclasses import dataclass
from typing import Any
from enum import Enum


class RequestMeaning(str, Enum):
    """请求意义分类"""

    MEANINGFUL = "meaningful"  # 有意义，需要保留
    NOT_MEANINGFUL = "not_meaningful"  # 无意义，可以过滤
    ENCRYPTED = "encrypted"  # 加密数据，无法使用
    UNKNOWN = "unknown"  # 无法判断


class Replayability(str, Enum):
    """可复现性"""

    REPLAYABLE = "replayable"  # 可以直接复现
    NOT_REPLAYABLE = "not_replayable"  # 不能复现（需要认证、加密等）
    UNKNOWN = "unknown"  # 无法判断


@dataclass
class DataDependency:
    """数据依赖关系"""

    field_name: str  # 字段名
    field_value: Any  # 字段值
    source_request_id: str  # 来源请求 ID
    source_path: str  # 在来源响应中的路径（如 "data.items[0].id"）
