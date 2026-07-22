"""Agent tools for owner-bound external coding sessions."""

from __future__ import annotations

import logging

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import error_json, make_tool_schema, to_json
from src.business.external_coding import ExternalCodingSessionService

logger = logging.getLogger(__name__)


START_EXTERNAL_CODING_SESSION_SCHEMA = make_tool_schema(
    name="start_external_coding_session",
    description=(
        "启动一个 owner-bound 外部 coding session（Claude Code 或 Codex CLI）。"
        "必须绑定 ownerType/ownerId；默认先产出 PLAN.md，由你审查后再批准实现。"
    ),
    properties={
        "ownerType": {"type": "string", "enum": ["task", "workflow"]},
        "ownerId": {"type": "string", "description": "任务 ID 或工作流 ID；不得为空"},
        "objective": {"type": "string", "description": "派给外部 coding agent 的目标"},
        "context": {"type": "string", "description": "约束、上下文、验收口径"},
        "toolPreference": {
            "type": "string",
            "enum": ["auto", "claude_code", "codex_cli"],
            "description": "默认 auto，按 quota/可用性选择",
        },
        "launchMode": {
            "type": "string",
            "enum": ["headless", "interactive"],
            "description": "默认 headless；interactive 也必须依赖 artifact 完成",
        },
        "targetBranch": {"type": "string", "description": "可选目标分支"},
        "targetWorktreePath": {
            "type": "string",
            "description": (
                "要改动的目标仓库绝对路径；必须指向一个可用的 git 仓库，不填即拒绝。"
                "若目标就是 Exemplar 自身仓库，也必须显式写出其绝对路径。"
            ),
        },
    },
    required=["ownerType", "ownerId", "objective", "targetWorktreePath"],
)

INSPECT_EXTERNAL_CODING_SESSION_SCHEMA = make_tool_schema(
    name="inspect_external_coding_session",
    description=(
        "查看外部 coding session 的当前状态、PLAN/RESULT 预览、attempt、quota 和可用动作。"
        "若 reviewSkippedReason 非空，最终汇报必须明确说明结果尚未经过独立 review/test。"
    ),
    properties={"codingSessionId": {"type": "string"}},
    required=["codingSessionId"],
)

RECORD_EXTERNAL_CODING_REVIEW_SCHEMA = make_tool_schema(
    name="record_external_coding_review_outcome",
    description=(
        "记录外部 coding 结果是否已由派活 agent 独立 review 和 test。"
        "任一项跳过时必须提供 skippedReason，并在最终汇报中明确说明。"
    ),
    properties={
        "codingSessionId": {"type": "string"},
        "independentlyReviewed": {"type": "boolean"},
        "independentlyTested": {"type": "boolean"},
        "skippedReason": {"type": "string"},
    },
    required=["codingSessionId", "independentlyReviewed", "independentlyTested"],
)

DECIDE_EXTERNAL_CODING_PLAN_SCHEMA = make_tool_schema(
    name="decide_external_coding_plan",
    description="审查外部 agent 写出的 PLAN.md 后，批准、打回或要求澄清。批准后才允许实现。",
    properties={
        "codingSessionId": {"type": "string"},
        "decision": {"type": "string", "enum": ["approved", "rejected", "clarification_requested"]},
        "feedback": {"type": "string", "description": "打回或澄清时必须给出安全反馈"},
    },
    required=["codingSessionId", "decision"],
)

RESUME_EXTERNAL_CODING_SESSION_SCHEMA = make_tool_schema(
    name="resume_external_coding_session",
    description="续跑同一个外部 coding session；不得切换 Claude/Codex 工具。",
    properties={
        "codingSessionId": {"type": "string"},
        "instruction": {"type": "string"},
        "phase": {"type": "string", "enum": ["plan", "implement"]},
    },
    required=["codingSessionId"],
)

ABANDON_EXTERNAL_CODING_SESSION_SCHEMA = make_tool_schema(
    name="abandon_external_coding_session",
    description="放弃一个外部 coding session，并保留审计状态。",
    properties={"codingSessionId": {"type": "string"}, "reason": {"type": "string"}},
    required=["codingSessionId", "reason"],
)

ESCALATE_TO_USER_EXTERNAL_CODING_SESSION_SCHEMA = make_tool_schema(
    name="escalate_to_user_external_coding_session",
    description=(
        "将中断的 coding session 升级给用户处理。" "只有 agent 判断中断无法内部解决时才调用。"
    ),
    properties={
        "codingSessionId": {"type": "string"},
        "reason": {"type": "string", "description": "为什么需要用户介入"},
    },
    required=["codingSessionId", "reason"],
)

ANALYZE_EXTERNAL_CODING_MERGE_SCHEMA = make_tool_schema(
    name="analyze_external_coding_merge",
    description="对已完成 coding session 做合并前 dirty/conflict 分析；不会执行 merge。",
    properties={
        "codingSessionId": {"type": "string"},
        "targetBranch": {"type": "string"},
        "targetWorktreePath": {"type": "string"},
    },
    required=["codingSessionId", "targetBranch", "targetWorktreePath"],
)

MERGE_EXTERNAL_CODING_SESSION_SCHEMA = make_tool_schema(
    name="merge_external_coding_session",
    description="由 Exemplar 执行外部 coding session 的合并。非低风险 merge 必须记录 agentDecision。",
    properties={
        "codingSessionId": {"type": "string"},
        "mergeRecordId": {"type": "string"},
        "agentDecision": {"type": "string"},
    },
    required=["codingSessionId", "mergeRecordId"],
)

ROLLBACK_EXTERNAL_CODING_PLAN_SCHEMA = make_tool_schema(
    name="plan_external_coding_rollback",
    description="根据用户意图生成这次 coding session 的受控回滚方案；不直接执行高风险回滚。",
    properties={
        "codingSessionId": {"type": "string"},
        "intentSummary": {"type": "string"},
    },
    required=["codingSessionId", "intentSummary"],
)

CONFIRM_EXTERNAL_CODING_ROLLBACK_SCHEMA = make_tool_schema(
    name="confirm_external_coding_rollback",
    description="确认并执行之前生成的回滚方案。reset_hard 策略必须由用户确认。",
    properties={
        "codingSessionId": {"type": "string"},
        "rollbackId": {"type": "string"},
        "confirmedBy": {
            "type": "string",
            "enum": ["agent", "user"],
            "description": "确认方；reset_hard 必须为 user",
        },
    },
    required=["codingSessionId", "rollbackId"],
)


def _run(tool_name: str, fn) -> str:
    try:
        return to_json(fn())
    except (LookupError, ValueError, PermissionError) as exc:
        return error_json(str(exc))
    except Exception:
        logger.error("[%s] failed", tool_name, exc_info=True)
        return error_json("外部 coding session 工具执行失败，请稍后重试。")


def create_external_coding_tools(
    *,
    session_id: str | None = None,
    bound_task_id: str | None = None,
) -> list[ToolDefinition]:
    def _service() -> ExternalCodingSessionService:
        return ExternalCodingSessionService()

    def start_external_coding_session(
        ownerType: str = "task",
        ownerId: str = "",
        objective: str = "",
        context: str = "",
        toolPreference: str = "auto",
        launchMode: str = "headless",
        targetBranch: str = "",
        targetWorktreePath: str = "",
    ) -> str:
        def invoke():
            effective_owner_type, effective_owner_id = _resolve_start_owner(ownerType, ownerId)
            return _start(
                ownerType=effective_owner_type,
                ownerId=effective_owner_id,
                objective=objective,
                context=context,
                toolPreference=toolPreference,
                launchMode=launchMode,
                targetBranch=targetBranch,
                targetWorktreePath=targetWorktreePath,
            )

        return _run(
            "start_external_coding_session",
            invoke,
        )

    def _start(**kwargs):
        with _service() as service:
            return service.start_session(
                session_id=session_id,
                owner_type=kwargs["ownerType"],
                owner_id=kwargs["ownerId"],
                objective=kwargs["objective"],
                context=kwargs.get("context") or "",
                tool_preference=kwargs.get("toolPreference") or "auto",
                launch_mode=kwargs.get("launchMode") or "headless",
                target_branch=kwargs.get("targetBranch") or None,
                target_worktree_path=kwargs.get("targetWorktreePath") or None,
            )

    def inspect_external_coding_session(codingSessionId: str) -> str:
        return _run(
            "inspect_external_coding_session",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.refresh_session(codingSessionId),
            ),
        )

    def decide_external_coding_plan(
        codingSessionId: str,
        decision: str,
        feedback: str = "",
    ) -> str:
        return _run(
            "decide_external_coding_plan",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.decide_plan(
                    coding_session_id=codingSessionId,
                    decision=decision,
                    decided_by="agent",
                    feedback=feedback,
                ),
            ),
        )

    def record_external_coding_review_outcome(
        codingSessionId: str,
        independentlyReviewed: bool,
        independentlyTested: bool,
        skippedReason: str = "",
    ) -> str:
        return _run(
            "record_external_coding_review_outcome",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.record_review_outcome(
                    coding_session_id=codingSessionId,
                    independently_reviewed=independentlyReviewed,
                    independently_tested=independentlyTested,
                    skipped_reason=skippedReason,
                ),
            ),
        )

    def resume_external_coding_session(
        codingSessionId: str,
        instruction: str = "",
        phase: str = "",
    ) -> str:
        return _run(
            "resume_external_coding_session",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.resume_session(
                    coding_session_id=codingSessionId,
                    instruction=instruction,
                    phase=phase or None,
                ),
            ),
        )

    def abandon_external_coding_session(codingSessionId: str, reason: str) -> str:
        return _run(
            "abandon_external_coding_session",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.abandon_session(
                    coding_session_id=codingSessionId,
                    reason=reason,
                ),
            ),
        )

    def escalate_to_user_external_coding_session(codingSessionId: str, reason: str) -> str:
        return _run(
            "escalate_to_user_external_coding_session",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.escalate_to_user(
                    coding_session_id=codingSessionId,
                    reason=reason,
                ),
            ),
        )

    def analyze_external_coding_merge(
        codingSessionId: str,
        targetBranch: str,
        targetWorktreePath: str,
    ) -> str:
        return _run(
            "analyze_external_coding_merge",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.analyze_merge(
                    coding_session_id=codingSessionId,
                    target_branch=targetBranch,
                    target_worktree_path=targetWorktreePath,
                ),
            ),
        )

    def merge_external_coding_session(
        codingSessionId: str,
        mergeRecordId: str,
        agentDecision: str = "",
    ) -> str:
        return _run(
            "merge_external_coding_session",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.merge_session(
                    coding_session_id=codingSessionId,
                    merge_record_id=mergeRecordId,
                    agent_decision=agentDecision,
                ),
            ),
        )

    def plan_external_coding_rollback(codingSessionId: str, intentSummary: str) -> str:
        return _run(
            "plan_external_coding_rollback",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.create_rollback_plan(
                    coding_session_id=codingSessionId,
                    intent_summary=intentSummary,
                ),
            ),
        )

    def confirm_external_coding_rollback(
        codingSessionId: str,
        rollbackId: str,
        confirmedBy: str = "agent",
    ) -> str:
        return _run(
            "confirm_external_coding_rollback",
            lambda: _with_owned_service(
                codingSessionId,
                lambda service: service.confirm_rollback(
                    coding_session_id=codingSessionId,
                    rollback_id=rollbackId,
                    confirmed_by=confirmedBy,
                ),
            ),
        )

    def _resolve_start_owner(owner_type: str, owner_id: str) -> tuple[str, str]:
        supplied_type = (owner_type or "").strip()
        supplied_id = (owner_id or "").strip()
        if not bound_task_id:
            raise PermissionError("external coding session actions require a bound task owner")
        if supplied_type != "task" or (supplied_id and supplied_id != bound_task_id):
            raise PermissionError("external coding owner must match the bound task")
        return "task", bound_task_id

    def _with_owned_service(coding_session_id: str, callback):
        if not bound_task_id:
            raise PermissionError("external coding session actions require a bound task owner")
        with _service() as service:
            service.require_owner(
                coding_session_id,
                owner_type="task",
                owner_id=bound_task_id,
            )
            return callback(service)

    return [
        ToolDefinition(
            name="start_external_coding_session",
            schema=START_EXTERNAL_CODING_SESSION_SCHEMA,
            handler=start_external_coding_session,
        ),
        ToolDefinition(
            name="inspect_external_coding_session",
            schema=INSPECT_EXTERNAL_CODING_SESSION_SCHEMA,
            handler=inspect_external_coding_session,
        ),
        ToolDefinition(
            name="decide_external_coding_plan",
            schema=DECIDE_EXTERNAL_CODING_PLAN_SCHEMA,
            handler=decide_external_coding_plan,
        ),
        ToolDefinition(
            name="record_external_coding_review_outcome",
            schema=RECORD_EXTERNAL_CODING_REVIEW_SCHEMA,
            handler=record_external_coding_review_outcome,
        ),
        ToolDefinition(
            name="resume_external_coding_session",
            schema=RESUME_EXTERNAL_CODING_SESSION_SCHEMA,
            handler=resume_external_coding_session,
        ),
        ToolDefinition(
            name="abandon_external_coding_session",
            schema=ABANDON_EXTERNAL_CODING_SESSION_SCHEMA,
            handler=abandon_external_coding_session,
        ),
        ToolDefinition(
            name="escalate_to_user_external_coding_session",
            schema=ESCALATE_TO_USER_EXTERNAL_CODING_SESSION_SCHEMA,
            handler=escalate_to_user_external_coding_session,
        ),
        ToolDefinition(
            name="analyze_external_coding_merge",
            schema=ANALYZE_EXTERNAL_CODING_MERGE_SCHEMA,
            handler=analyze_external_coding_merge,
        ),
        ToolDefinition(
            name="merge_external_coding_session",
            schema=MERGE_EXTERNAL_CODING_SESSION_SCHEMA,
            handler=merge_external_coding_session,
        ),
        ToolDefinition(
            name="plan_external_coding_rollback",
            schema=ROLLBACK_EXTERNAL_CODING_PLAN_SCHEMA,
            handler=plan_external_coding_rollback,
        ),
        ToolDefinition(
            name="confirm_external_coding_rollback",
            schema=CONFIRM_EXTERNAL_CODING_ROLLBACK_SCHEMA,
            handler=confirm_external_coding_rollback,
        ),
    ]
