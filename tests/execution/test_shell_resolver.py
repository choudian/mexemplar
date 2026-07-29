from types import SimpleNamespace

import pytest

from src.execution import shell_resolver


@pytest.fixture(autouse=True)
def _clear_shell_cache():
    shell_resolver.resolve_shell.cache_clear()
    yield
    shell_resolver.resolve_shell.cache_clear()


def test_windows_prefers_known_git_bash_before_path_wsl(tmp_path, monkeypatch):
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    git_bash.parent.mkdir(parents=True)
    git_bash.touch()
    wsl_bash = r"C:\Windows\System32\bash.exe"

    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(name="nt", environ={"WINDIR": r"C:\Windows"}),
    )
    monkeypatch.setattr(
        shell_resolver,
        "_WINDOWS_BASH_CANDIDATES",
        (str(git_bash),),
    )
    monkeypatch.setattr(
        shell_resolver.shutil,
        "which",
        lambda name: wsl_bash if name == "bash" else None,
    )

    assert shell_resolver.resolve_shell() == str(git_bash)


def test_windows_ignores_wsl_bash_on_path_when_git_bash_is_missing(
    tmp_path,
    monkeypatch,
):
    missing_git_bash = tmp_path / "missing" / "bash.exe"
    wsl_bash = r"C:\Windows\System32\bash.exe"
    cmd = r"C:\Windows\System32\cmd.exe"

    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(name="nt", environ={"WINDIR": r"C:\Windows"}),
    )
    monkeypatch.setattr(
        shell_resolver,
        "_WINDOWS_BASH_CANDIDATES",
        (str(missing_git_bash),),
    )

    def fake_which(name):
        return {"bash": wsl_bash, "cmd": cmd}.get(name)

    monkeypatch.setattr(shell_resolver.shutil, "which", fake_which)

    assert shell_resolver.resolve_shell() == cmd


def test_windows_finds_git_bash_beside_git_from_a_nonstandard_install(
    tmp_path,
    monkeypatch,
):
    install_root = tmp_path / "portable-git"
    git = install_root / "cmd" / "git.exe"
    git_bash = install_root / "bin" / "bash.exe"
    git.parent.mkdir(parents=True)
    git_bash.parent.mkdir(parents=True)
    git.touch()
    git_bash.touch()
    wsl_bash = r"C:\Windows\System32\bash.exe"

    monkeypatch.setattr(
        shell_resolver,
        "os",
        SimpleNamespace(name="nt", environ={"WINDIR": r"C:\Windows"}),
    )
    monkeypatch.setattr(
        shell_resolver,
        "_WINDOWS_BASH_CANDIDATES",
        (),
    )

    def fake_which(name):
        return {"git": str(git), "bash": wsl_bash}.get(name)

    monkeypatch.setattr(shell_resolver.shutil, "which", fake_which)

    assert shell_resolver.resolve_shell() == str(git_bash)
