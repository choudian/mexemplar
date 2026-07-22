"""Fail-closed target repository tests for external coding sessions."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.business.agents.tools.external_coding_tools import create_external_coding_tools
from src.business.external_coding.git_ops import GitOperationError, GitOps, GitProcessError
from src.business.external_coding.models import (
    ExternalCodingTool,
    QuotaSignal,
    QuotaState,
)
from src.business.external_coding.service import ExternalCodingSessionService
from src.data.repos.external_coding_session_repository import ExternalCodingSessionRepository


class _Config:
    def __init__(self, *, artifact_root: Path, worktree_root: Path) -> None:
        self._artifact_root = artifact_root
        self._worktree_root = worktree_root

    def get_external_coding_enabled(self):
        return True

    def get_external_coding_default_launch_mode(self):
        return "headless"

    def get_external_coding_preferred_tool(self):
        return "claude_code"

    def get_external_coding_artifact_root(self):
        return str(self._artifact_root)

    def get_external_coding_worktree_root(self):
        return str(self._worktree_root)

    def get_external_coding_autostart_enabled(self):
        return False

    def get_external_coding_log_tail_chars(self):
        return 1000


class _QuotaProbe:
    def probe_all(self):
        return {
            ExternalCodingTool.CLAUDE_CODE: QuotaSignal(
                tool=ExternalCodingTool.CLAUDE_CODE,
                state=QuotaState.AVAILABLE,
                source="test",
                confidence=1.0,
                checked_at="2026-07-21T00:00:00",
            )
        }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(repo: Path, *, commit: bool = True) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    if commit:
        (repo / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
        (repo / "README.md").write_text("test repository\n", encoding="utf-8")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "initial")


def _make_service(
    tmp_path: Path,
    *,
    worktree_root: Path = Path(".worktrees/coding"),
) -> tuple[ExternalCodingSessionService, ExternalCodingSessionRepository]:
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=tmp_path / "session-artifacts",
            worktree_root=worktree_root,
        ),
        git_ops=GitOps(),
        quota_probe=_QuotaProbe(),
    )
    return service, repo


def _start(service: ExternalCodingSessionService, target: str | None) -> dict:
    return service.start_session(
        session_id="sess_test",
        owner_type="task",
        owner_id="tsk_target_repository",
        objective="make a tiny documentation change",
        target_worktree_path=target,
    )


def _cleanup_created_worktree(target_repo: Path, created: dict | None) -> None:
    if not created:
        return
    GitOps().remove_worktree(
        target_worktree=target_repo,
        worktree_path=Path(created["worktreePath"]),
    )
    subprocess.run(
        ["git", "branch", "-D", created["branchName"]],
        cwd=target_repo,
        text=True,
        capture_output=True,
        check=False,
    )


def _tree_entries(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*")}


def test_missing_target_repository_is_rejected_without_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exemplar = tmp_path / "exemplar"
    _init_repo(exemplar)
    monkeypatch.chdir(exemplar)
    service, repo = _make_service(tmp_path)
    initial_branches = _git(exemplar, "branch", "--format=%(refname:short)").splitlines()
    created = None

    try:
        error = None
        try:
            created = _start(service, None)
        except ValueError as exc:
            error = exc

        assert error is not None
        assert "target repository path is required" in str(error).lower()
        assert repo.list_sessions(limit=10) == []
        assert not (exemplar / ".worktrees").exists()
        assert (
            _git(exemplar, "branch", "--format=%(refname:short)").splitlines() == initial_branches
        )
    finally:
        _cleanup_created_worktree(exemplar, created)
        repo.close()


def test_nonexistent_target_repository_has_actionable_safe_error(tmp_path: Path) -> None:
    service, repo = _make_service(tmp_path)
    missing = tmp_path / "repositories" / "missing"
    try:
        with pytest.raises(ValueError) as exc_info:
            _start(service, str(missing))

        message = str(exc_info.value).lower()
        assert "does not exist" in message
        assert "provide" in message
        assert "fatal" not in message
        assert repo.list_sessions(limit=10) == []
    finally:
        repo.close()


def test_non_git_target_repository_has_actionable_safe_error(tmp_path: Path) -> None:
    target = tmp_path / "not-a-repository"
    target.mkdir()
    service, repo = _make_service(tmp_path)
    try:
        with pytest.raises(ValueError) as exc_info:
            _start(service, str(target))

        message = str(exc_info.value).lower()
        assert "usable git repository" in message
        assert "at least one commit" in message
        assert "fatal" not in message
        assert repo.list_sessions(limit=10) == []
    finally:
        repo.close()


def test_git_process_failure_during_head_probe_has_actionable_safe_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class _UnavailableGitOps(GitOps):
        def head(self, worktree, ref="HEAD"):
            raise GitProcessError(r"private executable C:\secret\git.exe")

    target = tmp_path / "external-repository"
    target.mkdir()
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=tmp_path / "session-artifacts",
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=_UnavailableGitOps(),
        quota_probe=_QuotaProbe(),
    )

    try:
        with pytest.raises(ValueError) as caught:
            _start(service, str(target.resolve()))

        message = str(caught.value)
        assert "verify Git is installed" in message
        assert "secret" not in message
        assert "GitProcessError" in caplog.text
        assert "secret" not in caplog.text
        assert repo.list_sessions(limit=10) == []
    finally:
        repo.close()


def test_unexpected_head_probe_bug_is_not_silently_downgraded(tmp_path: Path) -> None:
    class _BuggyHeadGitOps(GitOps):
        def head(self, worktree, ref="HEAD"):
            raise RuntimeError("head probe bug")

    target = tmp_path / "external-repository"
    target.mkdir()
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=tmp_path / "session-artifacts",
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=_BuggyHeadGitOps(),
        quota_probe=_QuotaProbe(),
    )

    try:
        with pytest.raises(RuntimeError, match="head probe bug"):
            _start(service, str(target.resolve()))
        assert repo.list_sessions(limit=10) == []
    finally:
        repo.close()


def test_generated_branch_probe_failure_is_not_reported_as_path_collision(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    class _ProbeFailureGitOps(GitOps):
        def branch_exists(self, target_worktree, branch_name):
            raise GitOperationError("private repository diagnostic")

    target = tmp_path / "external-repository"
    _init_repo(target)
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=tmp_path / "session-artifacts",
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=_ProbeFailureGitOps(),
        quota_probe=_QuotaProbe(),
    )

    try:
        with pytest.raises(ValueError) as caught:
            _start(service, str(target.resolve()))

        message = str(caught.value)
        assert message == (
            "target repository state could not be verified; verify Git access and retry"
        )
        assert "allocate external coding session paths" not in message
        assert "private repository diagnostic" not in message
        assert "GitOperationError" in caplog.text
        assert repo.list_sessions(limit=10) == []
        assert not (tmp_path / "session-artifacts").exists()
    finally:
        repo.close()


def test_unexpected_generated_branch_probe_bug_is_not_silently_downgraded(
    tmp_path: Path,
) -> None:
    class _BuggyGitOps(GitOps):
        def branch_exists(self, target_worktree, branch_name):
            raise AssertionError("branch probe bug")

    target = tmp_path / "external-repository"
    _init_repo(target)
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=tmp_path / "session-artifacts",
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=_BuggyGitOps(),
        quota_probe=_QuotaProbe(),
    )

    try:
        with pytest.raises(AssertionError, match="branch probe bug"):
            _start(service, str(target.resolve()))
    finally:
        repo.close()


def test_repository_without_commits_is_rejected_safely(tmp_path: Path) -> None:
    target = tmp_path / "empty-repository"
    _init_repo(target, commit=False)
    service, repo = _make_service(tmp_path)
    try:
        with pytest.raises(ValueError) as exc_info:
            _start(service, str(target))

        message = str(exc_info.value).lower()
        assert "usable git repository" in message
        assert "at least one commit" in message
        assert "fatal" not in message
        assert repo.list_sessions(limit=10) == []
        assert _git(target, "branch", "--format=%(refname:short)") == ""
    finally:
        repo.close()


def test_relative_worktree_root_is_resolved_from_external_target_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exemplar = tmp_path / "exemplar"
    target = tmp_path / "external-repository"
    _init_repo(exemplar)
    _init_repo(target)
    monkeypatch.chdir(exemplar)
    exemplar_before = _tree_entries(exemplar)
    service, repo = _make_service(tmp_path)
    created = None

    try:
        created = _start(service, str(target.resolve()))
        worktree = Path(created["worktreePath"])

        assert worktree.is_relative_to(target.resolve())
        assert worktree.parent == target.resolve() / ".worktrees" / "coding"
        assert _tree_entries(exemplar) == exemplar_before
        assert (
            created["branchName"]
            in _git(target, "branch", "--format=%(refname:short)").splitlines()
        )
        assert len(repo.list_sessions(limit=10)) == 1
    finally:
        _cleanup_created_worktree(target, created)
        repo.close()


def test_explicit_exemplar_target_repository_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exemplar = tmp_path / "exemplar"
    _init_repo(exemplar)
    monkeypatch.chdir(exemplar)
    service, repo = _make_service(tmp_path)
    created = None

    try:
        created = _start(service, str(exemplar.resolve()))
        assert Path(created["worktreePath"]).is_relative_to(exemplar.resolve())
        assert len(repo.list_sessions(limit=10)) == 1
    finally:
        _cleanup_created_worktree(exemplar, created)
        repo.close()


def test_absolute_worktree_root_remains_authoritative(tmp_path: Path) -> None:
    target = tmp_path / "external-repository"
    absolute_root = (tmp_path / "central-worktrees").resolve()
    _init_repo(target)
    service, repo = _make_service(tmp_path, worktree_root=absolute_root)
    created = None

    try:
        created = _start(service, str(target.resolve()))
        assert Path(created["worktreePath"]).parent == absolute_root
    finally:
        _cleanup_created_worktree(target, created)
        repo.close()


def test_relative_artifact_root_is_persisted_as_absolute_for_external_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exemplar = tmp_path / "exemplar"
    target = tmp_path / "external-repository"
    _init_repo(exemplar)
    _init_repo(target)
    monkeypatch.chdir(exemplar)
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=Path("data/coding_sessions"),
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=GitOps(),
        quota_probe=_QuotaProbe(),
    )
    created = None

    try:
        created = _start(service, str(target.resolve()))
        artifact_dir = Path(created["artifactDir"])
        artifact_paths = [
            artifact_dir,
            Path(created["artifacts"]["handoff"]["path"]),
            Path(created["artifacts"]["plan"]["path"]),
            Path(created["artifacts"]["result"]["path"]),
        ]

        assert all(path.is_absolute() for path in artifact_paths)
        assert artifact_dir.parent == exemplar.resolve() / "data" / "coding_sessions"
        handoff = artifact_paths[1].read_text(encoding="utf-8")
        assert str(artifact_paths[2]) in handoff
        assert str(artifact_paths[3]) in handoff
        assert str(Path(created["worktreePath"])) in handoff
    finally:
        _cleanup_created_worktree(target, created)
        repo.close()


def test_linked_worktree_is_a_valid_target_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    linked_target = tmp_path / "linked-target"
    _init_repo(repository)
    _git(repository, "worktree", "add", "-b", "linked-target", str(linked_target), "HEAD")
    service, repo = _make_service(tmp_path)
    created = None

    try:
        created = _start(service, str(linked_target.resolve()))
        row = repo.get_session(created["codingSessionId"])

        assert (linked_target / ".git").is_file()
        assert Path(created["worktreePath"]).is_relative_to(linked_target.resolve())
        assert row is not None
        assert row.base_commit == _git(linked_target, "rev-parse", "HEAD")
        assert row.target_worktree_path == str(linked_target.resolve())
    finally:
        _cleanup_created_worktree(linked_target, created)
        repo.close()
        GitOps().remove_worktree(
            target_worktree=repository,
            worktree_path=linked_target,
        )
        GitOps().delete_branch(target_worktree=repository, branch_name="linked-target")


def test_handoff_write_failure_removes_partial_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "external-repository"
    _init_repo(target)
    service, repo = _make_service(tmp_path)

    def _write_then_fail(artifact_dir, **_kwargs):
        artifact_dir.joinpath("HANDOFF.md").write_text("partial", encoding="utf-8")
        raise OSError("disk write failed at C:/private/path")

    monkeypatch.setattr(
        "src.business.external_coding.service.write_handoff",
        _write_then_fail,
    )

    try:
        with pytest.raises(ValueError, match="failed to create external coding artifacts"):
            _start(service, str(target.resolve()))

        assert repo.list_sessions(limit=10) == []
        assert not (tmp_path / "session-artifacts").exists()
        assert not (target / ".worktrees").exists()
    finally:
        repo.close()


def test_partial_artifact_directory_failure_is_compensated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "external-repository"
    _init_repo(target)
    service, repo = _make_service(tmp_path)

    def _create_then_fail(artifact_root, coding_session_id):
        artifact_dir = artifact_root / coding_session_id
        artifact_dir.joinpath("logs").mkdir(parents=True)
        raise OSError("artifact directory initialization failed")

    monkeypatch.setattr(
        "src.business.external_coding.service.ensure_artifact_dir",
        _create_then_fail,
    )

    try:
        with pytest.raises(ValueError, match="failed to create external coding artifacts"):
            _start(service, str(target.resolve()))

        assert repo.list_sessions(limit=10) == []
        assert not (tmp_path / "session-artifacts").exists()
        assert not (target / ".worktrees").exists()
    finally:
        repo.close()


def test_partial_worktree_creation_failure_is_cleaned_without_leaking_details(
    tmp_path: Path,
) -> None:
    class _CreateThenFailGitOps(GitOps):
        def create_worktree(self, *, target_worktree, worktree_path, branch_name):
            super().create_worktree(
                target_worktree=target_worktree,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )
            raise RuntimeError(f"fatal checkout failure in {worktree_path}")

    target = tmp_path / "external-repository"
    _init_repo(target)
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=tmp_path / "session-artifacts",
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=_CreateThenFailGitOps(),
        quota_probe=_QuotaProbe(),
    )
    initial_branches = _git(target, "branch", "--format=%(refname:short)").splitlines()

    try:
        with pytest.raises(ValueError) as exc_info:
            _start(service, str(target.resolve()))

        message = str(exc_info.value).lower()
        assert message == (
            "failed to create external coding worktree; verify the repository "
            "and configured worktree root"
        )
        assert "fatal" not in message
        assert str(target).lower() not in message
        assert repo.list_sessions(limit=10) == []
        assert not (target / ".worktrees" / "coding").exists()
        assert _git(target, "branch", "--format=%(refname:short)").splitlines() == initial_branches
        assert not (tmp_path / "session-artifacts").exists()
    finally:
        repo.close()


def test_session_persistence_failure_removes_worktree_branch_and_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "external-repository"
    _init_repo(target)
    service, repo = _make_service(tmp_path)
    initial_branches = _git(target, "branch", "--format=%(refname:short)").splitlines()

    def _fail_create_session(**_kwargs):
        raise RuntimeError("database write failed at C:/private/mexemplar.db")

    monkeypatch.setattr(repo, "create_session", _fail_create_session)

    try:
        with pytest.raises(ValueError, match="failed to persist external coding session"):
            _start(service, str(target.resolve()))

        assert repo.list_sessions(limit=10) == []
        assert not (target / ".worktrees" / "coding").exists()
        assert _git(target, "branch", "--format=%(refname:short)").splitlines() == initial_branches
        assert not (tmp_path / "session-artifacts").exists()
    finally:
        repo.close()


def test_unknown_session_persistence_outcome_returns_recovery_session_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = tmp_path / "external-repository"
    _init_repo(target)
    service, repo = _make_service(tmp_path)
    original_get_session = repo.get_session

    monkeypatch.setattr(
        repo,
        "create_session",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("commit outcome unknown")),
    )
    monkeypatch.setattr(
        repo,
        "get_session",
        lambda _coding_session_id: (_ for _ in ()).throw(ConnectionError("database offline")),
    )

    coding_session_id = None
    try:
        with pytest.raises(ValueError) as caught:
            _start(service, str(target.resolve()))

        message = str(caught.value)
        match = re.search(r"session (ecs_[a-f0-9]+)$", message)
        assert match is not None
        coding_session_id = match.group(1)
        assert "persistence could not be verified" in message
        assert "commit outcome unknown" not in message
        assert "database offline" not in message
        assert (target / ".worktrees" / "coding" / coding_session_id).is_dir()
        assert (tmp_path / "session-artifacts" / coding_session_id).is_dir()
        assert coding_session_id in caplog.text
        assert "create=OSError" in caplog.text
        assert "lookup=ConnectionError" in caplog.text
        assert "commit outcome unknown" not in caplog.text
        assert "database offline" not in caplog.text
    finally:
        monkeypatch.setattr(repo, "get_session", original_get_session)
        if coding_session_id is not None:
            worktree_path = target / ".worktrees" / "coding" / coding_session_id
            GitOps().remove_worktree(
                target_worktree=target,
                worktree_path=worktree_path,
            )
            subprocess.run(
                ["git", "branch", "-D", f"coding/{coding_session_id}"],
                cwd=target,
                text=True,
                capture_output=True,
                check=False,
            )
            shutil.rmtree(
                tmp_path / "session-artifacts" / coding_session_id,
                ignore_errors=True,
            )
        repo.close()


def test_failed_startup_preserves_preexisting_shared_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "external-repository"
    _init_repo(target)
    artifact_root = tmp_path / "session-artifacts"
    worktree_root = target / ".worktrees" / "coding"
    artifact_root.mkdir()
    worktree_root.mkdir(parents=True)
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=artifact_root,
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=GitOps(),
        quota_probe=_QuotaProbe(),
    )

    def _fail_create_session(**_kwargs):
        raise RuntimeError("database write failed")

    monkeypatch.setattr(repo, "create_session", _fail_create_session)

    try:
        with pytest.raises(ValueError, match="failed to persist external coding session"):
            _start(service, str(target.resolve()))

        assert artifact_root.is_dir()
        assert worktree_root.is_dir()
        assert list(artifact_root.iterdir()) == []
        assert list(worktree_root.iterdir()) == []
    finally:
        repo.close()


def test_cleanup_failure_is_reported_instead_of_claiming_zero_residue(
    tmp_path: Path,
) -> None:
    class _CreateThenCleanupFailsGitOps(GitOps):
        def create_worktree(self, *, target_worktree, worktree_path, branch_name):
            super().create_worktree(
                target_worktree=target_worktree,
                worktree_path=worktree_path,
                branch_name=branch_name,
            )
            raise RuntimeError("checkout failed")

        def remove_worktree(self, *, target_worktree, worktree_path):
            raise RuntimeError("worktree is locked")

    target = tmp_path / "external-repository"
    _init_repo(target)
    repo = ExternalCodingSessionRepository()
    service = ExternalCodingSessionService(
        repo=repo,
        config=_Config(
            artifact_root=tmp_path / "session-artifacts",
            worktree_root=Path(".worktrees/coding"),
        ),
        git_ops=_CreateThenCleanupFailsGitOps(),
        quota_probe=_QuotaProbe(),
    )

    try:
        with pytest.raises(ValueError, match="cleanup could not be completed") as exc_info:
            _start(service, str(target.resolve()))

        assert "locked" not in str(exc_info.value).lower()
        assert repo.list_sessions(limit=10) == []
    finally:
        for path in (target / ".worktrees" / "coding").glob("ecs_*"):
            GitOps().remove_worktree(target_worktree=target, worktree_path=path)
        for branch in _git(target, "branch", "--format=%(refname:short)").splitlines():
            if branch.startswith("coding/ecs_"):
                GitOps().delete_branch(target_worktree=target, branch_name=branch)
        repo.close()


def test_generated_branch_collision_is_rejected_without_deleting_existing_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "external-repository"
    _init_repo(target)
    _git(target, "branch", "coding/ecs_collision")
    monkeypatch.setattr(
        "src.business.external_coding.service.generate_id",
        lambda _prefix: "ecs_collision",
    )
    service, repo = _make_service(tmp_path)

    try:
        with pytest.raises(ValueError, match="failed to allocate"):
            _start(service, str(target.resolve()))

        branches = _git(target, "branch", "--format=%(refname:short)").splitlines()
        assert "coding/ecs_collision" in branches
        assert repo.list_sessions(limit=10) == []
        assert not (tmp_path / "session-artifacts").exists()
    finally:
        repo.close()


def test_start_tool_schema_requires_an_explicit_target_repository() -> None:
    tool = next(
        tool
        for tool in create_external_coding_tools(
            session_id="sess_test", bound_task_id="tsk_target_repository"
        )
        if tool.name == "start_external_coding_session"
    )
    parameters = tool.schema["function"]["parameters"]
    description = parameters["properties"]["targetWorktreePath"]["description"]

    assert "targetWorktreePath" in parameters["required"]
    assert "绝对路径" in description
    assert "可用的 git 仓库" in description
    assert "不填" in description
    assert "Exemplar" in description
