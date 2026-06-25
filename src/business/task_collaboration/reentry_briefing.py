"""Construct the parent-side reentry briefing injected into the main assistant.

把回流 entries（普通结果 / question / needs_review）+ 可选 graph snapshot 组装成主助理续跑轮的 program-role prompt。纯函数，无 IO，便于单测。

Prompt 措辞（认可/打回/放弃、``decide_task_adjudication`` 工具指针）直接驱动父侧裁定状态机，
因此归 business 层；UI adapter（``desktop_api/assistant_runtime``）只转发预构造的 briefing
字符串，不再持有 prompt 构造逻辑。

024 扩展：snapshot 参数注入「下一步建议 / 自愈动作清单 / todo 概览」文本段（DEC-H）。
snapshot 由调用方传入，briefing 不做 IO，保持纯函数可单测。
"""

from __future__ import annotations

from collections import Counter

from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    TaskGraphSnapshot,
    TaskStatus,
)


def _sep(lines: list[str]) -> None:
    """在已有内容后插入空行分隔。"""
    if lines:
        lines.append("")


def build_reentry_briefing(
    entries: list[dict],
    *,
    snapshot: TaskGraphSnapshot | None = None,
) -> str:
    """把回流 ``entries`` + 可选 ``snapshot`` 组装成主助理续跑轮的 briefing 文本。

    entry 按 ``eventType`` 分流：
    - 普通结果：``taskId`` / ``deliveredStatus`` / ``safeSummary`` / 可选 ``adjudicationId``，
      失败时附 ``healingActions`` / ``safeRecoveryHint``；
    - ``needs_review``（024，高风险需确认）：``taskId`` / ``safeSummary``；
    - ``task_question``：``questionId`` / ``questionKind`` / ``safeSummary``。
    空 entries 且无 snapshot 返回"暂无新结果"提示。

    snapshot 非空时追加「任务图进度」「自愈动作清单」「节点 todo 概览」段；None 时退化
    为现状行为（向后兼容现有非图任务回流）。
    """
    if not entries and snapshot is None:
        return "你之前派发的子任务暂无新结果。"

    result_entries = [entry for entry in entries if entry.get("eventType") not in ("task_question", "needs_review")]
    question_entries = [entry for entry in entries if entry.get("eventType") == "task_question"]
    needs_review_entries = [entry for entry in entries if entry.get("eventType") == "needs_review"]
    lines: list[str] = []

    # === 现有 result 段 ===
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
        # 024: 失败 entry 附自愈动作清单
        healing_actions = entry.get("healingActions")
        if healing_actions:
            lines.append(_render_healing_actions(entry.get("taskId", ""), healing_actions))
        safe_hint = entry.get("safeRecoveryHint")
        if safe_hint:
            lines.append(f"  安全提示：{safe_hint}")

    if result_entries:
        lines.append(
            "若这些结果显示本次用户请求已无法继续完成（多条路径都失败、无法绕过），"
            "可调用 abandon_request_graph 工具放弃整张任务图（根任务失败，触发安全失败卡）。"
        )

    # === 现有 question 段 ===
    if question_entries:
        _sep(lines)
        lines.append("你之前派发的子任务正在等待你答复，请处理后让它继续：")
    for entry in question_entries:
        question_id = entry.get("questionId") or "unknown"
        kind = entry.get("questionKind") or "clarification"
        summary = entry.get("safeSummary") or "子任务请求派活方补充信息。"
        lines.append(f"- 任务 {entry.get('taskId')} 提问 {question_id}（{kind}）：{summary}")
        lines.append("  可调用 answer_task_question 工具答复；能力授予仅限你的当前任务授权子集。")

    # === 024: 需确认节点段（DEC-D）===
    if needs_review_entries:
        _sep(lines)
        lines.append("以下节点标记为需确认（高风险/不可逆），请裁定是否执行：")
    for entry in needs_review_entries:
        task_id = entry.get("taskId", "unknown")
        summary = entry.get("safeSummary", "节点标记为需确认，请裁定是否执行。")
        lines.append(f"- 任务 {task_id}：{summary}")
        lines.append("  可调用 decide_task_adjudication 工具裁定：accepted=放行执行，abandoned=放弃该节点。")

    # === 024: 任务图进度段（确定性，由 snapshot 计算）===
    if snapshot is not None:
        graph_segment = _render_graph_progress(snapshot)
        if graph_segment:
            _sep(lines)
            lines.append(graph_segment)

        # 024: 节点 todo 概览段
        todo_segment = _render_todo_overview(snapshot)
        if todo_segment:
            _sep(lines)
            lines.append(todo_segment)

    return "\n".join(lines)


def _render_graph_progress(snapshot: TaskGraphSnapshot) -> str:
    """从 snapshot 计算任务图进度段（确定性，非 LLM）。"""
    tasks = snapshot.tasks
    if not tasks:
        return ""

    # 单次遍历：统计状态、收集各类节点
    status_counts = Counter(t.status for t in tasks)
    needs_review_tasks: list[str] = []  # 普通结果待裁定（requires_review）
    confirmation_tasks: list[str] = []  # 高风险需确认（requires_confirmation）
    ready_tasks: list[str] = []
    failed_tasks: list[str] = []
    completed_ids: set[str] = set()

    # 收集 dependency 边的 target → source 映射（用于就绪判定）
    dep_sources: dict[str, list[str]] = {}
    for edge in snapshot.edges:
        if edge.type == "dependency":
            dep_sources.setdefault(edge.target_task_id, []).append(edge.source_task_id)

    for t in tasks:
        if t.status == TaskStatus.COMPLETED:
            completed_ids.add(t.task_id)
        if t.requires_confirmation:
            confirmation_tasks.append(t.title or t.task_id)
        elif t.requires_review:
            needs_review_tasks.append(t.title or t.task_id)
        if t.status == TaskStatus.PENDING_DISPATCH:
            sources = dep_sources.get(t.task_id, [])
            is_ready = not sources or all(s in completed_ids for s in sources)
            if is_ready:
                ready_tasks.append(t.title or t.task_id)
        if t.status == TaskStatus.FAILED:
            failed_tasks.append(t.title or t.task_id)

    # 判断全图是否完成
    all_terminal = all(t.status in TERMINAL_TASK_STATUSES for t in tasks)
    all_completed = all(t.status == TaskStatus.COMPLETED for t in tasks)

    lines: list[str] = []
    lines.append("【任务图进度】")

    # 状态统计
    parts = [
        f"completed={status_counts.get('completed', 0)}",
        f"running={status_counts.get('running', 0)}",
        f"pending={status_counts.get('pending_dispatch', 0)}",
        f"需裁定={len(needs_review_tasks)}",
        f"failed={status_counts.get('failed', 0)}",
    ]
    lines.append(f"- 图 {snapshot.graph_id} 共 {len(tasks)} 节点：{', '.join(parts)}")

    if ready_tasks:
        lines.append(f"- 就绪可派节点：{', '.join(ready_tasks[:5])}")

    if confirmation_tasks:
        lines.append(f"- 需确认/高风险（执行前请放行）：{', '.join(confirmation_tasks[:5])}")
    if needs_review_tasks:
        lines.append(f"- 待你裁定（认可/打回/放弃）：{', '.join(needs_review_tasks[:5])}")

    if failed_tasks:
        lines.append(f"- 失败节点：{', '.join(failed_tasks[:5])}")

    if all_completed:
        lines.append("- 全图状态：已全部完成，请向用户汇报最终结果。")
    elif all_terminal:
        lines.append("- 全图状态：已全部终止（含失败/取消），请决定后续处理。")

    return "\n".join(lines)


def _render_healing_actions(task_id: str, actions: list[str]) -> str:
    """渲染自愈动作清单段（advisory，CC-008）。"""
    action_map = {
        "retry": "重试该节点 → decide(decision=\"returned\")",
        "swap_executor": "换执行器重试 → 改 assignee 后 decide(decision=\"returned\")",
        "adjust_input": "调整输入后重做 → decide(decision=\"returned\", instruction=\"…\")",
        "skip": "跳过该节点 → mutate_task_graph(skip_node)（若可容忍，下游继续）",
        "replan": "改图绕过 → mutate_task_graph(add_node/remove_dependency)",
        "abandon": "放弃该分支 → decide(decision=\"abandoned\")",
    }
    lines = [f"  【节点 {task_id} 失败自愈选项】（选一个，用 decide_task_adjudication 落定）"]
    for action in actions:
        hint = action_map.get(action, action)
        lines.append(f"  - {hint}")
    lines.append("  - 兜不住/需用户定方向 → ask_user_question 升级用户")
    return "\n".join(lines)


def _render_todo_overview(snapshot: TaskGraphSnapshot) -> str:
    """列出进行中/暂停/待裁定节点，供主助理感知当前图状态。

    todo 子步骤详情（TaskSnapshot 暂无 todo_summary 字段）未接入：当前只列节点名，
    避免「（执行中，暂无子步骤信息）」这类占位噪声；接入 todo_summary 后再补每节点进度。
    """
    active_tasks = [
        t for t in snapshot.tasks
        if t.status in ("running", "suspended") or t.requires_review
    ]
    if not active_tasks:
        return ""

    lines = ["【进行中节点】"]
    for t in active_tasks[:5]:
        lines.append(f"- {t.title or t.task_id}")

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
