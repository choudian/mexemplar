import os

import pytest

from src.business.agents.hook_models import ToolCallContext, freeze_tool_args
from src.business.agents.tools import builtin_general_tools as general_tools


@pytest.fixture(autouse=True)
def reset_confirmation_state():
    general_tools.reset_confirmation_state_for_tests()
    yield
    general_tools.reset_confirmation_state_for_tests()


def _exec_context(command: str, *, cwd: str = ".") -> ToolCallContext:
    return ToolCallContext(
        tool_name="exec",
        args=freeze_tool_args({"command": command, "cwd": cwd}),
        session_id="exec-permission-test",
        agent_type="test",
        iteration=1,
    )


def test_shell_host_inline_flag_no_longer_hard_rejected(tmp_path, monkeypatch) -> None:
    """删 shell host 内联 flag 关卡后，powershell -Command 不再硬拒，改走默认确认。"""
    monkeypatch.chdir(tmp_path)

    result = general_tools.exec_pre_hook(_exec_context("powershell -Command Get-Date"))

    # 不再硬拒（command_rejected）；测试上下文无 UI → 走确认即 fail-closed
    assert result is not None
    assert result.error_code == "confirmation_failed_closed"


def test_shell_host_inline_flag_allowed_under_auto_approval(tmp_path, monkeypatch) -> None:
    """删 shell host 关卡后，powershell -Command 在 allow_all 下短路放行。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context("powershell -Command Get-Date"))

    assert result is None


def test_explicit_external_path_requires_confirmation_instead_of_hard_rejection(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    external_target = tmp_path.parent / "installer-target"

    result = general_tools.exec_pre_hook(_exec_context(f'installer --target "{external_target}"'))

    assert result is not None
    assert result.error_code == "confirmation_failed_closed"


def test_explicit_external_path_is_allowed_by_session_auto_approval(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    external_target = tmp_path.parent / "installer-target"
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context(f'installer --target "{external_target}"'))

    assert result is None


@pytest.mark.parametrize(
    "command",
    [
        "installer --target ../installer-target",
        "installer --target ..",
        "git -C.. status",
        "git -C .. status",
        "cat ..",
        "cat '..'",
        "grep pattern '..'",
        "grep pattern '../outside'",
        "grep -f ../patterns.txt file.txt",
        "grep -f../patterns.txt file.txt",
        "grep -fpatterns.txt '..'",
        "grep --file=patterns.txt '..'",
        "grep -epattern '..'",
        "grep --regexp=pattern '..'",
        "grep -e pattern ../outside",
        "rg -g '*.py' pattern '..'",
        "compiler -I../include",
        "installer --target:../installer-target",
        "build /p:OutputPath=../installer-target",
        pytest.param(
            r"cl /Fo..\outside.obj",
            marks=pytest.mark.skipif(os.name != "nt", reason="Windows slash option syntax"),
        ),
        pytest.param(
            r'cl /Fo"..\outside.obj"',
            marks=pytest.mark.skipif(os.name != "nt", reason="Windows slash option syntax"),
        ),
        pytest.param(
            r"cl /external:I..\outside.obj",
            marks=pytest.mark.skipif(os.name != "nt", reason="Windows slash option syntax"),
        ),
        r'installer --target:"../installer-target"',
        r'powershell -Command "New-Item -Path ..\installer-target"',
        r"gcc -Wl,-rpath,../lib",
        r'''powershell -Command "Set-Location('..')"''',
    ],
)
def test_parent_path_traversal_no_longer_hard_rejected_under_auto_approval(
    command, tmp_path, monkeypatch
) -> None:
    """删 `..` 穿越关卡后,含 `..` 的命令在 allow_all 下短路放行,不再硬拒。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context(command))

    assert result is None


@pytest.mark.parametrize(
    "command",
    [
        "installer --target foo../installer-target",
        "installer --target foo-../installer-target",
        "installer --target foo+../installer-target",
        "installer --label=foo..",
        "installer --target=foo../installer-target",
        "installer --target:foo../installer-target",
        "compiler -Ifoo../include",
        "grep '..' file.txt",
        "grep 'a .. b' file.txt",
        "grep '../' file.txt",
        "grep -e '..' file.txt",
        "grep -F '..' file.txt",
        "grep -C 2 '..' file.txt",
        "grep -I '../' file.txt",
        "grep --regexp='..' file.txt",
        "rg '../' workspace",
        "rg -g '*.py' '..' workspace",
        "echo '../'",
    ],
)
def test_double_dot_within_path_name_is_not_treated_as_parent_traversal(
    command, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context(command))

    assert result is None


@pytest.mark.parametrize(
    "command",
    [
        "echo ok; whoami",
        "echo ok | whoami",
        "echo `whoami`",
    ],
)
def test_shell_metachar_commands_short_circuit_under_auto_approval(
    command, tmp_path, monkeypatch
) -> None:
    """删元字符 force_interactive 关卡后，含管道/反引号的命令在 allow_all 下短路放行。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context(command))

    assert result is None


def test_inline_interpreter_code_no_longer_hard_rejected_under_auto_approval(
    tmp_path, monkeypatch
) -> None:
    """删内联代码关卡后,python -c 在 allow_all 下短路放行,不再硬拒。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context('python -c "print(1)"'))

    assert result is None


def test_bash_dash_c_not_hard_rejected_under_auto_approval(tmp_path, monkeypatch) -> None:
    """删 shell host 关卡后，bash -c 不再硬拒，allow_all 下短路放行。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL)
    result = general_tools.exec_pre_hook(_exec_context("bash -c 'rm -rf /'"))
    assert result is None


def test_cmd_slash_c_not_hard_rejected_under_auto_approval(tmp_path, monkeypatch) -> None:
    """删 shell host 关卡后，cmd /c 不再硬拒，allow_all 下短路放行。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL)
    result = general_tools.exec_pre_hook(_exec_context("cmd /c dir"))
    assert result is None


def test_os_system_path_in_command_arg_hard_rejected(tmp_path, monkeypatch) -> None:
    """命令参数命中 OS 系统路径（C:/Windows）硬拒。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL)
    result = general_tools.exec_pre_hook(_exec_context("rm -rf C:/Windows"))
    assert result is not None
    assert result.error_code == "command_rejected"


def test_python_command_short_circuits_under_auto_approval(tmp_path, monkeypatch) -> None:
    """删 allowlist 后 python script.py 不再特殊放行，但仍随 allow_all 默认短路。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL)
    result = general_tools.exec_pre_hook(_exec_context("python script.py"))
    assert result is None


def test_destructive_command_short_circuits_under_auto_approval(tmp_path, monkeypatch) -> None:
    """rm -rf build（非 OS 路径、非穿越）随 allow_all 默认短路放行。"""
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL)
    result = general_tools.exec_pre_hook(_exec_context("rm -rf build"))
    assert result is None
