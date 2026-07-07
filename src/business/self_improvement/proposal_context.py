"""改进提案 finding 上下文序列化——单一来源（028 D3）。

proposal_bridge 的任务图节点 description 与提案讨论会话的开场消息都从这里取
finding 文本，字段增减只改这一处，防止两条路径漂移。守卫测试断言两处消费方
均 import 本模块。
"""

from __future__ import annotations

from typing import Any

_SEVERITY_LABELS = {
    "high": "高",
    "med": "中",
    "medium": "中",
    "low": "低",
}


def format_proposal_finding_text(proposal: Any, *, include_outcome: bool = False) -> str:
    """把提案 finding 序列化为可读文本块。

    Args:
        proposal: ImprovementProposal ORM 行或具备同名属性的对象。
        include_outcome: True 时追加实施分支/结果摘要/测试结论/失败原因
            （仅讨论开场使用；bridge 在审批后实施前调用，无 outcome 可言）。

    Returns:
        多行文本；空字段整行省略，宁缺毋滥。
    """
    lines: list[str] = []
    what = (getattr(proposal, "what", None) or "").strip()
    evidence = (getattr(proposal, "evidence", None) or "").strip()
    suggestion = (getattr(proposal, "suggestion", None) or "").strip()
    severity = (getattr(proposal, "severity", None) or "").strip()
    finding_type = (getattr(proposal, "finding_type", None) or "").strip()
    supplement = (getattr(proposal, "user_supplement", None) or "").strip()

    if what:
        lines.append(f"问题：{what}")
    if evidence:
        lines.append(f"证据：{evidence}")
    if suggestion:
        lines.append(f"建议：{suggestion}")
    if severity:
        lines.append(f"严重度：{_SEVERITY_LABELS.get(severity, severity)}")
    if finding_type:
        lines.append(f"类型：{finding_type}")
    if supplement:
        lines.append(f"用户补充说明：{supplement}")

    if include_outcome:
        branch_name = (getattr(proposal, "branch_name", None) or "").strip()
        result_summary = (getattr(proposal, "result_summary", None) or "").strip()
        result_tests_passed = getattr(proposal, "result_tests_passed", None)
        error = (getattr(proposal, "error", None) or "").strip()
        outcome_lines: list[str] = []
        if branch_name:
            outcome_lines.append(f"实施分支：{branch_name}")
        if result_summary:
            outcome_lines.append(f"实施结果：{result_summary}")
        if result_tests_passed is not None:
            outcome_lines.append(f"测试结论：{'通过' if result_tests_passed else '未通过'}")
        if error:
            outcome_lines.append(f"失败原因：{error}")
        if outcome_lines:
            lines.append("")
            lines.extend(outcome_lines)

    return "\n".join(lines)


def format_discussion_opening_message(proposal: Any) -> str:
    """讨论会话的开场 assistant 消息（markdown，SafeMarkdown 渲染）。"""
    status = (getattr(proposal, "status", None) or "").strip()
    status_labels = {
        "pending_review": "待审批",
        "approved": "已批准",
        "in_progress": "正在实施",
        "done": "已完成",
        "failed": "实施失败",
        "rejected": "已拒绝",
    }
    status_line = status_labels.get(status, status)
    finding_block = format_proposal_finding_text(proposal, include_outcome=True)
    return (
        f"## 改进提案讨论\n\n"
        f"这条对话用于讨论下面这条改进提案（当前状态：{status_line}）。"
        f"你可以追问这条提案为什么会生成、证据是否充分，以及复盘提示词是否需要收紧；"
        f"需要分析来源时，助理可以读取该提案的来源复盘和相关消息片段。"
        f"批准或拒绝仍在提案页面完成。\n\n"
        f"{finding_block}"
    )
