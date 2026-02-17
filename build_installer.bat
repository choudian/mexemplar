@echo off
chcp 65001 >nul
title Mexemplar - 打包并创建安装程序

echo ============================================================
echo Mexemplar - 打包应用并创建安装程序
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

echo [1/4] 安装依赖...
uv sync --group dev
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)
echo.

echo [2/4] 打包应用（使用 PyInstaller）...
uv run pyinstaller build_exe.spec --clean
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 打包失败
    pause
    exit /b 1
)
echo.

echo [3/4] 检查 Inno Setup...
where iscc >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [警告] 未找到 Inno Setup，跳过安装程序创建
    echo.
    echo 如需创建安装程序，请安装 Inno Setup:
    echo https://jrsoftware.org/isdl.php
    echo.
    goto :skip_installer
)

echo [4/4] 创建安装程序...
iscc installer.iss
if %ERRORLEVEL% NEQ 0 (
    echo [错误] 安装程序创建失败
    pause
    exit /b 1
)

:skip_installer
echo.
echo ============================================================
echo 打包完成！
echo ============================================================
echo.
if exist "installer\Mexemplar-Setup-0.1.0.exe" (
    echo 安装程序位置: installer\Mexemplar-Setup-0.1.0.exe
    echo.
    echo 你可以:
    echo 1. 双击运行 installer\Mexemplar-Setup-0.1.0.exe 安装应用
    echo 2. 分发安装程序给其他用户
) else (
    echo 可执行文件位置: dist\Mexemplar.exe
    echo.
    echo 你可以:
    echo 1. 直接运行 dist\Mexemplar.exe
    echo 2. 手动创建快捷方式
    echo 3. 分发给其他用户（需要附带依赖文件）
)
echo.
pause
