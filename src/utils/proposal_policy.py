"""Proposal executor policy constants and pure helpers.

Low-level, no business-layer imports.  Used by:
- ``self_improvement.proposal_workspace`` (business layer)
- ``agents.tools.builtin_permissions`` (guard layer, fail-closed fallback)
- ``orchestration.agent.task_executor_adapter`` (execution layer)

Keeping these facts here avoids circular imports and ensures a single source
of truth for the proposal executor identity and workspace layout.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Session prefix
# ---------------------------------------------------------------------------

SELF_IMPROVEMENT_SESSION_PREFIX = "self_improvement:"


def is_proposal_session(session_id: str | None) -> bool:
    """Return whether *session_id* identifies a proposal executor session."""
    return bool(session_id and session_id.startswith(SELF_IMPROVEMENT_SESSION_PREFIX))


def extract_proposal_id(session_id: str | None) -> str | None:
    """Extract the proposal_id from a proposal executor session, or None."""
    if not session_id or not session_id.startswith(SELF_IMPROVEMENT_SESSION_PREFIX):
        return None
    return session_id[len(SELF_IMPROVEMENT_SESSION_PREFIX) :]


# ---------------------------------------------------------------------------
# Workspace layout
# ---------------------------------------------------------------------------

WORKTREES_DIR = ".worktrees"
IMPROVEMENT_DIR = "improvement"


def is_improvement_workspace_root(workspace_root: Path | str) -> bool:
    """Return whether *workspace_root* is a proposal implementation worktree.

    Checks the ``.worktrees/improvement/<proposal_id>`` layout using
    ``Path``-based directory name comparison.
    """
    try:
        root = Path(workspace_root).expanduser().resolve(strict=False)
    except Exception:
        return False
    return (
        root.parent.name.lower() == IMPROVEMENT_DIR
        and root.parent.parent.name.lower() == WORKTREES_DIR
    )


def is_improvement_workspace_root_str(workspace_root: str | None) -> bool:
    """String-level check for improvement worktree (no Path imports needed).

    Used by the execution layer where a conservative substring match is
    preferred over Path resolution (avoids OS-specific path semantics).
    """
    raw = str(workspace_root or "").replace("\\", "/").lower()
    return (
        f"/{WORKTREES_DIR}/{IMPROVEMENT_DIR}/" in raw
        and not raw.endswith(f"/{WORKTREES_DIR}/{IMPROVEMENT_DIR}/")
    )


def improvement_worktree_branch_name(proposal_id: str) -> str:
    """Compute the git branch name for a proposal worktree."""
    return f"{IMPROVEMENT_DIR}/{proposal_id}"
