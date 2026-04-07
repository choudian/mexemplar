"""
RecordingMixin — 录制生命周期管理

包含 MainWindow 中与浏览器录制相关的全部方法：
- 启动/停止录制
- 后台线程录制逻辑
- 录制信号槽（成功/失败/错误）
"""

import threading

from PyQt6.QtWidgets import QMessageBox


class RecordingMixin:
    """录制生命周期 Mixin，由 MainWindow 混入使用"""

    def _on_recording_started(self, mode: str, url: str) -> None:
        """开始录制处理函数"""
        self.logger.info(f"开始录制: mode={mode}, url={url}")

        if mode == "browser":
            self._start_browser_recording(url)
        else:
            self.logger.warning(f"暂不支持 {mode} 录制模式")
            QMessageBox.warning(
                self, "不支持的模式", f"暂不支持 {mode} 模式\n\n当前仅支持浏览器操作。"
            )
            self.recording_page.reset()

    def _start_browser_recording(self, url: str) -> None:
        """启动浏览器录制（在后台线程中）"""
        from src.recording.browser_recorder import BrowserRecorder

        def start_recording():
            browser_recorder = None
            try:
                if self.browser_recorder is not None:
                    self.logger.info("清理旧的录制器...")
                    try:
                        self.browser_recorder.cleanup()
                    except Exception as e:
                        self.logger.warning(f"清理旧录制器失败: {e}")
                    self.browser_recorder = None

                self.logger.info("正在启动浏览器录制器...")

                try:
                    browser_recorder = BrowserRecorder()
                except Exception as init_error:
                    error_msg = (
                        f"浏览器录制器初始化失败：\n{str(init_error)}\n\n可能的原因：\n"
                        f"1. DuckDB 数据库文件被其他程序占用（如 PyCharm）\n"
                        f"2. 数据库文件损坏\n"
                        f"3. 磁盘空间不足\n\n"
                        f"解决方案：\n"
                        f"1. 关闭 PyCharm 或其他可能占用数据库的程序\n"
                        f"2. 检查 data/mexemplar.duckdb 文件是否存在\n"
                        f"3. 查看日志获取详细信息"
                    )
                    self.logger.error(f"浏览器录制器初始化失败: {init_error}", exc_info=True)
                    self.recording_start_failed.emit(error_msg)
                    return

                start_url = url if url.strip() else None
                success = browser_recorder.start_recording(start_url=start_url)

                if success:
                    self.logger.info("浏览器录制已启动")
                    self.browser_recorder = browser_recorder
                    self.recording_start_success.emit()
                else:
                    self.logger.error("浏览器录制启动失败")
                    self.recording_start_failed.emit("浏览器录制启动失败，请查看日志了解详情。")

            except Exception as e:
                self.logger.error(f"启动浏览器录制时出错: {e}", exc_info=True)
                self.recording_error.emit(f"启动浏览器录制时出错：\n\n{str(e)}\n\n请查看日志了解详情。")
                if browser_recorder is not None:
                    try:
                        browser_recorder.cleanup()
                    except Exception as cleanup_error:
                        self.logger.error(f"清理录制器资源失败: {cleanup_error}", exc_info=True)

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

                self.logger.info(f"录制已停止: {recording_id}, 捕获了 {action_count} 个操作")
                self._switch_to_intent_page.emit()

                if not self._ensure_agent_bridge(timeout=30.0):
                    self.logger.error("AgentUIBridge 不可用，无法启动 Agent 分析")
                    return

                emit(
                    "recording_completed",
                    event_data=RecordingEventData(
                        session_id=recording_id,
                        recording_mode="browser",
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
        QMessageBox.critical(self, "教学失败", error_message)

    def _on_recording_error(self, error_message: str) -> None:
        """录制错误的槽函数（主线程）"""
        self.logger.error(f"录制错误: {error_message}")
        QMessageBox.critical(self, "教学错误", error_message)
