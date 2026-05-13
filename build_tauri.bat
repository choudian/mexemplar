@echo off
setlocal
cd /d %~dp0

echo Building Python sidecar...
uv run python build_executable.py
if errorlevel 1 exit /b %errorlevel%

cd frontend
echo Building Tauri app...
npm run tauri build
if errorlevel 1 exit /b %errorlevel%
endlocal
