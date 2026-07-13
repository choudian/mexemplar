"""System-provided skill compositions that are not user-editable database rows."""

from __future__ import annotations

from src.data.models import SkillComposition, SkillCompositionMember, Tool


EXTERNAL_CODING_COMPOSITION_ID = "comp_builtin_external_coding"
EXTERNAL_CODING_COMPOSITION_NAME = "外部 Coding"

EXTERNAL_CODING_TOOL_CATALOG: tuple[tuple[str, str], ...] = (
    ("start_external_coding_session", "启动外部 Coding session"),
    ("inspect_external_coding_session", "查看外部 Coding session 状态"),
    ("decide_external_coding_plan", "审查外部 Coding 计划"),
    ("record_external_coding_review_outcome", "记录外部 Coding 结果审查"),
    ("resume_external_coding_session", "续跑外部 Coding session"),
    ("abandon_external_coding_session", "放弃外部 Coding session"),
    ("escalate_to_user_external_coding_session", "将中断升级给用户处理"),
    ("analyze_external_coding_merge", "分析外部 Coding 合并风险"),
    ("merge_external_coding_session", "合并外部 Coding 结果"),
    ("plan_external_coding_rollback", "生成外部 Coding 回滚方案"),
    ("confirm_external_coding_rollback", "确认执行外部 Coding 回滚"),
)

EXTERNAL_CODING_TOOL_IDS = frozenset(tool_id for tool_id, _ in EXTERNAL_CODING_TOOL_CATALOG)


def external_coding_composition() -> SkillComposition:
    members = [
        SkillCompositionMember(
            member_id=f"builtin_external_coding_{index}",
            composition_id=EXTERNAL_CODING_COMPOSITION_ID,
            tool_id=tool_id,
            selected_order=index,
            tool=Tool(
                tool_id=tool_id,
                tool_name=description,
                description=description,
                source="builtin",
                status="published",
            ),
        )
        for index, (tool_id, description) in enumerate(EXTERNAL_CODING_TOOL_CATALOG, start=1)
    ]
    return SkillComposition(
        composition_id=EXTERNAL_CODING_COMPOSITION_ID,
        composition_name=EXTERNAL_CODING_COMPOSITION_NAME,
        description="使用 Claude Code 或 Codex CLI 完成受控的外部编码任务。",
        applicability="需要计划审批、执行、审查、合并或回滚的正式编码任务。",
        mode="range",
        status="published",
        assistant_enabled=True,
        recommend_order=False,
        needs_review=False,
        is_builtin=True,
        is_read_only=True,
        trial_supported=False,
        members=members,
    )


def list_builtin_compositions() -> list[SkillComposition]:
    return [external_coding_composition()]
