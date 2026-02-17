"""
代码修复器

使用 LLM 驱动的自动代码修复，支持多次重试
"""

import logging
import difflib
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.business.ai.llm_client import LangChainLLMClient
from src.business.tool_trial.error_diagnosis_models import (
    ErrorDiagnosis,
    FixedCode,
    CodeChange,
    FixStrategy,
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

    async def fix_code(
        self,
        code: str,
        diagnosis: ErrorDiagnosis,
        max_attempts: int = MAX_FIX_ATTEMPTS,
    ) -> FixedCode:
        """
        修复代码

        Args:
            code: 原始代码
            diagnosis: 错误诊断结果
            max_attempts: 最大尝试次数

        Returns:
            修复后的代码
        """
        logger.info(
            f"开始修复代码，错误类型: {diagnosis.error_type}, "
            f"最大尝试次数: {max_attempts}"
        )

        original_code = code
        current_code = code
        all_changes: List[CodeChange] = []

        # 如果建议手动修复，直接返回
        if diagnosis.fix_strategy == FixStrategy.MANUAL:
            logger.info("错误建议手动修复，返回原始代码")
            return FixedCode(
                original_code=original_code,
                fixed_code=original_code,
                changes_made=[],
                is_fixed=False,
                fix_attempts=0,
                final_error="需要手动修复",
            )

        # 多次尝试修复
        for attempt in range(1, max_attempts + 1):
            logger.info(f"第 {attempt} 次修复尝试")

            try:
                # 调用 LLM 修复代码
                fixed_code, change_description = await self._llm_fix(
                    current_code, diagnosis, attempt
                )

                # 记录变更
                change = CodeChange(
                    original_code=current_code,
                    fixed_code=fixed_code,
                    change_description=change_description,
                    fix_attempt=attempt,
                )
                all_changes.append(change)

                # 检查代码是否真的改变了
                if fixed_code == current_code:
                    logger.warning(f"第 {attempt} 次修复：代码未改变")
                    # 继续尝试
                    current_code = fixed_code
                    continue

                # 检查修复是否有效（简单验证：代码能被解析）
                is_valid = self._simple_syntax_check(fixed_code)

                if is_valid:
                    logger.info(f"✅ 第 {attempt} 次修复成功！")
                    return FixedCode(
                        original_code=original_code,
                        fixed_code=fixed_code,
                        changes_made=all_changes,
                        is_fixed=True,
                        fix_attempts=attempt,
                        final_error=None,
                    )
                else:
                    logger.warning(f"第 {attempt} 次修复：语法检查失败")
                    current_code = fixed_code
                    continue

            except Exception as e:
                logger.error(f"第 {attempt} 次修复失败: {e}")
                # 继续尝试

        # 达到最大尝试次数，返回原始代码
        logger.warning(f"达到最大尝试次数 ({max_attempts})，修复失败")
        return FixedCode(
            original_code=original_code,
            fixed_code=current_code,
            changes_made=all_changes,
            is_fixed=False,
            fix_attempts=max_attempts,
            final_error="达到最大尝试次数，修复失败",
        )

    async def fix_with_verification(
        self,
        code: str,
        diagnosis: ErrorDiagnosis,
        verifier,
        max_attempts: int = MAX_FIX_ATTEMPTS,
    ) -> FixedCode:
        """
        修复代码并验证（需要提供验证器）

        Args:
            code: 原始代码
            diagnosis: 错误诊断结果
            verifier: 验证器对象（需要有 verify_fix 方法）
            max_attempts: 最大尝试次数

        Returns:
            修复后的代码
        """
        logger.info("开始修复代码（带验证）")

        original_code = code
        current_code = code
        all_changes: List[CodeChange] = []
        current_error = diagnosis.error_message

        for attempt in range(1, max_attempts + 1):
            logger.info(f"第 {attempt} 次修复尝试（带验证）")

            try:
                # 修复代码
                fixed_code, change_description = await self._llm_fix(
                    current_code, diagnosis, attempt
                )

                # 记录变更
                change = CodeChange(
                    original_code=current_code,
                    fixed_code=fixed_code,
                    change_description=change_description,
                    fix_attempt=attempt,
                )
                all_changes.append(change)

                # 如果代码没有改变，停止尝试
                if fixed_code == current_code:
                    logger.warning("代码未改变，停止尝试")
                    break

                # 验证修复
                verification = await verifier.verify_fix(original_code, fixed_code)

                if verification.is_valid:
                    logger.info(f"✅ 第 {attempt} 次修复成功并通过验证！")
                    return FixedCode(
                        original_code=original_code,
                        fixed_code=fixed_code,
                        changes_made=all_changes,
                        is_fixed=True,
                        fix_attempts=attempt,
                        final_error=None,
                    )
                else:
                    logger.warning(
                        f"第 {attempt} 次修复验证失败: {verification.verification_message}"
                    )
                    # 更新错误信息，用于下次修复
                    current_error = verification.verification_message
                    current_code = fixed_code
                    continue

            except Exception as e:
                logger.error(f"第 {attempt} 次修复失败: {e}")
                current_code = fixed_code if 'fixed_code' in locals() else current_code

        # 达到最大尝试次数
        logger.warning(f"达到最大尝试次数 ({max_attempts})，修复失败")
        return FixedCode(
            original_code=original_code,
            fixed_code=current_code,
            changes_made=all_changes,
            is_fixed=False,
            fix_attempts=max_attempts,
            final_error=current_error,
        )

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

    def _diff_code(self, original: str, fixed: str) -> List[str]:
        """
        生成代码差异

        Args:
            original: 原始代码
            fixed: 修复后的代码

        Returns:
            差异列表
        """
        diff = difflib.unified_diff(
            original.splitlines(keepends=True),
            fixed.splitlines(keepends=True),
            fromfile="original.py",
            tofile="fixed.py",
        )
        return list(diff)
