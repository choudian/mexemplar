"""Construct the parent-side reentry briefing injected into the main assistant.

把子任务回流结果组装成主助理续跑轮的 program-role prompt。纯函数，无 IO，便于单测。

Prompt 措辞（认可/打回/放弃、``decide_task_adjudication`` 工具指针）直接驱动父侧裁定状态机，
因此归 business 层；UI adapter（``desktop_api/assistant_runtime``）只转发预构造的 briefing
字符串，不再持有 prompt 构造逻辑。
"""

from __future__ import annotations


def build_reentry_briefing(entries: list[dict]) -> str:
    """把回流 ``entries`` 组装成主助理续跑轮的 briefing 文本。

    每个 entry 含 ``taskId`` / ``deliveredStatus`` / ``safeSummary`` / 可选 ``adjudicationId``。
    空列表返回"暂无新结果"提示。
    """
    if not entries:
        return "你之前派发的子任务暂无新结果。"
    result_entries = [entry for entry in entries if entry.get("eventType") != "task_question"]
    question_entries = [entry for entry in entries if entry.get("eventType") == "task_question"]
    lines: list[str] = []
    if result_entries:
        lines.append("你之前派发的子任务有结果回流，请检查并决定（认可/打回/放弃）：")
    for entry in result_entries:
        status = entry.get("deliveredStatus")
        summary = entry.get("safeSummary") or ""
        line = f"- 任务 {entry.get('taskId')}：{status} — {summary}".rstrip()
        lines.append(line)
        adjudication_id = entry.get("adjudicationId")
        if adjudication_id:
            lines.append(
                f"  裁定ID {adjudication_id}：可调用 decide_task_adjudication 工具决策。"
            )
    if result_entries:
        lines.append(
            "若这些结果显示本次用户请求已无法继续完成（多条路径都失败、无法绕过），"
            "可调用 abandon_request_graph 工具放弃整张任务图（根任务失败，触发安全失败卡）。"
        )
    if question_entries:
        if lines:
            lines.append("")
        lines.append("你之前派发的子任务正在等待你答复，请处理后让它继续：")
    for entry in question_entries:
        question_id = entry.get("questionId") or "unknown"
        kind = entry.get("questionKind") or "clarification"
        summary = entry.get("safeSummary") or "子任务请求派活方补充信息。"
        lines.append(f"- 任务 {entry.get('taskId')} 提问 {question_id}（{kind}）：{summary}")
        lines.append("  可调用 answer_task_question 工具答复；能力授予仅限你的当前任务授权子集。")
    return "\n".join(lines)


def filter_pending_entries(entries: list[dict], pending_ids: set[str]) -> list[dict]:
    """剔除已决定的回流条目（``adjudicationId`` 不在 ``pending_ids`` 中）。

    续跑 worker 异常回填后，已在上一次 ``run_agent`` 中 ``decide`` 掉的裁定会残留在队列；
    不过滤会让下次 briefing 再次提示已决定裁定，LLM 调 ``decide_task_adjudication`` 撞
    ``pending adjudication not found``。无 ``adjudicationId`` 的条目保留（防御性，理论上
    所有回流都带 adjudicationId）。保持纯函数定位——调用方（assistant_runtime）负责查
    ``pending_ids`` 并传入，本函数只做过滤，便于单测。
    """
    return [
        entry
        for entry in entries
        if not entry.get("adjudicationId")
        or entry["adjudicationId"] in pending_ids
    ]
