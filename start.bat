@echo off
chcp 65001 >nul
title Mexemplar - 智能办公助理

echo ============================================================
echo Mexemplar - 智能办公助理
echo ============================================================
echo.

REM 检查 uv 是否安装
where uv >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 未找到 uv，请先安装 uv:
    echo pip install uv
    pause
    exit /b 1
)

REM 启动应用
uv run python -m src.main --gui

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] 应用启动失败
    pause
    exit /b 1
)
