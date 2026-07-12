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


def test_shell_host_requires_confirmation_instead_of_hard_rejection(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = general_tools.exec_pre_hook(_exec_context("powershell -Command Get-Date"))

    assert result is not None
    assert result.error_code == "confirmation_failed_closed"


def test_shell_host_is_allowed_by_session_auto_approval(tmp_path, monkeypatch) -> None:
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
def test_parent_path_traversal_remains_hard_rejected_during_auto_approval(
    command, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context(command))

    assert result is not None
    assert result.error_code == "command_rejected"


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
def test_shell_control_syntax_remains_hard_rejected_during_auto_approval(
    command, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context(command))

    assert result is not None
    assert result.error_code == "command_rejected"


def test_inline_interpreter_code_remains_hard_rejected_during_auto_approval(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    general_tools.set_auto_approve_enabled(
        True,
        general_tools.CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    )

    result = general_tools.exec_pre_hook(_exec_context('python -c "print(1)"'))

    assert result is not None
    assert result.error_code == "command_rejected"
