#!/usr/bin/env python3
"""Build the Python desktop API sidecar used by the Tauri shell."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SIDECAR_NAME = "mexamplar-sidecar"
WINDOWS_TRIPLE = "x86_64-pc-windows-msvc"


def project_root() -> Path:
    return Path(__file__).resolve().parent


def clean() -> None:
    root = project_root()
    for path in [root / "build" / SIDECAR_NAME, root / "dist" / f"{SIDECAR_NAME}.exe"]:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def build_sidecar() -> Path:
    root = project_root()
    entry = root / "src" / "desktop_api" / "__main__.py"
    if not entry.exists():
        raise FileNotFoundError(f"Sidecar entrypoint not found: {entry}")
    browser_extension = root / "src" / "recording" / "browser_extension"
    if not browser_extension.exists():
        raise FileNotFoundError(f"Browser recording extension not found: {browser_extension}")
    browser_extension_dest = Path("src") / "recording" / "browser_extension"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        f"--name={SIDECAR_NAME}",
        f"--workpath={root / 'build'}",
        f"--distpath={root / 'dist'}",
        "--clean",
        "--collect-submodules=uvicorn",
        "--collect-submodules=fastapi",
        "--collect-submodules=sqlglot",
        "--collect-data=tldextract",
        "--hidden-import=sqlite_vec",
        f"--add-data={browser_extension}{os.pathsep}{browser_extension_dest}",
        str(entry),
    ]
    subprocess.run(cmd, cwd=root, check=True)
    sidecar = root / "dist" / f"{SIDECAR_NAME}.exe"
    if not sidecar.exists():
        raise FileNotFoundError(f"PyInstaller did not produce {sidecar}")
    return sidecar


def copy_for_tauri(sidecar: Path) -> Path:
    root = project_root()
    target_dir = root / "src-tauri" / "binaries"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{SIDECAR_NAME}-{WINDOWS_TRIPLE}.exe"
    shutil.copy2(sidecar, target)
    return target


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        clean()
        return 0
    try:
        sidecar = build_sidecar()
        target = copy_for_tauri(sidecar)
        print(f"Built sidecar: {sidecar}")
        print(f"Copied for Tauri: {target}")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"Sidecar build failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode
    except Exception as exc:
        print(f"Sidecar build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
