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

from src.business.task_collaboration.graph_terminal import compute_graph_terminal_state
from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    TaskEdgeType,
    TaskGraphSnapshot,
    TaskStatus,
    safe_preview,
)

_DELIVERABLE_BRIEFING_MAX_CHARS = 6000

# 暂停原因 → 一句人话。主助理拿到的原本是兜底值 "result"，零信息量。
_PAUSE_HEADLINE = {
    "budget_exhausted": "撞到轮次上限，工作已完整保留",
    "waiting_system": "停下来等派活方处理",
    "interrupted": "上次异常中断，工作保留但最后一步的结果未知",
    "user_stop": "用户按了停",
    "waiting_user": "在等用户答复",
}

# 每种停法对应的可选动作。这是 advisory：最终选哪条仍由主助理判断，
# 但至少不能像原来那样把「认可/打回/放弃」摆给一个什么都没交的活。
_PAUSE_ACTIONS = {
    "budget_exhausted": (
        "可用 continue_subagent 追加预算续跑（工作完整保留，不必从头做）；"
        "也可以改任务书重派、跳过该节点、或放弃它。"
    ),
    "waiting_system": "可用 continue_subagent 续跑，或改任务书重派。",
    "interrupted": (
        "可用 continue_subagent 续跑——续跑指令会提示执行体先核对上次中断处的现场，"
        "再往下做。"
    ),
}
_PAUSE_ACTIONS_FALLBACK = "可用 continue_subagent 续跑，或决定跳过 / 放弃该节点。"


def _sep(lines: list[str]) -> None:
    """在已有内容后插入空行分隔。"""
    if lines:
        lines.append("")


def _is_paused_entry(entry: dict) -> bool:
    return str(entry.get("taskStatus") or "") == TaskStatus.SUSPENDED


def _render_paused(entry: dict) -> list[str]:
    """暂停回流的渲染：说清停在哪、还剩什么、下一步能做什么。"""
    task_id = entry.get("taskId") or "unknown"
    reason = str(entry.get("suspendReason") or entry.get("eventType") or "")
    line = f"- 任务 {task_id}：{_PAUSE_HEADLINE.get(reason, '已暂停')}"
    used, cap = entry.get("iterationsUsed"), entry.get("maxIterations")
    if used is not None and cap is not None:
        line = f"{line}（已用 {used} / 上限 {cap} 轮）"
    summary = entry.get("safeSummary")
    if summary:
        line = f"{line} — {summary}"

    lines = [line]
    subagent_id = entry.get("subagentId")
    if subagent_id:
        lines.append(f"  执行体 {subagent_id}")
    lines.append("  " + _PAUSE_ACTIONS.get(reason, _PAUSE_ACTIONS_FALLBACK))
    return lines


def build_reentry_briefing(
    entries: list[dict],
    *,
    snapshot: TaskGraphSnapshot | None = None,
) -> str:
    """把回流 ``entries`` + 可选 ``snapshot`` 组装成主助理续跑轮的 briefing 文本。

    entry 分四类渲染，前两类靠 ``taskStatus`` 区分、后两类靠 ``eventType``：
    - 普通结果（交了东西）：``taskId`` / ``deliveredStatus`` / ``safeSummary`` /
      可选 ``adjudicationId``，失败时附 ``healingActions`` / ``safeRecoveryHint``；
    - **暂停待推进**（``taskStatus == suspended``，什么都没交）：``suspendReason`` /
      可选 ``iterationsUsed`` / ``maxIterations`` / ``subagentId``。这一类**必须与交付
      分开**——让主助理对一个没交东西的活做"认可/打回/放弃"是错的引导，它该做的是
      决定怎么推进（续跑 / 改任务书 / 跳过 / 放弃）；
    - ``needs_review``（024，高风险需确认）：``taskId`` / ``safeSummary``；
    - ``task_question``：``questionId`` / ``questionKind`` / ``safeSummary``。
    空 entries 且无 snapshot 返回"暂无新结果"提示。

    snapshot 非空时追加「任务图进度」「自愈动作清单」「节点 todo 概览」段；None 时退化
    为现状行为（向后兼容现有非图任务回流）。
    """
    if not entries and snapshot is None:
        return "你之前派发的子任务暂无新结果。"

    _special = ("task_question", "needs_review")
    # 暂停回流与交付回流必须分开渲染：暂停的活**什么都没交**，让主助理去"认可/打回/
    # 放弃"是错的引导——它该做的是决定怎么推进（续跑/改任务书/跳过/放弃）。混在一起
    # 时主助理看到的是「任务 X：result」这种零信息量的行，还会被提示去放弃整张图。
    paused_entries = [
        entry
        for entry in entries
        if entry.get("eventType") not in _special and _is_paused_entry(entry)
    ]
    result_entries = [
        entry
        for entry in entries
        if entry.get("eventType") not in _special and not _is_paused_entry(entry)
    ]
    question_entries = [entry for entry in entries if entry.get("eventType") == "task_question"]
    needs_review_entries = [entry for entry in entries if entry.get("eventType") == "needs_review"]
    adjudications_by_id = {
        item.adjudication_id: item
        for item in (snapshot.adjudications if snapshot is not None else [])
    }
    lines: list[str] = []

    # === 现有 result 段 ===
    if result_entries:
        lines.append("你之前派发的子任务有结果回流，请检查并决定（认可/打回/放弃）：")
    for entry in result_entries:
        task_id = entry.get("taskId") or "unknown"
        status = entry.get("deliveredStatus") or entry.get("event") or "result"
        summary = entry.get("safeSummary") or ""
        if str(status) == "done":
            deliverable, deliverable_truncated, result_reference_id = _resolve_deliverable(
                entry, adjudications_by_id
            )
        else:
            deliverable, deliverable_truncated = "", False
            result_reference_id = entry.get("resultReferenceId") or entry.get("adjudicationId")
        line = f"- 任务 {task_id}：{status}"
        if not deliverable and summary:
            line = f"{line} — {summary}"
        lines.append(line)
        adjudication_id = entry.get("adjudicationId")
        if adjudication_id:
            lines.append(f"  裁定ID {adjudication_id}：可调用 decide_task_adjudication 工具决策。")
        if deliverable:
            lines.extend(
                _render_deliverable(
                    deliverable,
                    truncated=deliverable_truncated,
                    result_reference_id=result_reference_id,
                )
            )
        elif adjudication_id:
            lines.append(
                "  如需查看已保存的任务结果，请调用 "
                f'load_task_result(adjudication_id="{adjudication_id}")；'
                "不要把 taskId 传给 load_reference。"
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

    # === 暂停待推进段 ===
    if paused_entries:
        _sep(lines)
        lines.append("以下子任务停下来了（未交付成果），需要你决定怎么推进：")
    for entry in paused_entries:
        lines.extend(_render_paused(entry))

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
        lines.append(
            "  可调用 decide_task_adjudication 工具裁定：accepted=放行执行，abandoned=放弃该节点。"
        )

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


def _resolve_deliverable(entry: dict, adjudications_by_id: dict) -> tuple[str, bool, str | None]:
    """Return the result text that the parent assistant can use directly."""
    result_reference_id = entry.get("resultReferenceId") or entry.get("adjudicationId")
    raw = entry.get("deliverablePreview")
    truncated = bool(entry.get("deliverableTruncated"))
    if not raw and result_reference_id:
        adjudication = adjudications_by_id.get(result_reference_id)
        raw = getattr(adjudication, "raw_result_ref", None) if adjudication is not None else None
    text = str(raw or "")
    if not text:
        return "", truncated, result_reference_id
    if len(text) > _DELIVERABLE_BRIEFING_MAX_CHARS:
        return (
            safe_preview(text, max_chars=_DELIVERABLE_BRIEFING_MAX_CHARS),
            True,
            result_reference_id,
        )
    return text, truncated, result_reference_id


def _render_deliverable(
    deliverable: str,
    *,
    truncated: bool,
    result_reference_id: str | None,
) -> list[str]:
    lines = [
        "  【子任务最终交付物】",
        "  该内容已由执行体压缩整理；若足以回答用户，请裁定认可后直接汇报，"
        "不要重新抓取或重做同一子任务。",
    ]
    for line in deliverable.splitlines() or [""]:
        lines.append(f"  {line}")
    if truncated:
        if result_reference_id:
            lines.append(
                "  交付物已截断；需要更多内容时调用 "
                f'load_task_result(adjudication_id="{result_reference_id}")。'
            )
        else:
            lines.append("  交付物已截断；若信息不足，请打回返工，而不是自行重做。")
    return lines


def _render_graph_progress(snapshot: TaskGraphSnapshot) -> str:
    """从 snapshot 计算任务图进度段（确定性，非 LLM）。"""
    tasks = snapshot.tasks
    if not tasks:
        return ""

    # 根容器节点（parent_task_id is None，标题 "Assistant request"）代表整个用户请求，
    # 在图收口前永远停在 pending_dispatch。把它算进进度会输出
    # "completed=0, running=1, pending=1, 就绪可派节点：Assistant request"，
    # 误导主助理以为还有节点在跑、不敢把结果呈现给用户。
    # 与 graph_scheduler._advance 一致，统计/判定只看真实执行节点。
    real_tasks = [t for t in tasks if t.parent_task_id is not None]
    if not real_tasks:
        return ""

    # 单次遍历：统计状态、收集各类节点
    status_counts = Counter(t.status for t in real_tasks)
    needs_review_tasks: list[str] = []  # 普通结果待裁定（requires_review）
    confirmation_tasks: list[str] = []  # 高风险需确认（requires_confirmation）
    ready_tasks: list[str] = []
    failed_tasks: list[str] = []
    completed_ids: set[str] = set()

    # 收集 dependency 边的 target → source 映射（用于就绪判定）
    dep_sources: dict[str, list[str]] = {}
    for edge in snapshot.edges:
        if edge.type == TaskEdgeType.DEPENDENCY:
            dep_sources.setdefault(edge.target_task_id, []).append(edge.source_task_id)

    for t in real_tasks:
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

    # 判断全图是否完成——统一复用 task_collaboration 的公共终态函数。
    all_terminal, all_completed = compute_graph_terminal_state(
        real_tasks,
        terminal_statuses=TERMINAL_TASK_STATUSES,
        completed_status=TaskStatus.COMPLETED,
    )

    lines: list[str] = []
    lines.append("【任务图进度】")

    # 状态统计
    parts = [
        f"completed={status_counts.get(TaskStatus.COMPLETED, 0)}",
        f"running={status_counts.get(TaskStatus.RUNNING, 0)}",
        f"pending={status_counts.get(TaskStatus.PENDING_DISPATCH, 0)}",
        f"需裁定={len(needs_review_tasks)}",
        f"failed={status_counts.get(TaskStatus.FAILED, 0)}",
    ]
    lines.append(f"- 图 {snapshot.graph_id} 共 {len(real_tasks)} 节点：{', '.join(parts)}")

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
    """渲染自愈动作清单段（advisory，CC-008）。

    显示文案从 dispatcher._HEALING_ACTION_HINTS 统一读取，与 dispatcher 的动作候选集
    保持单一来源；新增动作只需在 dispatcher 常量中同时添加 action_name + display_hint。
    """
    from src.business.task_collaboration.dispatcher import _HEALING_ACTION_HINTS

    lines = [f"  【节点 {task_id} 失败自愈选项】（选一个，用 decide_task_adjudication 落定）"]
    for action in actions:
        hint = _HEALING_ACTION_HINTS.get(action, action)
        lines.append(f"  - {hint}")
    lines.append("  - 兜不住/需用户定方向 → ask_user_question 升级用户")
    return "\n".join(lines)


def _render_todo_overview(snapshot: TaskGraphSnapshot) -> str:
    """列出进行中/暂停/待裁定节点，供主助理感知当前图状态。

    todo 子步骤详情（TaskSnapshot 暂无 todo_summary 字段）未接入：当前只列节点名，
    避免「（执行中，暂无子步骤信息）」这类占位噪声；接入 todo_summary 后再补每节点进度。
    """
    active_tasks = [
        t
        for t in snapshot.tasks
        if t.parent_task_id is not None
        and (t.status in (TaskStatus.RUNNING, TaskStatus.SUSPENDED) or t.requires_review)
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
        if not entry.get("adjudicationId") or entry["adjudicationId"] in pending_ids
    ]
