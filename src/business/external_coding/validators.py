"""Semantic Markdown validators for PLAN.md and RESULT.md."""

from __future__ import annotations

import re

from .models import ValidationResult

_PLAN_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "target_restated": ("目标", "需求", "objective", "target", "restatement"),
    "planned_changes": ("计划", "改动", "steps", "changes", "approach"),
    "impact_area": ("影响", "范围", "files", "modules", "impact"),
    "assumptions": ("假设", "非目标", "non-goal", "assumption"),
    "risks": ("风险", "risk"),
    "test_plan": ("测试", "验证", "test"),
    "open_questions": ("问题", "待确认", "question", "unknown"),
    "recommendation": ("建议", "是否继续", "recommend", "proceed"),
}

_RESULT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "status": ("状态", "status", "completed", "done"),
    "summary": ("总结", "摘要", "summary"),
    "changed_files": ("文件", "changed", "files"),
    "deviations": ("偏差", "deviation", "plan"),
    "tests": ("测试", "test"),
    "test_results": ("测试结果", "test result", "passed", "failed"),
    "risks": ("风险", "risk"),
    "follow_ups": ("后续", "follow", "todo"),
    "completion_notes": ("完成备注", "完成说明", "completion note", "notes"),
}


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _validate(text: str | None, requirements: dict[str, tuple[str, ...]]) -> ValidationResult:
    normalized = _normalize(text)
    if len(normalized) < 80:
        return ValidationResult(
            valid=False, missing=list(requirements), warnings=["artifact too short"]
        )
    missing: list[str] = []
    for key, keywords in requirements.items():
        if not any(keyword.lower() in normalized for keyword in keywords):
            missing.append(key)
    return ValidationResult(valid=not missing, missing=missing)


def validate_plan_markdown(text: str | None) -> ValidationResult:
    """Validate semantic coverage without requiring exact heading text."""
    return _validate(text, _PLAN_REQUIREMENTS)


def validate_result_markdown(text: str | None) -> ValidationResult:
    """Validate RESULT.md semantic coverage without requiring exact heading text."""
    return _validate(text, _RESULT_REQUIREMENTS)
