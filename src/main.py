"""
Mexemplar 主入口

职责：
1. 初始化系统组件（配置、数据库、日志）
2. 命令行参数解析
3. 路由到相应模块
4. 资源清理
"""

import argparse
import sys
import logging
import signal
import atexit

from rich.console import Console
from rich.panel import Panel
from questionary import select, confirm

from src.utils.logger import get_logger, setup_logger
from src.data.unified_config import get_unified_config
from src.data.database import DatabaseManager

logger = get_logger(__name__)
console = Console()

# 全局资源
_resources = {
    "db_manager": None,
    "config": None,
}


def check_terminal_compatibility():
    """检测终端是否支持 questionary"""
    try:
        import os

        if "MSYSTEM" in os.environ or "TERM" in os.environ:
            return False
        from prompt_toolkit.output import win32  # noqa: F401

        return True
    except Exception:
        return False


def interactive_menu(config):
    """交互式菜单（自动检测终端兼容性）"""
    use_rich = check_terminal_compatibility()

    if not use_rich:
        console.print("[yellow]检测到不兼容的终端，使用简单菜单模式[/yellow]")
        console.print("[dim]提示: 在 PowerShell 或 cmd.exe 中可获得更好的体验[/dim]\n")

    while True:
        # 清屏并显示标题
        if use_rich:
            console.clear()
            console.print(
                Panel.fit(
                    "[bold blue]Mexemplar CLI[/bold blue]\n[dim]桌面端智能办公助理[/dim]",
                    border_style="blue",
                )
            )
        else:
            print("\n" + "=" * 50)
            print("Mexemplar CLI - 桌面端智能办公助理")
            print("=" * 50)

        # 显示菜单
        if use_rich:
            action = select(
                "请选择操作:",
                choices=[
                    {"name": "📹 开始录制", "value": "record"},
                    {"name": "▶️  执行工具", "value": "execute"},
                    {"name": "⚙️  查看配置", "value": "view_config"},
                    {"name": "🔧 设置配置", "value": "set_config"},
                    {"name": "📊 工具列表", "value": "list_tools"},
                    {"name": "❌ 退出", "value": "exit"},
                ],
            ).ask()

            if action == "exit":
                if confirm("确定要退出吗?").ask():
                    console.print("\n[yellow]再见！[/yellow]")
                    break
                continue
            if action is None:
                console.print("\n[yellow]再见！[/yellow]")
                break
        else:
            print("\n[1] 开始录制")
            print("[2] 执行工具")
            print("[3] 查看配置")
            print("[4] 设置配置")
            print("[5] 工具列表")
            print("[0] 退出")
            choice = input("\n请选择 (0-5): ").strip()

            action_map = {
                "1": "record",
                "2": "execute",
                "3": "view_config",
                "4": "set_config",
                "5": "list_tools",
                "0": "exit",
            }
            action = action_map.get(choice)

            if action == "exit":
                confirm_input = input("确定要退出吗? (y/n): ").strip().lower()
                if confirm_input in ["y", "yes", "是"]:
                    print("\n再见！")
                    break
                continue

        # 处理用户选择
        handle_menu_action(action, config, use_rich)


def handle_menu_action(action, config, use_rich=True):
    """处理菜单操作"""
    if action == "record":
        _handle_record(use_rich)
    elif action == "execute":
        _handle_execute(use_rich)
    elif action == "view_config":
        _handle_view_config(config, use_rich)
    elif action == "set_config":
        _handle_set_config(config, use_rich)
    elif action == "list_tools":
        _handle_list_tools(use_rich)


def _handle_record(use_rich):
    """处理录制"""
    if use_rich:
        mode = select(
            "选择录制模式:",
            choices=[
                {"name": "浏览器模式", "value": "browser"},
                {"name": "桌面模式", "value": "desktop"},
            ],
        ).ask()
        if mode:
            from src.recording.cli import start_interactive_recording

            start_interactive_recording(mode, simple_mode=False)
    else:
        print("\n--- 开始录制 ---")
        print("[1] 浏览器模式")
        print("[2] 桌面模式")
        print("[0] 返回")
        choice = input("请选择 (0-2): ").strip()

        mode_map = {"1": "browser", "2": "desktop"}
        mode = mode_map.get(choice)

        if mode:
            from src.recording.cli import start_interactive_recording

            start_interactive_recording(mode, simple_mode=True)


def _handle_execute(use_rich):
    """处理执行工具"""
    if use_rich:
        from questionary import text as qtext

        console.print("\n[bold cyan]执行工具[/bold cyan]")
        tool_id = qtext("请输入工具 ID:").ask()
        if tool_id:
            console.print(f"[green]✓[/green] 执行工具: {tool_id}")
            logger.info(f"执行工具: {tool_id}")
            input("\n按 Enter 继续...")
    else:
        print("\n--- 执行工具 ---")
        tool_id = input("请输入工具 ID: ").strip()
        if tool_id:
            print(f"[OK] 执行工具: {tool_id}")
            logger.info(f"执行工具: {tool_id}")


def _handle_view_config(config, use_rich):
    """查看配置"""
    if use_rich:
        from rich.table import Table

        console.print("\n[bold cyan]当前配置[/bold cyan]")
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("配置项", style="cyan", width=20)
        table.add_column("值", style="green")

        table.add_row("[bold]AI 配置[/bold]", "")
        table.add_row("  模型", config.get("ai.model", default="N/A"))
        table.add_row("  Temperature", str(config.get("ai.temperature", default="N/A")))
        table.add_row("  Max Tokens", str(config.get("ai.max_tokens", default="N/A")))

        table.add_row("[bold]录制配置[/bold]", "")
        table.add_row("  默认模式", config.get("recording.default_recording_mode", default="N/A"))
        table.add_row("  浏览器类型", config.get("recording.browser_type", default="N/A"))
        table.add_row(
            "  持久化用户数据", str(config.get("recording.persistent_user_data", default="N/A"))
        )

        table.add_row("[bold]数据库配置[/bold]", "")
        table.add_row("  路径", config.get("database.db_path", default="N/A") or "默认路径")

        console.print(table)
        input("\n按 Enter 返回...")
    else:
        print("\n--- 当前配置 ---")
        print("\n[AI 配置]")
        print(f"  模型: {config.get('ai.model', default='N/A')}")
        print(f"  Temperature: {config.get('ai.temperature', default='N/A')}")
        print(f"  Max Tokens: {config.get('ai.max_tokens', default='N/A')}")

        print("\n[录制配置]")
        print(f"  默认模式: {config.get('recording.default_recording_mode', default='N/A')}")
        print(f"  浏览器类型: {config.get('recording.browser_type', default='N/A')}")
        print(f"  持久化用户数据: {config.get('recording.persistent_user_data', default='N/A')}")

        print("\n[数据库配置]")
        print(f"  路径: {config.get('database.db_path', default='N/A') or '默认路径'}")


def _handle_set_config(config, use_rich):
    """设置配置"""
    if use_rich:
        from questionary import text as qtext

        console.print("\n[bold cyan]设置配置[/bold cyan]")
        setting = select(
            "选择要修改的配置:",
            choices=[
                {"name": "AI 模型", "value": "ai.model"},
                {"name": "Temperature", "value": "ai.temperature"},
                {"name": "默认录制模式", "value": "recording.default_recording_mode"},
                {"name": "浏览器类型", "value": "recording.browser_type"},
            ],
        ).ask()

        if setting:
            current_value = config.get(setting, default="")
            console.print(f"当前值: [yellow]{current_value}[/yellow]")
            new_value = qtext("请输入新值:").ask()

            if new_value and new_value != current_value:
                config.set(setting, new_value, persist="database")
                console.print(f"[green]✓[/green] 配置已更新: {setting} = {new_value}")
            else:
                console.print("[yellow]配置未修改[/yellow]")
            input("\n按 Enter 返回...")
    else:
        print("\n--- 设置配置 ---")
        print("[1] AI 模型")
        print("[2] Temperature")
        print("[3] 默认录制模式")
        print("[4] 浏览器类型")
        print("[0] 返回")

        choice = input("请选择 (0-4): ").strip()

        config_keys = {
            "1": "ai.model",
            "2": "ai.temperature",
            "3": "recording.default_recording_mode",
            "4": "recording.browser_type",
        }

        if choice in config_keys:
            key = config_keys[choice]
            current_value = config.get(key, default="")
            print(f"当前值: {current_value}")

            new_value = input("请输入新值: ").strip()

            if new_value and new_value != current_value:
                config.set(key, new_value, persist="database")
                print(f"[OK] 配置已更新: {key} = {new_value}")
            else:
                print("配置未修改")


def _handle_list_tools(use_rich):
    """查看工具列表"""
    if use_rich:
        console.print("\n[bold cyan]工具列表[/bold cyan]")
        console.print("[dim]TODO: 从数据库加载工具列表[/dim]")
        input("\n按 Enter 返回...")
    else:
        print("\n--- 工具列表 ---")
        print("TODO: 从数据库加载工具列表")


def cleanup():
    """清理资源"""
    logger.info("正在清理资源...")
    if _resources["db_manager"]:
        try:
            _resources["db_manager"].close()
            logger.info("[OK] 数据库已关闭")
        except Exception as e:
            logger.error(f"[ERROR] 关闭数据库失败: {e}")
    logger.info("Mexemplar 已退出")


def signal_handler(signum, frame):
    """信号处理器"""
    logger.info(f"收到信号: {signum}")
    cleanup()
    sys.exit(0)


# 注册信号处理
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
atexit.register(cleanup)


def _init_logging(args):
    """根据命令行参数初始化日志系统。

    包含全局日志级别设置和按模块 DEBUG 开启逻辑。
    """
    log_level = getattr(logging, args.log_level)
    setup_logger(name="mexemplar", log_level=log_level, console_output=True, file_output=True)

    if args.log_debug_modules:
        debug_modules = []
        for item in args.log_debug_modules:
            debug_modules.extend(m.strip() for m in item.split(",") if m.strip())
        for module in debug_modules:
            logging.getLogger(module).setLevel(logging.DEBUG)
        # 必须同步降低 root handlers 的 level，否则 DEBUG 消息经传播后会被 handler 过滤掉
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logger.info(f"[日志] 已为模块开启 DEBUG: {', '.join(debug_modules)}")


def _launch_gui():
    """启动 PyQt6 图形界面。

    Returns:
        int: app.exec() 的返回值（正常退出），或 1（启动失败）。

    包含完整的错误处理：主窗口启动失败时尝试显示 QMessageBox 错误对话框，
    若 PyQt6 不可用则回退到控制台输出。
    """
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        from PyQt6.QtGui import QFont
        from src.ui.main_window import MainWindow

        app = QApplication([])

        # 设置默认字体，避免 point size <= 0 的警告
        font = QFont()
        font.setPointSize(10)
        font.setFamily("Microsoft YaHei")
        app.setFont(font)

        window = MainWindow()
        window.show()
        return app.exec()
    except Exception as e:
        logger.error(f"启动 GUI 失败: {e}", exc_info=True)

        # 尝试显示错误对话框
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            from PyQt6.QtGui import QFont

            error_app = QApplication([])
            error_app.setFont(QFont("Microsoft YaHei", 10))
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Mexemplar 启动失败")
            msg.setText("应用程序初始化失败")
            msg.setInformativeText(str(e))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        except ImportError as ie:
            console.print(f"[red]GUI 模块导入失败: {ie}[/red]")
        except Exception as ex:
            console.print(f"[red]GUI 启动失败: {ex}[/red]")
        return 1


def main():
    """主程序入口"""
    # 先解析参数，以便尽早确定日志级别
    parser = argparse.ArgumentParser(
        description="Mexemplar - 桌面端智能办公助理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="Mexemplar 0.1.0")
    parser.add_argument("--gui", action="store_true", help="启动图形界面模式")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="全局日志级别（默认 INFO）",
    )
    parser.add_argument(
        "--log-debug",
        action="append",
        dest="log_debug_modules",
        metavar="MODULE",
        help=(
            "为指定模块开启 DEBUG（可多次使用，支持逗号分隔）。"
            "例: --log-debug src.business.ai --log-debug src.business.agents,src.data"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 子命令：record
    record_parser = subparsers.add_parser("record", help="启动录制模式")
    record_parser.add_argument("--mode", choices=["browser", "desktop"], default="browser")

    # 子命令：execute
    execute_parser = subparsers.add_parser("execute", help="执行工具")
    execute_parser.add_argument("tool_id", help="工具 ID")

    # 子命令：config
    config_parser = subparsers.add_parser("config", help="配置管理")
    config_parser.add_argument("--list", action="store_true", help="列出所有配置")

    # 子命令：interactive
    subparsers.add_parser("interactive", help="交互式菜单")

    # 子命令：recover
    recover_parser = subparsers.add_parser("recover", help="从队列文件恢复录制数据")
    recover_parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的数据")
    recover_parser.add_argument("--delete", action="store_true", help="恢复成功后删除队列文件")

    args = parser.parse_args()

    # 尽早初始化日志，后续所有模块都能按指定级别输出
    _init_logging(args)

    logger.info("=" * 60)
    logger.info("Mexemplar 启动中...")
    logger.info("=" * 60)

    config = None
    db_manager = None

    try:
        # 初始化配置系统
        config = get_unified_config()
        logger.info("[OK] 配置系统初始化成功")

        # 初始化数据库
        db_path = config.get("database.db_path")
        db_manager = DatabaseManager(db_path)
        db_manager.initialize()
        logger.info("[OK] 数据库初始化成功")

        # 保存到全局变量供清理使用
        _resources["config"] = config
        _resources["db_manager"] = db_manager

    except Exception as e:
        logger.error(f"[ERROR] 初始化失败: {e}", exc_info=True)
        if db_manager:
            db_manager.close()
        sys.exit(1)

    # GUI 模式优先处理
    if args.gui:
        return _launch_gui()

    if args.command is None:
        # 无参数时默认启动 GUI（用于打包后的 exe 双击启动）
        # 检测是否在 PyInstaller 打包环境中运行
        if getattr(sys, "frozen", False):
            # 打包后的 exe，默认启动 GUI
            return _launch_gui()
        else:
            # 开发环境，显示帮助
            console.print(
                Panel.fit(
                    "[bold blue]Mexemplar CLI[/bold blue]\n[dim]桌面端智能办公助理[/dim]",
                    border_style="blue",
                )
            )
        console.print(
            "\n[tip]提示: 使用 [cyan]python -m src.main interactive[/cyan] 进入交互式菜单\n"
        )
        console.print("[tip]提示: 使用 [cyan]python -m src.main --gui[/cyan] 启动图形界面\n")
        parser.print_help()
        return 0

    # 路由到相应模块
    if args.command == "record":
        from src.recording.cli import start_interactive_recording

        start_interactive_recording(args.mode, simple_mode=not check_terminal_compatibility())
        return 0

    elif args.command == "execute":
        logger.info(f"执行工具: {args.tool_id}")
        # TODO: 实现执行功能
        return 0

    elif args.command == "interactive":
        interactive_menu(config)
        return 0

    elif args.command == "config":
        if args.list:
            logger.info("配置列表:")
            logger.info("-" * 60)
            logger.info(f"  模型: {config.get('ai.model')}")
            logger.info(f"  Temperature: {config.get('ai.temperature')}")
            logger.info(f"  Max Tokens: {config.get('ai.max_tokens')}")
            logger.info(f"  默认模式: {config.get('recording.default_recording_mode')}")
            logger.info("-" * 60)
        return 0

    elif args.command == "recover":
        # 从队列文件恢复录制数据
        from src.data.recording_recovery import recover_from_queues

        logger.info("=" * 60)
        logger.info("开始从队列文件恢复录制数据...")
        logger.info("=" * 60)

        results = recover_from_queues(
            overwrite=getattr(args, "overwrite", False), delete_after=getattr(args, "delete", False)
        )

        logger.info("=" * 60)
        logger.info("恢复结果:")
        logger.info(f"  总计: {results['total']} 个文件")
        logger.info(f"  成功: {results['recovered']} 个")
        logger.info(f"  跳过: {results['skipped']} 个")
        logger.info(f"  失败: {results['failed']} 个")
        logger.info("=" * 60)

        if results["recovered"] > 0:
            logger.info("恢复成功！以下录制已恢复:")
            for detail in results["details"]:
                if detail["status"] == "recovered":
                    logger.info(f"  - {detail['recording_id']}: {detail['action_count']} 条操作")

        return 0

    logger.info("程序执行完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
