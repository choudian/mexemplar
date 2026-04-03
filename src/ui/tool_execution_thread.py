"""
工具执行线程（QThread）

使用 QThread 在后台线程中执行工具，避免阻塞 UI
"""

from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QMutexLocker
from PyQt6.QtWidgets import QApplication, QDialog
from typing import Dict, Any, Optional

from src.data.models import Tool
from src.utils.logger import get_logger


class ToolExecutionThread(QThread):
    """
    工具执行线程

    在后台线程中执行工具，避免阻塞主线程
    """

    # 定义信号
    started_signal = pyqtSignal()  # 执行开始
    progress_signal = pyqtSignal(str, int)  # 进度更新（消息, 百分比）
    finished_signal = pyqtSignal(bool, object, str)  # 执行完成（成功, 结果, 错误）
    error_signal = pyqtSignal(str)  # 执行出错

    def __init__(self, tool: Tool, parameters: Dict[str, Any]):
        """
        初始化执行线程

        Args:
            tool: 工具定义
            parameters: 执行参数
        """
        super().__init__()
        self.logger = get_logger(__name__)
        self.tool = tool
        self.parameters = parameters

        # 线程同步
        self._mutex = QMutex()
        self._is_cancelled = False

        # 执行结果
        self._success = False
        self._result = None
        self._error = None

    def run(self):
        """
        执行工具（在后台线程中运行）

        重写 QThread.run() 方法
        """
        try:
            self.logger.info(f"开始执行工具: {self.tool.tool_name}")
            self.started_signal.emit()

            # 检查是否已取消
            if self._is_cancelled:
                self.error_signal.emit("执行已被用户取消")
                return

            # 更新进度：开始执行
            self.progress_signal.emit("初始化执行环境...", 10)

            # 导入执行器
            from src.ui.tool_execution_dialog import ToolExecutor

            # 检查是否已取消
            if self._is_cancelled:
                self.error_signal.emit("执行已被用户取消")
                return

            # 更新进度：准备执行
            self.progress_signal.emit(f"执行工具: {self.tool.tool_name}...", 30)

            # 创建执行器并执行
            executor = ToolExecutor()

            # 执行工具（同步调用，但在后台线程中）
            self.progress_signal.emit("正在执行工具...", 50)

            success, result, error = executor.execute_tool(self.tool, self.parameters)

            # 检查是否已取消
            if self._is_cancelled:
                self.error_signal.emit("执行已被用户取消")
                return

            # 更新进度：执行完成
            self.progress_signal.emit("执行完成，正在处理结果...", 90)

            # 保存结果
            with QMutexLocker(self._mutex):
                self._success = success
                self._result = result
                self._error = error

            # 发送完成信号
            self.progress_signal.emit("完成", 100)

            if success:
                self.logger.info(f"工具执行成功: {self.tool.tool_name}")
                self.finished_signal.emit(True, result, "")
            else:
                self.logger.error(f"工具执行失败: {self.tool.tool_name}, error: {error}")
                self.finished_signal.emit(False, None, error or "未知错误")

        except Exception as e:
            error_msg = f"执行工具时发生异常: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.error_signal.emit(error_msg)
            self.finished_signal.emit(False, None, error_msg)

    def cancel(self):
        """
        取消执行

        注意：这不是立即停止，而是设置取消标志，实际执行逻辑需要检查此标志
        """
        self.logger.info(f"用户请求取消执行: {self.tool.tool_name}")
        with QMutexLocker(self._mutex):
            self._is_cancelled = True

    def get_result(self) -> tuple[bool, Optional[Any], Optional[str]]:
        """
        获取执行结果

        Returns:
            (success, result, error)
        """
        with QMutexLocker(self._mutex):
            return self._success, self._result, self._error


class ToolExecutionProgressDialog:
    """
    工具执行进度对话框

    显示工具执行的进度和状态
    """

    def __init__(self, tool_name: str, parent=None):
        """
        初始化进度对话框

        Args:
            tool_name: 工具名称
            parent: 父窗口
        """
        from PyQt6.QtWidgets import (
            QDialog,
            QVBoxLayout,
            QHBoxLayout,
            QLabel,
            QProgressBar,
            QPushButton,
        )

        self.tool_name = tool_name
        self.logger = get_logger(__name__)

        # 创建对话框
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle(f"执行工具: {tool_name}")
        self.dialog.setMinimumWidth(500)

        self.tool_name = tool_name
        self.logger = get_logger(__name__)

        # 创建对话框
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle(f"执行工具: {tool_name}")
        self.dialog.setMinimumWidth(500)

        # 布局
        layout = QVBoxLayout()

        # 标题
        title_label = QLabel(f"正在执行工具: <b>{tool_name}</b>")
        title_label.setStyleSheet("font-size: 14px; margin-bottom: 10px;")
        layout.addWidget(title_label)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # 状态消息
        self.status_label = QLabel("准备执行...")
        self.status_label.setStyleSheet("color: #666; margin-top: 10px;")
        layout.addWidget(self.status_label)

        # 按钮
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        button_layout.addWidget(self.cancel_button)

        layout.addLayout(button_layout)

        self.dialog.setLayout(layout)

        # 执行线程
        self.execution_thread = None

    def set_execution_thread(self, thread: ToolExecutionThread):
        """
        设置执行线程

        Args:
            thread: ToolExecutionThread 实例
        """
        self.execution_thread = thread

        # 连接信号
        thread.started_signal.connect(self._on_started)
        thread.progress_signal.connect(self._on_progress)
        thread.finished_signal.connect(self._on_finished)
        thread.error_signal.connect(self._on_error)

    def _on_started(self):
        """执行开始"""
        self.status_label.setText("开始执行...")
        self.cancel_button.setEnabled(True)

    def _on_progress(self, message: str, percentage: int):
        """进度更新"""
        self.status_label.setText(message)
        self.progress_bar.setValue(percentage)

        # 处理事件，确保 UI 及时更新
        QApplication.processEvents()

    def _on_finished(self, success: bool, result, error: str):
        """执行完成"""
        self.progress_bar.setValue(100)

        if success:
            self.status_label.setText("执行成功！")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText(f"执行失败: {error}")
            self.status_label.setStyleSheet("color: red;")

        self.cancel_button.setEnabled(False)

        # 延迟关闭对话框
        QApplication.processEvents()

    def _on_error(self, error: str):
        """执行出错"""
        self.status_label.setText(f"执行出错: {error}")
        self.status_label.setStyleSheet("color: red;")
        self.progress_bar.setValue(0)
        self.cancel_button.setEnabled(False)

    def _on_cancel_clicked(self):
        """取消按钮点击"""
        if self.execution_thread and self.execution_thread.isRunning():
            self.execution_thread.cancel()
            self.status_label.setText("正在取消...")
            self.cancel_button.setEnabled(False)

    def exec(self) -> bool:
        """
        显示对话框并等待执行完成

        Returns:
            是否成功完成
        """
        # 启动线程
        if self.execution_thread:
            self.execution_thread.start()

        # 显示对话框（模态）
        result = self.dialog.exec()

        # 等待线程结束
        if self.execution_thread and self.execution_thread.isRunning():
            self.execution_thread.wait()

        return result == QDialog.DialogCode.Accepted

    def get_result(self) -> tuple[bool, Optional[Any], Optional[str]]:
        """
        获取执行结果

        Returns:
            (success, result, error)
        """
        if self.execution_thread:
            return self.execution_thread.get_result()
        return False, None, "未创建执行线程"
