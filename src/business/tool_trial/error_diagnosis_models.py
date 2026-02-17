"""
错误诊断和自动修复数据模型

定义错误诊断、代码修复和验证相关的数据结构
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
import datetime
import uuid


class ErrorType(str, Enum):
    """错误类型枚举"""

    SYNTAX = "syntax"  # 语法错误
    RUNTIME = "runtime"  # 运行时错误
    LOGIC = "logic"  # 逻辑错误
    IMPORT = "import"  # 导入错误
    TYPE = "type"  # 类型错误
    ATTRIBUTE = "attribute"  # 属性错误
    UNKNOWN = "unknown"  # 未知错误


class ErrorSeverity(str, Enum):
    """错误严重程度"""

    LOW = "low"  # 低（警告）
    MEDIUM = "medium"  # 中（不影响主流程）
    HIGH = "high"  # 高（导致功能失败）
    CRITICAL = "critical"  # 严重（导致程序崩溃）


class FixStrategy(str, Enum):
    """修复策略"""

    AUTOMATIC = "automatic"  # 自动修复
    SEMI_AUTOMATIC = "semi_automatic"  # 半自动（需要用户确认）
    MANUAL = "manual"  # 手动修复
    SKIP = "skip"  # 跳过修复


@dataclass
class ErrorDiagnosis:
    """
    错误诊断结果

    包含错误类型、根本原因、修复建议等信息
    """

    diagnosis_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # 错误信息
    error_type: ErrorType = ErrorType.UNKNOWN
    error_message: str = ""
    error_traceback: Optional[str] = None
    error_severity: ErrorSeverity = ErrorSeverity.MEDIUM

    # 诊断结果
    root_cause: str = ""  # 根本原因分析
    suggested_fix: str = ""  # 修复建议
    fix_strategy: FixStrategy = FixStrategy.AUTOMATIC
    confidence: float = 0.0  # 诊断置信度 (0.0-1.0)

    # 上下文信息
    code_snippet: Optional[str] = None  # 出错的代码片段
    line_number: Optional[int] = None  # 错误行号

    # 元数据
    diagnosed_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    llm_model_used: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "diagnosis_id": self.diagnosis_id,
            "error_type": self.error_type.value if isinstance(self.error_type, ErrorType) else self.error_type,
            "error_message": self.error_message,
            "error_traceback": self.error_traceback,
            "error_severity": self.error_severity.value if isinstance(self.error_severity, ErrorSeverity) else self.error_severity,
            "root_cause": self.root_cause,
            "suggested_fix": self.suggested_fix,
            "fix_strategy": self.fix_strategy.value if isinstance(self.fix_strategy, FixStrategy) else self.fix_strategy,
            "confidence": self.confidence,
            "code_snippet": self.code_snippet,
            "line_number": self.line_number,
            "diagnosed_at": self.diagnosed_at.isoformat(),
            "llm_model_used": self.llm_model_used,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ErrorDiagnosis":
        """从字典创建"""
        # 解析枚举
        error_type = data.get("error_type", ErrorType.UNKNOWN)
        if isinstance(error_type, str):
            error_type = ErrorType(error_type)

        error_severity = data.get("error_severity", ErrorSeverity.MEDIUM)
        if isinstance(error_severity, str):
            error_severity = ErrorSeverity(error_severity)

        fix_strategy = data.get("fix_strategy", FixStrategy.AUTOMATIC)
        if isinstance(fix_strategy, str):
            fix_strategy = FixStrategy(fix_strategy)

        return cls(
            diagnosis_id=data.get("diagnosis_id") or str(uuid.uuid4()),
            error_type=error_type,
            error_message=data.get("error_message", ""),
            error_traceback=data.get("error_traceback"),
            error_severity=error_severity,
            root_cause=data.get("root_cause", ""),
            suggested_fix=data.get("suggested_fix", ""),
            fix_strategy=fix_strategy,
            confidence=data.get("confidence", 0.0),
            code_snippet=data.get("code_snippet"),
            line_number=data.get("line_number"),
            diagnosed_at=datetime.datetime.fromisoformat(data["diagnosed_at"]) if data.get("diagnosed_at") else datetime.datetime.now(),
            llm_model_used=data.get("llm_model_used"),
        )


@dataclass
class CodeChange:
    """
    代码变更记录

    记录单次代码修改的详细信息
    """

    change_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # 变更内容
    original_code: str = ""
    fixed_code: str = ""
    change_description: str = ""  # 变更说明

    # 变更位置
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    # 变更元数据
    changed_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    fix_attempt: int = 0  # 第几次修复尝试

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "change_id": self.change_id,
            "original_code": self.original_code,
            "fixed_code": self.fixed_code,
            "change_description": self.change_description,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "changed_at": self.changed_at.isoformat(),
            "fix_attempt": self.fix_attempt,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeChange":
        """从字典创建"""
        return cls(
            change_id=data.get("change_id") or str(uuid.uuid4()),
            original_code=data.get("original_code", ""),
            fixed_code=data.get("fixed_code", ""),
            change_description=data.get("change_description", ""),
            line_start=data.get("line_start"),
            line_end=data.get("line_end"),
            changed_at=datetime.datetime.fromisoformat(data["changed_at"]) if data.get("changed_at") else datetime.datetime.now(),
            fix_attempt=data.get("fix_attempt", 0),
        )


@dataclass
class FixedCode:
    """
    修复后的代码

    包含修复后的代码和变更记录
    """

    # 代码内容
    original_code: str = ""
    fixed_code: str = ""

    # 变更记录
    changes_made: List[CodeChange] = field(default_factory=list)

    # 修复结果
    is_fixed: bool = False
    fix_attempts: int = 0  # 总共尝试次数
    final_error: Optional[str] = None  # 最终错误（如果未修复）

    # 元数据
    fixed_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "original_code": self.original_code,
            "fixed_code": self.fixed_code,
            "changes_made": [change.to_dict() for change in self.changes_made],
            "is_fixed": self.is_fixed,
            "fix_attempts": self.fix_attempts,
            "final_error": self.final_error,
            "fixed_at": self.fixed_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FixedCode":
        """从字典创建"""
        changes_made = []
        for change_data in data.get("changes_made", []):
            changes_made.append(CodeChange.from_dict(change_data))

        return cls(
            original_code=data.get("original_code", ""),
            fixed_code=data.get("fixed_code", ""),
            changes_made=changes_made,
            is_fixed=data.get("is_fixed", False),
            fix_attempts=data.get("fix_attempts", 0),
            final_error=data.get("final_error"),
            fixed_at=datetime.datetime.fromisoformat(data["fixed_at"]) if data.get("fixed_at") else datetime.datetime.now(),
        )


@dataclass
class TestCase:
    """
    测试用例

    用于验证修复后的代码是否正确
    """

    test_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # 测试输入
    input_data: Dict[str, Any] = field(default_factory=dict)

    # 预期输出
    expected_output: Optional[Dict[str, Any]] = None
    expected_error: Optional[str] = None  # 如果预期抛出错误

    # 测试结果
    actual_output: Optional[Dict[str, Any]] = None
    actual_error: Optional[str] = None
    passed: bool = False

    # 元数据
    test_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "test_id": self.test_id,
            "input_data": self.input_data,
            "expected_output": self.expected_output,
            "expected_error": self.expected_error,
            "actual_output": self.actual_output,
            "actual_error": self.actual_error,
            "passed": self.passed,
            "test_name": self.test_name,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestCase":
        """从字典创建"""
        return cls(
            test_id=data.get("test_id") or str(uuid.uuid4()),
            input_data=data.get("input_data", {}),
            expected_output=data.get("expected_output"),
            expected_error=data.get("expected_error"),
            actual_output=data.get("actual_output"),
            actual_error=data.get("actual_error"),
            passed=data.get("passed", False),
            test_name=data.get("test_name"),
        )


@dataclass
class FixVerification:
    """
    修复验证结果

    验证修复后的代码是否可用
    """

    verification_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # 验证结果
    is_valid: bool = False  # 修复是否有效
    confidence: float = 0.0  # 验证置信度 (0.0-1.0)

    # 测试结果
    test_cases: List[TestCase] = field(default_factory=list)
    passed_tests: int = 0
    total_tests: int = 0

    # 验证信息
    verification_message: str = ""
    warnings: List[str] = field(default_factory=list)

    # 对比分析
    improvement_score: float = 0.0  # 改进评分 (-1.0 到 1.0)
    regression_detected: bool = False  # 是否检测到回归

    # 元数据
    verified_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    llm_model_used: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "verification_id": self.verification_id,
            "is_valid": self.is_valid,
            "confidence": self.confidence,
            "test_cases": [test.to_dict() for test in self.test_cases],
            "passed_tests": self.passed_tests,
            "total_tests": self.total_tests,
            "verification_message": self.verification_message,
            "warnings": self.warnings,
            "improvement_score": self.improvement_score,
            "regression_detected": self.regression_detected,
            "verified_at": self.verified_at.isoformat(),
            "llm_model_used": self.llm_model_used,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FixVerification":
        """从字典创建"""
        test_cases = []
        for test_data in data.get("test_cases", []):
            test_cases.append(TestCase.from_dict(test_data))

        return cls(
            verification_id=data.get("verification_id") or str(uuid.uuid4()),
            is_valid=data.get("is_valid", False),
            confidence=data.get("confidence", 0.0),
            test_cases=test_cases,
            passed_tests=data.get("passed_tests", 0),
            total_tests=data.get("total_tests", 0),
            verification_message=data.get("verification_message", ""),
            warnings=data.get("warnings", []),
            improvement_score=data.get("improvement_score", 0.0),
            regression_detected=data.get("regression_detected", False),
            verified_at=datetime.datetime.fromisoformat(data["verified_at"]) if data.get("verified_at") else datetime.datetime.now(),
            llm_model_used=data.get("llm_model_used"),
        )

    def calculate_success_rate(self) -> float:
        """计算测试成功率"""
        if self.total_tests == 0:
            return 0.0
        return self.passed_tests / self.total_tests
