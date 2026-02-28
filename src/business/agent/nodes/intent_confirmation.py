"""
意图确认节点

等待用户确认意图（使用 interrupt）。

核心逻辑：
- 有问题时：显示问题 → 用户回答 → 点击"提交问题" → 重新分析（可能产生新问题）
- 无问题时：显示分析结果 → 点击"最终意图确认" → 生成工具

流程是循环的，不是线性的。"最终意图确认"是"没有确认问题"时的自然状态。
"""

import re
import json
from typing import Dict, Any, List, Optional
from langgraph.types import interrupt
from langchain_core.messages import AIMessage

from ..state import AgentState, IntentData, IntentAnalysisResult, PatternRecognition, ParameterizationItem, ConfirmationQuestion, ToolDescription
from src.utils.logger import get_logger

logger = get_logger(__name__)


def intent_confirmation_node(state: AgentState) -> Dict[str, Any]:
    """
    意图确认节点

    核心逻辑：
    - 根据是否有确认问题决定按钮文字
    - "提交问题"：将答案合并到意图数据，重新调用意图分析，可能产生新问题
    - "最终意图确认"：只在无问题时可用，直接生成工具
    - 用户可随时发送反馈，打断当前流程

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

    # 获取确认问题列表
    questions = _get_confirmation_questions(full_analysis)

    # 构建初始 interrupt 数据
    interrupt_data = _build_interrupt_data(
        current_intent,
        full_analysis,
        questions
    )

    # 使用循环处理多轮交互
    while True:
        # 暂停，等待用户响应
        user_response = interrupt(interrupt_data)

        # 处理用户响应
        action = user_response.get("action")

        if action == "submit":
            # ========== 提交问题：重新分析意图 ==========
            answers = user_response.get("answers", {})

            if current_intent:
                current_intent.user_confirmations = answers

            logger.info(f"用户提交问题答案，数量: {len(answers)}")

            # 调用 LLM 重新分析（将用户答案作为上下文）
            ai_response, new_intent_data = _reanalyze_with_answers(
                state, current_intent, full_analysis, answers
            )

            if new_intent_data:
                current_intent = new_intent_data
                full_analysis = new_intent_data.full_analysis
                questions = _get_confirmation_questions(full_analysis)
                logger.info(f"重新分析完成，新问题数量: {len(questions)}")
            else:
                # 分析失败，保持当前状态
                logger.warning("重新分析失败，保持当前分析结果")
                ai_response = "抱歉，重新分析时出错。请重试或直接确认意图。"

            # 构建下一次 interrupt 数据（可能有问题也可能没有）
            interrupt_data = _build_interrupt_data(
                current_intent,
                full_analysis,
                questions,
                ai_response=ai_response
            )
            # 继续循环，等待用户下一步操作
            continue

        elif action == "confirm":
            # ========== 最终确认：只在无问题时到达这里 ==========
            logger.info("用户最终确认意图")
            return {
                "current_intent": current_intent,
                "messages": [AIMessage(content="用户已确认意图")]
            }

        elif action == "feedback":
            # ========== 用户反馈：重新分析 ==========
            feedback = user_response.get("feedback", "")

            if not feedback:
                logger.warning("收到空反馈，继续等待用户响应")
                continue

            # 重新分析意图，包含用户反馈作为上下文
            ai_response, new_intent_data = _process_user_feedback(
                state, current_intent, full_analysis, feedback
            )

            # 更新意图数据
            if new_intent_data:
                current_intent = new_intent_data
                full_analysis = new_intent_data.full_analysis
                questions = _get_confirmation_questions(full_analysis)
            else:
                # 分析失败，保持当前状态，让用户可以重试或确认
                logger.warning("反馈处理失败，保持当前分析结果")

            # 构建下一次 interrupt 数据（包含 AI 回复）
            interrupt_data = _build_interrupt_data(
                current_intent,
                full_analysis,
                questions,
                ai_response=ai_response
            )

            # 继续循环，等待用户下一步操作
            logger.info("等待用户对更新后分析结果的响应")
            continue

        else:
            # 未知操作，记录警告并继续等待
            logger.warning(f"未知的用户操作: {action}，继续等待")
            continue


def _build_interrupt_data(
    current_intent,
    full_analysis,
    questions: List[Dict[str, Any]],
    ai_response: Optional[str] = None
) -> Dict[str, Any]:
    """
    构建 interrupt 数据结构

    不再有阶段概念，根据 questions 是否为空决定前端显示什么按钮。

    Args:
        current_intent: 当前意图数据
        full_analysis: 完整分析结果
        questions: 所有确认问题列表
        ai_response: AI 回复（如果有）

    Returns:
        interrupt 数据字典
    """
    interrupt_data = {
        "type": "intent_confirmation",
        "intent": {
            "intent_type": current_intent.intent_type,
            "description": current_intent.description,
            "parameters": current_intent.parameters,
            "confidence": current_intent.confidence,
        },
        "confirmation_questions": questions,
        "message": _build_confirmation_message(current_intent, full_analysis),
    }

    # 添加完整分析结果
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

        # 工具描述
        interrupt_data["tool_description"] = {
            "name": full_analysis.tool_description.name,
            "description": full_analysis.tool_description.description,
            "category": full_analysis.tool_description.category,
            "natural_language_description": full_analysis.tool_description.natural_language_description,
            "input_parameters": full_analysis.tool_description.input_parameters,
        }

    # 如果有 AI 回复，添加到数据中
    if ai_response:
        interrupt_data["ai_response"] = ai_response

    return interrupt_data


def _get_confirmation_questions(full_analysis) -> List[Dict[str, Any]]:
    """
    从完整分析结果中提取确认问题列表

    Args:
        full_analysis: 完整分析结果

    Returns:
        问题列表
    """
    if not full_analysis or not hasattr(full_analysis, 'confirmation_questions'):
        return []

    questions = []
    for q in full_analysis.confirmation_questions:
        questions.append({
            "id": q.id,
            "question": q.question,
            "context": q.context,
            "options": q.options,
            "recommended": q.recommended,
            "priority": q.priority,
        })

    return questions


def _reanalyze_with_answers(
    state,
    current_intent,
    full_analysis,
    answers: Dict[str, str]
) -> tuple:
    """
    根据用户答案重新分析意图

    将用户答案作为上下文，重新调用意图分析 LLM，
    LLM 根据答案调整分析结果，可能产生新的确认问题。

    Args:
        state: 当前状态（包含录制数据）
        current_intent: 当前意图数据
        full_analysis: 完整分析结果
        answers: 用户对确认问题的回答

    Returns:
        (ai_response, updated_intent_data) - AI 回复和更新后的意图数据
    """
    from src.business.ai.llm_client import create_llm_client
    from src.data.unified_config import get_unified_config
    from ..prompts.intent_analysis import get_intent_analysis_prompt

    config = get_unified_config()

    # 构建 LLM 客户端配置
    client_config = {
        "provider": config.get_ai_provider(),
        "model": config.get_ai_model(),
        "api_key": config.get_ai_api_key(),
        "temperature": config.get_ai_temperature(),
        "max_tokens": 4096,
    }

    base_url = config.get_ai_base_url()
    if base_url:
        client_config["base_url"] = base_url

    llm = create_llm_client(client_config)

    # 获取录制数据
    recording_data = state.get("recording_data", {})
    actions = recording_data.get("actions", [])
    metadata = recording_data.get("metadata", {})

    # 构建用户答案上下文
    answers_context = []
    if answers and full_analysis:
        for q in full_analysis.confirmation_questions:
            q_id = q.id
            if q_id in answers:
                # 查找答案标签
                answer_value = answers[q_id]
                answer_label = answer_value
                for opt in q.options:
                    if opt.get("value") == answer_value:
                        answer_label = opt.get("label", answer_value)
                        break
                answers_context.append(f"- 问题: {q.question}\n  回答: {answer_label}")

    # 构建之前的分析结果（包含用户答案）
    previous_analysis = {}
    if full_analysis:
        previous_analysis = {
            "pattern_recognition": {
                "primary_pattern": full_analysis.pattern_recognition.primary_pattern,
                "confidence": full_analysis.pattern_recognition.confidence,
                "description": full_analysis.pattern_recognition.description,
            },
            "intent_analysis": {
                "deep_intent": full_analysis.deep_intent,
                "final_goal": full_analysis.final_goal,
                "user_needs": full_analysis.user_needs,
            },
            "tool_description": {
                "name": full_analysis.tool_description.name,
                "description": full_analysis.tool_description.description,
                "natural_language_description": full_analysis.tool_description.natural_language_description,
            },
        }

    # 添加用户答案到上下文
    if answers_context:
        user_feedback = f"用户对确认问题的回答：\n" + "\n".join(answers_context)
    else:
        user_feedback = None

    try:
        # 生成包含用户答案的提示词
        prompt = get_intent_analysis_prompt(
            actions=actions,
            metadata=metadata,
            user_feedback=user_feedback,
            previous_analysis=previous_analysis
        )

        # 调用 LLM 重新分析意图
        response_text = llm.chat(prompt=prompt, max_tokens=4096)
        logger.info(f"根据用户答案重新分析，响应长度: {len(response_text)}")

        # 解析响应
        intent_result = _parse_intent_response(response_text)

        # 构建新的完整分析结果
        new_full_analysis = _build_full_analysis(intent_result)

        # 创建新的 IntentData
        new_intent_data = IntentData(
            intent_type=_determine_intent_type(intent_result),
            description=intent_result.get("intent_analysis", {}).get("deep_intent", "未知任务"),
            parameters=_extract_parameters(intent_result),
            confidence=intent_result.get("pattern_recognition", {}).get("confidence", 0.8),
            raw_analysis=intent_result,
            full_analysis=new_full_analysis,
            user_confirmations=answers  # 保留用户答案
        )

        logger.info(f"重新分析完成: {new_intent_data.description}")
        logger.info(f"新确认问题数量: {len(new_full_analysis.confirmation_questions)}")

        # 生成 AI 回复
        if len(new_full_analysis.confirmation_questions) > 0:
            ai_response = f"感谢您的回答！我已根据您的选择重新分析，还有 {len(new_full_analysis.confirmation_questions)} 个问题需要确认。"
        else:
            ai_response = f"感谢您的回答！我已根据您的选择调整了分析结果，现在可以确认生成工具了。"

        return ai_response, new_intent_data

    except Exception as e:
        logger.error(f"根据用户答案重新分析失败: {e}", exc_info=True)
        return f"抱歉，重新分析时出错：{str(e)}。请重试或直接确认意图。", None


def _process_user_feedback(state, current_intent, full_analysis, feedback: str) -> tuple:
    """
    处理用户反馈，重新调用意图分析

    Args:
        state: 当前状态（包含录制数据）
        current_intent: 当前意图数据
        full_analysis: 完整分析结果
        feedback: 用户反馈内容

    Returns:
        (ai_response, updated_intent_data) - AI 回复和更新后的意图数据
    """
    from src.business.ai.llm_client import create_llm_client
    from src.data.unified_config import get_unified_config
    from ..prompts.intent_analysis import get_intent_analysis_prompt
    from ..state import IntentData, IntentAnalysisResult, PatternRecognition, ParameterizationItem, ConfirmationQuestion, ToolDescription
    import json
    import re

    config = get_unified_config()

    # 构建 LLM 客户端配置
    client_config = {
        "provider": config.get_ai_provider(),
        "model": config.get_ai_model(),
        "api_key": config.get_ai_api_key(),
        "temperature": config.get_ai_temperature(),
        "max_tokens": 4096,
    }

    base_url = config.get_ai_base_url()
    if base_url:
        client_config["base_url"] = base_url

    llm = create_llm_client(client_config)

    # 获取录制数据
    recording_data = state.get("recording_data", {})
    actions = recording_data.get("actions", [])
    metadata = recording_data.get("metadata", {})

    # 构建之前的分析结果（用于提示词）
    previous_analysis = {}
    if full_analysis:
        previous_analysis = {
            "pattern_recognition": {
                "primary_pattern": full_analysis.pattern_recognition.primary_pattern,
                "confidence": full_analysis.pattern_recognition.confidence,
                "description": full_analysis.pattern_recognition.description,
            },
            "intent_analysis": {
                "deep_intent": full_analysis.deep_intent,
                "final_goal": full_analysis.final_goal,
                "user_needs": full_analysis.user_needs,
            },
            "tool_description": {
                "name": full_analysis.tool_description.name,
                "description": full_analysis.tool_description.description,
                "natural_language_description": full_analysis.tool_description.natural_language_description,
            },
        }

    # 生成包含用户反馈的提示词
    prompt = get_intent_analysis_prompt(
        actions=actions,
        metadata=metadata,
        user_feedback=feedback,
        previous_analysis=previous_analysis
    )

    try:
        # 调用 LLM 重新分析意图
        response_text = llm.chat(prompt=prompt, max_tokens=4096)
        logger.info(f"用户反馈后重新分析，响应长度: {len(response_text)}")

        # 解析响应
        intent_result = _parse_intent_response(response_text)

        # 构建新的完整分析结果
        new_full_analysis = _build_full_analysis(intent_result)

        # 创建新的 IntentData
        new_intent_data = IntentData(
            intent_type=_determine_intent_type(intent_result),
            description=intent_result.get("intent_analysis", {}).get("deep_intent", "未知任务"),
            parameters=_extract_parameters(intent_result),
            confidence=intent_result.get("pattern_recognition", {}).get("confidence", 0.8),
            raw_analysis=intent_result,
            full_analysis=new_full_analysis
        )

        logger.info(f"重新分析完成: {new_intent_data.description}")
        logger.info(f"新确认问题数量: {len(new_full_analysis.confirmation_questions)}")

        # 生成 AI 回复
        ai_response = f"好的，我已根据您的反馈重新分析。{new_full_analysis.tool_description.natural_language_description}"

        return ai_response, new_intent_data

    except Exception as e:
        logger.error(f"处理用户反馈失败: {e}", exc_info=True)
        return f"抱歉，处理您的反馈时出错：{str(e)}。请重试或直接确认意图。", None


def _parse_intent_response(response_text: str) -> Dict[str, Any]:
    """解析 LLM 响应"""
    # 查找 JSON 代码块
    json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败（代码块）: {e}")

    # 尝试直接解析
    try:
        return json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败（直接）: {e}")

    # 返回默认值
    return {
        "pattern_recognition": {
            "primary_pattern": "未知模式",
            "confidence": 0.0,
            "description": "无法识别操作模式"
        },
        "intent_analysis": {
            "surface_operations": [],
            "deep_intent": "无法识别任务意图",
            "final_goal": "未知",
            "user_needs": "未知"
        },
        "parameterization_analysis": [],
        "confirmation_questions": [],
        "tool_description": {
            "name": "未知工具",
            "description": "无法生成工具描述",
            "category": "其他"
        },
        "code_generation_hints": {
            "libraries_needed": [],
            "complexity": "simple",
            "error_handling_needed": [],
            "special_considerations": []
        }
    }


def _build_full_analysis(result: Dict[str, Any]) -> IntentAnalysisResult:
    """构建完整的分析结果对象"""
    # 模式识别
    pattern_data = result.get("pattern_recognition", {})
    pattern_recognition = PatternRecognition(
        primary_pattern=pattern_data.get("primary_pattern", "未知"),
        confidence=pattern_data.get("confidence", 0.0),
        description=pattern_data.get("description", ""),
        sub_patterns=pattern_data.get("sub_patterns", [])
    )

    # 参数化分析
    param_items = []
    for item in result.get("parameterization_analysis", []):
        param_items.append(ParameterizationItem(
            element=item.get("element", ""),
            element_selector=item.get("element_selector", ""),
            recorded_value=item.get("recorded_value", ""),
            should_parameterize=item.get("should_parameterize", "uncertain"),
            reason=item.get("reason", ""),
            confidence=item.get("confidence", 0.0),
            parameter_name=item.get("parameter_name", ""),
            parameter_type=item.get("parameter_type", "string"),
            default_value=item.get("default_value", ""),
            need_confirmation=item.get("need_confirmation", False)
        ))

    # 确认问题
    questions = []
    for q in result.get("confirmation_questions", []):
        questions.append(ConfirmationQuestion(
            id=q.get("id", ""),
            question=q.get("question", ""),
            context=q.get("context", ""),
            options=q.get("options", []),
            recommended=q.get("recommended", ""),
            priority=q.get("priority", "medium")
        ))

    # 工具描述
    tool_data = result.get("tool_description", {})
    tool_description = ToolDescription(
        name=tool_data.get("name", ""),
        description=tool_data.get("description", ""),
        category=tool_data.get("category", "其他"),
        input_parameters=tool_data.get("input_parameters", []),
        natural_language_description=tool_data.get("natural_language_description", ""),
        use_cases=tool_data.get("use_cases", [])
    )

    # 代码生成提示
    code_hints = result.get("code_generation_hints", {})

    # 意图分析
    intent_data = result.get("intent_analysis", {})

    return IntentAnalysisResult(
        pattern_recognition=pattern_recognition,
        surface_operations=intent_data.get("surface_operations", []),
        deep_intent=intent_data.get("deep_intent", ""),
        final_goal=intent_data.get("final_goal", ""),
        user_needs=intent_data.get("user_needs", ""),
        parameterization_analysis=param_items,
        confirmation_questions=questions,
        tool_description=tool_description,
        libraries_needed=code_hints.get("libraries_needed", []),
        complexity=code_hints.get("complexity", "simple"),
        error_handling_needed=code_hints.get("error_handling_needed", []),
        special_considerations=code_hints.get("special_considerations", [])
    )


def _extract_parameters(result: Dict[str, Any]) -> Dict[str, Any]:
    """从分析结果中提取参数"""
    parameters = {}

    for item in result.get("parameterization_analysis", []):
        if item.get("should_parameterize") == True:
            param_name = item.get("parameter_name", "")
            if param_name:
                parameters[param_name] = {
                    "type": item.get("parameter_type", "string"),
                    "default": item.get("default_value", ""),
                    "description": item.get("element", ""),
                    "recorded_value": item.get("recorded_value", "")
                }

    return parameters


def _determine_intent_type(result: Dict[str, Any]) -> str:
    """
    根据分析结果确定意图类型

    Returns:
        'browser_automation' | 'api_call' | 'hybrid'
    """
    pattern = result.get("pattern_recognition", {}).get("primary_pattern", "").lower()
    category = result.get("tool_description", {}).get("category", "").lower()

    if "api" in pattern or "api" in category:
        return "api_call"
    elif "浏览器" in pattern or "网页" in pattern or "搜索" in pattern:
        return "browser_automation"
    else:
        return "hybrid"


def _build_confirmation_message(
    current_intent,
    full_analysis,
) -> str:
    """构建确认消息"""
    parts = []

    # 根据是否有确认问题，调整消息
    questions_count = 0
    if full_analysis:
        questions_count = len(full_analysis.confirmation_questions)

    if questions_count > 0:
        parts.append("我已分析完成您的操作！请确认以下分析结果并回答问题。")
    else:
        parts.append("我已分析完成您的操作！请确认以下分析结果。")

    if full_analysis:
        # 模式识别
        pattern = full_analysis.pattern_recognition
        if pattern.primary_pattern:
            parts.append(f"\n\n**操作模式**：{pattern.primary_pattern}（置信度：{pattern.confidence:.0%}）")

        # 深层意图
        if full_analysis.deep_intent:
            parts.append(f"\n\n**深层意图**：{full_analysis.deep_intent}")

        # 工具描述
        tool_desc = full_analysis.tool_description
        if tool_desc.natural_language_description:
            parts.append(f"\n\n{tool_desc.natural_language_description}")

        # 提示用户确认问题（仅当有问题时）
        if questions_count > 0:
            parts.append(f"\n\n📋 **请回答下方 {questions_count} 个确认问题**")
        else:
            parts.append("\n\n✅ **分析完成，请确认后生成工具**")

    return "".join(parts)