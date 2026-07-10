"""Git/worktree helpers for external coding sessions."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .models import ConflictRisk, MergeAnalysis

_logger = logging.getLogger(__name__)


class GitOperationError(RuntimeError):
    pass


def _run_git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitOperationError(f"git {' '.join(args)} timed out after 60s") from exc
    if check and result.returncode != 0:
        raise GitOperationError((result.stderr or result.stdout or "git command failed").strip())
    return result


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _nul_paths(value: str) -> list[str]:
    return [path for path in value.split("\0") if path]


def _command_error(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    return (result.stderr or result.stdout or fallback).strip()


class GitOps:
    def create_worktree(
        self, *, target_worktree: Path, worktree_path: Path, branch_name: str
    ) -> None:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if worktree_path.exists():
            raise GitOperationError("coding worktree path already exists")
        _run_git(
            ["worktree", "add", "-b", branch_name, str(worktree_path), "HEAD"], cwd=target_worktree
        )

    def dirty_files(self, worktree: Path) -> list[str]:
        return self._working_tree_files(worktree)

    def changed_files_against(self, *, worktree: Path, base_ref: str = "HEAD") -> list[str]:
        """Return committed and local changes relative to ``base_ref``.

        The four sources are intentionally queried separately.  In particular,
        ``git diff HEAD`` does not include untracked files, while
        ``git diff --cached <base>`` mixes committed and staged changes.
        """
        committed = self._diff_files(worktree, f"{base_ref}...HEAD")
        return sorted(set(committed).union(self._working_tree_files(worktree)))

    def committed_files_against(self, *, worktree: Path, base_ref: str) -> list[str]:
        return self._diff_files(worktree, f"{base_ref}...HEAD")

    def head(self, worktree: Path, ref: str = "HEAD") -> str:
        return _run_git(["rev-parse", ref], cwd=worktree).stdout.strip()

    def current_branch(self, worktree: Path) -> str:
        return _run_git(["symbolic-ref", "--short", "HEAD"], cwd=worktree).stdout.strip()

    def merge_analysis(
        self,
        *,
        coding_worktree: Path,
        coding_branch: str,
        target_worktree: Path,
        target_branch: str,
    ) -> MergeAnalysis:
        if self.current_branch(target_worktree) != target_branch:
            raise GitOperationError("target worktree is not on the requested target branch")
        if self.current_branch(coding_worktree) != coding_branch:
            raise GitOperationError("coding worktree is not on its recorded coding branch")

        coding_dirty = self.dirty_files(coding_worktree)
        if coding_dirty:
            preview = ", ".join(coding_dirty[:10])
            raise GitOperationError(
                f"coding worktree has uncommitted changes: {preview}; "
                "commit or otherwise preserve them before merge analysis"
            )

        pre_merge_head = self.head(target_worktree, "HEAD")
        coding_branch_head = self.head(coding_worktree, "HEAD")
        dirty = self.dirty_files(target_worktree)
        changed = self.committed_files_against(
            worktree=coding_worktree,
            base_ref=target_branch,
        )
        if not changed:
            raise GitOperationError("coding branch has no committed changes to merge")
        overlap = sorted(set(dirty).intersection(changed))
        if not overlap:
            conflict_predicted = self._predict_merge_conflicts(
                target_worktree=target_worktree,
                target_branch=target_branch,
                coding_branch=coding_branch,
            )
            if conflict_predicted is None:
                risk = ConflictRisk.UNKNOWN
            else:
                risk = ConflictRisk.CONFLICT_PREDICTED if conflict_predicted else ConflictRisk.LOW
        else:
            risk = ConflictRisk.OVERLAP
        return MergeAnalysis(
            target_branch=target_branch,
            target_worktree_path=str(target_worktree),
            pre_merge_head=pre_merge_head,
            coding_branch_head=coding_branch_head,
            dirty_files=dirty,
            changed_files=changed,
            overlap_files=overlap,
            conflict_risk=risk,
        )

    @staticmethod
    def _predict_merge_conflicts(
        *, target_worktree: Path, target_branch: str, coding_branch: str
    ) -> bool | None:
        """Predict a merge conflict without changing the index or worktree.

        Modern ``git merge-tree --write-tree`` returns 0 for a clean merge and
        1 when the virtual merge contains conflicts.  Any other exit code is
        treated as unknown so callers fail closed instead of assuming safety.
        """
        result = _run_git(
            ["merge-tree", "--write-tree", "--quiet", target_branch, coding_branch],
            cwd=target_worktree,
            check=False,
        )
        if result.returncode == 0:
            return False
        if result.returncode == 1:
            return True
        _logger.warning(
            "git merge-tree could not classify merge risk for %s and %s (exit %s)",
            target_branch,
            coding_branch,
            result.returncode,
        )
        return None

    def merge(
        self,
        *,
        target_worktree: Path,
        branch_name: str,
        expected_target_head: str | None = None,
        expected_coding_head: str | None = None,
        expected_changed_files: list[str] | None = None,
    ) -> str:
        """Create and verify one non-fast-forward merge commit.

        The merge is stopped before commit so its staged file set can be
        checked against the approved analysis.  A conflict, stale ref, no-op,
        or unexpected file aborts the in-progress merge before returning.
        """
        pre_merge_head = self.head(target_worktree)
        coding_head = self.head(target_worktree, branch_name)
        if expected_target_head and pre_merge_head != expected_target_head:
            raise GitOperationError("target HEAD changed after merge analysis")
        if expected_coding_head and coding_head != expected_coding_head:
            raise GitOperationError("coding branch changed after merge analysis")

        expected = set(expected_changed_files or [])
        if expected_changed_files is not None and not expected:
            raise GitOperationError("merge analysis contains no changed files")

        result = _run_git(
            ["merge", "--no-ff", "--no-commit", "--no-edit", branch_name],
            cwd=target_worktree,
            check=False,
        )
        if result.returncode != 0:
            self._abort_merge(target_worktree, expected_head=pre_merge_head)
            raise GitOperationError(_command_error(result, "git merge failed"))

        if not self._operation_in_progress(target_worktree, "MERGE_HEAD"):
            raise GitOperationError("merge produced no changes")

        staged = set(self._staged_files(target_worktree))
        if not staged:
            self._abort_merge(target_worktree, expected_head=pre_merge_head)
            raise GitOperationError("merge produced no changed files")
        unexpected = staged.difference(expected) if expected_changed_files is not None else set()
        if unexpected:
            self._abort_merge(target_worktree, expected_head=pre_merge_head)
            raise GitOperationError(
                "merge result contains files outside the analyzed change set: "
                + ", ".join(sorted(unexpected)[:10])
            )

        commit_result = _run_git(["commit", "--no-edit"], cwd=target_worktree, check=False)
        if commit_result.returncode != 0:
            self._abort_merge(target_worktree, expected_head=pre_merge_head)
            raise GitOperationError(_command_error(commit_result, "git merge commit failed"))

        merge_commit = self.head(target_worktree)
        try:
            self.verify_merge_result(
                target_worktree=target_worktree,
                merge_commit=merge_commit,
                expected_target_head=pre_merge_head,
                expected_coding_head=coding_head,
                expected_changed_files=(
                    sorted(expected) if expected_changed_files is not None else None
                ),
            )
        except Exception:
            self._restore_failed_merge_commit(
                target_worktree=target_worktree,
                merge_commit=merge_commit,
                pre_merge_head=pre_merge_head,
            )
            raise
        return merge_commit

    def verify_merge_result(
        self,
        *,
        target_worktree: Path,
        merge_commit: str,
        expected_target_head: str,
        expected_coding_head: str,
        expected_changed_files: list[str] | None,
    ) -> list[str]:
        if self.head(target_worktree) != merge_commit or merge_commit == expected_target_head:
            raise GitOperationError("merge did not advance target HEAD to a new commit")
        parents = self._commit_parents(target_worktree, merge_commit)
        if parents != [expected_target_head, expected_coding_head]:
            raise GitOperationError("merge commit parents do not match the analyzed refs")

        actual_files = self._diff_files(
            target_worktree,
            f"{expected_target_head}..{merge_commit}",
        )
        if not actual_files:
            raise GitOperationError("merge commit has no file changes")
        if expected_changed_files is not None:
            unexpected = set(actual_files).difference(expected_changed_files)
            if unexpected:
                raise GitOperationError(
                    "verified merge contains unexpected files: "
                    + ", ".join(sorted(unexpected)[:10])
                )
        return actual_files

    def revert_commit(
        self,
        *,
        target_worktree: Path,
        commit: str,
        expected_parent: str | None = None,
        expected_branch: str | None = None,
    ) -> str:
        """Revert exactly one recorded merge commit using its first parent."""
        if expected_branch and self.current_branch(target_worktree) != expected_branch:
            raise GitOperationError("target worktree is not on the recorded merge branch")
        dirty = self.dirty_files(target_worktree)
        if dirty:
            raise GitOperationError(
                "target worktree must be clean before rollback: " + ", ".join(dirty[:10])
            )
        parents = self._commit_parents(target_worktree, commit)
        if len(parents) != 2:
            raise GitOperationError("recorded merge commit is not a two-parent merge commit")
        if expected_parent and parents[0] != expected_parent:
            raise GitOperationError("recorded merge commit does not match its pre-merge HEAD")
        ancestor = _run_git(
            ["merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=target_worktree,
            check=False,
        )
        if ancestor.returncode != 0:
            if ancestor.returncode == 1:
                raise GitOperationError("recorded merge commit is not in target HEAD history")
            raise GitOperationError(_command_error(ancestor, "could not inspect target history"))

        pre_revert_head = self.head(target_worktree)
        result = _run_git(
            ["revert", "--mainline", "1", "--no-edit", commit],
            cwd=target_worktree,
            check=False,
        )
        if result.returncode != 0:
            _run_git(["revert", "--abort"], cwd=target_worktree, check=False)
            if self.head(target_worktree) != pre_revert_head:
                raise GitOperationError("rollback failed and changed target HEAD")
            raise GitOperationError(_command_error(result, "git revert failed"))
        revert_head = self.head(target_worktree)
        if revert_head == pre_revert_head:
            raise GitOperationError("rollback produced no new commit")
        return revert_head

    def _working_tree_files(self, worktree: Path) -> list[str]:
        staged = self._staged_files(worktree)
        unstaged = _nul_paths(_run_git(["diff", "--name-only", "-z"], cwd=worktree).stdout)
        untracked = _nul_paths(
            _run_git(
                ["ls-files", "--others", "--exclude-standard", "-z"],
                cwd=worktree,
            ).stdout
        )
        return sorted(set(staged + unstaged + untracked))

    @staticmethod
    def _staged_files(worktree: Path) -> list[str]:
        return _nul_paths(
            _run_git(
                ["diff", "--cached", "--name-only", "-z", "HEAD"],
                cwd=worktree,
            ).stdout
        )

    @staticmethod
    def _diff_files(worktree: Path, revision_range: str) -> list[str]:
        return sorted(
            set(
                _nul_paths(
                    _run_git(
                        ["diff", "--name-only", "-z", revision_range],
                        cwd=worktree,
                    ).stdout
                )
            )
        )

    @staticmethod
    def _commit_parents(worktree: Path, commit: str) -> list[str]:
        line = _run_git(
            ["rev-list", "--parents", "-n", "1", commit],
            cwd=worktree,
        ).stdout.strip()
        fields = line.split()
        if not fields or fields[0] != commit:
            raise GitOperationError("could not verify commit parents")
        return fields[1:]

    @staticmethod
    def _operation_in_progress(worktree: Path, marker: str) -> bool:
        result = _run_git(
            ["rev-parse", "--quiet", "--verify", marker],
            cwd=worktree,
            check=False,
        )
        return result.returncode == 0

    def _abort_merge(self, worktree: Path, *, expected_head: str) -> None:
        if self._operation_in_progress(worktree, "MERGE_HEAD"):
            result = _run_git(["merge", "--abort"], cwd=worktree, check=False)
            if result.returncode != 0 or self._operation_in_progress(worktree, "MERGE_HEAD"):
                raise GitOperationError("git merge failed and merge state could not be cleaned")
        if self.head(worktree) != expected_head:
            raise GitOperationError("git merge failure changed target HEAD")

    def _restore_failed_merge_commit(
        self,
        *,
        target_worktree: Path,
        merge_commit: str,
        pre_merge_head: str,
    ) -> None:
        if self.head(target_worktree) != merge_commit:
            raise GitOperationError("invalid merge result could not be restored safely")
        result = _run_git(
            ["reset", "--merge", pre_merge_head],
            cwd=target_worktree,
            check=False,
        )
        if result.returncode != 0 or self.head(target_worktree) != pre_merge_head:
            raise GitOperationError("invalid merge result could not be restored safely")

    def remove_worktree(self, *, target_worktree: Path, worktree_path: Path) -> None:
        """Remove a coding worktree registered under target_worktree.

        Used to clean up worktrees leaked when session creation/abandon fails
        after the worktree has already been created.  Best-effort: a missing or
        already-removed worktree is not an error.
        """
        _run_git(
            ["worktree", "remove", "--force", str(worktree_path)],
            cwd=target_worktree,
            check=False,
        )
