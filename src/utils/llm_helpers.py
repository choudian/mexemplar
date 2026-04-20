"""
LLM 辅助工具函数

提供 LLM 响应解析的公共方法，消除各模块的重复代码。
"""

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 控制字符清洗正则：保留 \t(0x09) \n(0x0A) \r(0x0D)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def sanitize_text_for_llm(text: str, *, max_chars: int = 0) -> str:
    """
    清洗发往 LLM 的文本：移除非法控制字符，可选截断超长内容。

    Args:
        text: 待清洗文本
        max_chars: 最大字符数，0 表示不截断
    """
    cleaned = _CONTROL_CHAR_RE.sub("", text)
    if max_chars > 0 and len(cleaned) > max_chars:
        remain = len(cleaned) - max_chars
        return cleaned[:max_chars] + f"\n...[TRUNCATED {remain} chars]"
    return cleaned


def extract_json_from_response(
    response_text: str,
    require_dict: bool = True,
    log_prefix: str = "",
) -> Dict[str, Any]:
    """
    从 LLM 响应中提取 JSON 对象

    依次尝试以下策略：
    1. 提取 ```json``` 代码块
    2. 提取 ``` ``` 通用代码块
    3. 括号匹配算法查找完整 JSON 对象
    4. 直接解析整个响应

    Args:
        response_text: LLM 返回的原始文本
        require_dict: 是否要求结果必须是 dict（默认 True）
        log_prefix: 日志前缀（用于区分调用来源）

    Returns:
        解析出的 JSON 对象

    Raises:
        ValueError: 无法提取有效 JSON 时
    """
    response_text = response_text.strip()
    prefix = f"[{log_prefix}]" if log_prefix else ""

    # 策略 1: ```json``` 代码块
    match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        try:
            result = json.loads(json_str)
            if not require_dict or isinstance(result, dict):
                return result
            logger.warning(f"{prefix} LLM 返回的不是字典而是 {type(result)}")
        except json.JSONDecodeError as e:
            logger.warning(f"{prefix} ```json``` 代码块解析失败: {e}")

    # 策略 2: ``` ``` 通用代码块
    match = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        try:
            result = json.loads(json_str)
            if not require_dict or isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 策略 3: 括号匹配算法
    json_str = _extract_json_by_bracket_matching(response_text)
    if json_str:
        try:
            result = json.loads(json_str)
            if not require_dict or isinstance(result, dict):
                return result
        except json.JSONDecodeError as e:
            logger.warning(f"{prefix} 括号匹配提取的 JSON 解析失败: {e}")

    # 策略 4: 直接解析
    try:
        result = json.loads(response_text)
        if not require_dict or isinstance(result, dict):
            return result
        raise ValueError(
            f"LLM 返回的不是 JSON 对象（字典），而是 {type(result).__name__}: {str(result)[:100]}"
        )
    except json.JSONDecodeError as e:
        logger.error(f"{prefix} JSON 解析失败: {e}")
        logger.error(f"{prefix} 响应前500字符: {response_text[:500]}")
        raise ValueError(
            f"无法从响应中提取有效 JSON: {e}\n响应内容: {response_text[:200]}"
        ) from e


def _extract_json_by_bracket_matching(text: str) -> Optional[str]:
    """
    使用括号匹配算法从文本中提取完整的 JSON 对象

    支持任意层级的嵌套，正确处理字符串内的转义字符。

    Args:
        text: 待搜索的文本

    Returns:
        提取到的 JSON 字符串，如果找不到则返回 None
    """
    start_idx = text.find("{")
    if start_idx == -1:
        return None

    stack = []
    in_string = False
    escape_next = False

    for i in range(start_idx, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\" and in_string:
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char in "{[":
            stack.append(char)
        elif char in "}]":
            if not stack:
                break

            last_bracket = stack.pop()
            if (char == "}" and last_bracket != "{") or (char == "]" and last_bracket != "["):
                break

            if not stack:
                return text[start_idx : i + 1]

    return None
