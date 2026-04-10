"""
RecordingMixin — 录制生命周期管理

包含 MainWindow 中与浏览器录制相关的全部方法：
- 启动/停止录制
- 后台线程录制逻辑
- 录制信号槽（成功/失败/错误）
"""

import threading

from PyQt6.QtWidgets import QMessageBox
from src.recording.browser_recorder import RecordingMode


class RecordingMixin:
    """录制生命周期 Mixin，由 MainWindow 混入使用"""

    def _initialize_browser_recorder(self) -> bool:
        """确保 App 生命周期级别的 BrowserRecorder 单例已创建。"""
        if self.browser_recorder is not None:
            self.browser_recorder.arm_extension_triggered_mode()
            return True

        from src.recording.browser_recorder import BrowserRecorder

        try:
            self.browser_recorder = BrowserRecorder()
            self.browser_recorder.arm_extension_triggered_mode()
            self.logger.info("BrowserRecorder 已初始化并拉起 WS 服务器（App 生命周期级别）")
            return True
        except Exception as init_error:
            self.logger.error(f"浏览器录制器初始化失败: {init_error}", exc_info=True)
            return False

    def _on_recording_started(self, mode: str, url: str) -> None:
        """开始录制处理函数"""
        self.logger.info(f"开始录制: mode={mode}, url={url}")

        if mode == RecordingMode.BROWSER:
            self._start_browser_recording(url)
        elif mode == RecordingMode.EXTENSION_TRIGGERED:
            self._arm_extension_triggered_recording()
        else:
            self.logger.warning(f"暂不支持 {mode} 录制模式")
            QMessageBox.warning(
                self, "不支持的模式", f"暂不支持 {mode} 模式\n\n当前仅支持浏览器操作。"
            )
            self.recording_page.reset()

    def _arm_extension_triggered_recording(self) -> None:
        """扩展触发模式只需确保 BrowserRecorder/WS 服务器已准备好。"""
        if not self._initialize_browser_recorder():
            self.recording_start_failed.emit(
                "扩展触发模式初始化失败，请检查日志或数据库连接状态。"
            )
            self.recording_page.reset()
            return

        self.logger.info("扩展触发模式已就绪，请在 Chrome 扩展弹窗中点击开始录制")
        self.recording_start_success.emit()

    def _start_browser_recording(self, url: str) -> None:
        """启动浏览器录制（在后台线程中）"""
        def start_recording():
            try:
                if not self._initialize_browser_recorder():
                    error_msg = (
                        "浏览器录制器初始化失败。\n\n可能的原因：\n"
                        f"1. DuckDB 数据库文件被其他程序占用（如 PyCharm）\n"
                        f"2. 数据库文件损坏\n"
                        f"3. 磁盘空间不足\n\n"
                        f"解决方案：\n"
                        f"1. 关闭 PyCharm 或其他可能占用数据库的程序\n"
                        f"2. 检查 data/mexemplar.duckdb 文件是否存在\n"
                        f"3. 查看日志获取详细信息"
                    )
                    self.recording_start_failed.emit(error_msg)
                    return

                start_url = url if url.strip() else None
                success = self.browser_recorder.start_recording(start_url=start_url)

                if success:
                    self.logger.info("浏览器录制已启动")
                    self.recording_start_success.emit()
                else:
                    self.logger.error("浏览器录制启动失败")
                    self.recording_start_failed.emit("浏览器录制启动失败，请查看日志了解详情。")

            except Exception as e:
                self.logger.error(f"启动浏览器录制时出错: {e}", exc_info=True)
                self.recording_error.emit(f"启动浏览器录制时出错：\n\n{str(e)}\n\n请查看日志了解详情。")

        threading.Thread(target=start_recording, daemon=True).start()

    def _on_recording_stopped(self) -> None:
        """停止录制处理函数"""
        self.logger.info("停止录制")

        if not self.browser_recorder:
            return

        from src.utils.events import RecordingEventData, emit

        def stop_recording():
            try:
                result = self.browser_recorder.stop_recording()
                recording_id = result.get("recording_id")
                action_count = result.get("action_count", 0)
                recording_mode = result.get("recording_mode", "browser")

                self.logger.info(f"录制已停止: {recording_id}, 捕获了 {action_count} 个操作")

                if not self._ensure_agent_bridge(timeout=30.0):
                    self.logger.error("AgentUIBridge 不可用，无法启动 Agent 分析")
                    return

                self._switch_to_intent_page.emit()

                if recording_mode == RecordingMode.EXTENSION_TRIGGERED:
                    self.logger.info("扩展触发模式已由 BrowserRecorder 发射 recording_completed 事件")
                    return

                emit(
                    "recording_completed",
                    event_data=RecordingEventData(
                        session_id=recording_id,
                        recording_mode=RecordingMode.BROWSER,
                        start_time=result.get("start_time"),
                        end_time=result.get("end_time"),
                        action_count=action_count,
                    ),
                )
                self.logger.info("已发射 recording_completed 事件，等待 Agent 处理...")
            except Exception as e:
                self.logger.error(f"停止录制时出错: {e}", exc_info=True)

        threading.Thread(target=stop_recording, daemon=True).start()

    def _on_recording_start_success(self) -> None:
        """录制启动成功的槽函数（主线程）"""
        self.logger.info("录制启动成功")

    def _on_recording_start_failed(self, error_message: str) -> None:
        """录制启动失败的槽函数（主线程）"""
        self.logger.error(f"录制启动失败: {error_message}")
        self.recording_page.reset()
        QMessageBox.critical(self, "教学失败", error_message)

    def _on_recording_error(self, error_message: str) -> None:
        """录制错误的槽函数（主线程）"""
        self.logger.error(f"录制错误: {error_message}")
        self.recording_page.reset()
        QMessageBox.critical(self, "教学错误", error_message)
