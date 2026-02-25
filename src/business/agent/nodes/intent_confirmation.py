"""
意图确认节点

等待用户确认意图（使用 interrupt）。
支持确认问题和选项展示。
"""

from typing import Dict, Any
from langgraph.types import interrupt
from langchain_core.messages import AIMessage

from ..state import AgentState
from src.utils.logger import get_logger

logger = get_logger(__name__)


def intent_confirmation_node(state: AgentState) -> Dict[str, Any]:
    """
    意图确认节点

    展示完整的意图分析结果和确认问题，等待用户确认。
    使用内部循环处理多轮反馈对话，避免图级别的无限循环。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取当前意图
    current_intent = state.get("current_intent")
    if not current_intent:
        return {
            "error_info": {
                "code": "NO_INTENT",
                "message": "No intent to confirm"
            }
        }

    # 获取完整分析结果
    full_analysis = current_intent.full_analysis

    # 构建初始 interrupt 数据
    interrupt_data = _build_interrupt_data(current_intent, full_analysis)

    # ========== 关键修复：使用内部循环处理多轮对话 ==========
    # 不再依赖图的条件边循环，而是在节点内部循环处理
    # 这样可以正确使用 interrupt() 等待每次用户输入

    while True:
        # 暂停，等待用户确认或反馈
        user_response = interrupt(interrupt_data)

        if user_response.get("action") == "confirm":
            # 用户确认，保存用户的回答并退出循环
            user_confirmations = user_response.get("confirmations", {})
            if current_intent and user_confirmations:
                current_intent.user_confirmations = user_confirmations

            return {
                "current_intent": current_intent,
                "messages": [AIMessage(content="用户已确认意图")]
            }
        else:
            # 用户发送了反馈
            feedback = user_response.get("feedback", "")

            if not feedback:
                # 没有反馈内容，更新提示并继续循环
                interrupt_data["message"] = "请提供您的反馈或点击确认按钮继续。\n\n" + _build_confirmation_message(current_intent, full_analysis)
                continue

            # 调用 LLM 处理用户反馈
            ai_response = _process_user_feedback(current_intent, full_analysis, feedback)

            # 更新 interrupt 消息，包含 AI 回复
            interrupt_data["message"] = f"{ai_response}\n\n---\n\n{_build_confirmation_message(current_intent, full_analysis)}"

            # 继续循环，等待用户下一轮输入


def _build_interrupt_data(current_intent, full_analysis) -> Dict[str, Any]:
    """
    构建 interrupt 数据结构

    Args:
        current_intent: 当前意图数据
        full_analysis: 完整分析结果

    Returns:
        interrupt 数据字典
    """
    confirmation_message = _build_confirmation_message(current_intent, full_analysis)

    interrupt_data = {
        "type": "intent_confirmation",
        "intent": {
            "intent_type": current_intent.intent_type,
            "description": current_intent.description,
            "parameters": current_intent.parameters,
            "confidence": current_intent.confidence,
        },
        "message": confirmation_message,
    }

    # 添加完整分析结果（如果有）
    if full_analysis:
        # 模式识别
        interrupt_data["pattern_recognition"] = {
            "primary_pattern": full_analysis.pattern_recognition.primary_pattern,
            "confidence": full_analysis.pattern_recognition.confidence,
            "description": full_analysis.pattern_recognition.description,
        }

        # 意图分析
        interrupt_data["intent_analysis"] = {
            "surface_operations": full_analysis.surface_operations,
            "deep_intent": full_analysis.deep_intent,
            "final_goal": full_analysis.final_goal,
            "user_needs": full_analysis.user_needs,
        }

        # 参数化分析
        interrupt_data["parameterization_analysis"] = [
            {
                "element": item.element,
                "recorded_value": item.recorded_value,
                "should_parameterize": item.should_parameterize,
                "reason": item.reason,
                "confidence": item.confidence,
                "parameter_name": item.parameter_name,
            }
            for item in full_analysis.parameterization_analysis
        ]

        # 确认问题
        interrupt_data["confirmation_questions"] = [
            {
                "id": q.id,
                "question": q.question,
                "context": q.context,
                "options": q.options,
                "recommended": q.recommended,
                "priority": q.priority,
            }
            for q in full_analysis.confirmation_questions
        ]

        # 工具描述
        interrupt_data["tool_description"] = {
            "name": full_analysis.tool_description.name,
            "description": full_analysis.tool_description.description,
            "category": full_analysis.tool_description.category,
            "natural_language_description": full_analysis.tool_description.natural_language_description,
            "input_parameters": full_analysis.tool_description.input_parameters,
        }

    return interrupt_data


def _process_user_feedback(current_intent, full_analysis, feedback: str) -> str:
    """
    处理用户反馈，调用 LLM 生成回复

    Args:
        current_intent: 当前意图数据
        full_analysis: 完整分析结果
        feedback: 用户反馈内容

    Returns:
        AI 生成的回复
    """
    from src.business.ai.llm_client import create_llm_client
    from src.data.unified_config import get_unified_config

    config = get_unified_config()

    # 构建 LLM 客户端配置
    client_config = {
        "provider": config.get_ai_provider(),
        "model": config.get_ai_model(),
        "api_key": config.get_ai_api_key(),
        "temperature": config.get_ai_temperature(),
        "max_tokens": 1024,  # 短回复即可
    }

    base_url = config.get_ai_base_url()
    if base_url:
        client_config["base_url"] = base_url

    llm = create_llm_client(client_config)

    # 构建处理用户反馈的提示词
    feedback_prompt = f"""用户对意图分析结果提供了以下反馈：

**用户反馈**：{feedback}

**当前意图分析**：
- 描述：{current_intent.description}
- 模式：{full_analysis.pattern_recognition.primary_pattern if full_analysis else '未知'}
- 深层意图：{full_analysis.deep_intent if full_analysis else '未知'}

请根据用户反馈，选择以下处理方式：

1. 如果用户只是询问问题或要求澄清，直接回复用户，然后再次请求确认
2. 如果用户要求修改意图分析，说明你理解了用户的需求，并告诉用户你会如何调整

回复要求：
- 简洁友好
- 如果需要调整意图分析，明确说明调整内容
- 最后引导用户确认或继续反馈

请直接输出回复内容（不要加引号或其他格式）："""

    try:
        # 调用 LLM 生成回复
        response_text = llm.chat(prompt=feedback_prompt, max_tokens=1024)
        return response_text

    except Exception as e:
        logger.error(f"处理用户反馈失败: {e}", exc_info=True)
        return f"抱歉，处理您的反馈时出错：{str(e)}。请重试或直接确认意图。"


def _build_confirmation_message(current_intent, full_analysis) -> str:
    """构建确认消息"""
    parts = []

    # 基本信息
    parts.append(f"我已分析完成您的操作！")

    if full_analysis:
        # 模式识别
        pattern = full_analysis.pattern_recognition
        if pattern.primary_pattern:
            parts.append(f"\n**操作模式**：{pattern.primary_pattern}（置信度：{pattern.confidence:.0%}）")

        # 深层意图
        if full_analysis.deep_intent:
            parts.append(f"\n**深层意图**：{full_analysis.deep_intent}")

        # 工具描述
        tool_desc = full_analysis.tool_description
        if tool_desc.natural_language_description:
            parts.append(f"\n\n{tool_desc.natural_language_description}")

        # 确认问题提示
        questions = full_analysis.confirmation_questions
        if questions:
            parts.append(f"\n\n**需要您确认 {len(questions)} 个问题**，请查看左侧的确认选项。")
        else:
            parts.append("\n\n请确认以上分析是否正确，然后点击「确认并继续」按钮。")
    else:
        # 降级到简单消息
        parts.append(f"\n\n**描述**：{current_intent.description}")
        parts.append("\n\n请确认以上分析是否正确。")

    return "".join(parts)