"""Workspace root resolution and hashing helpers.

Pure stdlib utilities shared across layers. Kept in ``utils`` so the data
layer can hash a workspace root without importing business code, preserving
the data -> business layering boundary.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def resolve_workspace_root(workspace_root: Path | str | None = None) -> Path:
    return Path(workspace_root or Path.cwd()).expanduser().resolve()


def workspace_hash(workspace_root: Path | str | None = None) -> str:
    root = resolve_workspace_root(workspace_root)
    return hashlib.sha256(str(root).encode("utf-8", errors="replace")).hexdigest()
