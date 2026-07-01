"""Guardrail: proposal executor 必须在有效 improvement worktree 内执行。

proposal executor 由 ``self_improvement:<proposal_id>`` synthetic session 标识。
若其 ``task.workspace_root`` 缺失或漂移到主仓库根,workspace 注入链路断裂,
路径白名单失效 —— executor 可改写 self_improvement / task_collaboration /
src-tauri 等核心路径,击穿 FR-014 blast radius 与 SC-003「100% fail-closed」承诺。

该 guard 在 TaskExecutorAdapter 派发源头 fail-closed:所有经 scheduler 的
proposal 执行都必经此处,是覆盖 workspace 数据丢失/漂移的最可靠拦截点。
"""

from __future__ import annotations

import pytest

from src.business.orchestration.agent.task_executor_adapter import (
    _assert_proposal_executor_workspace_or_raise,
)


def test_proposal_executor_with_missing_workspace_fails_closed():
    """task.workspace_root 数据丢失(最可能失效路径)→ fail-closed,不得执行。"""
    with pytest.raises(RuntimeError, match="workspace"):
        _assert_proposal_executor_workspace_or_raise(
            "self_improvement:prop_missing", None
        )


def test_proposal_executor_with_drifted_workspace_fails_closed():
    """workspace 漂移到主仓库根(非 improvement worktree)→ fail-closed。"""
    with pytest.raises(RuntimeError):
        _assert_proposal_executor_workspace_or_raise(
            "self_improvement:prop_drift", "/home/user/Exemplar"
        )


def test_proposal_executor_with_empty_workspace_fails_closed():
    """空字符串 workspace 等同缺失 → fail-closed。"""
    with pytest.raises(RuntimeError):
        _assert_proposal_executor_workspace_or_raise(
            "self_improvement:prop_empty", ""
        )


def test_proposal_executor_with_valid_improvement_worktree_passes():
    """workspace 指向 .worktrees/improvement/<id> → 放行。"""
    _assert_proposal_executor_workspace_or_raise(
        "self_improvement:prop_ok",
        "/home/user/Exemplar/.worktrees/improvement/prop_ok",
    )  # 不抛


def test_proposal_executor_with_windows_style_worktree_path_passes():
    """Windows 反斜杠路径也能识别。"""
    _assert_proposal_executor_workspace_or_raise(
        "self_improvement:prop_win",
        r"E:\code\Exemplar\.worktrees\improvement\prop_win",
    )  # 不抛


def test_non_proposal_executor_unaffected_by_missing_workspace():
    """普通 task executor(workspace 自由)不受该 guard 影响。"""
    _assert_proposal_executor_workspace_or_raise(
        "assistant_session_xyz", None
    )  # 不抛
