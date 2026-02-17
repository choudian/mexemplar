"""
工具试用模块 - 错误诊断和自动修复

包含错误诊断、代码修复和修复验证功能
"""

# 数据模型（试用）
from .trial_models import (
    PendingTool,
    PendingToolStatus,
    ToolTrial,
    TrialStatus,
)

# 数据模型（错误诊断）
from .error_diagnosis_models import (
    ErrorDiagnosis,
    ErrorType,
    ErrorSeverity,
    FixStrategy,
    CodeChange,
    FixedCode,
    TestCase,
    FixVerification,
)

# 核心模块（试用）
from .trial_manager import TrialManager
from .trial_repository import PendingToolRepository, ToolTrialRepository

# 核心模块（错误诊断）
from .error_diagnoser import ErrorDiagnoser
from .code_fixer import CodeFixer
from .fix_verifier import FixVerifier

__all__ = [
    # 数据模型（试用）
    "PendingTool",
    "PendingToolStatus",
    "ToolTrial",
    "TrialStatus",
    # 数据模型（错误诊断）
    "ErrorDiagnosis",
    "ErrorType",
    "ErrorSeverity",
    "FixStrategy",
    "CodeChange",
    "FixedCode",
    "TestCase",
    "FixVerification",
    # 核心模块（试用）
    "TrialManager",
    "PendingToolRepository",
    "ToolTrialRepository",
    # 核心模块（错误诊断）
    "ErrorDiagnoser",
    "CodeFixer",
    "FixVerifier",
]
