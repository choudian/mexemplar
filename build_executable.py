#!/usr/bin/env python3
"""
打包 Mexemplar 为独立可执行文件

使用 PyInstaller 将项目打包为独立的可执行文件，无需安装 Python 环境即可运行。

重要说明：
- PyInstaller 会将 Python 运行时和所有依赖打包到可执行文件中
- 打包后的 .exe 文件是完全独立的，无需安装 Python 即可运行
- 用户只需要双击 .exe 文件即可使用

支持平台：
- Windows: 生成 .exe 文件
- macOS: 生成 .app 文件
- Linux: 生成可执行文件

使用方法：
    python build_executable.py

输出目录：
    dist/Mexemplar.exe (Windows)
    dist/Mexemplar (macOS/Linux)
"""

import sys
import shutil
import subprocess
from pathlib import Path


def get_project_root() -> Path:
    """获取项目根目录"""
    # 脚本在项目根目录，直接返回父目录
    return Path(__file__).parent.resolve()


def check_icon() -> Path:
    """检查图标文件是否存在"""
    project_root = get_project_root()
    icon_path = project_root / "src" / "ui" / "resources" / "icons" / "app_icon.ico"

    if not icon_path.exists():
        print(f"⚠️  警告: 图标文件不存在: {icon_path}")
        print("   将使用默认图标（或不使用图标）")
        return None

    return icon_path


def build_executable() -> int:
    """使用 PyInstaller 打包可执行文件"""
    project_root = get_project_root()

    print("=" * 60)
    print("Mexemplar 可执行文件打包工具")
    print("=" * 60)
    print()

    # 检查 PyInstaller 是否安装
    try:
        import PyInstaller

        print(f"✓ PyInstaller 版本: {PyInstaller.__version__}")
    except ImportError:
        print("✗ 错误: PyInstaller 未安装")
        print()
        print("请先安装 PyInstaller:")
        print("  uv sync --dev")
        return 1

    print()

    # 确定入口文件
    entry_script = project_root / "mexemplar_gui.py"
    if not entry_script.exists():
        print(f"✗ 错误: 入口文件不存在: {entry_script}")
        return 1

    print(f"✓ 入口文件: {entry_script}")
    print()

    # 检查图标
    icon_path = check_icon()

    # 构建 PyInstaller 命令
    cmd = [
        "pyinstaller",
        "--onefile",  # 打包为单个文件
        "--name=Mexemplar",  # 可执行文件名称
        f"--work-path={project_root / 'build'}",  # 工作目录
        f"--dist-path={project_root / 'dist'}",  # 输出目录
        "--clean",  # 清理缓存
    ]

    # 添加图标（如果存在）
    if icon_path:
        cmd.append(f"--icon={icon_path}")
        print(f"✓ 使用图标: {icon_path}")

    # GUI 模式（不显示控制台）
    if sys.platform == "win32":
        cmd.append("--windowed")
        print("✓ 模式: GUI（无控制台）")
    else:
        # macOS 和 Linux 也使用窗口模式
        cmd.append("--windowed")
        print("✓ 模式: GUI")

    print()

    # 添加数据文件
    data_files = [
        ("src", "src"),  # 源代码目录
    ]

    for src, dst in data_files:
        src_path = project_root / src
        if src_path.exists():
            cmd.append(
                f"--add-data={src};{dst}" if sys.platform == "win32" else f"--add-data={src}:{dst}"
            )
            print(f"✓ 添加数据: {src} -> {dst}")

    # 添加隐藏导入
    hidden_imports = [
        "PyQt6",
        "PyQt6.QtWidgets",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "playwright",
        "anthropic",
        "blinker",
        "duckdb",
        "keyring",
        "websockets",
    ]

    for module in hidden_imports:
        cmd.append(f"--hidden-import={module}")

    print()
    print(f"✓ 添加 {len(hidden_imports)} 个隐藏导入模块")

    # 添加收集模块
    collect_modules = [
        "PyQt6",
        "playwright",
    ]

    for module in collect_modules:
        cmd.append(f"--collect-module={module}")

    print(f"✓ 收集 {len(collect_modules)} 个模块及其依赖")

    print()
    print("=" * 60)
    print("开始打包...")
    print("=" * 60)
    print()

    # 添加入口脚本
    cmd.append(str(entry_script))

    # 打印完整命令（调试用）
    print("命令:", " ".join(cmd))
    print()

    # 执行打包
    try:
        subprocess.run(cmd, cwd=project_root, check=True)
        print()
        print("=" * 60)
        print("✓ 打包成功！")
        print("=" * 60)
        print()

        # 确定输出文件路径
        if sys.platform == "win32":
            exe_path = project_root / "dist" / "Mexemplar.exe"
        elif sys.platform == "darwin":
            exe_path = project_root / "dist" / "Mexemplar.app"
        else:
            exe_path = project_root / "dist" / "Mexemplar"

        if exe_path.exists():
            file_size = exe_path.stat().st_size / (1024 * 1024)  # MB
            print(f"✓ 可执行文件: {exe_path}")
            print(f"✓ 文件大小: {file_size:.2f} MB")
            print()
            print("现在可以双击运行可执行文件了！")
        else:
            print("⚠️  警告: 输出文件不存在，请检查打包日志")

        return 0

    except subprocess.CalledProcessError as e:
        print()
        print("=" * 60)
        print("✗ 打包失败")
        print("=" * 60)
        print()
        print(f"错误代码: {e.returncode}")
        print("请检查上面的错误信息")
        return 1
    except Exception as e:
        print()
        print("=" * 60)
        print("✗ 打包失败")
        print("=" * 60)
        print()
        print(f"错误: {e}")
        return 1


def clean_build_artifacts() -> None:
    """清理打包产物"""
    project_root = get_project_root()

    print("清理打包产物...")

    # 清理 build 目录
    build_dir = project_root / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print(f"✓ 清理: {build_dir}")

    # 清理 dist 目录
    dist_dir = project_root / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
        print(f"✓ 清理: {dist_dir}")

    # 清理 .spec 文件
    spec_files = list(project_root.glob("*.spec"))
    for spec_file in spec_files:
        spec_file.unlink()
        print(f"✓ 清理: {spec_file}")

    print()


def main():
    """主函数"""
    # 解析命令行参数
    if len(sys.argv) > 1 and sys.argv[1] == "--clean":
        clean_build_artifacts()
        return 0

    # 执行打包
    return build_executable()


if __name__ == "__main__":
    sys.exit(main())
