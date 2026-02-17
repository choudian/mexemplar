"""
Pipeline 框架

提供简单的管道模式实现，用于编排数据处理流程。
"""

from typing import List, Dict, Any, Callable
from dataclasses import dataclass, field


@dataclass
class PipelineContext:
    """管道上下文（在阶段间传递数据）"""

    actions: List[Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    analysis: Dict[str, Any] = field(default_factory=dict)


class PipelineStage:
    """管道阶段（基类）"""

    def __init__(self, name: str):
        self.name = name

    def process(self, context: PipelineContext) -> PipelineContext:
        """处理阶段（子类实现）"""
        raise NotImplementedError(f"{self.__class__.__name__}.process() 未实现")

    def __call__(self, context: PipelineContext) -> PipelineContext:
        """使对象可调用"""
        return self.process(context)


class Pipeline:
    """预处理管道（编排器）"""

    def __init__(self, stages: List[PipelineStage] = None):
        self.stages = stages or []

    def add_stage(self, stage: PipelineStage) -> "Pipeline":
        """添加阶段（支持链式调用）"""
        self.stages.append(stage)
        return self

    def process(self, initial_actions: List[Any]) -> PipelineContext:
        """执行管道"""
        context = PipelineContext(actions=initial_actions)

        for stage in self.stages:
            context = stage.process(context)

        return context

    def __or__(self, stage: PipelineStage) -> "Pipeline":
        """支持 | 操作符（类似 Apache Beam）"""
        return self.add_stage(stage)
