"""
Self-improvement business logic sub-package.

Public services:
- SelfImprovementAuditService: audit log and metric recording
- SafetyGovernor: rate limits, convergence detection, and rollback triggers
- ExecutionReflectionService: post-task reflection and avoidance rule management
- PromptEffectivenessTracker: collects prompt effectiveness metrics
- PromptOptimizationService: generates and evaluates prompt supplements
- ToolGapDetector: detects missing tools, repeated patterns, high-iteration sessions
- ToolFixProposalService: manages lifecycle of tool fix proposals
"""

from src.business.self_improvement.audit_service import SelfImprovementAuditService
from src.business.self_improvement.execution_reflection_service import ExecutionReflectionService
from src.business.self_improvement.prompt_optimization_service import (
    PromptEffectivenessTracker,
    PromptOptimizationService,
)
from src.business.self_improvement.safety_governor import SafetyGovernor
from src.business.self_improvement.tool_gap_detector import (
    ToolFixProposalService,
    ToolGapDetector,
)

__all__ = [
    "SelfImprovementAuditService",
    "SafetyGovernor",
    "ExecutionReflectionService",
    "PromptEffectivenessTracker",
    "PromptOptimizationService",
    "ToolGapDetector",
    "ToolFixProposalService",
]
