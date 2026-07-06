"""Guardrails for automated self-improvement proposal executors."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from src.business.agents.hook_models import ToolCallContext, freeze_tool_args
from src.business.agents.tools import builtin_general_tools as general_tools
from src.business.agents.tools.builtin_contracts import use_tool_runtime
from src.business.agents.tools.builtin_permissions import (
    command_path_policy_violation,
    permission_for_path,
)


def _proposal_workspace(tmp_path):
    workspace = tmp_path / ".worktrees" / "improvement" / "prop_guard"
    workspace.mkdir(parents=True)
    return workspace


def test_proposal_workspace_denies_self_improvement_core_mutation(tmp_path) -> None:
    workspace = _proposal_workspace(tmp_path)

    check = permission_for_path(
        workspace / "src" / "business" / "self_improvement" / "proposal_bridge.py",
        operation="write",
        workspace_root=workspace,
    )

    assert not check.allowed
    assert check.error_code == "path_denied_by_self_improvement_guard"


def test_proposal_workspace_allows_regular_source_mutation(tmp_path) -> None:
    workspace = _proposal_workspace(tmp_path)

    check = permission_for_path(
        workspace / "src" / "business" / "reports" / "cache.py",
        operation="write",
        workspace_root=workspace,
    )

    assert check.allowed


def test_proposal_exec_denies_network_and_git_merge(tmp_path) -> None:
    workspace = _proposal_workspace(tmp_path)

    curl = command_path_policy_violation(
        "curl https://example.test",
        workspace_root=workspace,
    )
    merge = command_path_policy_violation("git merge main", workspace_root=workspace)

    assert curl is not None
    assert curl.error_code == "command_rejected"
    assert merge is not None
    assert merge.error_code == "command_rejected"


@pytest.mark.parametrize(
    "command",
    [
        "python -m pip install pytest",
        "uv run python -m pip install pytest",
        "uv run pip install pytest",
        "npm install",
        "npm i",
        "npm ci",
        "pnpm install",
        "pnpm add vitest",
        "yarn add vitest",
        "yarn install",
    ],
)
def test_proposal_exec_denies_package_install_commands_anywhere(tmp_path, command) -> None:
    workspace = _proposal_workspace(tmp_path)

    violation = command_path_policy_violation(command, workspace_root=workspace)

    assert violation is not None
    assert violation.error_code == "command_rejected"


def test_proposal_exec_pre_hook_uses_runtime_workspace_for_guard(tmp_path, monkeypatch) -> None:
    workspace = _proposal_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    emitted = []

    class ConfirmSignal:
        def emit(self, request_id, message):
            emitted.append((request_id, message))
            raise AssertionError("proposal exec policy must reject before confirmation")

    with general_tools._confirm_lock:
        general_tools._pending_confirms.clear()
    monkeypatch.setattr(general_tools, "_confirm_signal", ConfirmSignal())
    ctx = ToolCallContext(
        tool_name="exec",
        args=freeze_tool_args({"command": "curl https://example.test", "cwd": "."}),
        session_id="proposal-pre-hook",
        agent_type="test",
        iteration=1,
    )

    with use_tool_runtime(
        session_id="proposal-pre-hook",
        tool_call_id="call-1",
        tool_name="exec",
        workspace_root=workspace,
    ):
        result = general_tools.exec_pre_hook(ctx)

    assert result is not None
    assert result.error_code == "command_rejected"
    assert emitted == []
    with general_tools._confirm_lock:
        assert general_tools._pending_confirms == {}


def test_proposal_exec_allows_test_commands_inside_worktree(tmp_path) -> None:
    workspace = _proposal_workspace(tmp_path)

    violation = command_path_policy_violation(
        "uv run pytest tests/business/test_report_cache.py",
        workspace_root=workspace,
    )

    assert violation is None


@pytest.mark.parametrize(
    "command",
    [
        "black src/business/self_improvement/proposal_bridge.py",
        "ruff check --fix src/business/self_improvement/proposal_bridge.py",
        "ruff format src/business/self_improvement/proposal_bridge.py",
        "eslint --fix frontend/src/screens/BrainScreen/BrainScreen.tsx",
    ],
)
def test_proposal_exec_denies_mutating_formatter_and_linter_modes(tmp_path, command) -> None:
    """proposal exec 不允许 formatter/fixer 写回受保护代码路径来绕过 mutation guard。"""
    workspace = _proposal_workspace(tmp_path)

    violation = command_path_policy_violation(command, workspace_root=workspace)

    assert violation is not None
    assert violation.error_code == "command_rejected"


@pytest.mark.parametrize(
    "command",
    [
        "black --check src/business/reports/cache.py",
        "black --diff src/business/reports/cache.py",
        "ruff check src/business/reports/cache.py",
        "ruff format --check src/business/reports/cache.py",
    ],
)
def test_proposal_exec_allows_non_mutating_formatter_and_linter_checks(
    tmp_path,
    command,
) -> None:
    workspace = _proposal_workspace(tmp_path)

    violation = command_path_policy_violation(command, workspace_root=workspace)

    assert violation is None


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/business/agents/agent_loop.py",
        "src/business/agents/tools/builtin_permissions.py",
        "src/business/orchestration/agent/orchestrator.py",
        "src/desktop_api/routers/proposals.py",
        "tests/guardrails/test_proposal_guardrails.py",
        # 026 review CG-5:FR-014(c) 禁改调度内核、Tauri 启动壳、legacy/启动入口此前
        # 无参数化钉住——递归砖化/坏提案反馈环的核心防线。
        "src/business/task_collaboration/graph_scheduler.py",
        "src/business/task_collaboration/dispatcher.py",
        "src-tauri/src/main.rs",
        "src/main.py",
        "mexemplar_gui.py",
        "start.bat",
        "src/desktop_api/app.py",
    ],
)
def test_proposal_workspace_denies_constraint_code_mutation(tmp_path, relative_path) -> None:
    """proposal 执行体不得改写约束/守卫代码本身（agent_loop、builtin_permissions、
    orchestration、desktop_api 路由、guardrail 测试），否则可拆掉自己的牢笼（026 I1）。"""
    workspace = _proposal_workspace(tmp_path)
    check = permission_for_path(
        workspace / relative_path,
        operation="write",
        workspace_root=workspace,
    )
    assert not check.allowed
    assert check.error_code == "path_denied_by_self_improvement_guard"


@pytest.mark.parametrize(
    "relative_path",
    [
        "config/app_settings.json",
        "secrets.json",
        "credentials.json",
        "deploy/id_rsa",
    ],
)
def test_proposal_workspace_denies_secret_bearing_files(tmp_path, relative_path) -> None:
    """proposal 执行体不得改写 secret/凭证文件（app_settings/secrets/credentials/id_rsa），
    CLAUDE.md 明确 secret 存 app_settings（026 I2）。"""
    workspace = _proposal_workspace(tmp_path)
    check = permission_for_path(
        workspace / relative_path,
        operation="write",
        workspace_root=workspace,
    )
    assert not check.allowed
    assert check.error_code == "path_denied_by_self_improvement_guard"


def test_proposal_worktree_fails_closed_when_guard_unavailable(tmp_path, monkeypatch) -> None:
    """FR-014 / SC-003：当自我改进 guard 自身抛异常（import 失败/部分重载/循环导入等）
    时，proposal worktree 内的 mutation/exec 仍 MUST fail-closed；普通工作区不受影响。
    否则执行体可在 guard 不可用时拆掉自己的牢笼（V1 回归）。"""
    import src.business.self_improvement.proposal_workspace as proposal_workspace

    def _boom(*_args, **_kwargs):
        raise RuntimeError("guard unavailable simulation")

    workspace = _proposal_workspace(tmp_path)
    normal_workspace = tmp_path / "normal-ws"
    (normal_workspace / "src" / "business" / "reports").mkdir(parents=True)

    monkeypatch.setattr(proposal_workspace, "check_improvement_workspace_mutation", _boom)
    monkeypatch.setattr(proposal_workspace, "check_improvement_exec_command", _boom)

    # proposal worktree 内：mutation 仍被拒（fail-closed）。
    denied_write = permission_for_path(
        workspace / "src" / "business" / "reports" / "cache.py",
        operation="write",
        workspace_root=workspace,
    )
    assert not denied_write.allowed
    assert denied_write.error_code == "path_denied_by_self_improvement_guard"

    # proposal worktree 内：exec 仍被拒（fail-closed）。
    denied_exec = command_path_policy_violation(
        "uv run pytest tests/business/test_report_cache.py",
        workspace_root=workspace,
    )
    assert denied_exec is not None
    assert denied_exec.error_code == "command_rejected"

    # proposal worktree 内：read 不受 mutation guard 管辖，guard 抛异常也照常放行。
    allowed_read = permission_for_path(
        workspace / "src" / "business" / "reports" / "cache.py",
        operation="read",
        workspace_root=workspace,
    )
    assert allowed_read.allowed

    # 普通工作区：guard 抛异常时 fail-open，不阻断正常工作。
    normal_write = permission_for_path(
        normal_workspace / "src" / "business" / "reports" / "cache.py",
        operation="write",
        workspace_root=normal_workspace,
    )
    assert normal_write.allowed


@pytest.mark.parametrize(
    "command",
    [
        "git merge main",
        "git rebase main",
        "git push origin main",
        "git reset --hard HEAD~1",
        "git clean -fdx",
        "git checkout main",
    ],
)
def test_proposal_exec_denies_fr015_git_state_change_commands(tmp_path, command) -> None:
    """FR-015（exec 级）：proposal 执行体不得触发任何改变 git 状态/历史的命令
    （merge/rebase/push/reset/clean/checkout）——第一版合并保持手动。"""
    workspace = _proposal_workspace(tmp_path)
    violation = command_path_policy_violation(command, workspace_root=workspace)
    assert violation is not None
    assert violation.error_code == "command_rejected"


# FR-015（代码路径级）：桥接/worktree 生命周期代码 MUST NOT 调用 merge/rebase/push/
# reset/checkout/cherry-pick 或应用重启。下述 token 在当前实现中均不存在（已核实），本静态
# 守卫用于捕捉未来回归。
_FR015_FORBIDDEN_SUBSTRINGS = [
    "git merge",
    "git rebase",
    "git push",
    "git reset",
    "git clean",
    "git checkout",
    "cherry-pick",
    "os.execv",
    "os._exit",
]
_FR015_FORBIDDEN_LIST_FORM = re.compile(
    r"""['"]git['"]\s*,\s*['"](merge|rebase|push|reset|clean|checkout)['"]""",
)


@pytest.mark.parametrize(
    "relative_path",
    [
        "src/business/self_improvement/proposal_bridge.py",
        "src/business/self_improvement/proposal_workspace.py",
    ],
)
def test_proposal_bridge_and_workspace_never_invoke_merge_or_restart(relative_path) -> None:
    """FR-015 负向（代码路径级）：建图/踢图/回报/worktree 生命周期代码绝不调用
    merge/rebase/push/reset/clean/checkout/cherry-pick 或应用重启（SC-006 命门：
    桥接与回报路径绝不触发 merge / 应用重启）。"""
    repo_root = Path(__file__).resolve().parents[2]
    source = repo_root / relative_path
    assert source.exists(), f"missing source: {source}"
    text = source.read_text(encoding="utf-8")
    for token in _FR015_FORBIDDEN_SUBSTRINGS:
        assert (
            token not in text
        ), f"FR-015 违例：{source.name} 含被禁命令 {token!r}（合并/重启必须保持手动）"
    assert not _FR015_FORBIDDEN_LIST_FORM.search(
        text
    ), f"FR-015 违例：{source.name} 含列表形式 git merge/rebase/push/reset/clean/checkout 调用"


# ---------------------------------------------------------------------------
# 028: 讨论功能守卫 — 序列化单一来源 + 讨论路径零实施副作用
# ---------------------------------------------------------------------------


def test_finding_serialization_single_source() -> None:
    """028 D3：bridge 与讨论开场必须都消费 proposal_context，禁止手拼 finding 模板回潮。"""
    import inspect

    from src.business.self_improvement import proposal_bridge, proposal_service

    bridge_src = inspect.getsource(proposal_bridge)
    service_src = inspect.getsource(proposal_service)

    assert "format_proposal_finding_text" in bridge_src, "bridge 必须消费 proposal_context"
    assert "format_discussion_opening_message" in service_src, "讨论开场必须消费 proposal_context"
    # 手拼模板的特征串只允许存在于 proposal_context 单一来源
    assert "问题：" not in bridge_src, "bridge 不得手拼 finding 模板（问题：…）"
    assert "问题：" not in service_src, "proposal_service 不得手拼 finding 模板（问题：…）"


def test_discussion_path_has_no_implementation_references() -> None:
    """028 FR-425：讨论入口的实现不得触碰实施桥/任务图/worktree 符号。

    静态守卫：get_or_create_discussion_session 方法体内出现 proposal_bridge、
    build_task_graph 或 worktree 任一符号即失败——讨论路径与实施路径必须在
    源码层就不共享入口，而不是靠运行时自觉。
    """
    import inspect

    from src.business.self_improvement.proposal_service import ProposalService

    source = inspect.getsource(ProposalService.get_or_create_discussion_session)
    for forbidden in ("proposal_bridge", "build_task_graph", "trigger_implementation", "worktree"):
        assert forbidden not in source, f"讨论路径不得引用 {forbidden}"
