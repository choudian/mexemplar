"""
意图分析节点

分析用户录制操作的意图，基于完整的提示词设计。
"""

from typing import Dict, Any, List
from langchain_core.messages import AIMessage
import logging
import json
import re

from ..state import AgentState, IntentData, IntentAnalysisResult, PatternRecognition, ParameterizationItem, ConfirmationQuestion, ToolDescription

logger = logging.getLogger(__name__)


def intent_analysis_node(state: AgentState) -> Dict[str, Any]:
    """
    意图分析节点

    分析录制数据，识别用户意图，生成完整的分析结果。

    Args:
        state: 当前状态

    Returns:
        状态更新
    """
    # 获取录制数据
    recording_data = state.get("recording_data")
    if not recording_data:
        return {
            "error_info": {
                "code": "NO_RECORDING_DATA",
                "message": "No recording data provided"
            }
        }

    # 提取 actions 和 metadata
    actions = recording_data.get("actions", [])
    metadata = recording_data.get("metadata", {})

    # 生成提示词
    from ..prompts.intent_analysis import get_intent_analysis_prompt
    prompt = get_intent_analysis_prompt(actions, metadata)

    try:
        # 调用 LLM 分析意图
        from src.business.ai.llm_client import create_llm_client
        from src.data.unified_config import get_unified_config

        config = get_unified_config()

        # 构建 LLM 客户端配置
        client_config = {
            "provider": config.get_ai_provider(),
            "model": config.get_ai_model(),
            "api_key": config.get_ai_api_key(),
            "temperature": config.get_ai_temperature(),
            "max_tokens": 4096,  # 增加输出长度以适应完整分析
        }

        base_url = config.get_ai_base_url()
        if base_url:
            client_config["base_url"] = base_url

        # 创建客户端并调用
        client = create_llm_client(client_config)
        response_text = client.chat(prompt=prompt, max_tokens=4096)

        logger.info(f"LLM 响应长度: {len(response_text)} 字符")

        # 解析响应
        intent_result = _parse_intent_response(response_text)

        # 构建完整的 IntentAnalysisResult
        full_analysis = _build_full_analysis(intent_result)

        # 创建 IntentData（简化版，用于状态传递）
        intent_data = IntentData(
            intent_type=_determine_intent_type(intent_result),
            description=intent_result.get("intent_analysis", {}).get("deep_intent", "未知任务"),
            parameters=_extract_parameters(intent_result),
            confidence=intent_result.get("pattern_recognition", {}).get("confidence", 0.8),
            raw_analysis=intent_result,
            full_analysis=full_analysis
        )

        logger.info(f"意图分析完成: {intent_data.description}")
        logger.info(f"确认问题数量: {len(full_analysis.confirmation_questions)}")

        # 返回状态更新
        return {
            "current_intent": intent_data,
            "messages": [AIMessage(content=f"已分析意图：{intent_data.description}")]
        }

    except Exception as e:
        logger.error(f"意图分析失败: {e}", exc_info=True)
        # 返回默认意图
        intent_data = IntentData(
            intent_type="browser_automation",
            description="用户录制了一个浏览器操作",
            parameters={},
            confidence=0.5,
            raw_analysis={"error": str(e)}
        )
        return {
            "current_intent": intent_data,
            "messages": [AIMessage(content=f"意图分析失败，使用默认意图：{e}")]
        }


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
