from __future__ import annotations

import sys

from src.utils.helpers import get_default_data_dir


def test_get_default_data_dir_prefers_explicit_env(monkeypatch, tmp_path):
    configured = tmp_path / "configured-data"
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(configured))

    assert get_default_data_dir() == configured
    assert configured.exists()


def test_get_default_data_dir_uses_repo_data_for_frozen_dev_sidecar(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    for name in ("src-tauri", "frontend", "src"):
        (repo / name).mkdir(parents=True)

    executable = repo / "src-tauri" / "target" / "debug" / "mexamplar-sidecar.exe"
    monkeypatch.delenv("EXEMPLAR_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert get_default_data_dir() == repo / "data"
    assert (repo / "data").exists()


def test_get_default_data_dir_uses_install_dir_for_frozen_packaged_sidecar(
    monkeypatch, tmp_path
):
    # Data sits beside the program so the whole install folder moves as one unit:
    # installed to E:\mnt\test → data in E:\mnt\test\data.
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    executable = install_dir / "mexamplar-sidecar.exe"
    monkeypatch.delenv("EXEMPLAR_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    expected = install_dir / "data"
    assert get_default_data_dir() == expected
    assert expected.exists()


def test_get_default_data_dir_falls_back_to_local_app_data_when_install_dir_is_readonly(
    monkeypatch, tmp_path
):
    # Program Files installed without elevation: writing beside the exe fails,
    # and without this fallback the sidecar could not start at all.
    local_app_data = tmp_path / "local-app-data"
    monkeypatch.delenv("EXEMPLAR_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pf" / "sidecar.exe"))
    monkeypatch.setattr("src.utils.helpers._install_dir_data_dir", lambda: None)

    expected = local_app_data / "Mexemplar" / "data"
    assert get_default_data_dir() == expected
    assert expected.exists()
