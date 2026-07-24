"""Where the packaged app keeps its data.

Data lives beside the executable so the whole install folder can be moved or
backed up as one unit. Program Files is the exception: a non-elevated process
cannot write there, and failing to fall back would leave the sidecar unable to
start with an error nobody can act on.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.utils import helpers


def test_explicit_env_var_wins_over_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path / "chosen"))

    assert helpers.get_default_data_dir() == tmp_path / "chosen"


def test_blank_env_var_is_ignored(monkeypatch):
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", "   ")

    # A blank value means "not configured", not "use the empty path".
    assert helpers.get_default_data_dir() == Path(helpers.__file__).parents[2] / "data"


def test_development_run_uses_the_repo_data_dir(monkeypatch):
    monkeypatch.delenv("EXEMPLAR_DATA_DIR", raising=False)
    monkeypatch.setattr(helpers.sys, "frozen", False, raising=False)

    assert helpers.get_default_data_dir() == Path(helpers.__file__).parents[2] / "data"


def test_packaged_run_puts_data_next_to_the_executable(monkeypatch, tmp_path):
    install_dir = tmp_path / "mnt" / "test"
    install_dir.mkdir(parents=True)
    monkeypatch.delenv("EXEMPLAR_DATA_DIR", raising=False)
    monkeypatch.setattr(helpers.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        helpers.sys, "executable", str(install_dir / "app.exe"), raising=False
    )

    assert helpers.get_default_data_dir() == install_dir / "data"


def test_unwritable_install_dir_falls_back_to_user_data(monkeypatch, tmp_path):
    fallback = tmp_path / "localappdata"
    monkeypatch.delenv("EXEMPLAR_DATA_DIR", raising=False)
    monkeypatch.setattr(helpers.sys, "frozen", True, raising=False)
    monkeypatch.setattr(helpers.sys, "executable", str(tmp_path / "pf" / "app.exe"))
    monkeypatch.setenv("LOCALAPPDATA", str(fallback))
    monkeypatch.setattr(
        helpers, "_install_dir_data_dir", lambda: None
    )  # stands in for Program Files

    assert helpers.get_default_data_dir() == fallback / "Mexemplar" / "data"


def test_write_probe_reports_unwritable_paths(monkeypatch):
    # The probe is what distinguishes "install dir" from "Program Files"; if it
    # ever silently returned a path, the sidecar would fail at first write.
    monkeypatch.setattr(helpers.sys, "executable", "", raising=False)

    assert helpers._install_dir_data_dir() is None


def test_write_probe_leaves_no_residue(monkeypatch, tmp_path):
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    monkeypatch.setattr(helpers.sys, "executable", str(install_dir / "app.exe"))

    resolved = helpers._install_dir_data_dir()

    assert resolved == install_dir / "data"
    assert list(resolved.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="repo layout probe is path-shaped")
def test_repo_checkout_still_wins_for_a_frozen_binary_inside_it(monkeypatch, tmp_path):
    # A packaged binary run from inside a checkout should use that checkout's
    # data dir, so developers do not get a second, surprising database.
    repo = tmp_path / "repo"
    for name in ("src-tauri", "frontend", "src"):
        (repo / name).mkdir(parents=True)
    monkeypatch.delenv("EXEMPLAR_DATA_DIR", raising=False)
    monkeypatch.setattr(helpers.sys, "frozen", True, raising=False)
    monkeypatch.setattr(helpers.sys, "executable", str(repo / "dist" / "app.exe"))

    assert helpers.get_default_data_dir() == repo / "data"
