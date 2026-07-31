"""Bridge approved improvement proposals into durable task graphs.

The approve endpoint only changes proposal state and schedules this bridge.  The
bridge owns the side effects: isolated worktree creation, task graph creation,
scheduler kicking, parent-side auto adjudication for synthetic self-improvement
graphs, and proposal result write-back.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.business.self_improvement.proposal_workspace import (
    ProposalWorkspaceError,
    create_worktree,
    remove_worktree,
)
from src.business.task_collaboration.models import DeliveredStatus, TaskStatus, WaitingOn
from src.data.repos.assistant_task_adjudication_repository import (
    AssistantTaskAdjudicationRepository,
)
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository
from src.utils.events import emit
from src.utils.proposal_policy import SELF_IMPROVEMENT_SESSION_PREFIX

logger = logging.getLogger(__name__)
_EXECUTION_STATUSES = {TaskStatus.COMPLETED, TaskStatus.ABANDONED, TaskStatus.CANCELLED}
# ⚠️ 这一行的 "failed" 是 **improvement_proposals** 的状态，跟上一行的 task 状态无关，
# 两个状态机恰好共用同一个词。改 TaskStatus 时不要顺手改到这里。
_RETENTION_CANDIDATE_STATUSES = ["done", "failed", "rejected"]
_SAFE_TEXT_FALLBACK = "详情不可用"
# 永久失败 worktree 的回收重试上限（026 M6）：超过即强清 DB 元数据停止无界重试。
_PRUNE_FAILURE_COUNTS: dict[str, int] = {}
_PRUNE_FAILURE_THRESHOLD = 3

_PLANNER_CAPABILITIES = ["read_file", "search_files"]
_IMPLEMENTER_CAPABILITIES = [
    "read_file",
    "write_file",
    "edit_file",
    "apply_patch",
    "search_files",
]
_TEST_CAPABILITIES = ["exec", "read_file", "search_files"]
_IMPLEMENTATION_SLOT_LOCK = threading.Lock()


@dataclass(frozen=True)
class SchedulerKickResult:
    status: Literal["started", "unavailable", "failed"]
    safe_error: str | None = None


def trigger_implementation_async(proposal_id: str) -> None:
    """Start proposal implementation in a daemon thread."""
    thread = threading.Thread(
        target=trigger_implementation,
        args=(proposal_id,),
        daemon=True,
        name=f"proposal-implementation-{proposal_id[:18]}",
    )
    thread.start()


def trigger_implementation(proposal_id: str) -> None:
    """Trigger approved proposal implementation.  Exceptions are logged only."""
    try:
        with _IMPLEMENTATION_SLOT_LOCK:
            _trigger_implementation_inner(proposal_id)
    except Exception:
        logger.exception("trigger_implementation failed for proposal %s", proposal_id)


def run_proposal_recovery_cycle(limit: int = 20) -> int:
    """Recover self-improvement proposal graphs and drain the approved queue.

    This is intentionally deterministic and non-LLM: it kicks an available graph
    scheduler, auto-accepts executor results for synthetic proposal graphs, and
    maps terminal graph status back to proposal status.
    """
    handled = 0
    handled += _process_in_progress_proposals(limit=limit)
    handled += _kick_next_approved_if_idle()
    handled += _prune_retained_worktrees()
    return handled


def _trigger_implementation_inner(proposal_id: str) -> None:
    with ImprovementProposalRepository() as proposal_repo:
        proposal = proposal_repo.get_by_id(proposal_id)
        if proposal is None:
            logger.warning("Proposal %s not found, skip", proposal_id)
            return
        if proposal.status != "approved":
            logger.info("Proposal %s status=%s, skip", proposal_id, proposal.status)
            return
        if proposal_repo.has_in_progress():
            logger.info(
                "Proposal %s: another implementation in progress, deferring",
                proposal_id,
            )
            return

    worktree_path: Path | None = None
    try:
        worktree_path, branch_name = create_worktree(proposal_id)
        graph_id = _build_implementation_graph(
            proposal_id=proposal_id,
            worktree_path=worktree_path,
            proposal=proposal,
        )
    except ProposalWorkspaceError as exc:
        logger.warning(
            "Proposal %s implementation pre-flight failed (isolated workspace)",
            proposal_id,
            exc_info=True,
        )
        _mark_failed(proposal_id, error=_safe_error(exc), tests_passed=None)
        return
    except Exception as exc:
        logger.warning(
            "Proposal %s implementation pre-flight failed (workspace/graph build)",
            proposal_id,
            exc_info=True,
        )
        if worktree_path is not None:
            _remove_worktree_quietly(worktree_path)
        _mark_failed(proposal_id, error=_safe_error(exc), tests_passed=None)
        return

    try:
        with ImprovementProposalRepository() as proposal_repo:
            row = proposal_repo.mark_in_progress(
                proposal_id,
                graph_id=graph_id,
                worktree_path=str(worktree_path),
                branch_name=branch_name,
            )
    except Exception as exc:
        logger.warning(
            "Proposal %s mark_in_progress failed; cancelling graph and cleaning worktree",
            proposal_id,
            exc_info=True,
        )
        _cancel_graph_quietly(proposal_id, graph_id)
        _remove_worktree_quietly(worktree_path)
        _mark_failed(proposal_id, error=_safe_error(exc), tests_passed=None)
        return
    if row is None:
        # CAS 失败（并发抢占/状态已变）：cancel 刚建的孤儿 graph + mark_failed 打破
        # recovery 重入 + 删 worktree。不得留孤儿 graph 或保持 approved（026 C4）。
        _cancel_graph_quietly(proposal_id, graph_id)
        _remove_worktree_quietly(worktree_path)
        _mark_failed(
            proposal_id,
            error="mark_in_progress CAS lost; graph cancelled",
            tests_passed=None,
        )
        return

    _emit_changed(row, change_type="in_progress")
    kick = _start_graph(graph_id)
    if kick.status == "failed":
        _mark_failed(
            proposal_id,
            error=kick.safe_error or "task graph scheduler failed to start",
            tests_passed=None,
        )
        return
    if kick.status == "unavailable":
        logger.warning(
            "GraphScheduler not available for graph %s; proposal %s will be "
            "recovered by the background proposal job",
            graph_id,
            proposal_id,
        )


def _build_implementation_graph(
    *,
    proposal_id: str,
    worktree_path: Path,
    proposal: Any,
) -> str:
    """Build a planner -> implementer -> test task graph."""
    from src.business.task_collaboration.service import TaskCollaborationService

    from src.business.self_improvement.proposal_context import (
        format_proposal_finding_text,
    )

    session_id = _proposal_session_id(proposal_id)
    worktree = str(worktree_path)
    # finding 块（问题/证据/建议/严重度/类型/用户补充）单一来源：proposal_context（028 D3）
    finding_block = format_proposal_finding_text(proposal, include_outcome=False)
    guard_block = (
        "\n\n安全边界：只能在隔离 worktree 内修改源码、测试或文档；不得修改 "
        "src/business/self_improvement、src/business/task_collaboration、src-tauri、"
        "legacy/startup 入口、本地配置、数据库、依赖目录或生成产物；命令执行只用于测试、"
        "lint、format check 或 typecheck。"
    )

    service = TaskCollaborationService()
    result = service.build_task_graph(
        session_id=session_id,
        nodes=[
            {
                "nodeId": f"{proposal_id}_plan",
                "title": f"规划改进：{proposal.what}",
                "description": (
                    f"为改进提案「{proposal.what}」制定代码实施计划。\n\n"
                    f"{finding_block}"
                    f"{guard_block}\n\n"
                    "只输出计划和风险点，不执行修改。"
                ),
                "assigneeHint": "ephemeral_subagent",
                "capabilityScope": _PLANNER_CAPABILITIES,
                "workspaceRoot": worktree,
            },
            {
                "nodeId": f"{proposal_id}_implement",
                "title": f"实施改进：{proposal.what}",
                "description": (
                    f"按照规划实施改进提案「{proposal.what}」。\n\n"
                    f"{finding_block}"
                    f"{guard_block}\n\n"
                    "完成后交给验证节点运行测试。"
                ),
                "assigneeHint": "ephemeral_subagent",
                "capabilityScope": _IMPLEMENTER_CAPABILITIES,
                "workspaceRoot": worktree,
            },
            {
                "nodeId": f"{proposal_id}_test",
                "title": f"验证改进：{proposal.what}",
                "description": (
                    f"在隔离 worktree 中验证改进提案「{proposal.what}」。\n\n"
                    "优先运行相关后端 pytest 或前端 test/lint/typecheck；如范围不明确，"
                    "运行最小必要的回归测试并报告命令和结果。"
                ),
                "assigneeHint": "ephemeral_subagent",
                "capabilityScope": _TEST_CAPABILITIES,
                "workspaceRoot": worktree,
            },
        ],
        dependencies=[
            {"from": f"{proposal_id}_plan", "to": f"{proposal_id}_implement"},
            {"from": f"{proposal_id}_implement", "to": f"{proposal_id}_test"},
        ],
    )
    return result["graphId"]


def _start_graph(graph_id: str) -> SchedulerKickResult:
    """Kick GraphScheduler via blinker event, matching assistant_tools pattern.

    Returns ``unavailable`` when the scheduler singleton is not installed,
    preserving the pre-emit contract that callers depend on.

    直接调用 scheduler.start_graph() 而非仅 emit，确保调用方获得确定性结果。
    emit 仍用于其他解耦路径（assistant_tools / recovery）。
    """
    try:
        from src.business.task_collaboration.graph_scheduler import get_graph_scheduler

        scheduler = get_graph_scheduler()
        if scheduler is None:
            return SchedulerKickResult("unavailable")
        scheduler.start_graph(graph_id)
        return SchedulerKickResult("started")
    except Exception as exc:
        logger.exception("start_graph failed for %s", graph_id)
        return SchedulerKickResult("failed", _safe_error(exc))


def _kick_or_fail(proposal: Any, graph_id: str) -> tuple[SchedulerKickResult, bool]:
    """Kick the scheduler; if it reports failure, mark the proposal failed.

    Returns ``(kick, handled)`` where ``handled`` is True when ``_mark_failed``
    transitioned the proposal (CAS hit). Centralises the kick→failed mapping so
    the "task graph scheduler failed to start" wording and the tests_passed=None
    invariant live in one place (026 simplify O2).
    """
    kick = _start_graph(graph_id)
    if kick.status == "failed":
        handled = bool(
            _mark_failed(
                proposal.id,
                error=kick.safe_error or "task graph scheduler failed to start",
                tests_passed=None,
            )
        )
        return kick, handled
    return kick, False


def _process_in_progress_proposals(*, limit: int) -> int:
    handled = 0
    with ImprovementProposalRepository() as repo:
        proposals = repo.list_by_status("in_progress")[:limit]

    for proposal in proposals:
        try:
            if not proposal.graph_id:
                if _mark_failed(
                    proposal.id,
                    error="in-progress proposal has no task graph",
                    tests_passed=None,
                ):
                    handled += 1
                continue

            # Kick scheduler to advance any stalled nodes.  Self-improvement
            # graphs have no real parent assistant, so pending adjudications
            # must be drained by this recovery job regardless of scheduler
            # availability; otherwise executor results can leave the proposal
            # permanently in_progress.
            kick, failed_handled = _kick_or_fail(proposal, proposal.graph_id)
            if failed_handled:
                handled += 1
            if kick.status == "failed":
                continue

            handled += _auto_decide_pending_adjudications(proposal.graph_id)
            if kick.status == "unavailable":
                # Try one more kick after auto-decide in case the scheduler has
                # since been assembled.  The started path intentionally avoids
                # a second kick; the scheduler callback from decide() is enough
                # to continue normal graph progress.
                kick, failed_handled = _kick_or_fail(proposal, proposal.graph_id)
                if failed_handled:
                    handled += 1
                if kick.status == "failed":
                    continue
            if _write_back_terminal_graph(proposal):
                handled += 1
        except Exception as exc:
            logger.warning(
                "Failed to recover in-progress proposal %s",
                proposal.id,
                exc_info=True,
            )
            if _mark_failed(
                proposal.id,
                error=_safe_error(exc),
                tests_passed=None,
            ):
                handled += 1
    return handled


def _auto_decide_pending_adjudications(graph_id: str) -> int:
    with AssistantTaskAdjudicationRepository() as repo:
        pending = repo.list_pending_for_graph(graph_id)
    if not pending:
        return 0

    from src.business.task_collaboration.adjudication import TaskAdjudicationService

    count = 0
    for item in pending:
        decision = "accepted" if item.delivered_status == DeliveredStatus.DONE else "abandoned"
        try:
            TaskAdjudicationService().decide(
                adjudication_id=item.adjudication_id,
                decision=decision,
                decided_by="self_improvement",
            )
            count += 1
        except LookupError:
            continue
        except Exception:
            logger.warning(
                "Failed to auto-decide self-improvement adjudication %s",
                item.adjudication_id,
                exc_info=True,
            )
    return count


def _identify_test_nodes(snapshot: Any, execution_nodes: list[Any]) -> list[Any]:
    """识别测试节点：按图结构（出度为 0 的叶子），与标题文案解耦（026 I3）。

    proposal_bridge 建的 ``plan -> implement -> test`` 图中 test 是唯一叶子。
    标题文案漂移（本地化、改写）不应让已通过的提案静默 failed，故优先用
    结构定位。多叶子或无叶子（异常结构）时 fallback 到 ``验证改进`` 标题
    前缀，保持向后兼容防御。
    """
    successor_sources = {edge.source_task_id for edge in snapshot.edges}
    leaf_nodes = [t for t in execution_nodes if t.task_id not in successor_sources]
    if len(leaf_nodes) == 1:
        return leaf_nodes
    return [t for t in execution_nodes if t.title.startswith("验证改进")]


def _write_back_terminal_graph(proposal: Any) -> bool:
    from src.business.task_collaboration.service import TaskCollaborationService

    snapshot = TaskCollaborationService().get_graph_snapshot(
        session_id=_proposal_session_id(proposal.id),
        graph_id=proposal.graph_id,
    )
    if snapshot is None:
        return bool(
            _mark_failed(
                proposal.id,
                error="task graph snapshot not found",
                tests_passed=None,
            )
        )

    execution_nodes = [task for task in snapshot.tasks if task.parent_task_id is not None]
    if not execution_nodes:
        return False

    non_terminal = [task for task in execution_nodes if task.status not in _EXECUTION_STATUSES]
    if non_terminal:
        # self_improvement:<id> 是合成 session——**没有用户在看，也没有父助理在等**。
        # 所以等人的节点在这里不是"还在进行中"，是永久死锁：每个 recovery tick 重新
        # 判定一次、静默返回、一行日志都不留，而 _kick_next_approved_if_idle 看到
        # has_in_progress() 就不再启动下一个提案——整个已批准队列被队头堵死。
        stuck = [
            task
            for task in non_terminal
            if task.waiting_on in (WaitingOn.USER.value, WaitingOn.ASSISTANT.value)
        ]
        if stuck:
            return bool(
                _mark_failed(
                    proposal.id,
                    error=(
                        "实施图卡在等人处理的节点，而自我改进会话没有用户也没有父助理："
                        + ", ".join(f"{t.task_id}({t.suspend_reason})" for t in stuck[:5])
                    ),
                    tests_passed=None,
                )
            )
        # 只剩 waiting_on=system（会自动重试）或还在跑的节点 → 正常等待
        return False

    test_nodes = _identify_test_nodes(snapshot, execution_nodes)
    test_results = [_structured_test_result_for_task(task) for task in test_nodes]
    tests_have_structured_results = bool(test_nodes) and all(
        result.get("known") for result in test_results
    )
    tests_passed = tests_have_structured_results and all(
        bool(result.get("tests_passed")) for result in test_results
    )
    all_completed = all(task.status == TaskStatus.COMPLETED for task in execution_nodes)
    summary = _terminal_summary(
        proposal=proposal,
        graph_id=snapshot.graph_id,
        execution_nodes=execution_nodes,
        tests_passed=tests_passed,
        test_results=test_results,
    )
    if all_completed and tests_passed:
        with ImprovementProposalRepository() as repo:
            row = repo.mark_done(
                proposal.id,
                tests_passed=True,
                summary=_safe_public_text(summary),
            )
        if row is not None:
            _emit_changed(row, change_type="done")
            return True
        return False

    if all_completed and not tests_have_structured_results:
        error = "test node completed without structured test result"
        result_tests_passed: bool | None = None
    elif all_completed and not tests_passed:
        error = "test node reported failing tests"
        result_tests_passed = False
    else:
        error = "implementation task graph finished with abandoned or cancelled nodes"
        result_tests_passed = None

    return bool(
        _mark_failed(
            proposal.id,
            error=error,
            tests_passed=result_tests_passed,
            summary=summary,
        )
    )


def _kick_next_approved_if_idle() -> int:
    with ImprovementProposalRepository() as repo:
        if repo.has_in_progress():
            return 0
        next_proposal = repo.get_oldest_by_status("approved")
    if next_proposal is None:
        return 0
    trigger_implementation(next_proposal.id)
    return 1


def _prune_retained_worktrees() -> int:
    try:
        from src.data.unified_config import get_unified_config

        keep = get_unified_config().get_self_improvement_proposals_worktree_retention_max()
    except Exception:
        logger.warning(
            "Failed to read proposal worktree retention config; fallback to keep=10",
            exc_info=True,
        )
        keep = 10

    with ImprovementProposalRepository() as repo:
        candidates = repo.list_with_worktrees(statuses=_RETENTION_CANDIDATE_STATUSES)
    stale = candidates[keep:]
    removed = 0
    for proposal in stale:
        if not proposal.worktree_path:
            continue
        try:
            remove_worktree(proposal.worktree_path)
            _PRUNE_FAILURE_COUNTS.pop(proposal.id, None)
            with ImprovementProposalRepository() as repo:
                repo.clear_worktree_location(proposal.id)
            removed += 1
        except Exception:
            failures = _PRUNE_FAILURE_COUNTS.get(proposal.id, 0) + 1
            _PRUNE_FAILURE_COUNTS[proposal.id] = failures
            if failures >= _PRUNE_FAILURE_THRESHOLD:
                # 永久失败(权限锁/盘只读/路径损坏)不应每个 tick 无界重试 warn;
                # 超阈值后强清 DB 元数据停止重试,目录残留需手动处理(FR-019)。
                logger.error(
                    "Force-clearing worktree metadata for proposal %s after %d failed "
                    "prune attempts; filesystem directory may need manual cleanup",
                    proposal.id,
                    failures,
                )
                with ImprovementProposalRepository() as repo:
                    repo.clear_worktree_location(proposal.id)
                _PRUNE_FAILURE_COUNTS.pop(proposal.id, None)
                removed += 1
            else:
                logger.warning(
                    "Failed to prune proposal worktree proposal=%s (attempt %d/%d)",
                    proposal.id,
                    failures,
                    _PRUNE_FAILURE_THRESHOLD,
                    exc_info=True,
                )
    return removed


def _mark_failed(
    proposal_id: str,
    *,
    error: str,
    tests_passed: bool | None = None,
    summary: str | None = None,
) -> Any | None:
    with ImprovementProposalRepository() as repo:
        row = repo.mark_failed(
            proposal_id,
            error=_safe_public_text(error),
            tests_passed=tests_passed,
            summary=_safe_public_text(summary),
        )
    if row is not None:
        _emit_changed(row, change_type="failed")
    return row


def _emit_changed(row: Any, *, change_type: str) -> None:
    try:
        emit(
            "improvement_proposal_changed",
            proposal_id=row.id,
            source_review_id=row.source_review_id,
            status=row.status,
            severity=row.severity,
            change_type=change_type,
        )
    except Exception:
        logger.warning(
            "Failed to emit improvement_proposal_changed for proposal %s",
            row.id,
            exc_info=True,
        )


def _terminal_summary(
    *,
    proposal: Any,
    graph_id: str,
    execution_nodes: list[Any],
    tests_passed: bool,
    test_results: list[dict[str, Any]] | None = None,
) -> str:
    status_counts: dict[str, int] = {}
    for task in execution_nodes:
        status_counts[str(task.status)] = status_counts.get(str(task.status), 0) + 1
    test_summary = "; ".join(
        str(item.get("summary") or "") for item in (test_results or []) if item.get("summary")
    )
    return (
        f"Task graph {graph_id} reached terminal state; "
        f"tests_passed={tests_passed}; "
        f"status_counts={status_counts}; "
        f"branch={proposal.branch_name or 'unknown'}"
        + (f"; test_summary={test_summary}" if test_summary else "")
    )


def _structured_test_result_for_task(task: Any) -> dict[str, Any]:
    """Read deterministic test evidence for a completed proposal test node."""
    if task.status != TaskStatus.COMPLETED:
        return {
            "known": True,
            "tests_passed": False,
            "summary": f"{task.title}: status={task.status}",
        }

    from src.data.repos.assistant_task_attempt_repository import (
        AssistantTaskAttemptRepository,
    )

    with AssistantTaskAttemptRepository() as attempts:
        rows = attempts.list_for_task(task.task_id)

    for attempt in reversed(rows):
        parsed = _parse_test_result_ref(attempt.result_ref)
        if parsed is not None:
            return parsed
        executor_session_id = _executor_session_id_from_ref(attempt.result_ref)
        if executor_session_id:
            parsed = _latest_exec_test_result(executor_session_id)
            if parsed is not None:
                return parsed

    return {
        "known": False,
        "tests_passed": False,
        "summary": f"{task.title}: missing structured test result",
    }


def _parse_test_result_ref(value: str | None) -> dict[str, Any] | None:
    obj = _json_object(value)
    if obj is None:
        return None
    candidates = [
        obj,
        obj.get("testResult") if isinstance(obj.get("testResult"), dict) else None,
        obj.get("payload") if isinstance(obj.get("payload"), dict) else None,
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if "tests_passed" in candidate:
            return _test_result(_parse_passed_flag(candidate["tests_passed"]), candidate)
        if "testsPassed" in candidate:
            return _test_result(_parse_passed_flag(candidate["testsPassed"]), candidate)
        exec_result = _exec_envelope_result(candidate)
        if exec_result is not None:
            return exec_result
    return None


def _executor_session_id_from_ref(value: str | None) -> str | None:
    obj = _json_object(value)
    if obj is None:
        return None
    raw = obj.get("executor_session_id") or obj.get("executorSessionId")
    text = str(raw or "").strip()
    return text or None


def _latest_exec_test_result(session_id: str) -> dict[str, Any] | None:
    from src.data.repos.message_repository import MessageRepository

    with MessageRepository() as messages:
        rows = messages.get_all(session_id)
    for message in reversed(rows):
        if message.role != "tool" or message.tool_name != "exec":
            continue
        obj = _json_object(message.content)
        if obj is None:
            continue
        parsed = _exec_envelope_result(obj)
        if parsed is not None:
            return parsed
    return None


def _exec_envelope_result(obj: dict[str, Any]) -> dict[str, Any] | None:
    if obj.get("tool") != "exec":
        return None
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    exit_code = payload.get("exitCode")
    outcome = str(obj.get("outcome") or "")
    if isinstance(exit_code, bool):
        exit_code = int(exit_code)
    if isinstance(exit_code, int):
        passed = outcome == "success" and exit_code == 0
        return {
            "known": True,
            "tests_passed": passed,
            "summary": f"exec exitCode={exit_code} outcome={outcome or 'unknown'}",
        }
    if outcome:
        return {
            "known": True,
            "tests_passed": False,
            "summary": f"exec produced no exitCode; outcome={outcome}",
        }
    return None


def _test_result(passed: bool | None, obj: dict[str, Any]) -> dict[str, Any]:
    if passed is None:
        return {
            "known": False,
            "tests_passed": False,
            "summary": "structured tests_passed value is not a recognized boolean",
        }
    # Summary comes from untrusted LLM output — sanitize immediately.
    summary = _safe_public_text(
        str(
            obj.get("safe_summary")
            or obj.get("summary")
            or obj.get("message")
            or f"structured tests_passed={passed}"
        )
    )
    return {
        "known": True,
        "tests_passed": passed,
        "summary": summary,
    }


def _parse_passed_flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "pass", "passed"}:
            return True
        if normalized in {"0", "false", "no", "n", "fail", "failed"}:
            return False
    return None


def _json_object(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _proposal_session_id(proposal_id: str) -> str:
    return f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}"


def _safe_error(exc: Exception) -> str:
    """Normalize and sanitize exception text for public-facing error fields."""
    text = " ".join(str(exc).split())
    if not text:
        text = exc.__class__.__name__
    return _safe_public_text(text)


def _safe_public_text(text: str | None) -> str:
    if not text:
        return ""
    try:
        from src.business.self_improvement.proposal_service import (
            sanitize_proposal_public_text,
        )

        return sanitize_proposal_public_text(text) or ""
    except Exception:
        logger.error("Proposal public text sanitizer unavailable", exc_info=True)
        return _SAFE_TEXT_FALLBACK


def _cancel_graph_quietly(proposal_id: str, graph_id: str) -> None:
    try:
        from src.business.task_collaboration.service import TaskCollaborationService

        TaskCollaborationService().cancel_graph(
            session_id=_proposal_session_id(proposal_id),
            graph_id=graph_id,
        )
    except Exception:
        logger.warning(
            "Failed to cancel orphan graph %s for proposal %s",
            graph_id,
            proposal_id,
            exc_info=True,
        )


def _remove_worktree_quietly(path: Path | str) -> None:
    try:
        remove_worktree(path)
    except Exception:
        logger.warning("Failed to cleanup worktree after bridge failure", exc_info=True)
