"""
Pipeline 框架 - 预处理管道实现

编排 DataPreprocessor 的所有处理阶段。
"""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from src.business.ai.preprocessing.models import CompressionLevel
from src.recording.recorder import Action
from src.business.ai.preprocessing.analyzers.intelligence_analyzer import (
    CompressionModelError,
    TokenLimitExceededError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


# ==================== 基础类 ====================


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


# ==================== 预处理管道专用类 ====================


@dataclass
class PreprocessingPipelineContext:
    """预处理管道上下文"""

    # 输入参数
    actions: List[Action]
    compression_level: CompressionLevel
    enable_analysis: bool
    recording_id: str
    preprocessor: Any  # DataPreprocessor 实例

    # 中间结果
    compressed_actions: List[Action] = field(default_factory=list)
    intelligent_analysis: List[Any] = field(default_factory=list)
    filter_result: Dict[str, Any] = field(default_factory=dict)

    # 压缩模型错误
    compression_model_error: Optional[Dict[str, Any]] = None

    # 最终结果
    processed_actions: List[Any] = field(default_factory=list)
    key_actions: List[Any] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def metadata_with_stats(self) -> Dict[str, Any]:
        """获取包含统计信息的完整 metadata"""
        metadata = self.metadata.copy()

        if self.enable_analysis and self.compression_model_error:
            if "analysis_stats" not in metadata:
                metadata["analysis_stats"] = {}
            metadata["analysis_stats"]["compression_model_error"] = self.compression_model_error
            metadata["analysis_stats"]["compression_model_fallback"] = True

        return metadata


class PreprocessingPipeline:
    """预处理管道 - 编排所有处理阶段"""

    def __init__(
        self,
        preprocessor: Any,
        compression_level: CompressionLevel = CompressionLevel.MODERATE,
        enable_analysis: bool = True,
        recording_id: str = "unknown",
    ):
        """
        初始化预处理管道

        Args:
            preprocessor: DataPreprocessor 实例
            compression_level: 压缩级别
            enable_analysis: 是否启用分析
            recording_id: 录制 ID
        """
        self.preprocessor = preprocessor
        self.compression_level = compression_level
        self.enable_analysis = enable_analysis
        self.recording_id = recording_id

    def process(self, initial_actions: List[Action]) -> PreprocessingPipelineContext:
        """执行管道"""
        context = PreprocessingPipelineContext(
            actions=initial_actions,
            compression_level=self.compression_level,
            enable_analysis=self.enable_analysis,
            recording_id=self.recording_id,
            preprocessor=self.preprocessor,
        )

        # 按顺序执行各个 Stage
        stages = [
            CompressionStage(),
            IntelligenceFilterStage(),
            RecommendationFilterStage(),
            ActionProcessingStage(),
            KeyActionsStage(),
            ScreenshotOptimizationStage(),
            MetadataStage(),
        ]

        for stage in stages:
            context = stage.process(context)
            if context is None:
                raise RuntimeError(f"Stage {stage.name} 返回了 None")

        return context


# ==================== 具体阶段实现 ====================


class CompressionStage(PipelineStage):
    """基础压缩：合并输入、过滤重复、清理 DOM"""

    def __init__(self):
        super().__init__("compression")

    def process(self, context: PreprocessingPipelineContext) -> PreprocessingPipelineContext:
        logger.info("步骤1: 基础压缩...")
        compressed_actions = context.preprocessor._apply_compression(
            context.actions, context.compression_level
        )
        logger.info(f"  ✅ 基础压缩完成，保留 {len(compressed_actions)} 个操作")

        context.compressed_actions = compressed_actions
        context.actions = compressed_actions
        return context


class IntelligenceFilterStage(PipelineStage):
    """智能过滤：规则引擎 + LLM 数据压缩模型"""

    def __init__(self):
        super().__init__("intelligence_filter")

    def _fallback_to_rule_engine(
        self, context: PreprocessingPipelineContext,
        error_type: str, message: str, detail: str,
    ) -> None:
        """压缩模型失败时回退到规则引擎"""
        context.compression_model_error = {
            "type": error_type,
            "message": message,
            "detail": detail,
        }
        logger.warning(f"  ⚠️ {message}")
        intelligent_analysis = (
            context.preprocessor.request_intelligence_analyzer.analyze_requests(
                context.actions, use_llm=False
            )
        )
        context.compressed_actions = context.preprocessor._filter_requests_by_intelligence(
            context.compressed_actions, intelligent_analysis
        )
        context.intelligent_analysis = intelligent_analysis
        context.actions = context.compressed_actions

    def process(self, context: PreprocessingPipelineContext) -> PreprocessingPipelineContext:
        if not context.enable_analysis:
            return context

        use_compression_model = context.preprocessor._should_use_compression_level(
            context.compression_level
        )
        logger.info(
            f"步骤2: 智能网络请求过滤 (数据压缩模型: {'启用' if use_compression_model else '禁用'})..."
        )

        try:
            intelligent_analysis = (
                context.preprocessor.request_intelligence_analyzer.analyze_requests(
                    context.actions, use_llm=use_compression_model
                )
            )

            # 异步更新 DuckDB
            context.preprocessor._duckdb_update_queue.put(
                (context.recording_id, intelligent_analysis)
            )
            logger.info("  ✅ DuckDB更新任务已放入队列（异步）")

            context.compressed_actions = context.preprocessor._filter_requests_by_intelligence(
                context.compressed_actions, intelligent_analysis
            )
            context.intelligent_analysis = intelligent_analysis
            context.actions = context.compressed_actions

        except TokenLimitExceededError as e:
            self._fallback_to_rule_engine(
                context, "token_exceeded",
                "压缩模型 Token 超量，已回退到规则引擎", str(e),
            )

        except RateLimitError as e:
            self._fallback_to_rule_engine(
                context, "rate_limit",
                "压缩模型请求频率限制，已回退到规则引擎", str(e),
            )

        except CompressionModelError as e:
            self._fallback_to_rule_engine(
                context, e.error_type,
                "压缩模型错误，已回退到规则引擎", str(e),
            )

        return context


class RecommendationFilterStage(PipelineStage):
    """推荐内容过滤：过滤不应传给主 LLM 的请求"""

    def __init__(self):
        super().__init__("recommendation_filter")

    def process(self, context: PreprocessingPipelineContext) -> PreprocessingPipelineContext:
        if not context.enable_analysis:
            context.filter_result = {"stats": {}}
            return context

        logger.info("步骤3: 过滤推荐内容...")
        filter_result = context.preprocessor.filter_for_main_llm(context.intelligent_analysis)
        logger.info(f"  ✅ 过滤完成，传给主LLM {filter_result['stats']['kept']} 个请求")

        context.filter_result = filter_result
        return context


class ActionProcessingStage(PipelineStage):
    """操作处理：转换为 ProcessedAction"""

    def __init__(self):
        super().__init__("action_processing")

    def process(self, context: PreprocessingPipelineContext) -> PreprocessingPipelineContext:
        logger.info("步骤4: 处理操作...")
        processed_actions = []
        for idx, action in enumerate(context.actions):
            processed = context.preprocessor._process_action(action, idx)
            processed_actions.append(processed)

        context.processed_actions = processed_actions
        return context


class KeyActionsStage(PipelineStage):
    """提取关键操作"""

    def __init__(self):
        super().__init__("key_actions")

    def process(self, context: PreprocessingPipelineContext) -> PreprocessingPipelineContext:
        logger.info("步骤5: 提取关键操作...")
        key_actions = context.preprocessor._extract_key_actions(context.processed_actions)
        context.key_actions = key_actions
        return context


class ScreenshotOptimizationStage(PipelineStage):
    """截图优化：智能筛选截图"""

    def __init__(self):
        super().__init__("screenshot_optimization")

    def process(self, context: PreprocessingPipelineContext) -> PreprocessingPipelineContext:
        logger.info("步骤6: 优化截图...")
        screenshots = context.preprocessor._optimize_screenshots(
            context.actions, context.key_actions, context.compression_level
        )
        context.screenshots = screenshots
        return context


class MetadataStage(PipelineStage):
    """元数据生成：生成压缩和分析统计"""

    def __init__(self):
        super().__init__("metadata")

    def process(self, context: PreprocessingPipelineContext) -> PreprocessingPipelineContext:
        logger.info("步骤7: 生成元数据...")

        # 基础元数据
        metadata = context.preprocessor._generate_metadata(
            context.actions, context.processed_actions
        )

        # 压缩统计
        original_count = len(context.actions)
        metadata["compression_stats"] = {
            "original_count": original_count,
            "compressed_count": len(context.compressed_actions),
            "compression_ratio": f"{(1 - len(context.compressed_actions) / original_count) * 100:.1f}%",
            "screenshots_original": len(context.preprocessor._collect_screenshots(context.actions)),
            "screenshots_optimized": len(context.screenshots),
            "compression_level": context.compression_level.value,
        }

        # 分析统计
        if context.enable_analysis:
            total_count = sum(
                len(a.network_requests) if a.network_requests else 0 for a in context.actions
            )
            filtered_count = total_count - sum(
                len(a.network_requests) if a.network_requests else 0
                for a in context.compressed_actions
            )

            metadata["analysis_stats"] = {
                "compression_level": context.compression_level.value,
                "compression_model_enabled": context.preprocessor._should_use_compression_level(
                    context.compression_level
                ),
                "intelligent_filter": {
                    "total_requests": total_count,
                    "filtered_out": filtered_count,
                    "meaningful_kept": total_count - filtered_count,
                    "filter_ratio": (
                        f"{(filtered_count / total_count * 100):.1f}" if total_count > 0 else "0%"
                    ),
                },
                "recommendation_filter": context.filter_result.get("stats", {}),
            }

        context.metadata = metadata
        return context
