"""
AI 模块

提供 AI 驱动的工作流生成功能
"""

# 从 preprocessing 模块导入（新的统一位置）
from src.business.ai.preprocessing import (
    DataPreprocessor,
    CompressionLevel,
    PreprocessingResult,
)
from src.business.ai.preprocessing.models import ProcessedAction
from src.business.ai.vision_analyzer import VisionAnalyzer
from src.business.ai.semantic_analyzer import SemanticAnalyzer
from src.business.ai.workflow_generator import WorkflowGenerator
from src.business.ai.workflow_orchestrator import WorkflowOrchestrator, ProcessingProgress

__all__ = [
    # 数据预处理
    "DataPreprocessor",
    "ProcessedAction",
    "PreprocessingResult",
    "CompressionLevel",
    # AI 分析器
    "VisionAnalyzer",
    "SemanticAnalyzer",
    # 工作流生成器
    "WorkflowGenerator",
    # 工作流编排器
    "WorkflowOrchestrator",
    "ProcessingProgress",
]
