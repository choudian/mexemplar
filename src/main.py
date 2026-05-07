"""
Mexemplar 主入口（GUI-only）

职责：
1. 初始化日志与配置
2. 仅支持 GUI 模式启动
3. 资源清理
"""

import argparse
import atexit
import logging
import signal
import sys

from src.data.recording_repository import RecordingRepository
from src.data.unified_config import get_unified_config
from src.utils.logger import get_logger, setup_logger

logger = get_logger(__name__)


def cleanup() -> None:
    """清理资源。"""
    logger.info("正在清理资源...")
    logger.info("Mexemplar 已退出")


def signal_handler(signum, _frame) -> None:
    """信号处理器。"""
    logger.info(f"收到信号: {signum}")
    cleanup()
    sys.exit(0)


def _register_shutdown_handlers() -> None:
    """注册退出清理钩子。"""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup)


def _init_logging(log_level: str = "INFO") -> None:
    """初始化日志系统。"""
    level = getattr(logging, log_level.upper(), logging.INFO)
    setup_logger(name="mexemplar", log_level=level, console_output=True, file_output=True)


def _launch_gui() -> int:
    """启动 PyQt6 图形界面。"""
    from src.recording.desktop.dpi_awareness import apply as apply_desktop_dpi_awareness

    dpi_result = apply_desktop_dpi_awareness()
    if not dpi_result.ok:
        logger.info(
            "[desktop dpi] degraded: level=%s reason=%s",
            dpi_result.level,
            dpi_result.reason,
        )

    try:
        from PyQt6.QtGui import QFont
        from PyQt6.QtWidgets import QApplication, QMessageBox

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

        # fallback：主路径已失败，再尝试弹窗通知用户
        try:
            from PyQt6.QtGui import QFont
            from PyQt6.QtWidgets import QApplication, QMessageBox

            error_app = QApplication([])
            error_app.setFont(QFont("Microsoft YaHei", 10))
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("Mexemplar 启动失败")
            msg.setText("应用程序初始化失败")
            msg.setInformativeText(str(e))
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
        except Exception as ex:
            print(f"GUI 启动失败: {ex}")
        return 1


def main() -> int:
    """主程序入口（仅 GUI）。"""
    # PyInstaller 打包后无参数启动时，自动注入 --gui
    if getattr(sys, "frozen", False) and "--gui" not in sys.argv:
        sys.argv.append("--gui")

    parser = argparse.ArgumentParser(description="Mexemplar - GUI only")
    parser.add_argument("--version", action="version", version="Mexemplar 0.1.0")
    parser.add_argument("--gui", action="store_true", required=True, help="启动图形界面模式")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="全局日志级别（默认 INFO）",
    )

    args = parser.parse_args()
    _init_logging(args.log_level)
    _register_shutdown_handlers()

    logger.info("=" * 60)
    logger.info("Mexemplar 启动中（GUI-only）...")
    logger.info("=" * 60)

    try:
        get_unified_config()  # 数据库迁移必须在 GUI 启动前完成
        RecordingRepository.ensure_startup_recovery()
        logger.info("[OK] 配置系统、数据库与录制恢复检查初始化成功")
    except Exception as e:
        logger.error(f"[ERROR] 初始化失败: {e}", exc_info=True)
        return 1

    return _launch_gui()


if __name__ == "__main__":
    sys.exit(main())
