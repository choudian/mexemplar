"""
录制模块的CLI交互

处理录制相关的用户交互逻辑，包括：
- 浏览器录制交互流程
- 桌面录制交互流程
- 统一的CLI接口
"""

from rich.console import Console
from questionary import text, confirm

from src.data.unified_config import get_unified_config
from src.utils.logger import get_logger

logger = get_logger(__name__)
console = Console()


def start_interactive_recording(mode: str = "browser", simple_mode: bool = False):
    """
    启动交互式录制

    Args:
        mode: 录制模式 ('browser' 或 'desktop')
        simple_mode: 是否使用简单模式（不使用 Rich/Questionary）
    """
    if mode == "browser":
        if simple_mode:
            return _simple_browser_recording()
        else:
            return _rich_browser_recording()
    else:
        if simple_mode:
            return _simple_desktop_recording()
        else:
            return _rich_desktop_recording()


def _rich_browser_recording():
    """浏览器录制交互（Rich模式）"""
    try:
        from src.recording.recorder import Recorder

        config = get_unified_config()

        # 获取起始 URL
        start_url = config.get("recording.browser_start_url", default=None)

        if not start_url:
            console.print("[yellow]未配置起始 URL[/yellow]")
            use_custom = confirm("是否要输入起始 URL? (默认为空白页)").ask()
            if use_custom:
                start_url = text("请输入起始 URL:").ask()
                if not start_url:
                    start_url = None
            else:
                start_url = None

        # 创建录制器
        recorder = Recorder(recording_mode="browser")

        # 显示录制提示
        console.print("\n[bold green]正在启动浏览器...[/bold green]")
        console.print("[dim]浏览器将自动加载 Mexemplar 录制扩展[/dim]")

        if start_url:
            console.print(f"[dim]起始 URL: {start_url}[/dim]")

        # 开始录制
        recording_id = recorder.start_recording(start_url=start_url)

        console.print("[green]✓[/green] 录制已启动")
        console.print(f"[dim]录制 ID: {recording_id}[/dim]")

        # 显示录制提示
        console.print("\n[bold cyan]录制进行中...[/bold cyan]")
        console.print("提示:")
        console.print("  1. 在浏览器中进行你想要录制的操作")
        console.print("  2. 完成后返回此终端")
        console.print("  3. 按任意键停止录制\n")

        # 等待用户停止
        input("[dim]按 Enter 键停止录制...[/dim]")

        # 停止录制
        console.print("\n[yellow]正在停止录制...[/yellow]")
        session = recorder.stop_recording()

        if session:
            # 显示录制结果
            duration = (
                session.end_time - session.start_time
                if session.end_time and session.start_time
                else 0
            )
            action_count = session.metadata.get("action_count", 0)

            console.print("\n[bold green]录制已完成！[/bold green]")
            console.print(f"[dim]录制 ID: {session.recording_id}[/dim]")
            console.print(f"[dim]录制时长: {duration:.2f} 秒[/dim]")
            console.print(f"[dim]操作数量: {action_count}[/dim]")

            if "queue_file" in session.metadata:
                console.print(f"[dim]队列文件: {session.metadata['queue_file']}[/dim]")

            logger.info(
                f"浏览器录制完成: {session.recording_id}, "
                f"操作数: {action_count}, 时长: {duration:.2f}s"
            )
        else:
            console.print("[red]录制停止失败[/red]")
            logger.error("停止录制失败")

        # 清理资源
        recorder.close()

        input("\n按 Enter 返回...")

    except Exception as e:
        console.print(f"\n[red]录制失败: {e}[/red]")
        logger.error(f"浏览器录制失败: {e}", exc_info=True)
        input("\n按 Enter 返回...")


def _simple_browser_recording():
    """浏览器录制交互（简单模式）"""
    try:
        from src.recording.recorder import Recorder

        config = get_unified_config()

        # 获取起始 URL
        start_url = config.get("recording.browser_start_url", default=None)

        if not start_url:
            print("\n未配置起始 URL")
            use_custom = input("是否要输入起始 URL? (y/n, 默认为空白页): ").strip().lower()
            if use_custom in ["y", "yes", "是"]:
                start_url = input("请输入起始 URL: ").strip()
                if not start_url:
                    start_url = None
            else:
                start_url = None

        # 创建录制器
        recorder = Recorder(recording_mode="browser")

        # 显示录制提示
        print("\n[OK] 正在启动浏览器...")
        print("浏览器将自动加载 Mexemplar 录制扩展")

        if start_url:
            print(f"起始 URL: {start_url}")

        # 开始录制
        recording_id = recorder.start_recording(start_url=start_url)

        print("[OK] 录制已启动")
        print(f"录制 ID: {recording_id}")

        # 显示录制提示
        print("\n录制进行中...")
        print("提示:")
        print("  1. 在浏览器中进行你想要录制的操作")
        print("  2. 完成后返回此终端")
        print("  3. 按任意键停止录制\n")

        # 等待用户停止
        input("按 Enter 键停止录制...")

        # 停止录制
        print("\n正在停止录制...")
        session = recorder.stop_recording()

        if session:
            # 显示录制结果
            duration = (
                session.end_time - session.start_time
                if session.end_time and session.start_time
                else 0
            )
            action_count = session.metadata.get("action_count", 0)

            print("\n[OK] 录制已完成！")
            print(f"录制 ID: {session.recording_id}")
            print(f"录制时长: {duration:.2f} 秒")
            print(f"操作数量: {action_count}")

            if "queue_file" in session.metadata:
                print(f"队列文件: {session.metadata['queue_file']}")

            logger.info(
                f"浏览器录制完成: {session.recording_id}, "
                f"操作数: {action_count}, 时长: {duration:.2f}s"
            )
        else:
            print("[ERROR] 录制停止失败")
            logger.error("停止录制失败")

        # 清理资源
        recorder.close()

    except Exception as e:
        print(f"\n[ERROR] 录制失败: {e}")
        logger.error(f"浏览器录制失败: {e}", exc_info=True)


def _rich_desktop_recording():
    """桌面录制交互（Rich模式）"""
    console.print("\n[bold yellow]桌面录制模式尚未实现[/bold yellow]")
    console.print("[dim]此功能将在后续版本中提供[/dim]")
    logger.info("桌面录制模式尚未实现")
    input("\n按 Enter 返回...")


def _simple_desktop_recording():
    """桌面录制交互（简单模式）"""
    print("\n[WARN] 桌面录制模式尚未实现")
    print("此功能将在后续版本中提供")
    logger.info("桌面录制模式尚未实现")
