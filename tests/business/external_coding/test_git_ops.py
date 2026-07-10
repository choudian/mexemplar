import subprocess
from pathlib import Path

import pytest

from src.business.external_coding.git_ops import GitOperationError, GitOps


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")


def _coding_worktree(repo: Path, path: Path) -> Path:
    _git(repo, "worktree", "add", "-b", "coding/test", str(path), "HEAD")
    return path


def test_create_worktree_refuses_a_preexisting_path(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"a.txt": "base\n"})
    stale = tmp_path / "stale-coding"
    stale.mkdir()

    with pytest.raises(GitOperationError, match="already exists"):
        GitOps().create_worktree(
            target_worktree=repo,
            worktree_path=stale,
            branch_name="coding/stale",
        )


def test_merge_analysis_detects_dirty_overlap(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-m", "base")

    coding_worktree = tmp_path / "coding"
    _git(repo, "worktree", "add", "-b", "coding/test", str(coding_worktree), "HEAD")
    (coding_worktree / "a.txt").write_text("coding\n", encoding="utf-8")
    _git(coding_worktree, "add", "a.txt")
    _git(coding_worktree, "commit", "-m", "coding")

    (repo / "a.txt").write_text("dirty\n", encoding="utf-8")

    analysis = GitOps().merge_analysis(
        coding_worktree=coding_worktree,
        coding_branch="coding/test",
        target_worktree=repo,
        target_branch="main",
    )

    assert analysis.conflict_risk.value == "overlap"
    assert analysis.overlap_files == ["a.txt"]


def test_changed_files_include_committed_staged_unstaged_and_untracked(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(
        repo,
        {
            "committed.txt": "base\n",
            "staged.txt": "base\n",
            "unstaged.txt": "base\n",
        },
    )
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "committed.txt").write_text("committed\n", encoding="utf-8")
    _git(coding, "add", "committed.txt")
    _git(coding, "commit", "-m", "committed change")
    (coding / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(coding, "add", "staged.txt")
    (coding / "unstaged.txt").write_text("unstaged\n", encoding="utf-8")
    (coding / "untracked.txt").write_text("untracked\n", encoding="utf-8")

    changed = GitOps().changed_files_against(worktree=coding, base_ref="main")

    assert changed == [
        "committed.txt",
        "staged.txt",
        "unstaged.txt",
        "untracked.txt",
    ]


def test_merge_analysis_rejects_uncommitted_coding_changes(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"a.txt": "base\n"})
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "untracked.txt").write_text("not committed\n", encoding="utf-8")

    with pytest.raises(GitOperationError, match="uncommitted changes"):
        GitOps().merge_analysis(
            coding_worktree=coding,
            coding_branch="coding/test",
            target_worktree=repo,
            target_branch="main",
        )


def test_merge_analysis_predicts_content_conflict(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"shared.txt": "base\n"})
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "shared.txt").write_text("coding\n", encoding="utf-8")
    _git(coding, "commit", "-am", "coding change")
    (repo / "shared.txt").write_text("target\n", encoding="utf-8")
    _git(repo, "commit", "-am", "target change")

    analysis = GitOps().merge_analysis(
        coding_worktree=coding,
        coding_branch="coding/test",
        target_worktree=repo,
        target_branch="main",
    )

    assert analysis.conflict_risk.value == "conflict_predicted"
    assert analysis.changed_files == ["shared.txt"]


def test_merge_creates_verified_commit_and_preserves_nonoverlapping_dirty_file(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"a.txt": "base\n", "local.txt": "base\n"})
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "a.txt").write_text("coding\n", encoding="utf-8")
    _git(coding, "commit", "-am", "coding change")
    (repo / "local.txt").write_text("local dirty\n", encoding="utf-8")

    ops = GitOps()
    analysis = ops.merge_analysis(
        coding_worktree=coding,
        coding_branch="coding/test",
        target_worktree=repo,
        target_branch="main",
    )
    merge_commit = ops.merge(
        target_worktree=repo,
        branch_name="coding/test",
        expected_target_head=analysis.pre_merge_head,
        expected_coding_head=analysis.coding_branch_head,
        expected_changed_files=analysis.changed_files,
    )

    assert merge_commit != analysis.pre_merge_head
    assert (repo / "a.txt").read_text(encoding="utf-8") == "coding\n"
    assert (repo / "local.txt").read_text(encoding="utf-8") == "local dirty\n"
    assert ops.dirty_files(repo) == ["local.txt"]
    assert ops.verify_merge_result(
        target_worktree=repo,
        merge_commit=merge_commit,
        expected_target_head=analysis.pre_merge_head,
        expected_coding_head=analysis.coding_branch_head,
        expected_changed_files=analysis.changed_files,
    ) == ["a.txt"]


def test_failed_merge_aborts_conflict_state_and_restores_head(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"shared.txt": "base\n"})
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "shared.txt").write_text("coding\n", encoding="utf-8")
    _git(coding, "commit", "-am", "coding change")
    (repo / "shared.txt").write_text("target\n", encoding="utf-8")
    _git(repo, "commit", "-am", "target change")
    pre_merge_head = _git(repo, "rev-parse", "HEAD")
    coding_head = _git(coding, "rev-parse", "HEAD")

    with pytest.raises(GitOperationError):
        GitOps().merge(
            target_worktree=repo,
            branch_name="coding/test",
            expected_target_head=pre_merge_head,
            expected_coding_head=coding_head,
            expected_changed_files=["shared.txt"],
        )

    assert _git(repo, "rev-parse", "HEAD") == pre_merge_head
    assert (repo / "shared.txt").read_text(encoding="utf-8") == "target\n"
    marker = subprocess.run(
        ["git", "rev-parse", "--quiet", "--verify", "MERGE_HEAD"],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    assert marker.returncode != 0


def test_merge_refuses_already_merged_branch_as_no_op(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"a.txt": "base\n"})
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "a.txt").write_text("coding\n", encoding="utf-8")
    _git(coding, "commit", "-am", "coding change")
    _git(repo, "merge", "--no-ff", "--no-edit", "coding/test")
    pre_merge_head = _git(repo, "rev-parse", "HEAD")
    coding_head = _git(coding, "rev-parse", "HEAD")

    with pytest.raises(GitOperationError, match="no changes"):
        GitOps().merge(
            target_worktree=repo,
            branch_name="coding/test",
            expected_target_head=pre_merge_head,
            expected_coding_head=coding_head,
            expected_changed_files=["a.txt"],
        )

    assert _git(repo, "rev-parse", "HEAD") == pre_merge_head


def test_revert_commit_reverts_exact_recorded_merge(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"a.txt": "base\n"})
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "a.txt").write_text("coding\n", encoding="utf-8")
    _git(coding, "commit", "-am", "coding change")

    ops = GitOps()
    analysis = ops.merge_analysis(
        coding_worktree=coding,
        coding_branch="coding/test",
        target_worktree=repo,
        target_branch="main",
    )
    merge_commit = ops.merge(
        target_worktree=repo,
        branch_name="coding/test",
        expected_target_head=analysis.pre_merge_head,
        expected_coding_head=analysis.coding_branch_head,
        expected_changed_files=analysis.changed_files,
    )

    revert_commit = ops.revert_commit(
        target_worktree=repo,
        commit=merge_commit,
        expected_parent=analysis.pre_merge_head,
        expected_branch="main",
    )

    assert revert_commit not in {merge_commit, analysis.pre_merge_head}
    assert (repo / "a.txt").read_text(encoding="utf-8") == "base\n"


def test_revert_commit_refuses_a_different_checked_out_branch(tmp_path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, {"a.txt": "base\n"})
    coding = _coding_worktree(repo, tmp_path / "coding")
    (coding / "a.txt").write_text("coding\n", encoding="utf-8")
    _git(coding, "commit", "-am", "coding change")
    ops = GitOps()
    analysis = ops.merge_analysis(
        coding_worktree=coding,
        coding_branch="coding/test",
        target_worktree=repo,
        target_branch="main",
    )
    merge_commit = ops.merge(
        target_worktree=repo,
        branch_name="coding/test",
        expected_target_head=analysis.pre_merge_head,
        expected_coding_head=analysis.coding_branch_head,
        expected_changed_files=analysis.changed_files,
    )
    _git(repo, "switch", "-c", "unrelated")

    with pytest.raises(GitOperationError, match="recorded merge branch"):
        ops.revert_commit(
            target_worktree=repo,
            commit=merge_commit,
            expected_parent=analysis.pre_merge_head,
            expected_branch="main",
        )

    assert _git(repo, "rev-parse", "HEAD") == merge_commit
