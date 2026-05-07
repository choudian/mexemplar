import threading
import time
import uuid

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox
from src.recording.browser_recorder import RecordingMode


class RecordingMixin:
    def _initialize_browser_recorder(self) -> bool:
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
        self.logger.info(f"开始录制: mode={mode}, url={url}")

        if mode == RecordingMode.BROWSER:
            self._start_browser_recording(url)
        elif mode == RecordingMode.DESKTOP:
            self._start_desktop_recording()
        elif mode == RecordingMode.EXTENSION_TRIGGERED:
            self._arm_extension_triggered_recording()
        else:
            self.logger.warning(f"暂不支持 {mode} 录制模式")
            QMessageBox.warning(
                self, "不支持的模式", f"暂不支持 {mode} 模式。"
            )
            self.recording_page.reset()

    def _get_desktop_recording_service(self):
        service = getattr(self, "_desktop_recording_service", None)
        if service is None:
            from src.business.services.desktop_recording_service import DesktopRecordingService

            service = DesktopRecordingService()
            self._desktop_recording_service = service
        return service

    def _start_desktop_recording(self) -> None:
        """最小化主窗后启动桌面录制，避免“开始教学”的点击被 hook 捕获。"""
        recording_id = str(uuid.uuid4())
        self._pending_desktop_recording_id = recording_id
        self._active_desktop_recording_id = None
        self._desktop_stop_in_progress = False
        self._desktop_recording_started_at = getattr(self, "_desktop_recording_started_at", None)

        self.logger.info(f"准备启动桌面录制: {recording_id}")
        self.showMinimized()
        QTimer.singleShot(250, self._begin_pending_desktop_recording_if_minimized)

    def _begin_pending_desktop_recording_if_minimized(self) -> None:
        recording_id = getattr(self, "_pending_desktop_recording_id", None)
        if not recording_id or not self.isMinimized():
            return

        self._pending_desktop_recording_id = None
        service = self._get_desktop_recording_service()

        def start_recording():
            try:
                service.start_after_minimize(recording_id)
                self.desktop_recording_start_ready.emit(recording_id)
            except Exception as exc:
                self.logger.error(f"桌面录制启动失败: {exc}", exc_info=True)
                self.recording_start_failed.emit(f"桌面录制启动失败：\n\n{str(exc)}")

        threading.Thread(target=start_recording, daemon=True, name="DesktopRecordingStart").start()

    def _on_desktop_recording_start_ready(self, recording_id: str) -> None:
        self._active_desktop_recording_id = recording_id
        self._desktop_recording_started_at = time.time()
        self.logger.info(f"桌面录制已启动: {recording_id}")

        from src.utils.events import RecordingEventData, emit

        emit(
            "recording_started",
            event_data=RecordingEventData(
                session_id=recording_id,
                recording_mode=RecordingMode.DESKTOP,
                start_time=self._desktop_recording_started_at,
            ),
        )
        self._show_desktop_floating_widget(recording_id)
        self.recording_start_success.emit()

    def _show_desktop_floating_widget(self, recording_id: str) -> None:
        self._hide_desktop_floating_widget()

        from src.ui.widgets.recording_floating_widget import RecordingFloatingWidget

        floating = RecordingFloatingWidget()
        floating.stopRequested.connect(self._on_recording_stopped)
        floating.set_action_count(0)
        floating.show()
        self._desktop_recording_floating_widget = floating

    def _hide_desktop_floating_widget(self) -> None:
        floating = getattr(self, "_desktop_recording_floating_widget", None)
        if floating is None:
            return
        floating.hide()
        floating.deleteLater()
        self._desktop_recording_floating_widget = None

    def _on_desktop_action_count_changed(self, recording_id: str, action_count: int) -> None:
        if recording_id != getattr(self, "_active_desktop_recording_id", None):
            return
        floating = getattr(self, "_desktop_recording_floating_widget", None)
        if floating is not None:
            floating.set_action_count(action_count)

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
                        "1. DuckDB 数据库文件被其他程序占用（如 PyCharm）\n"
                        "2. 数据库文件损坏\n"
                        "3. 磁盘空间不足\n\n"
                        "解决方案：\n"
                        "1. 关闭 PyCharm 或其他可能占用数据库的程序\n"
                        "2. 检查 data/mexemplar.duckdb 文件是否存在\n"
                        "3. 查看日志获取详细信息"
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

        if getattr(self, "_active_desktop_recording_id", None):
            self._stop_desktop_recording()
            return

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

    def _stop_desktop_recording(self) -> None:
        recording_id = getattr(self, "_active_desktop_recording_id", None)
        if not recording_id or getattr(self, "_desktop_stop_in_progress", False):
            return

        self._desktop_stop_in_progress = True
        self._hide_desktop_floating_widget()
        service = self._get_desktop_recording_service()

        def stop_recording():
            try:
                stats = service.stop(recording_id)
                self.desktop_recording_stop_finished.emit(recording_id, stats)
            except Exception as exc:
                self.logger.error(f"停止桌面录制时出错: {exc}", exc_info=True)
                self.recording_error.emit(f"停止桌面录制时出错：\n\n{str(exc)}")

        threading.Thread(target=stop_recording, daemon=True, name="DesktopRecordingStop").start()

    def _on_desktop_recording_stop_finished(self, recording_id: str, stats) -> None:
        self._desktop_stop_in_progress = False
        self._active_desktop_recording_id = None
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.recording_page.reset()

        from src.data.unified_config import get_unified_config
        from src.ui.widgets.desktop_sanity_check_dialog import DesktopSanityCheckDialog

        enable_clip = get_unified_config().get_desktop_enable_clip()
        dialog = DesktopSanityCheckDialog(recording_id, stats=stats, enable_clip=enable_clip, parent=self)
        dialog.continueAnalysisRequested.connect(self._continue_desktop_analysis)
        dialog.abandonRequested.connect(self._abandon_desktop_recording)
        dialog.rerecordRequested.connect(self._rerecord_desktop_recording)
        dialog.exec()

    def _continue_desktop_analysis(self, recording_id: str) -> None:
        self._get_desktop_recording_service().mark_stopped(recording_id)
        if not self._ensure_agent_bridge(timeout=30.0):
            self.logger.error("AgentUIBridge 不可用，无法启动桌面录制 Agent 分析")
            return

        self._maybe_show_desktop_vision_model_warning(recording_id)
        self._switch_to_intent_page.emit()

        from src.utils.events import RecordingEventData, emit

        started_at = getattr(self, "_desktop_recording_started_at", None) or time.time()
        stats = self._get_desktop_recording_service().get_health_stats(recording_id)
        emit(
            "recording_completed",
            event_data=RecordingEventData(
                session_id=recording_id,
                recording_mode=RecordingMode.DESKTOP,
                start_time=started_at,
                end_time=time.time(),
                action_count=stats.action_total,
            ),
        )
        self.logger.info("已发射桌面 recording_completed 事件，等待 Agent 处理...")

    def _abandon_desktop_recording(self, recording_id: str) -> None:
        self._get_desktop_recording_service().mark_abandoned(recording_id)
        self.recording_page.reset()

    def _rerecord_desktop_recording(self, recording_id: str) -> None:
        self._abandon_desktop_recording(recording_id)
        self._start_desktop_recording()

    def _maybe_show_desktop_vision_model_warning(self, recording_id: str) -> None:
        if not hasattr(self, "_vision_model_warning_shown_for_recordings"):
            self._vision_model_warning_shown_for_recordings: set[str] = set()
        shown = self._vision_model_warning_shown_for_recordings
        if recording_id in shown:
            return
        from src.data.unified_config import get_unified_config

        if get_unified_config().get_desktop_vision_model():
            return
        shown.add(recording_id)
        self._show_toast(
            "未配置桌面视觉模型，将仅使用动作文本和结构化数据分析。",
            auto_dismiss_ms=8000,
            toast_type="warning",
        )

    def _on_recording_start_success(self) -> None:
        self.logger.info("录制启动成功")

    def _on_recording_start_failed(self, error_message: str) -> None:
        self.logger.error(f"录制启动失败: {error_message}")
        self._pending_desktop_recording_id = None
        self._active_desktop_recording_id = None
        self._desktop_stop_in_progress = False
        self._hide_desktop_floating_widget()
        self.showNormal()
        self.recording_page.reset()
        QMessageBox.critical(self, "教学失败", error_message)

    def _on_recording_error(self, error_message: str) -> None:
        self.logger.error(f"录制错误: {error_message}")
        self.recording_page.reset()
        QMessageBox.critical(self, "教学错误", error_message)
