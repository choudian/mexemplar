"""
错误诊断和自动修复单元测试
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.business.tool_trial.error_diagnoser import ErrorDiagnoser
from src.business.tool_trial.code_fixer import CodeFixer
from src.business.tool_trial.fix_verifier import FixVerifier
from src.business.tool_trial.error_diagnosis_models import (
    ErrorDiagnosis,
    FixedCode,
    FixVerification,
    ErrorType,
    ErrorSeverity,
    FixStrategy,
)


@pytest.fixture
def mock_llm_client():
    """模拟 LLM 客户端"""
    client = MagicMock()
    client.call_llm = AsyncMock()
    return client


# ============================================================================
# ErrorDiagnoser 测试
# ============================================================================


class TestErrorDiagnoser:
    """错误诊断器测试"""

    @pytest.fixture
    def diagnoser(self, mock_llm_client):
        """创建诊断器实例"""
        return ErrorDiagnoser(mock_llm_client)

    @pytest.mark.asyncio
    async def test_diagnose_syntax_error(self, diagnoser):
        """测试诊断语法错误"""
        error = SyntaxError("invalid syntax")
        code = "print('hello'  # 缺少右括号"

        diagnosis = await diagnoser.diagnose(error, code)

        assert diagnosis.error_type == ErrorType.SYNTAX
        assert diagnosis.error_severity == ErrorSeverity.CRITICAL
        assert diagnosis.confidence > 0.5

    @pytest.mark.asyncio
    async def test_diagnose_name_error(self, diagnoser):
        """测试诊断 NameError"""
        error = NameError("name 'x' is not defined")
        code = "print(x)"

        diagnosis = await diagnoser.diagnose(error, code)

        assert diagnosis.error_type == ErrorType.RUNTIME
        assert diagnosis.error_severity == ErrorSeverity.MEDIUM
        assert "x" in diagnosis.error_message

    @pytest.mark.asyncio
    async def test_diagnose_type_error(self, diagnoser):
        """测试诊断 TypeError"""
        error = TypeError("can only concatenate str (not \"int\") to str")
        code = "result = 'hello' + 123"

        diagnosis = await diagnoser.diagnose(error, code)

        assert diagnosis.error_type == ErrorType.TYPE
        assert diagnosis.error_severity == ErrorSeverity.MEDIUM

    @pytest.mark.asyncio
    async def test_diagnose_attribute_error(self, diagnoser):
        """测试诊断 AttributeError"""
        error = AttributeError("'dict' object has no attribute 'name'")
        code = "data = {'name': 'Alice'}\nprint(data.name)"

        diagnosis = await diagnoser.diagnose(error, code)

        assert diagnosis.error_type == ErrorType.ATTRIBUTE
        assert diagnosis.error_severity == ErrorSeverity.MEDIUM

    @pytest.mark.asyncio
    async def test_diagnose_import_error(self, diagnoser):
        """测试诊断 ImportError"""
        error = ImportError("No module named 'nonexistent_module'")
        code = "import nonexistent_module"

        diagnosis = await diagnoser.diagnose(error, code)

        assert diagnosis.error_type == ErrorType.IMPORT
        assert diagnosis.error_severity == ErrorSeverity.MEDIUM  # 改为MEDIUM

    @pytest.mark.asyncio
    async def test_extract_error_context(self, diagnoser):
        """测试提取错误上下文"""
        code = """line 1
line 2
line 3
line 4
line 5
"""
        error_traceback = 'File "<string>", line 3, in <module>'

        snippet, line_number = diagnoser._extract_error_context(code, error_traceback)

        assert line_number == 3
        assert snippet is not None
        assert "line 2" in snippet
        assert "line 3" in snippet
        assert "line 4" in snippet

    def test_classify_error_by_rules(self, diagnoser):
        """测试规则引擎分类"""
        # 测试 SyntaxError
        error = SyntaxError("test")
        error_type = diagnoser._classify_error_by_rules(error, "SyntaxError")
        assert error_type == ErrorType.SYNTAX

        # 测试 TypeError
        error = TypeError("test")
        error_type = diagnoser._classify_error_by_rules(error, "TypeError")
        assert error_type == ErrorType.TYPE

    def test_assess_severity(self, diagnoser):
        """测试严重程度评估"""
        # 语法错误应该是 CRITICAL
        severity = diagnoser._assess_severity(Exception(), ErrorType.SYNTAX)
        assert severity == ErrorSeverity.CRITICAL

        # 导入错误应该是 MEDIUM（已调整）
        severity = diagnoser._assess_severity(Exception(), ErrorType.IMPORT)
        assert severity == ErrorSeverity.MEDIUM

        # 运行时错误应该是 MEDIUM
        severity = diagnoser._assess_severity(Exception(), ErrorType.RUNTIME)
        assert severity == ErrorSeverity.MEDIUM


# ============================================================================
# CodeFixer 测试
# ============================================================================


class TestCodeFixer:
    """代码修复器测试"""

    @pytest.fixture
    def fixer(self, mock_llm_client):
        """创建修复器实例"""
        return CodeFixer(mock_llm_client)

    @pytest.mark.asyncio
    async def test_fix_code_success(self, fixer, mock_llm_client):
        """测试成功修复代码"""
        code = "print(x)"
        diagnosis = ErrorDiagnosis(
            error_type=ErrorType.RUNTIME,
            error_message="name 'x' is not defined",
            root_cause="变量 x 未定义",
            suggested_fix="定义变量 x",
            fix_strategy=FixStrategy.AUTOMATIC,
            confidence=0.9,
        )

        # 模拟 LLM 返回修复后的代码
        mock_llm_client.call_llm.return_value = """{
  "fixed_code": "x = 'hello'\\nprint(x)",
  "change_description": "定义变量 x"
}"""

        result = await fixer.fix_code(code, diagnosis)

        assert result.is_fixed is True
        assert result.fix_attempts == 1
        assert "x = 'hello'" in result.fixed_code
        assert len(result.changes_made) == 1

    @pytest.mark.asyncio
    async def test_fix_code_max_attempts(self, fixer, mock_llm_client):
        """测试达到最大尝试次数"""
        code = "print(x)"
        diagnosis = ErrorDiagnosis(
            error_type=ErrorType.RUNTIME,
            error_message="name 'x' is not defined",
            root_cause="变量 x 未定义",
            suggested_fix="定义变量 x",
            fix_strategy=FixStrategy.AUTOMATIC,
            confidence=0.9,
        )

        # 模拟 LLM 返回未修复的代码
        mock_llm_client.call_llm.return_value = """{
  "fixed_code": "print(x)",
  "change_description": "未修复"
}"""

        result = await fixer.fix_code(code, diagnosis, max_attempts=2)

        assert result.is_fixed is False
        assert result.fix_attempts == 2
        assert "达到最大尝试次数" in result.final_error

    @pytest.mark.asyncio
    async def test_fix_code_manual_strategy(self, fixer, mock_llm_client):
        """测试手动修复策略（不调用 LLM）"""
        code = "complex_code_with_bug"
        diagnosis = ErrorDiagnosis(
            error_type=ErrorType.UNKNOWN,
            error_message="复杂错误",
            root_cause="需要人工分析",
            suggested_fix="手动修复",
            fix_strategy=FixStrategy.MANUAL,
            confidence=0.3,
        )

        result = await fixer.fix_code(code, diagnosis)

        assert result.is_fixed is False
        assert result.fix_attempts == 0
        assert result.fixed_code == code  # 返回原始代码
        assert not mock_llm_client.call_llm.called  # 不应该调用 LLM

    def test_simple_syntax_check(self, fixer):
        """测试简单语法检查"""
        # 正确的代码
        assert fixer._simple_syntax_check("print('hello')") is True

        # 错误的代码
        assert fixer._simple_syntax_check("print('hello'") is False


# ============================================================================
# FixVerifier 测试
# ============================================================================


class TestFixVerifier:
    """修复验证器测试"""

    @pytest.fixture
    def verifier(self, mock_llm_client):
        """创建验证器实例"""
        return FixVerifier(mock_llm_client)

    @pytest.mark.asyncio
    async def test_verify_fix_syntax_error(self, verifier):
        """测试验证包含语法错误的修复"""
        original_code = "print('hello')"
        fixed_code = "print('hello'  # 语法错误"

        verification = await verifier.verify_fix(original_code, fixed_code)

        assert verification.is_valid is False
        assert "语法错误" in verification.verification_message
        assert verification.confidence == 0.0

    @pytest.mark.asyncio
    async def test_verify_fix_success(self, verifier):
        """测试验证成功的修复"""
        original_code = "print(x)"
        fixed_code = "x = 'hello'\nprint(x)"

        verification = await verifier.verify_fix(original_code, fixed_code)

        assert verification.is_valid is True
        assert verification.confidence >= 0.7
        assert "基本验证" in verification.verification_message

    def test_check_syntax(self, verifier):
        """测试语法检查"""
        # 正确的代码
        assert verifier._check_syntax("print('hello')") is True

        # 错误的代码
        assert verifier._check_syntax("print('hello'") is False

    def test_check_regression(self, verifier):
        """测试回退检测"""
        original_code = "line1\nline2\nline3\nline4\nline5"
        fixed_code = "line1"  # 代码大幅减少

        has_regression = verifier._check_regression(original_code, fixed_code)
        assert has_regression is True

    def test_extract_imports(self, verifier):
        """测试导入提取"""
        code = """
import os
import sys
from typing import Dict
"""
        imports = verifier._extract_imports(code)

        assert "os" in imports
        assert "sys" in imports
        assert "typing" in imports

    def test_calculate_improvement_score(self, verifier):
        """测试改进评分计算"""
        original = "print('hello')"
        fixed = "x = 'hello'\nprint(x)"

        score = verifier._calculate_improvement_score(original, fixed)

        assert -1.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_execute_in_sandbox(self, verifier):
        """测试沙箱执行"""
        code = "result = 1 + 1"
        input_data = {}

        result = await verifier._execute_in_sandbox(code, input_data)

        assert result["error"] is None
        assert result["output"] == 2

    @pytest.mark.asyncio
    async def test_execute_in_sandbox_with_error(self, verifier):
        """测试沙箱执行错误代码"""
        code = "1 / 0"
        input_data = {}

        result = await verifier._execute_in_sandbox(code, input_data)

        assert result["error"] is not None
        assert "ZeroDivisionError" in result["error"] or "division by zero" in result["error"]


# ============================================================================
# 数据模型测试
# ============================================================================


class TestDataModels:
    """数据模型测试"""

    def test_error_diagnosis_to_dict(self):
        """测试 ErrorDiagnosis 序列化"""
        diagnosis = ErrorDiagnosis(
            error_type=ErrorType.SYNTAX,
            error_message="test error",
            error_severity=ErrorSeverity.HIGH,
            root_cause="test cause",
            suggested_fix="test fix",
            confidence=0.8,
        )

        data = diagnosis.to_dict()

        assert data["error_type"] == "syntax"
        assert data["error_message"] == "test error"
        assert data["error_severity"] == "high"
        assert data["confidence"] == 0.8

    def test_error_diagnosis_from_dict(self):
        """测试 ErrorDiagnosis 反序列化"""
        data = {
            "error_type": "runtime",
            "error_message": "test error",
            "error_severity": "medium",
            "root_cause": "test cause",
            "suggested_fix": "test fix",
            "confidence": 0.7,
            "diagnosed_at": "2026-02-10T00:00:00",
        }

        diagnosis = ErrorDiagnosis.from_dict(data)

        assert diagnosis.error_type == ErrorType.RUNTIME
        assert diagnosis.error_severity == ErrorSeverity.MEDIUM
        assert diagnosis.confidence == 0.7

    def test_fixed_code_to_dict(self):
        """测试 FixedCode 序列化"""
        fixed = FixedCode(
            original_code="original",
            fixed_code="fixed",
            is_fixed=True,
            fix_attempts=1,
        )

        data = fixed.to_dict()

        assert data["original_code"] == "original"
        assert data["fixed_code"] == "fixed"
        assert data["is_fixed"] is True
        assert data["fix_attempts"] == 1

    def test_fix_verification_to_dict(self):
        """测试 FixVerification 序列化"""
        verification = FixVerification(
            is_valid=True,
            confidence=0.9,
            verification_message="Test passed",
            passed_tests=5,
            total_tests=5,
        )

        data = verification.to_dict()

        assert data["is_valid"] is True
        assert data["confidence"] == 0.9
        assert data["passed_tests"] == 5
        assert data["total_tests"] == 5

    def test_fix_verification_calculate_success_rate(self):
        """测试计算成功率"""
        verification = FixVerification(
            is_valid=False,
            confidence=0.0,
            passed_tests=3,
            total_tests=5,
        )

        success_rate = verification.calculate_success_rate()

        assert success_rate == 0.6
