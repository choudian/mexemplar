"""Tests for proposal_workspace — git worktree 生命周期管理。

用 tmp_path 内真实 git 仓库验证 create/remove/脏拒绝。
"""

from __future__ import annotations

import subprocess

import pytest

from src.business.self_improvement import proposal_workspace as pw


@pytest.fixture()
def mini_repo(tmp_path, monkeypatch):
    """在 tmp_path 内建一个有初始 commit 的迷你 git 仓库，monkeypatch resolve_repo_root 返回它。"""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    # monkeypatch resolve_repo_root 返回这个迷你仓库
    monkeypatch.setattr(
        "src.business.self_improvement.proposal_workspace.resolve_repo_root",
        lambda: repo,
    )
    return repo


def test_create_worktree_produces_isolated_dir_and_branch(mini_repo):
    wt_path, branch = pw.create_worktree("prop_001")

    assert branch == "improvement/prop_001"
    assert wt_path.exists()
    assert (wt_path / "hello.txt").exists()
    # worktree HEAD 独立于主工作树
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=wt_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == pw._branch_name("prop_001")


def test_create_worktree_writes_in_expected_layout(mini_repo):
    wt_path, _ = pw.create_worktree("prop_002")
    expected = mini_repo / ".worktrees" / "improvement" / "prop_002"
    assert wt_path == expected.resolve()


def test_create_worktree_rejects_dirty_existing_path(mini_repo):
    pw.create_worktree("prop_003")
    with pytest.raises(pw.ProposalWorkspaceDirty):
        pw.create_worktree("prop_003")


def test_remove_worktree_cleans_up(mini_repo):
    wt_path, branch = pw.create_worktree("prop_004")
    assert wt_path.exists()

    pw.remove_worktree(wt_path)

    assert not wt_path.exists()
    # 分支应被删除
    result = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=mini_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""


def test_remove_worktree_idempotent_on_missing_path(mini_repo):
    ghost = mini_repo / ".worktrees" / "improvement" / "ghost"
    pw.remove_worktree(ghost)  # 不抛


def test_remove_worktree_raises_when_fallback_directory_cleanup_fails(
    mini_repo,
    monkeypatch,
):
    wt_path, _ = pw.create_worktree("prop_cleanup_fail")
    original_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        if cmd[3:5] == ["worktree", "remove"]:
            raise subprocess.CalledProcessError(1, cmd, stderr="locked")
        return original_run(cmd, *args, **kwargs)

    monkeypatch.setattr(pw.subprocess, "run", fake_run)
    monkeypatch.setattr(
        pw.shutil,
        "rmtree",
        lambda path: (_ for _ in ()).throw(OSError("locked")),
    )

    with pytest.raises(pw.ProposalWorkspaceError):
        pw.remove_worktree(wt_path)

    assert wt_path.exists()


def test_remove_worktree_deletes_orphan_branch_when_directory_already_gone(mini_repo):
    """目录已被前次清理删除、分支却残留时,remove_worktree 不得早退,仍须删除孤儿分支。

    回归 FR-016/T027:git worktree remove 成功删了目录但分支删除未发生/失败时,
    下次 remove_worktree 不能因 ``wt_path.exists()`` 为假就 return —— 否则
    ``improvement/<proposal_id>`` 分支永久泄漏。
    """
    wt_path, branch = pw.create_worktree("prop_orphan_branch")
    assert wt_path.exists()

    # 模拟前次清理:git worktree remove 成功删了目录,但分支删除未发生
    # (git worktree remove 不会删除特性分支)
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt_path)],
        cwd=mini_repo,
        check=True,
        capture_output=True,
    )
    assert not wt_path.exists()

    # 孤儿分支仍残留
    listing = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=mini_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert listing.stdout.strip() != ""

    # 现在调 remove_worktree:不得因目录已不存在而早退漏掉分支清理
    pw.remove_worktree(wt_path)

    # 期望:孤儿分支已被删除
    listing = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=mini_repo,
        capture_output=True,
        text=True,
        check=True,
    )
    assert listing.stdout.strip() == ""


def test_resolve_repo_root_finds_repo(mini_repo):
    root = pw.resolve_repo_root()
    assert root == mini_repo
    assert (root / ".git").exists()
