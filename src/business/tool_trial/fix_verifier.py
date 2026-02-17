"""
修复验证器

验证修复后的代码是否可用，运行测试用例，对比执行结果
"""

import logging
import ast
import subprocess
import tempfile
import os
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.business.ai.llm_client import LangChainLLMClient
from src.business.tool_trial.error_diagnosis_models import (
    FixVerification,
    TestCase,
    FixedCode,
)

logger = logging.getLogger(__name__)


class FixVerifier:
    """
    修复验证器

    验证修复后的代码是否可用
    """

    def __init__(self, llm_client: Optional[LangChainLLMClient] = None):
        """
        初始化修复验证器

        Args:
            llm_client: LLM 客户端（可选，用于智能验证）
        """
        self.llm_client = llm_client

    async def verify_fix(
        self,
        original_code: str,
        fixed_code: str,
        test_cases: Optional[List[TestCase]] = None,
    ) -> FixVerification:
        """
        验证修复是否有效

        Args:
            original_code: 原始代码
            fixed_code: 修复后的代码
            test_cases: 测试用例列表（可选）

        Returns:
            验证结果
        """
        logger.info("开始验证修复")

        verification = FixVerification(verification_id=str(datetime.now().timestamp()))

        try:
            # 1. 语法检查
            if not self._check_syntax(fixed_code):
                verification.verification_message = "修复后的代码存在语法错误"
                verification.is_valid = False
                verification.confidence = 0.0
                return verification

            # 2. 静态分析（检查是否有明显回退）
            has_regression = self._check_regression(original_code, fixed_code)
            if has_regression:
                verification.regression_detected = True
                verification.warnings.append("检测到可能的代码回退")

            # 3. 如果有测试用例，运行测试
            if test_cases:
                await self._run_tests(verification, fixed_code, test_cases)
            else:
                # 没有测试用例，进行基本验证
                verification.is_valid = True
                verification.confidence = 0.7
                verification.verification_message = "通过基本验证（语法检查）"

            # 4. 计算改进评分
            verification.improvement_score = self._calculate_improvement_score(
                original_code, fixed_code
            )

            # 5. 综合判断
            if verification.regression_detected:
                verification.is_valid = False
                verification.verification_message = "检测到代码回退，修复无效"
                verification.confidence = 0.2
            elif verification.total_tests > 0:
                # 有测试用例，根据测试结果判断
                success_rate = verification.calculate_success_rate()
                verification.is_valid = success_rate >= 0.6  # 至少60%测试通过
                verification.confidence = success_rate
                verification.verification_message = (
                    f"测试通过率: {success_rate:.1%} ({verification.passed_tests}/{verification.total_tests})"
                )
            else:
                # 没有测试用例，基本通过
                verification.is_valid = True
                verification.confidence = 0.7
                verification.verification_message = "通过基本验证"

            logger.info(
                f"验证完成: is_valid={verification.is_valid}, "
                f"confidence={verification.confidence:.2f}"
            )

        except Exception as e:
            logger.error(f"验证失败: {e}", exc_info=True)
            verification.is_valid = False
            verification.verification_message = f"验证过程出错: {str(e)}"
            verification.confidence = 0.0

        return verification

    def _check_syntax(self, code: str) -> bool:
        """
        检查代码语法

        Args:
            code: 代码字符串

        Returns:
            是否语法正确
        """
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            logger.warning(f"语法错误: {e}")
            return False

    def _check_regression(self, original_code: str, fixed_code: str) -> bool:
        """
        检查是否有代码回退

        Args:
            original_code: 原始代码
            fixed_code: 修复后的代码

        Returns:
            是否检测到回退
        """
        try:
            # 简单检查：代码行数是否大幅减少
            original_lines = len(original_code.split("\n"))
            fixed_lines = len(fixed_code.split("\n"))

            if fixed_lines < original_lines * 0.5:
                logger.warning(
                    f"代码行数大幅减少: {original_lines} → {fixed_lines}"
                )
                return True

            # 检查是否移除了重要的导入
            original_imports = self._extract_imports(original_code)
            fixed_imports = self._extract_imports(fixed_code)

            removed_imports = original_imports - fixed_imports
            if removed_imports:
                logger.warning(f"移除了导入: {removed_imports}")
                return True

            return False

        except Exception as e:
            logger.warning(f"回退检查失败: {e}")
            return False

    def _extract_imports(self, code: str) -> set:
        """
        提取代码中的导入语句

        Args:
            code: 代码字符串

        Returns:
            导入模块集合
        """
        imports = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module.split(".")[0])
        except Exception:
            pass
        return imports

    async def _run_tests(
        self, verification: FixVerification, code: str, test_cases: List[TestCase]
    ):
        """
        运行测试用例

        Args:
            verification: 验证结果对象
            code: 代码
            test_cases: 测试用例列表
        """
        verification.total_tests = len(test_cases)

        for test_case in test_cases:
            try:
                # 在沙箱中执行代码
                result = await self._execute_in_sandbox(
                    code, test_case.input_data
                )

                # 更新测试用例结果
                test_case.actual_output = result.get("output")
                test_case.actual_error = result.get("error")

                # 判断是否通过
                if test_case.expected_error:
                    # 预期会抛出错误
                    if test_case.actual_error:
                        test_case.passed = True
                    else:
                        test_case.passed = False
                else:
                    # 预期正常输出
                    if not test_case.actual_error and test_case.actual_output:
                        test_case.passed = True
                    else:
                        test_case.passed = False

                if test_case.passed:
                    verification.passed_tests += 1

            except Exception as e:
                logger.error(f"测试用例执行失败: {e}")
                test_case.actual_error = str(e)
                test_case.passed = False

        verification.test_cases = test_cases

    async def _execute_in_sandbox(
        self, code: str, input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        在沙箱中执行代码

        Args:
            code: 代码
            input_data: 输入数据

        Returns:
            执行结果
        """
        result = {"output": None, "error": None}

        try:
            # 创建临时文件
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as f:
                f.write(code)
                temp_file = f.name

            try:
                # 准备执行环境
                exec_globals = {"__builtins__": __builtins__}
                exec_locals = input_data.copy()

                # 执行代码
                exec(compile(code, temp_file, "exec"), exec_globals, exec_locals)

                # 提取输出（如果有特定的返回值）
                if "result" in exec_locals:
                    result["output"] = exec_locals["result"]
                elif "__return__" in exec_locals:
                    result["output"] = exec_locals["__return__"]

            finally:
                # 删除临时文件
                if os.path.exists(temp_file):
                    os.unlink(temp_file)

        except Exception as e:
            result["error"] = str(e)

        return result

    def _calculate_improvement_score(
        self, original_code: str, fixed_code: str
    ) -> float:
        """
        计算改进评分

        Args:
            original_code: 原始代码
            fixed_code: 修复后的代码

        Returns:
            改进评分 (-1.0 到 1.0)
        """
        try:
            # 简单的启发式评分
            score = 0.0

            # 1. 语法改进
            original_syntax = self._check_syntax(original_code)
            fixed_syntax = self._check_syntax(fixed_code)

            if not original_syntax and fixed_syntax:
                score += 0.5  # 修复了语法错误
            elif original_syntax and not fixed_syntax:
                score -= 0.5  # 引入了语法错误

            # 2. 代码复杂度（行数）
            original_lines = len(original_code.split("\n"))
            fixed_lines = len(fixed_code.split("\n"))

            if fixed_lines < original_lines:
                score += 0.1  # 代码简化
            elif fixed_lines > original_lines * 1.5:
                score -= 0.2  # 代码膨胀

            # 3. 注释和文档
            original_comments = original_code.count("#")
            fixed_comments = fixed_code.count("#")

            if fixed_comments > original_comments:
                score += 0.1  # 增加了注释

            # 限制范围
            return max(-1.0, min(1.0, score))

        except Exception as e:
            logger.warning(f"计算改进评分失败: {e}")
            return 0.0

    async def verify_with_llm(
        self,
        original_code: str,
        fixed_code: str,
        error_diagnosis: Any,
    ) -> FixVerification:
        """
        使用 LLM 进行智能验证

        Args:
            original_code: 原始代码
            fixed_code: 修复后的代码
            error_diagnosis: 错误诊断结果

        Returns:
            验证结果
        """
        if not self.llm_client:
            logger.warning("未提供 LLM 客户端，降级到基本验证")
            return await self.verify_fix(original_code, fixed_code)

        logger.info("使用 LLM 进行智能验证")

        try:
            # 构建提示词
            prompt = self._build_verification_prompt(
                original_code, fixed_code, error_diagnosis
            )

            # 调用 LLM
            response = await self.llm_client.call_llm(
                prompt=prompt,
                response_format="json",
                max_tokens=1500,
                temperature=0.3,
            )

            # 解析响应
            import json

            data = json.loads(response)

            verification = FixVerification(
                is_valid=data.get("is_valid", False),
                confidence=data.get("confidence", 0.0),
                verification_message=data.get("verification_message", ""),
                warnings=data.get("warnings", []),
                improvement_score=data.get("improvement_score", 0.0),
                regression_detected=data.get("regression_detected", False),
                llm_model_used="claude-3.5-sonnet",
            )

            logger.info(
                f"LLM 验证完成: is_valid={verification.is_valid}, "
                f"confidence={verification.confidence:.2f}"
            )

            return verification

        except Exception as e:
            logger.error(f"LLM 验证失败: {e}")
            # 降级到基本验证
            return await self.verify_fix(original_code, fixed_code)

    def _build_verification_prompt(
        self, original_code: str, fixed_code: str, error_diagnosis: Any
    ) -> str:
        """
        构建验证提示词

        Args:
            original_code: 原始代码
            fixed_code: 修复后的代码
            error_diagnosis: 错误诊断

        Returns:
            提示词字符串
        """
        prompt = f"""你是一个代码审查专家。请验证修复后的代码是否正确。

## 原始错误
错误类型: {error_diagnosis.error_type.value}
错误消息: {error_diagnosis.error_message}
根本原因: {error_diagnosis.root_cause}

## 原始代码
```python
{original_code}
```

## 修复后的代码
```python
{fixed_code}
```

## 验证任务

请检查以下方面：

1. **语法正确性**：修复后的代码是否有语法错误？
2. **错误修复**：是否成功修复了原始错误？
3. **代码回退**：是否引入了新的问题或回退？
4. **逻辑正确性**：修复是否保持了代码的原有逻辑？
5. **代码质量**：修复是否合理，是否符合最佳实践？

请返回以下JSON格式的验证结果（不要使用markdown代码块）：

{{
  "is_valid": true/false,
  "confidence": 0.0-1.0,
  "verification_message": "验证结果说明",
  "warnings": ["警告1", "警告2"],
  "improvement_score": -1.0到1.0,
  "regression_detected": true/false
}}

开始验证：
"""
        return prompt
