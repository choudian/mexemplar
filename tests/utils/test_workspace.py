from __future__ import annotations

import hashlib
from pathlib import Path

from src.utils.workspace import resolve_workspace_root, workspace_hash


def test_workspace_hash_is_sha256_of_resolved_root(tmp_path):
    expected = hashlib.sha256(str(tmp_path.resolve()).encode("utf-8", errors="replace")).hexdigest()
    assert workspace_hash(tmp_path) == expected


def test_workspace_hash_path_and_str_inputs_are_equivalent(tmp_path):
    assert workspace_hash(tmp_path) == workspace_hash(str(tmp_path))


def test_workspace_hash_is_stable_across_calls(tmp_path):
    assert workspace_hash(tmp_path) == workspace_hash(tmp_path)


def test_workspace_hash_distinct_roots_differ(tmp_path):
    assert workspace_hash(tmp_path) != workspace_hash(tmp_path.parent)


def test_workspace_hash_none_uses_cwd():
    assert workspace_hash(None) == workspace_hash(Path.cwd())


def test_workspace_hash_returns_64_char_hex(tmp_path):
    value = workspace_hash(tmp_path)
    assert len(value) == 64
    int(value, 16)  # 合法 hex


def test_resolve_workspace_root_defaults_to_cwd():
    assert resolve_workspace_root() == Path.cwd().resolve()


def test_resolve_workspace_root_accepts_str_or_path(tmp_path):
    assert resolve_workspace_root(tmp_path) == tmp_path.resolve()
    assert resolve_workspace_root(str(tmp_path)) == tmp_path.resolve()
