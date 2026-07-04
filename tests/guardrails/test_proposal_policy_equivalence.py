"""Proposal policy equivalence tests (P3).

Verifies that the three detection sites (proposal_policy, builtin_permissions
fallback, task_executor_adapter string check) agree on improvement workspace
detection, and that the session prefix constant is consistent across modules.
"""

import pytest

from src.utils.proposal_policy import (
    SELF_IMPROVEMENT_SESSION_PREFIX,
    is_improvement_workspace_root,
    is_improvement_workspace_root_str,
    is_proposal_session,
    extract_proposal_id,
)


class TestWorkspaceDetectionEquivalence:
    """Path-based and string-based workspace detection must agree."""

    @pytest.mark.parametrize(
        "workspace_root",
        [
            "/home/user/project/.worktrees/improvement/prop_123",
            "E:\\code\\Exemplar\\.worktrees\\improvement\\prop_win",
            "/tmp/project/.worktrees/improvement/abc",
        ],
    )
    def test_path_and_string_checks_agree_on_valid_worktrees(self, workspace_root):
        assert is_improvement_workspace_root(workspace_root) == \
            is_improvement_workspace_root_str(workspace_root), \
            f"Path and string checks disagree for {workspace_root}"

    @pytest.mark.parametrize(
        "workspace_root",
        [
            "/home/user/project/src",
            "/home/user/project/.worktrees/other/prop_123",
            "/home/user/project",
            "",
            None,
        ],
    )
    def test_path_and_string_checks_agree_on_invalid_worktrees(self, workspace_root):
        assert is_improvement_workspace_root(workspace_root or "") == \
            is_improvement_workspace_root_str(workspace_root), \
            f"Path and string checks disagree for {workspace_root}"

    def test_main_repo_rejected(self):
        assert not is_improvement_workspace_root("E:\\code\\Exemplar")
        assert not is_improvement_workspace_root_str("E:\\code\\Exemplar")

    def test_improvement_worktree_accepted(self):
        assert is_improvement_workspace_root("E:\\code\\Exemplar\\.worktrees\\improvement\\prop_ok")
        assert is_improvement_workspace_root_str("E:\\code\\Exemplar\\.worktrees\\improvement\\prop_ok")

    def test_bare_improvement_dir_rejected(self):
        """`/.worktrees/improvement/` without a proposal ID must be rejected."""
        assert not is_improvement_workspace_root_str("/project/.worktrees/improvement/")


class TestSessionPrefixConsistency:
    """Session prefix must be consistent across modules."""

    def test_proposal_bridge_prefix_matches_policy(self):
        from src.business.self_improvement.proposal_bridge import (
            SELF_IMPROVEMENT_SESSION_PREFIX as bridge_prefix,
        )
        assert bridge_prefix == SELF_IMPROVEMENT_SESSION_PREFIX

    def test_executor_adapter_uses_proposal_policy(self):
        """task_executor_adapter 不再保留本地前缀别名，直接使用 proposal_policy。"""
        import src.business.orchestration.agent.task_executor_adapter as adapter_mod

        assert not hasattr(adapter_mod, "_SELF_IMPROVEMENT_SESSION_PREFIX"), (
            "adapter should not retain local prefix alias; use proposal_policy.is_proposal_session instead"
        )

    def test_is_proposal_session(self):
        assert is_proposal_session("self_improvement:prop_123")
        assert not is_proposal_session("regular_session")
        assert not is_proposal_session(None)
        assert not is_proposal_session("")

    def test_extract_proposal_id(self):
        assert extract_proposal_id("self_improvement:prop_123") == "prop_123"
        assert extract_proposal_id("regular_session") is None
        assert extract_proposal_id(None) is None


class TestBuiltinPermissionsFallback:
    """builtin_permissions fallback must match proposal_policy when available."""

    def test_fallback_agrees_with_policy_on_valid_worktree(self):
        from src.business.agents.tools.builtin_permissions import (
            _looks_like_improvement_workspace_root,
        )
        path = "E:\\code\\Exemplar\\.worktrees\\improvement\\prop_ok"
        assert _looks_like_improvement_workspace_root(path) == \
            is_improvement_workspace_root(path)

    def test_fallback_agrees_with_policy_on_invalid_path(self):
        from src.business.agents.tools.builtin_permissions import (
            _looks_like_improvement_workspace_root,
        )
        path = "E:\\code\\Exemplar\\src"
        assert _looks_like_improvement_workspace_root(path) == \
            is_improvement_workspace_root(path)

    def test_fallback_agrees_with_policy_on_none(self):
        from src.business.agents.tools.builtin_permissions import (
            _looks_like_improvement_workspace_root,
        )
        # Both should return False for empty/invalid paths
        assert not _looks_like_improvement_workspace_root("")
        assert not is_improvement_workspace_root("")
