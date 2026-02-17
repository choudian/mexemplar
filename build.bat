@echo off
chcp 65001 >nul
title Mexemplar - 打包应用

echo ============================================================
echo Mexemplar - 打包成可执行文件
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

echo [1/3] 安装依赖...
uv sync --group dev
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo.

echo [2/3] 打包应用（使用 PyInstaller）...
uv run pyinstaller build_exe.spec --clean
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)
echo.

echo [3/3] 打包完成！
echo.
echo 可执行文件位置: dist\Mexemplar.exe
echo.
echo 你可以:
echo 1. 直接运行 dist\Mexemplar.exe
echo 2. 创建快捷方式到桌面
echo 3. 分发给其他用户（无需安装 Python）
echo.
pause
