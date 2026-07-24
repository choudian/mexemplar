"""Read-only resources must resolve both in the repo and inside the bundle.

This class of bug is invisible during development: `Path.cwd()` happens to be
the repo root, so everything works — and then fails only on an installed
machine, where cwd is the install directory and no source tree exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.utils.helpers import bundled_resource_path


def test_resolves_against_the_repo_root_during_development(monkeypatch):
    monkeypatch.delattr("sys._MEIPASS", raising=False)

    resolved = bundled_resource_path("src/business/brain/seed")

    assert resolved.is_dir()


def test_resolves_against_the_extraction_dir_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    resolved = bundled_resource_path("src/business/brain/seed/x.md")

    assert resolved == tmp_path / "src/business/brain/seed/x.md"


def test_never_depends_on_the_working_directory(monkeypatch, tmp_path):
    # cwd is the install directory once packaged; anything derived from it
    # points at a source tree that is not there.
    monkeypatch.delattr("sys._MEIPASS", raising=False)
    monkeypatch.chdir(tmp_path)

    assert bundled_resource_path("src/business/brain/seed").is_dir()


def test_accepts_both_str_and_path(monkeypatch, tmp_path):
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    assert bundled_resource_path("a/b") == bundled_resource_path(Path("a") / "b")


@pytest.mark.parametrize(
    "relative",
    [
        "src/business/brain/seed/how_to_create_skill_methodology.md",
        "src/business/brain/seed/coding_executor_specialist.md",
    ],
)
def test_every_seed_file_shipped_is_actually_present(relative):
    # If a seed file is added without also adding it to the PyInstaller
    # --add-data list, the packaged app raises FileNotFoundError at startup.
    resolved = bundled_resource_path(relative)

    assert resolved.is_file(), f"missing seed resource: {relative}"
    assert resolved.read_text(encoding="utf-8").strip()


def test_build_script_bundles_the_whole_seed_directory():
    # The guard that keeps the two lists from drifting apart.
    build_script = bundled_resource_path("build_executable.py").read_text(encoding="utf-8")

    assert "brain_seed" in build_script
    assert "--add-data={brain_seed}" in build_script
