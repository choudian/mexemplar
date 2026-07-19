"""桌面 sidecar 构建脚本必须 fail-fast，且不得回退到 legacy GUI 入口。"""

from __future__ import annotations

from pathlib import Path


def _script_text() -> str:
    return Path("scripts/build_desktop_sidecar.ps1").read_text(encoding="utf-8")


def test_sidecar_build_targets_desktop_api_and_checks_native_exit_code() -> None:
    source = _script_text()

    assert "src/desktop_api/__main__.py" in source
    assert "src/main.py" not in source
    assert "src/ui/resources" not in source
    assert "$LASTEXITCODE -ne 0" in source


def test_sidecar_build_cannot_copy_a_stale_fuzzy_candidate() -> None:
    source = _script_text()

    assert "Remove-Item -LiteralPath $candidate" in source
    assert 'Join-Path "dist" "$SidecarName$extension"' in source
    assert 'Get-ChildItem -Path "dist" -Recurse' not in source


def test_sidecar_build_keeps_generated_spec_out_of_the_repository_root() -> None:
    source = _script_text()

    assert '--specpath "build"' in source
    assert '$entryPoint = Join-Path $rootPath "src/desktop_api/__main__.py"' in source
    assert (
        '$browserExtensionSource = Join-Path $rootPath "src/recording/browser_extension"' in source
    )
    assert "--paths $rootPath" in source
