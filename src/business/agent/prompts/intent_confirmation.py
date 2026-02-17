"""
意图确认提示词

用于展示和确认用户意图。
"""


def get_intent_confirmation_prompt(intent_data: dict) -> str:
    """
    生成意图确认提示词

    Args:
        intent_data: 意图分析结果

    Returns:
        提示词字符串
    """
    return f"""我理解您想要执行以下操作：

意图类型：{intent_data.get('intent_type')}
描述：{intent_data.get('description')}
参数：{intent_data.get('parameters')}

请确认：
- 如果正确，请回复"确认"
- 如果需要修改，请告诉我您的调整
"""
