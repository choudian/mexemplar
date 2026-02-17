"""
Intent 模型适配器

桥接自定义的 IntentAnalysisResult 和标准的 Intent 模型
"""

from typing import Dict, List, Any
from datetime import datetime

from src.business.intent.intent_models import Intent, IntentStatus
from src.business.ai.prompts.intent_analysis_models import (
    IntentAnalysisResult,
    CoreOperation,
)


def intent_analysis_to_standard(
    analysis_result: IntentAnalysisResult, recording_id: str
) -> Intent:
    """
    将 IntentAnalysisResult 转换为标准的 Intent 模型

    Args:
        analysis_result: 意图分析结果
        recording_id: 录制ID

    Returns:
        标准的 Intent 对象
    """
    # 从 CoreOperation 对象列表提取操作描述
    core_operations_str = []
    for op in analysis_result.core_operations:
        if isinstance(op, CoreOperation):
            core_operations_str.append(op.operation)
        elif isinstance(op, str):
            core_operations_str.append(op)
        elif isinstance(op, dict):
            core_operations_str.append(op.get("operation", ""))

    # 创建标准 Intent 对象
    intent = Intent(
        intent_id=analysis_result.recording_id or str(datetime.now().timestamp()),
        recording_id=recording_id,
        core_operations=core_operations_str,
        target=analysis_result.target,
        business_scenario=analysis_result.business_scenario,
        expected_results=analysis_result.expected_results,
        status=IntentStatus.PENDING_CONFIRMATION,
        analysis_confidence=analysis_result.confidence,
        llm_model_used="claude-3.5-sonnet",  # TODO: 从配置读取
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )

    # 将推理过程存储在 user_message 中
    if analysis_result.reasoning:
        intent.user_message = f"[分析推理]: {analysis_result.reasoning}"

    # 将参数信息追加到 user_message
    if analysis_result.suggested_parameters:
        params_desc = "\n[建议参数]:\n"
        for param in analysis_result.suggested_parameters:
            if hasattr(param, "name"):
                params_desc += f"- {param.name}: {param.description}\n"
            elif isinstance(param, dict):
                params_desc += f"- {param.get('name')}: {param.get('description')}\n"
        intent.user_message = (intent.user_message or "") + params_desc

    return intent


def create_standard_intent_from_analysis(
    analysis_result: IntentAnalysisResult, recording_id: str
) -> Intent:
    """
    从分析结果创建标准 Intent 对象的便捷函数

    这是 intent_analysis_to_standard 的别名，提供更直观的命名

    Args:
        analysis_result: 意图分析结果
        recording_id: 录制ID

    Returns:
        标准的 Intent 对象
    """
    return intent_analysis_to_standard(analysis_result, recording_id)
