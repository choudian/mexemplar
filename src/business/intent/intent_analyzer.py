"""
意图分析器

负责从录制数据中提取用户意图信息
"""

import uuid
import time
import logging
from typing import Dict, List, Any, Optional
from src.business.ai.llm_client import LangChainLLMClient
from src.business.ai.prompts.intent_analysis_prompt import (
    INTENT_ANALYSIS_PROMPT,
    INTENT_CONFIRMATION_PROMPT,
    format_recording_data,
    format_conversation_history,
)
from src.business.ai.prompts.intent_analysis_models import (
    IntentAnalysisResult,
    IntentConfirmationTurn,
    Intent,
    CoreOperation,
    SuggestedParameter,
)

logger = logging.getLogger(__name__)


class IntentAnalyzer:
    """意图分析器"""

    def __init__(self, llm_client: LangChainLLMClient):
        """
        初始化意图分析器

        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client

    async def analyze_intent(self, recording_session: Dict[str, Any]) -> IntentAnalysisResult:
        """
        分析录制数据，提取用户意图

        Args:
            recording_session: 录制会话数据

        Returns:
            意图分析结果
        """
        try:
            logger.info(f"开始分析意图，录制ID: {recording_session.get('recording_id')}")

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
            result = self._parse_intent_response(
                response, recording_session.get("recording_id", "")
            )

            logger.info(
                f"意图分析完成，置信度: {result.confidence:.2f}, "
                f"业务场景: {result.business_scenario}"
            )

            return result

        except Exception as e:
            logger.error(f"意图分析失败: {e}", exc_info=True)
            # 返回默认结果
            return IntentAnalysisResult(
                core_operations=[],
                target="未知",
                business_scenario="other - 分析失败",
                expected_results=[],
                suggested_parameters=[],
                confidence=0.0,
                reasoning=f"分析过程出错: {str(e)}",
                recording_id=recording_session.get("recording_id", ""),
                status="failed",
            )

    def _parse_intent_response(self, response: str, recording_id: str) -> IntentAnalysisResult:
        """
        解析 LLM 响应

        Args:
            response: LLM 返回的 JSON 字符串
            recording_id: 录制ID

        Returns:
            意图分析结果
        """
        import json

        try:
            # 解析 JSON
            data = json.loads(response)

            # 解析 core_operations
            core_operations = []
            for op_data in data.get("core_operations", []):
                op = CoreOperation.from_dict(op_data)
                core_operations.append(op)

            # 解析 suggested_parameters
            suggested_parameters = []
            for param_data in data.get("suggested_parameters", []):
                param = SuggestedParameter.from_dict(param_data)
                suggested_parameters.append(param)

            # 构建结果
            result = IntentAnalysisResult(
                core_operations=core_operations,
                target=data.get("target", ""),
                business_scenario=data.get("business_scenario", ""),
                expected_results=data.get("expected_results", []),
                suggested_parameters=suggested_parameters,
                confidence=data.get("confidence", 0.8),
                reasoning=data.get("reasoning", ""),
                recording_id=recording_id,
                status="pending_confirmation",
            )

            return result

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
            raise ValueError(f"LLM 返回的不是有效的 JSON: {response}") from e
        except Exception as e:
            logger.error(f"解析响应失败: {e}", exc_info=True)
            raise

    async def refine_intent(
        self,
        original_intent: IntentAnalysisResult,
        user_feedback: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> IntentAnalysisResult:
        """
        根据用户反馈优化意图分析结果

        Args:
            original_intent: 原始意图分析结果
            user_feedback: 用户反馈
            conversation_history: 对话历史（可选）

        Returns:
            优化后的意图分析结果
        """
        try:
            logger.info(f"开始优化意图，用户反馈: {user_feedback[:50]}...")

            # 格式化原始意图
            original_intent_json = original_intent.to_json()

            # 格式化对话历史
            if conversation_history is None:
                conversation_history = []
            history_str = format_conversation_history(conversation_history)

            # 构建提示词
            prompt = INTENT_CONFIRMATION_PROMPT.format(
                original_intent=original_intent_json,
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
            refined_result = self._parse_intent_response(response, original_intent.recording_id)

            logger.info(
                f"意图优化完成，新置信度: {refined_result.confidence:.2f}, "
                f"推理: {refined_result.reasoning[:100]}..."
            )

            return refined_result

        except Exception as e:
            logger.error(f"意图优化失败: {e}", exc_info=True)
            # 返回原始意图
            logger.warning("优化失败，返回原始意图")
            return original_intent

    async def add_confirmation_turn(
        self,
        intent: Intent,
        user_feedback: str,
        assistant_response: str,
        updated_intent: IntentAnalysisResult,
    ) -> IntentConfirmationTurn:
        """
        添加确认对话轮次

        Args:
            intent: 意图对象
            user_feedback: 用户反馈
            assistant_response: 助手回复
            updated_intent: 更新后的意图

        Returns:
            对话轮次对象
        """
        # 创建对话轮次
        turn = IntentConfirmationTurn(
            turn_id=str(uuid.uuid4()),
            intent_id=intent.intent_id,
            user_feedback=user_feedback,
            assistant_response=assistant_response,
            updated_intent=updated_intent,
            timestamp=time.time(),
        )

        # 添加到意图
        intent.add_confirmation_turn(turn)

        # 更新意图的分析结果
        intent.analysis_result = updated_intent

        return turn
