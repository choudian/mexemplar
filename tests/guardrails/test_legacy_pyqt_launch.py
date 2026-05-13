from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_tauri_launch_uses_sidecar_binary_not_legacy_pyqt_entrypoint() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    external_bins = config["bundle"]["externalBin"]
    assert "binaries/mexamplar-sidecar" in external_bins
    assert all("mexamplar_gui" not in item and "src/main.py" not in item for item in external_bins)


def test_desktop_api_sidecar_entrypoint_does_not_import_pyqt_ui() -> None:
    entrypoint = (ROOT / "src" / "desktop_api" / "__main__.py").read_text(encoding="utf-8")
    forbidden_fragments = [
        "PyQt6",
        "src.ui",
        "main_window",
        "mexamplar_gui",
    ]
    for fragment in forbidden_fragments:
        assert fragment not in entrypoint


def test_inno_installer_targets_tauri_release_executable() -> None:
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    cargo = (ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")

    assert 'name = "mexemplar-desktop"' in cargo
    assert '#define AppExeName "mexemplar-desktop.exe"' in installer
    assert '#define AppExeName "mexamplar.exe"' not in installer
