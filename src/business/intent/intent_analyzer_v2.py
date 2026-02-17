"""
意图分析器 V2

使用后端工程师 A 创建的标准 Intent 模型
与 intent_analyzer.py 功能兼容,但直接返回标准 Intent 对象
"""

import uuid
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.business.ai.llm_client import LangChainLLMClient
from src.business.ai.prompts.intent_analysis_prompt import (
    INTENT_ANALYSIS_PROMPT,
    INTENT_CONFIRMATION_PROMPT,
    format_recording_data,
    format_conversation_history,
)
from src.business.intent.intent_models import Intent, IntentStatus
from src.business.intent.intent_adapter import intent_analysis_to_standard

logger = logging.getLogger(__name__)


class IntentAnalyzer:
    """意图分析器（使用标准 Intent 模型）"""

    def __init__(self, llm_client: LangChainLLMClient):
        """
        初始化意图分析器

        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client

    async def analyze_intent(
        self, recording_session: Dict[str, Any]
    ) -> Intent:
        """
        分析录制数据，提取用户意图

        Args:
            recording_session: 录制会话数据

        Returns:
            Intent 对象（使用后端工程师 A 创建的标准模型）
        """
        try:
            recording_id = recording_session.get("recording_id", "")
            logger.info(f"开始分析意图，录制ID: {recording_id}")

            # 格式化录制数据
            formatted_data = format_recording_data(recording_session)

            # 构建提示词
            prompt = INTENT_ANALYSIS_PROMPT.format(**formatted_data)

            # 调用 LLM
            response = await self.llm_client.call_llm(
                prompt=prompt,
                response_format="json",
                max_tokens=2000,
                temperature=0.3,  # 较低温度以获得稳定结果
            )

            # 解析响应
            import json

            data = json.loads(response)

            # 提取核心操作（从对象列表转换为字符串列表）
            core_operations = []
            for op_data in data.get("core_operations", []):
                if isinstance(op_data, dict):
                    operation = op_data.get("operation", "")
                    if operation:
                        core_operations.append(operation)
                elif isinstance(op_data, str):
                    core_operations.append(op_data)

            # 创建标准 Intent 对象
            intent = Intent(
                intent_id=str(uuid.uuid4()),
                recording_id=recording_id,
                core_operations=core_operations,
                target=data.get("target", ""),
                business_scenario=data.get("business_scenario", ""),
                expected_results=data.get("expected_results", []),
                status=IntentStatus.PENDING_CONFIRMATION,
                analysis_confidence=data.get("confidence", 0.8),
                llm_model_used="claude-3.5-sonnet",  # TODO: 从配置读取
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            # 将推理过程存储在 user_message 中
            if data.get("reasoning"):
                intent.user_message = f"[分析推理]: {data['reasoning']}"

            # 将参数信息追加到 user_message
            suggested_params = data.get("suggested_parameters", [])
            if suggested_params:
                params_desc = "\n[建议参数]:\n"
                for param in suggested_params:
                    if isinstance(param, dict):
                        name = param.get("name", "")
                        desc = param.get("description", "")
                        param_type = param.get("type", "")
                        params_desc += f"- {name} ({param_type}): {desc}\n"
                intent.user_message = (intent.user_message or "") + params_desc

            logger.info(
                f"意图分析完成，置信度: {intent.analysis_confidence:.2f}, "
                f"业务场景: {intent.business_scenario}"
            )

            return intent

        except Exception as e:
            logger.error(f"意图分析失败: {e}", exc_info=True)
            # 返回默认 Intent 对象
            return Intent(
                intent_id=str(uuid.uuid4()),
                recording_id=recording_session.get("recording_id", ""),
                core_operations=[],
                target="未知",
                business_scenario="other - 分析失败",
                expected_results=[],
                status=IntentStatus.ANALYZING,
                analysis_confidence=0.0,
                created_at=datetime.now(),
            )

    async def refine_intent(
        self,
        original_intent: Intent,
        user_feedback: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> Intent:
        """
        根据用户反馈优化意图分析结果

        Args:
            original_intent: 原始 Intent 对象
            user_feedback: 用户反馈
            conversation_history: 对话历史（可选）

        Returns:
            优化后的 Intent 对象
        """
        try:
            logger.info(f"开始优化意图，用户反馈: {user_feedback[:50]}...")

            # 构建原始意图的字典表示
            original_intent_dict = {
                "core_operations": original_intent.core_operations,
                "target": original_intent.target,
                "business_scenario": original_intent.business_scenario,
                "expected_results": original_intent.expected_results,
                "confidence": original_intent.analysis_confidence,
            }

            # 格式化对话历史
            if conversation_history is None:
                conversation_history = []
            history_str = format_conversation_history(conversation_history)

            # 构建提示词
            prompt = INTENT_CONFIRMATION_PROMPT.format(
                original_intent=str(original_intent_dict).replace("'", '"'),
                user_feedback=user_feedback,
                conversation_history=history_str,
            )

            # 调用 LLM
            response = await self.llm_client.call_llm(
                prompt=prompt,
                response_format="json",
                max_tokens=2000,
                temperature=0.3,
            )

            # 解析响应
            import json

            data = json.loads(response)

            # 提取核心操作
            core_operations = []
            for op_data in data.get("core_operations", []):
                if isinstance(op_data, dict):
                    operation = op_data.get("operation", "")
                    if operation:
                        core_operations.append(operation)
                elif isinstance(op_data, str):
                    core_operations.append(op_data)

            # 创建优化后的 Intent 对象
            refined_intent = Intent(
                intent_id=original_intent.intent_id,  # 保持原有 ID
                recording_id=original_intent.recording_id,
                core_operations=core_operations,
                target=data.get("target", original_intent.target),
                business_scenario=data.get(
                    "business_scenario", original_intent.business_scenario
                ),
                expected_results=data.get(
                    "expected_results", original_intent.expected_results
                ),
                status=IntentStatus.PENDING_CONFIRMATION,
                analysis_confidence=data.get("confidence", original_intent.analysis_confidence),
                llm_model_used=original_intent.llm_model_used,
                created_at=original_intent.created_at,  # 保持原有创建时间
                updated_at=datetime.now(),
            )

            logger.info(
                f"意图优化完成，新置信度: {refined_intent.analysis_confidence:.2f}"
            )

            return refined_intent

        except Exception as e:
            logger.error(f"意图优化失败: {e}", exc_info=True)
            # 返回原始意图
            logger.warning("优化失败，返回原始意图")
            return original_intent

    async def create_intent_from_recording(
        self, recording_session: Dict[str, Any]
    ) -> Intent:
        """
        从录制会话创建意图对象

        Args:
            recording_session: 录制会话数据

        Returns:
            Intent 对象（使用后端工程师 A 创建的标准模型）
        """
        # 分析意图（直接返回 Intent 对象）
        intent = await self.analyze_intent(recording_session)
        return intent

    def validate_intent(self, intent: Intent) -> Dict[str, Any]:
        """
        验证意图分析结果的质量

        Args:
            intent: Intent 对象（使用标准模型）

        Returns:
            验证结果字典，包含:
            - is_valid: 是否有效
            - issues: 问题列表
            - suggestions: 建议列表
        """
        issues = []
        suggestions = []

        # 检查置信度
        if intent.analysis_confidence < 0.7:
            issues.append(f"置信度较低 ({intent.analysis_confidence:.2f})")
            suggestions.append("建议与用户确认意图是否准确")

        # 检查核心操作数量
        if len(intent.core_operations) == 0:
            issues.append("未提取到核心操作")
            suggestions.append("检查录制数据是否完整")
        elif len(intent.core_operations) < 2:
            issues.append("核心操作数量过少")
            suggestions.append("确认是否遗漏了关键步骤")

        # 检查目标
        if not intent.target or intent.target == "未知":
            issues.append("未能识别操作目标")
            suggestions.append("明确用户操作的网站或应用")

        # 检查业务场景
        if not intent.business_scenario:
            issues.append("未识别业务场景")

        # 检查预期结果
        if len(intent.expected_results) == 0:
            issues.append("未提取预期结果")
            suggestions.append("补充用户期望达成的目标")

        # 验证通过条件
        is_valid = (
            len(issues) == 0
            and intent.analysis_confidence >= 0.7
            and len(intent.core_operations) >= 2
        )

        return {
            "is_valid": is_valid,
            "issues": issues,
            "suggestions": suggestions,
            "confidence": intent.analysis_confidence,
            "operation_count": len(intent.core_operations),
        }
