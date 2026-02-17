"""
代码修复提示词

用于自动修复执行出错的代码。
"""


def get_code_repair_prompt(
    code: str,
    error_message: str,
    context: dict
) -> str:
    """
    生成代码修复提示词

    Args:
        code: 出错的代码
        error_message: 错误信息
        context: 上下文信息

    Returns:
        提示词字符串
    """
    return f"""以下代码执行时出错，请修复：

代码：
```python
{code}
```

错误信息：
{error_message}

上下文：
{context}

请输出修复后的代码。
"""
