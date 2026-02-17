@echo off
chcp 65001 >nul
title Mexemplar - 智能办公助理 (开发模式)

echo ============================================================
echo Mexemplar - 智能办公助理 (开发模式)
echo ============================================================
echo.

REM 启动应用（开发模式，保留窗口）
uv run python -m src.main --gui

echo.
echo 应用已退出
pause
