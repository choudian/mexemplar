"""
工具执行对话框

提供工具执行时的参数输入和执行结果展示
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QScrollArea,
    QFrame,
    QMessageBox,
    QWidget,
    QSpinBox,
    QDoubleSpinBox,
)
from PyQt6.QtCore import Qt
from typing import Dict, Any, Optional, List
import json

from src.data.models import Tool
from src.utils.logger import get_logger


class ParameterInputWidget(QFrame):
    """参数输入组件"""

    def __init__(self, param: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.param = param
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        self.setObjectName("parameter_input_widget")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # 参数名称和必填标记
        name_layout = QHBoxLayout()
        name_label = QLabel(self.param.get("name", "参数"))
        name_label.setObjectName("parameter_name_label")
        name_layout.addWidget(name_label)

        if self.param.get("required", False):
            required_label = QLabel("*")
            required_label.setObjectName("parameter_required_label")
            required_label.setStyleSheet("color: red;")
            name_layout.addWidget(required_label)

        name_layout.addStretch()
        layout.addLayout(name_layout)

        # 参数描述
        if "description" in self.param:
            desc_label = QLabel(self.param["description"])
            desc_label.setObjectName("parameter_description_label")
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #666; font-size: 11px;")
            layout.addWidget(desc_label)

        # 参数输入
        param_type = self.param.get("type", "text")

        if param_type == "text":
            self.input_widget = QLineEdit()
            self.input_widget.setObjectName("parameter_text_input")
            if "default" in self.param:
                self.input_widget.setText(self.param["default"])
            layout.addWidget(self.input_widget)

        elif param_type == "password":
            self.input_widget = QLineEdit()
            self.input_widget.setObjectName("parameter_password_input")
            self.input_widget.setEchoMode(QLineEdit.EchoMode.Password)
            if "default" in self.param:
                self.input_widget.setText(self.param["default"])
            layout.addWidget(self.input_widget)

        elif param_type == "number":
            default_val = self.param.get("default")
            if isinstance(default_val, float) or (
                isinstance(default_val, str) and "." in default_val
            ):
                self.input_widget = QDoubleSpinBox()
                self.input_widget.setObjectName("parameter_number_input")
                self.input_widget.setRange(-999999, 999999)
                self.input_widget.setDecimals(4)
                if default_val is not None:
                    self.input_widget.setValue(float(default_val))
            else:
                self.input_widget = QSpinBox()
                self.input_widget.setObjectName("parameter_number_input")
                self.input_widget.setRange(-999999, 999999)
                if default_val is not None:
                    self.input_widget.setValue(int(default_val))
            layout.addWidget(self.input_widget)

        elif param_type == "textarea":
            self.input_widget = QTextEdit()
            self.input_widget.setObjectName("parameter_textarea_input")
            self.input_widget.setMaximumHeight(100)
            if "default" in self.param:
                self.input_widget.setPlainText(self.param["default"])
            layout.addWidget(self.input_widget)

        else:
            # 默认文本输入
            self.input_widget = QLineEdit()
            self.input_widget.setObjectName("parameter_default_input")
            if "default" in self.param:
                self.input_widget.setText(self.param["default"])
            layout.addWidget(self.input_widget)

    def get_value(self) -> Any:
        """获取参数值"""
        param_type = self.param.get("type", "text")

        if param_type in ["text", "password"]:
            return self.input_widget.text()
        elif param_type == "number":
            if isinstance(self.input_widget, QDoubleSpinBox):
                return self.input_widget.value()
            text = self.input_widget.text()
            return int(text) if text else None
        elif param_type == "textarea":
            return self.input_widget.toPlainText()
        else:
            return self.input_widget.text()

    def is_valid(self) -> bool:
        """验证参数值"""
        if not self.param.get("required", False):
            return True

        value = self.get_value()
        return value is not None and value != ""


class ToolExecutionDialog(QDialog):
    """工具执行对话框"""

    def __init__(self, tool: Tool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.logger = get_logger(__name__)
        self.parameter_widgets: List[ParameterInputWidget] = []
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle(f"执行工具：{self.tool.tool_name}")
        self.setMinimumSize(600, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # === 工具信息 ===
        info_layout = QVBoxLayout()
        info_layout.setSpacing(8)

        # 工具名称
        name_label = QLabel(f"🔧 {self.tool.tool_name}")
        name_label.setObjectName("tool_execution_name_label")
        name_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        info_layout.addWidget(name_label)

        # 工具描述
        if self.tool.description:
            desc_label = QLabel(self.tool.description)
            desc_label.setObjectName("tool_execution_desc_label")
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color: #666;")
            info_layout.addWidget(desc_label)

        layout.addLayout(info_layout)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # === 参数输入区域 ===
        if self.tool.parameters:
            params_label = QLabel("📝 参数输入")
            params_label.setObjectName("params_section_label")
            params_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            layout.addWidget(params_label)

            # 参数输入滚动区域
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setObjectName("params_scroll_area")
            scroll_area.setFrameShape(QFrame.Shape.NoFrame)
            scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

            params_container = QWidget()
            params_layout = QVBoxLayout(params_container)
            params_layout.setSpacing(12)
            params_layout.setContentsMargins(0, 0, 0, 0)

            # 创建参数输入组件
            for param in self.tool.parameters:
                param_widget = ParameterInputWidget(param)
                params_layout.addWidget(param_widget)
                self.parameter_widgets.append(param_widget)

            params_layout.addStretch()
            scroll_area.setWidget(params_container)
            layout.addWidget(scroll_area, 1)  # stretch=1
        else:
            # 无参数提示
            no_params_label = QLabel("✅ 此工具无需参数")
            no_params_label.setObjectName("no_params_label")
            no_params_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_params_label.setStyleSheet("color: #4CAF50; font-size: 14px; padding: 20px;")
            layout.addWidget(no_params_label, 1)  # stretch=1

        # === 底部按钮 ===
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        button_layout.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.setObjectName("tool_execution_cancel_button")
        cancel_btn.setMinimumWidth(100)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        execute_btn = QPushButton("▶️ 执行")
        execute_btn.setObjectName("tool_execution_execute_button")
        execute_btn.setMinimumWidth(120)
        execute_btn.setDefault(True)
        execute_btn.clicked.connect(self._on_execute_clicked)
        button_layout.addWidget(execute_btn)

        layout.addLayout(button_layout)

    def _on_execute_clicked(self):
        """执行按钮点击"""
        # 验证参数
        for param_widget in self.parameter_widgets:
            if not param_widget.is_valid():
                param_name = param_widget.param.get("name", "参数")
                QMessageBox.warning(self, "参数验证失败", f"请填写必填参数：{param_name}")
                return

        # 所有参数有效，接受对话框
        self.accept()

    def get_parameters(self) -> Dict[str, Any]:
        """获取参数值"""
        parameters = {}
        for param_widget in self.parameter_widgets:
            param_name = param_widget.param.get("name")
            if param_name:
                parameters[param_name] = param_widget.get_value()
        return parameters


class ExecutionResultDialog(QDialog):
    """执行结果对话框"""

    def __init__(
        self,
        tool_name: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        execution_log: Optional[str] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.tool_name = tool_name
        self.success = success
        self.result = result
        self.error = error
        self.execution_log = execution_log
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        status_text = "✅ 执行成功" if self.success else "❌ 执行失败"
        self.setWindowTitle(f"{status_text}：{self.tool_name}")
        self.setMinimumSize(700, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # === 状态图标和消息 ===
        status_layout = QHBoxLayout()
        status_layout.setSpacing(12)

        status_icon = QLabel("✅" if self.success else "❌")
        status_icon.setStyleSheet("font-size: 48px;")
        status_layout.addWidget(status_icon)

        status_label = QLabel(status_text)
        status_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        status_layout.addWidget(status_label)

        status_layout.addStretch()
        layout.addLayout(status_layout)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # === 结果展示 ===
        if self.success and self.result:
            result_label = QLabel("📊 执行结果：")
            result_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            layout.addWidget(result_label)

            result_text = QTextEdit()
            result_text.setObjectName("execution_result_text")
            result_text.setReadOnly(True)
            result_text.setPlainText(self._format_result(self.result))
            layout.addWidget(result_text, 1)  # stretch=1

        # === 错误信息 ===
        if not self.success and self.error:
            error_label = QLabel("⚠️ 错误信息：")
            error_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            layout.addWidget(error_label)

            error_text = QTextEdit()
            error_text.setObjectName("execution_error_text")
            error_text.setReadOnly(True)
            error_text.setPlainText(self.error)
            error_text.setStyleSheet("background-color: #FFEBEE; color: #C62828;")
            layout.addWidget(error_text, 1)  # stretch=1

        # === 执行日志 ===
        if self.execution_log:
            log_label = QLabel("📝 执行日志：")
            log_label.setStyleSheet("font-size: 14px; font-weight: bold;")
            layout.addWidget(log_label)

            log_text = QTextEdit()
            log_text.setObjectName("execution_log_text")
            log_text.setReadOnly(True)
            log_text.setPlainText(self.execution_log)
            log_text.setStyleSheet("font-family: monospace; font-size: 11px;")
            layout.addWidget(log_text, 1)  # stretch=1

        # === 底部按钮 ===
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        button_layout.addStretch()

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("execution_result_close_button")
        close_btn.setMinimumWidth(100)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _format_result(self, result: Dict[str, Any]) -> str:
        """格式化结果"""

        try:
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception:
            return str(result)


class ToolExecutor:
    """工具执行器（委托给 execution/tool_executor.py 的 venv 隔离执行）"""

    def __init__(self):
        self.logger = get_logger(__name__)

    def execute_tool(
        self, tool: Tool, parameters: Dict[str, Any]
    ) -> tuple[bool, Optional[Any], Optional[str]]:
        """
        执行工具

        Args:
            tool: 工具定义
            parameters: 执行参数

        Returns:
            (success, result, error) - 成功标志、结果、错误信息
        """
        try:
            self.logger.info(f"开始执行工具: {tool.tool_name}")

            if tool.execution_code:
                from src.execution.tool_executor import run_tool_code

                result = run_tool_code(tool.execution_code, parameters)
                success = result.get("success", False)
                error = result.get("message") if not success else None
                return success, result, error

            elif tool.steps:
                self.logger.warning(f"WorkflowExecutor 尚未集成，工具: {tool.tool_name}")
                return False, None, "WorkflowExecutor 尚未集成"

            else:
                return False, None, "工具既没有执行代码也没有步骤定义"

        except Exception as e:
            error_msg = f"执行工具时发生异常: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return False, None, error_msg
