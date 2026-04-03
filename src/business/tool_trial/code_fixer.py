"""
代码修复器

使用 LLM 驱动的自动代码修复，支持多次重试
"""

import logging

from src.business.ai.llm_client import LangChainLLMClient
from src.business.tool_trial.error_diagnosis_models import (
    ErrorDiagnosis,
)

logger = logging.getLogger(__name__)


class CodeFixer:
    """
    代码修复器

    使用 LLM 自动修复代码错误
    """

    MAX_FIX_ATTEMPTS = 3  # 最大修复尝试次数

    def __init__(self, llm_client: LangChainLLMClient):
        """
        初始化代码修复器

        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client

    async def _llm_fix(
        self, code: str, diagnosis: ErrorDiagnosis, attempt: int
    ) -> tuple[str, str]:
        """
        使用 LLM 修复代码

        Args:
            code: 当前代码
            diagnosis: 错误诊断
            attempt: 当前尝试次数

        Returns:
            (修复后的代码, 变更说明)
        """
        # 构建提示词
        prompt = self._build_fix_prompt(code, diagnosis, attempt)

        try:
            # 调用 LLM
            response = await self.llm_client.call_llm(
                prompt=prompt,
                response_format="json",
                max_tokens=2000,
                temperature=0.2,  # 较低温度，更稳定
            )

            # 解析响应
            import json

            data = json.loads(response)

            fixed_code = data.get("fixed_code", code)
            change_description = data.get("change_description", "无说明")

            return fixed_code, change_description

        except Exception as e:
            logger.error(f"LLM 修复失败: {e}")
            raise

    def _build_fix_prompt(
        self, code: str, diagnosis: ErrorDiagnosis, attempt: int
    ) -> str:
        """
        构建修复提示词

        Args:
            code: 当前代码
            diagnosis: 错误诊断
            attempt: 当前尝试次数

        Returns:
            提示词字符串
        """
        prompt = f"""你是一个Python代码修复专家。请修复以下代码中的错误。

## 错误信息
错误类型: {diagnosis.error_type.value}
错误消息: {diagnosis.error_message}
严重程度: {diagnosis.error_severity.value}

## 根本原因
{diagnosis.root_cause}

## 修复建议
{diagnosis.suggested_fix}

## 当前代码（第 {attempt} 次尝试）
```python
{code}
```

## 修复要求

1. **只修复错误**：不要改变代码的原有逻辑，只修复错误
2. **保持结构**：保持代码的缩进、注释和整体结构
3. **最小改动**：只修改必要的部分
4. **验证语法**：确保修复后的代码语法正确
5. **添加注释**：如果有重要的修改，在代码中添加注释说明

## Few-Shot 示例

### 示例1：修复 NameError
**错误代码**：
```python
def login(username):
    print(user)  # 错误：变量名拼写错误
    return True
```

**错误信息**：
```
NameError: name 'user' is not defined
```

**修复后的代码**：
```python
def login(username):
    print(username)  # 修复：使用正确的变量名
    return True
```

**变更说明**：将 `user` 改为 `username`

### 示例2：修复 TypeError
**错误代码**：
```python
def add_numbers(a, b):
    return a + b

result = add_numbers("1", 2)  # 错误：类型不匹配
```

**错误信息**：
```
TypeError: can only concatenate str (not "int") to str
```

**修复后的代码**：
```python
def add_numbers(a, b):
    return a + b

result = add_numbers(int("1"), 2)  # 修复：将字符串转换为整数
```

**变更说明**：将 `"1"` 转换为整数 `int("1")`

### 示例3：修复 AttributeError
**错误代码**：
```python
data = {{"name": "Alice", "age": 30}}
print(data.name)
```

**错误信息**：
```
AttributeError: 'dict' object has no attribute 'name'
```

**修复后的代码**：
```python
data = {{"name": "Alice", "age": 30}}
print(data["name"])
```

**变更说明**：将 data.name 改为 data["name"]

## 输出格式

请严格按照以下JSON格式返回（不要使用markdown代码块）：

{{
  "fixed_code": "修复后的完整代码（保持原有格式和缩进）",
  "change_description": "简要说明做了哪些修改"
}}

开始修复：
"""
        return prompt

    def _simple_syntax_check(self, code: str) -> bool:
        """
        简单的语法检查

        Args:
            code: 代码字符串

        Returns:
            是否语法正确
        """
        try:
            import ast
            ast.parse(code)
            return True
        except SyntaxError:
            return False
