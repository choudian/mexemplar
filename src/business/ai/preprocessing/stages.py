"""
~~已废弃 - 新的 Pipeline 实现在 pipeline.py 中~~

处理阶段实现（已废弃）

此文件中的 Stage 类已不再使用，所有预处理逻辑已重构到 pipeline.py 中的 PreprocessingPipeline。
保留此文件仅用于向后兼容，将在未来版本中移除。

新的 Pipeline 架构：
- PreprocessingPipelineContext: 预处理管道上下文
- PreprocessingPipeline: 预处理管道编排器
- 具体阶段: CompressionStage, IntelligenceFilterStage, NetworkAnalysisStage, etc.

请参考 pipeline.py 以获取最新的实现。
"""

# ~~已废弃的 Stage 类~~
# 以下类已不再使用，保留仅用于文档目的