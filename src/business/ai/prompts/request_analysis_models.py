"""
网络请求智能分析的数据模型
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
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


@dataclass
class RequestAnalysisResult:
    """单个请求的分析结果"""

    request_id: str
    is_meaningful: bool
    meaning: RequestMeaning
    is_replayable: bool
    replayability: Replayability
    reason: str

    # 依赖关系
    depends_on: List[DataDependency] = field(default_factory=list)  # 这个请求使用了哪些数据
    used_by: List[str] = field(default_factory=list)  # 这个请求的数据被哪些请求使用

    # 加密检测
    is_encrypted: bool = False
    encryption_type: Optional[str] = None

    # 置信度
    confidence: float = 0.0  # 0.0 - 1.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "is_meaningful": self.is_meaningful,
            "meaning": self.meaning.value,
            "is_replayable": self.is_replayable,
            "replayability": self.replayability.value,
            "reason": self.reason,
            "depends_on": [
                {
                    "field_name": d.field_name,
                    "field_value": d.field_value,
                    "source_request_id": d.source_request_id,
                    "source_path": d.source_path,
                }
                for d in self.depends_on
            ],
            "used_by": self.used_by,
            "is_encrypted": self.is_encrypted,
            "encryption_type": self.encryption_type,
            "confidence": self.confidence,
        }


@dataclass
class BatchAnalysisResult:
    """批量分析结果"""

    results: List[RequestAnalysisResult]
    total_requests: int
    meaningful_count: int
    encrypted_count: int
    not_meaningful_count: int

    def get_meaningful_request_ids(self) -> List[str]:
        """获取所有有意义请求的 ID"""
        return [r.request_id for r in self.results if r.is_meaningful]

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """获取依赖关系图"""
        graph = {}
        for result in self.results:
            if result.depends_on:
                graph[result.request_id] = [dep.source_request_id for dep in result.depends_on]
        return graph
