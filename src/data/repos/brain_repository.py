"""
BrainRepository -- 大脑架构数据仓库兼容入口

实现已拆分到 BrainSegmentRepository、BrainMemoryEntryRepository、
BrainPredictionRepository 和 BrainFeedbackSignalRepository。这个类保留旧调用点的
统一入口，同时让新调用方可以依赖更窄的 repository。
"""

from .brain_prediction_repository import BrainPredictionRepository
from .brain_segment_repository import BrainSegmentRepository


class BrainRepository(BrainSegmentRepository, BrainPredictionRepository):
    """Compatibility facade combining the brain repository modules."""
