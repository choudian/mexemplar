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


def test_tauri_shell_kills_sidecar_on_window_and_app_exit() -> None:
    lib = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    sidecar = (ROOT / "src-tauri" / "src" / "sidecar.rs").read_text(encoding="utf-8")
    window = (ROOT / "src-tauri" / "src" / "window.rs").read_text(encoding="utf-8")

    assert "pub fn kill_sidecar(app: &AppHandle)" in sidecar
    assert "state.kill();" in sidecar
    assert "kill_process_tree(child.pid())" in sidecar
    assert "kill_stale_sidecars_for_current_binary()" in sidecar
    assert "taskkill.exe" in sidecar
    assert "crate::sidecar::kill_sidecar(window.app_handle())" in window
    assert ".on_window_event(" in lib
    assert "tauri::WindowEvent::CloseRequested" in lib
    assert "tauri::WindowEvent::Destroyed" in lib
    assert "tauri::RunEvent::ExitRequested" in lib
    assert "tauri::RunEvent::Exit" in lib


def test_tauri_sidecar_output_is_written_to_data_log_file() -> None:
    sidecar = (ROOT / "src-tauri" / "src" / "sidecar.rs").read_text(encoding="utf-8")

    assert 'data_dir.join("logs")' in sidecar
    assert 'log_dir.join("sidecar.log")' in sidecar
    assert "CommandEvent::Stdout(bytes)" in sidecar
    assert "CommandEvent::Stderr(bytes)" in sidecar
    assert 'write_sidecar_output(&mut sidecar_log, "stdout", &bytes)' in sidecar
    assert 'write_sidecar_output(&mut sidecar_log, "stderr", &bytes)' in sidecar
    assert ".current_dir(&working_dir)" in sidecar
    assert 'env("PYTHONIOENCODING", "utf-8")' in sidecar
    assert 'env("PYTHONUTF8", "1")' in sidecar
    assert "resolve_playwright_browsers_path()" in sidecar
    assert '"PLAYWRIGHT_BROWSERS_PATH"' in sidecar
    assert '"ms-playwright"' in sidecar
    assert "cfg!(debug_assertions)" in sidecar
    assert 'command = command.arg("--verbose")' in sidecar


def test_sidecar_build_includes_browser_extension_resources() -> None:
    build_script = (ROOT / "build_executable.py").read_text(encoding="utf-8")

    assert '"browser_extension"' in build_script
    assert "--collect-submodules=sqlglot" in build_script
    assert "--collect-data=tldextract" in build_script
    assert "--add-data" in build_script
    assert "src\" / \"recording\" / \"browser_extension" in build_script
