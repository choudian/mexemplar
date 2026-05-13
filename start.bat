@echo off
chcp 65001 >nul
echo Legacy PyQt launch is no longer supported.
echo Use "cd frontend && npm run tauri dev" for development.
echo Use "build_tauri.bat" to build the packaged desktop app.
exit /b 2
