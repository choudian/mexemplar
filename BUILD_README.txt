==========================================
Mexemplar Tauri + Python Sidecar Build
==========================================

The maintained desktop build is now:

1. React frontend under frontend/
2. Tauri shell under src-tauri/
3. Python FastAPI sidecar from src.desktop_api.__main__

Build steps:

  uv sync
  cd frontend
  npm install
  cd ..
  build_tauri.bat

`build_tauri.bat` runs:

  uv run python build_executable.py
  cd frontend
  npm run tauri build

The Python sidecar is copied to:

  src-tauri/binaries/mexamplar-sidecar-x86_64-pc-windows-msvc.exe

Tauri bundles that sidecar through `src-tauri/tauri.conf.json`.
The default Windows bundle target is NSIS to avoid requiring WiX/MSI tooling
on every build machine.

Legacy PyQt launchers are no longer a supported packaging target.
