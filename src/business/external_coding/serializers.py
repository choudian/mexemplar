"""Serialization helpers: convert ORM rows to dict responses for the API layer."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from src.business.services.ui_event_safety_service import redact_public_ui_event_text

from .artifacts import preview_markdown, tail_file
from .models import (
    CodingSessionStatus,
    RESUMABLE_CODING_STATUSES,
    TERMINAL_CODING_STATUSES,
)

logger = logging.getLogger(__name__)


def _json_loads_list(value: str | None) -> list[str]:
    try:
        data = json.loads(value or "[]")
    except json.JSONDecodeError:
        logger.warning("Malformed JSON in list field: %s", (value or "")[:100])
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _safe_text(value: str | None, *, max_chars: int = 1200) -> str:
    return redact_public_ui_event_text(
        "externalCoding",
        (value or "")[:max_chars],
        max_preview_chars=max_chars,
    )


def summary_to_dict(row, *, config) -> dict:
    """Build a summary dict from a session ORM row."""
    plan_path = Path(row.plan_path) if row.plan_path else None
    result_path = Path(row.result_path) if row.result_path else None
    return {
        "codingSessionId": row.coding_session_id,
        "sessionId": row.session_id,
        "ownerType": row.owner_type,
        "ownerId": row.owner_id,
        "tool": row.tool,
        "launchMode": row.launch_mode,
        "status": row.status,
        "phase": row.phase,
        "selectedReason": row.selected_reason,
        "quotaState": row.quota_state,
        "worktreePath": row.worktree_path,
        "branchName": row.branch_name,
        "artifactDir": row.artifact_dir,
        "planPreview": preview_markdown(plan_path),
        "resultPreview": preview_markdown(result_path),
        "logTail": None,  # summaries omit log tail; detail_to_dict overrides this
        "lastErrorCategory": row.last_error_category,
        "lastErrorMessage": row.last_error_message,
        "resumeCount": row.resume_count,
        "reviewRecommended": bool(row.review_recommended),
        "reviewSkippedReason": row.review_skipped_reason,
        "createdAt": row.created_at,
        "updatedAt": row.updated_at,
        "completedAt": row.completed_at,
    }


def detail_to_dict(row, *, repo, config) -> dict:
    """Build a detail dict from a session ORM row with sub-collections.

    Composes on top of ``summary_to_dict`` so summary and detail never drift on
    the shared fields; only detail-exclusive collections are added here.
    """
    attempts = repo.list_attempts(row.coding_session_id)
    last_log_path = Path(attempts[-1].log_path) if attempts and attempts[-1].log_path else None

    data = summary_to_dict(row, config=config)
    data["logTail"] = tail_file(
        last_log_path, max_chars=config.get_external_coding_log_tail_chars()
    )
    data["attempts"] = [attempt_to_dict(a) for a in attempts]
    data["quota"] = [quota_to_dict(q) for q in repo.latest_quota_by_tool().values()]
    data["mergeRecords"] = [
        merge_record_to_dict(m) for m in repo.list_merge_records(row.coding_session_id)
    ]
    data["rollbackDecisions"] = [
        rollback_to_dict(r) for r in repo.list_rollback_decisions(row.coding_session_id)
    ]
    data["availableActions"] = available_actions(row)
    data["artifacts"] = {
        "handoff": {
            "path": row.handoff_path,
            "preview": preview_markdown(Path(row.handoff_path)),
        },
        "plan": {
            "path": row.plan_path,
            "preview": preview_markdown(Path(row.plan_path)) if row.plan_path else None,
        },
        "result": {
            "path": row.result_path,
            "preview": preview_markdown(Path(row.result_path)) if row.result_path else None,
        },
    }
    return data


def available_actions(row) -> list[str]:
    """Compute available user/agent actions for a session based on its status."""
    actions: list[str] = ["inspect"]
    if row.status == CodingSessionStatus.PLAN_READY.value:
        actions += ["approve_plan", "reject_plan"]
    if row.status in RESUMABLE_CODING_STATUSES:
        actions.append("resume")
    if row.status == CodingSessionStatus.INTERRUPTED.value:
        actions.append("escalate_to_user")
    if row.status in {
        CodingSessionStatus.COMPLETED.value,
        CodingSessionStatus.MERGE_READY.value,
        CodingSessionStatus.MERGE_BLOCKED.value,
    }:
        actions.append("merge_analysis")
    if row.status in {
        CodingSessionStatus.MERGE_READY.value,
        CodingSessionStatus.MERGE_BLOCKED.value,
    }:
        actions.append("merge")
    if row.status not in TERMINAL_CODING_STATUSES:
        actions.append("abandon")
    if row.status == CodingSessionStatus.MERGED.value:
        actions.append("rollback_plan")
    if row.status == CodingSessionStatus.ROLLBACK_PROPOSED.value:
        actions.append("confirm_rollback")
    return actions


def attempt_to_dict(row) -> dict:
    return {
        "attemptId": row.attempt_id,
        "codingSessionId": row.coding_session_id,
        "phase": row.phase,
        "launchMode": row.launch_mode,
        "commandSummary": row.command_summary,
        "externalSessionRef": row.external_session_ref,
        "status": row.status,
        "pid": row.pid,
        "exitCode": row.exit_code,
        "startedAt": row.started_at,
        "finishedAt": row.finished_at,
        "logPath": row.log_path,
        "logTail": row.log_tail,
        "errorCategory": row.error_category,
        "errorMessage": row.error_message,
    }


def quota_to_dict(row) -> dict:
    return {
        "observationId": row.observation_id,
        "tool": row.tool,
        "state": row.state,
        "source": row.source,
        "confidence": row.confidence,
        "resetAt": row.reset_at,
        "checkedAt": row.checked_at,
        "safeDetail": row.safe_detail,
    }


def merge_record_to_dict(row) -> dict:
    return {
        "mergeRecordId": row.merge_record_id,
        "codingSessionId": row.coding_session_id,
        "targetBranch": row.target_branch,
        "targetWorktreePath": row.target_worktree_path,
        "preMergeHead": row.pre_merge_head,
        "codingBranchHead": row.coding_branch_head,
        "dirtyFiles": _json_loads_list(row.dirty_files_json),
        "changedFiles": _json_loads_list(row.changed_files_json),
        "overlapFiles": _json_loads_list(row.overlap_files_json),
        "conflictRisk": row.conflict_risk,
        "agentDecision": row.agent_decision,
        "status": row.status,
        "mergeCommit": row.merge_commit,
        "error": row.error,
        "createdAt": row.created_at,
        "mergedAt": row.merged_at,
    }


def rollback_to_dict(row) -> dict:
    return {
        "rollbackId": row.rollback_id,
        "codingSessionId": row.coding_session_id,
        "mergeRecordId": row.merge_record_id,
        "intentSummary": row.intent_summary,
        "chosenStrategy": row.chosen_strategy,
        "safeExplanation": _rollback_safe_explanation(row),
        "requiresConfirmation": row.requires_confirmation,
        "confirmedBy": row.confirmed_by,
        "status": row.status,
        "createdAt": row.created_at,
        "appliedAt": row.applied_at,
    }


def _rollback_safe_explanation(row) -> str:
    if row.chosen_strategy == "revert_commit":
        return "确认后会创建一个新的 revert commit，撤销本次 coding session 的 merge commit。"
    if row.chosen_strategy == "reverse_patch":
        return "需要先生成并审查反向补丁；当前确认不会重写 Git 历史。"
    if row.chosen_strategy == "reset_hard":
        return "该策略会重写工作区状态，V1 不支持自动执行。"
    return "需要人工核对仓库状态后完成回滚。"
