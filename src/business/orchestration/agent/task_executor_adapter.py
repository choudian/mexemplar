"""TaskAttempt executor adapter：统一任务派发的异步执行器。

把 ``TaskDispatcher.executor_callback``（签名 ``Callable[[str], str|dict|None]``，入参仅
``attempt_id``）接到 DelegationOrchestrator 的同步委派执行接口，
让持久化的 ``TaskAttempt`` 真正在 dispatcher 线程池里被执行，而不是永久停在
``pending_dispatch``。这是 023 V-01「执行链路接通」的核心适配层。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, TYPE_CHECKING

from src.business.agents.config import AgentType
from src.business.agents.delegation_context import prepare_delegated_execution_context
from src.business.task_collaboration.models import SuspendReason

if TYPE_CHECKING:
    from src.business.orchestration.agent.orchestrator import AgentOrchestrator

logger = logging.getLogger(__name__)


class TaskExecutorAdapter:
    """``attempt_id`` → 反查 task → 复用 Orchestrator 委派执行内核 → 映射 done/stuck。

    作为 ``TaskDispatcher.executor_callback`` 注入。dispatcher 在其线程池 worker 里调用
    ``__call__``，同步执行子代理。返回 dict 视为 ``delivered=done``（父侧裁定 accept /
    return / abandon）；抛异常视为 ``delivered=stuck``（交父侧裁定）。
    """

    def __init__(
        self,
        orchestrator: "AgentOrchestrator",
        *,
        orchestrator_factory: Callable[[], "AgentOrchestrator"] | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._orchestrator_factory = orchestrator_factory

    def __call__(self, attempt_id: str) -> dict[str, Any]:
        from src.data.repos import AssistantTaskAttemptRepository, AssistantTaskRepository

        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.get_by_id(attempt_id)
        if attempt is None:
            raise RuntimeError(f"task attempt not found: {attempt_id}")
        with AssistantTaskRepository() as tasks:
            task = tasks.get_task(attempt.task_id)
        if task is None:
            raise RuntimeError(f"task not found for attempt {attempt_id}: {attempt.task_id}")

        parent_session_id = task.owner_session_id or task.session_id
        capability_scope = _parse_capability_scope(task.capability_scope)
        workspace_root = task.workspace_root

        # FR-014/SC-003 fail-closed: proposal executor 必须在有效 improvement worktree
        # 内执行;workspace 丢失/漂移时拒绝派发,不得回退主仓库击穿 blast radius。
        _assert_proposal_executor_workspace_or_raise(parent_session_id, workspace_root)

        executor_orchestrator = self._new_executor_orchestrator()
        try:
            resumed = self._try_resume_from_checkpoint(
                executor_orchestrator,
                task,
                parent_session_id,
                attempt.checkpoint_ref,
            )
            if resumed is not None:
                result = resumed
            elif task.assignee_type == AgentType.SPECIALIST.value:
                result = self._run_specialist(
                    executor_orchestrator,
                    task,
                    parent_session_id,
                    capability_scope,
                    checkpoint_ref=attempt.checkpoint_ref,
                    workspace_root=workspace_root,
                )
            else:
                result = self._run_ephemeral(
                    executor_orchestrator,
                    task,
                    parent_session_id,
                    capability_scope,
                    checkpoint_ref=attempt.checkpoint_ref,
                    workspace_root=workspace_root,
                )
        finally:
            if executor_orchestrator is not self._orchestrator:
                _close_orchestrator_resources(executor_orchestrator)

        return self._map_to_outcome(result)

    def _new_executor_orchestrator(self):
        if self._orchestrator_factory is None:
            return self._orchestrator
        return self._orchestrator_factory()

    def _run_ephemeral(
        self,
        orchestrator,
        task,
        parent_session_id: str,
        tool_whitelist,
        *,
        checkpoint_ref: str | None = None,
        workspace_root: str | None = None,
    ) -> dict:
        return orchestrator.delegation_orchestrator.run_ephemeral_via_delegated_executor(
            parent_session_id=parent_session_id,
            task=task.title,
            execution_context=_execution_context_with_checkpoint(
                task.description or task.title,
                checkpoint_ref,
            ),
            tool_whitelist=tool_whitelist,
            current_task_id=task.task_id,
            workspace_root=workspace_root,
        )

    def _run_specialist(
        self,
        orchestrator,
        task,
        parent_session_id: str,
        tool_whitelist,
        *,
        checkpoint_ref: str | None = None,
        workspace_root: str | None = None,
    ) -> dict:
        from src.data.repos.specialist_repository import SpecialistRepository

        specialist = None
        if task.assignee_id:
            with SpecialistRepository() as repo:
                specialist = repo.get_specialist(task.assignee_id)
        if specialist is None:
            return {"success": False, "message": f"专员不可用: {task.assignee_id}"}
        if not getattr(specialist, "is_active", 1):
            return {"success": False, "message": f"专员已停用: {task.assignee_id}"}
        # 032: 与 _run_ephemeral 对称——task.description(可能含委派时展开的
        # "主对话相关原文"全文)作为 execution_context 传递,不再被静默丢弃;
        # checkpoint 提示随 execution_context 一并进入"补充上下文"段。
        # 统一派发会在 context 为空时把 title 兜底写进 description；专员在 032
        # 之前忽略 description，因此空值和 title 兜底都不得新增“补充上下文”重复。
        effective_context = (
            task.description if task.description and task.description != task.title else ""
        )
        return orchestrator.delegation_orchestrator.run_specialist_via_delegated_executor(
            parent_session_id=parent_session_id,
            specialist=specialist,
            task=task.title,
            execution_context=_execution_context_with_checkpoint(
                effective_context,
                checkpoint_ref,
            ),
            tool_whitelist=tool_whitelist,
            current_task_id=task.task_id,
            workspace_root=workspace_root,
        )

    @staticmethod
    def _try_resume_from_checkpoint(
        orchestrator,
        task,
        parent_session_id: str,
        checkpoint_ref: str | None,
    ) -> dict | None:
        resume_id = _subagent_id_from_checkpoint(checkpoint_ref)
        if not resume_id:
            return None
        try:
            return orchestrator.delegation_orchestrator.continue_subagent(
                parent_session_id=parent_session_id,
                subagent_id=resume_id,
                workspace_root=task.workspace_root,
            )
        except Exception:
            logger.warning(
                "[task attempt] checkpoint resume failed for task %s; falling back to checkpoint context",
                getattr(task, "task_id", ""),
                exc_info=True,
            )
            return None

    @staticmethod
    def _map_to_outcome(result: dict) -> dict[str, Any]:
        # success 视为"交付了一个结果"（done），由父侧裁定 accept/return/abandon。
        # paused/cancelled 是可续暂停，不是交付结果：交给 dispatcher 落为 Task.suspended。
        # 只有"没干完且非暂停"（委派内部错误 / 未完成）才抛异常 → dispatcher 记 stuck。
        if result.get("success"):
            outcome = {"safe_summary": _summary(result.get("result_text") or result.get("message"))}
            # Private bookkeeping for proposal recovery: the public task snapshot
            # stays safe_summary-only, but proposal_bridge can use this session id
            # to inspect deterministic exec tool envelopes from test nodes.
            if result.get("executor_session_id"):
                outcome["executor_session_id"] = result.get("executor_session_id")
            if result.get("result_text"):
                outcome["result_text"] = result.get("result_text")
            return outcome
        if result.get("paused"):
            suspend_reason = (
                SuspendReason.USER_STOP.value
                if result.get("cancelled")
                else result.get("suspend_reason") or SuspendReason.WAITING_SYSTEM.value
            )
            outcome = {
                "task_outcome": "suspended",
                "suspend_reason": suspend_reason,
                "safe_summary": _summary(result.get("safe_summary") or result.get("message")),
                "subagent_id": result.get("subagent_id") or result.get("executor_session_id"),
                "result_type": result.get("result_type"),
            }
            for key in ("reentry_type", "question_id", "question_kind"):
                if result.get(key):
                    outcome[key] = result[key]
            return outcome
        raise RuntimeError(result.get("message") or "委派执行未返回可用结果")


# Proposal executor synthetic session 前缀 — 唯一真实来源在
# ``src.utils.proposal_policy``。判断走 proposal_policy 的
# ``is_proposal_session`` / ``is_improvement_workspace_root_str``，
# 不再保留本地别名。


def _assert_proposal_executor_workspace_or_raise(
    parent_session_id: str | None,
    workspace_root: str | None,
) -> None:
    """Fail-closed: proposal executor 必须在有效 improvement worktree 内执行。

    proposal executor 由 ``self_improvement:<proposal_id>`` synthetic session 标识
    (build_task_graph 注入该 session 到 task graph)。若其 ``task.workspace_root``
    缺失或不像隔离 worktree,说明 workspace 注入链路断裂(数据丢失/漂移)—— 不得
    回退主仓库继续执行,否则路径白名单失效、executor 可改写 self_improvement /
    task_collaboration / src-tauri 等核心路径,击穿 FR-014 blast radius 与 SC-003
    「100% fail-closed」承诺。

    使用 ``src.utils.proposal_policy`` 的低层常量和字符串级判定，
    避免向上 import ``self_improvement`` 违反分层。
    """
    from src.utils.proposal_policy import (
        is_improvement_workspace_root_str,
        is_proposal_session,
    )

    if not is_proposal_session(parent_session_id):
        return  # 非 proposal executor,workspace 不受 FR-014 约束

    if not is_improvement_workspace_root_str(workspace_root):
        raise RuntimeError(
            "proposal executor workspace missing or drifted outside improvement "
            "worktree; fail-closed to preserve FR-014 blast radius"
        )


def _parse_capability_scope(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        legacy = [item.strip() for item in str(raw).split(",") if item.strip()]
        return legacy or None
    if isinstance(parsed, list) and parsed:
        return parsed
    return None


def _summary(text: str | None) -> str:
    text = (text or "").strip()
    # dispatcher 的 _safe_result_summary 会再做一次 safe_preview 脱敏；这里只截断长度。
    return text[:500] if text else "任务已回传结果，等待上级检查。"


def _subagent_id_from_checkpoint(checkpoint_ref: str | None) -> str | None:
    if not checkpoint_ref:
        return None
    try:
        parsed = json.loads(checkpoint_ref)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get("subagent_id") or parsed.get("executor_session_id")
    text = str(value or "").strip()
    return text or None


def _execution_context_with_checkpoint(text: str, checkpoint_ref: str | None) -> str:
    # 普通上下文沿用旧 strip 语义；系统逐字展开块的 provenance 在中间层保留，
    # 只由最终执行体格式化边界消费，避免异步链路二次 strip 原文。
    base = prepare_delegated_execution_context(text)
    if not checkpoint_ref:
        return base
    checkpoint = str(checkpoint_ref).strip()
    if not checkpoint:
        return base
    return f"{base}\n\n恢复检查点:\n{checkpoint}" if base.strip() else f"恢复检查点:\n{checkpoint}"


def _close_orchestrator_resources(orchestrator) -> None:
    """Best-effort close for per-attempt orchestrators created only for thread isolation.

    统一遍历 OrchestratorRepos 的全部 8 个字段（含 task/brain，原为方法内局部 with，
    升为长生命周期后必须随 per-attempt orchestrator 关闭，否则泄漏 SQLite session）。
    profile_repo 与 _prompt_builder._profile_repo 是同一对象，BaseRepository.close 幂等，
    重复关闭无害。RecordingRepository 不在 bundle 内（DuckDB 句柄、无 close()），不参与关闭。
    """
    repos = getattr(orchestrator, "_repos", None)
    for attr in (
        "session_repo",
        "message_repo",
        "transition_repo",
        "failure_repo",
        "tool_repo",
        "profile_repo",
        "task_repo",
        "brain_repo",
    ):
        close = getattr(getattr(repos, attr, None), "close", None)
        if callable(close):
            close()
    prompt_builder = getattr(orchestrator, "_prompt_builder", None)
    close = getattr(getattr(prompt_builder, "_profile_repo", None), "close", None)
    if callable(close):
        close()
