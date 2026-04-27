# Blueprint: 高危操作确认 Toast 化（Auth Toast）

**Branch**: `004-auth-toast` | **Date**: 2026-04-27
**Mode**: scaffold
**Total Tasks**: 38 | **Files**: 4 new, 9 modified, 0 deleted

## Key Decisions

- 保留现有 `request_id + threading.Event + pyqtSignal(str, str)` 的同步确认协议，只在业务层补元数据、自动放行状态和结构化日志，不改线程模型。 → T005, T013, T014, T022
- 新增独立于普通 Toast 的 `AuthToastSurface` 与 UI FIFO 队列；确认浮层与普通通知各自维护生命周期、定位和关闭逻辑。 → T001, T015, T016, T017, T018
- “全部允许”与顶栏“免确认”共享同一个会话级内存态；无论从浮层还是顶栏开启，都立即清空待展示确认队列。 → T021, T023, T024, T027, T029
- “新对话”不仅复位会话级自动放行，还要把旧会话中已显示或排队的确认请求按拒绝/超时语义收敛。 → T021, T024, T026, T029
- 规格里的量化要求全部落到测试：`<=100ms` UI 响应、`<=1s` 超时收敛、`5 Worker` FIFO/无丢失，以及“同帧或下一帧”同步契约。 → T010, T011, T012, T020, T026, T027

## Implementation Order

```text
T001 -> {T002, T003, T004}
{T002, T003, T004} -> {T005, T006, T007, T008, T009}
{T005, T006, T007, T008, T009} -> {T010, T011, T012}
{T010, T011, T012} -> {T013, T014, T015, T016, T017, T018}
{T013, T014, T015, T016, T017, T018} -> T019
T019 -> {T020, T021}
{T020, T021} -> {T022, T023, T024}
{T022, T023, T024} -> T025
T025 -> {T026, T027}
{T026, T027} -> {T028, T029, T030}
{T028, T029, T030} -> T031
T031 -> {T032, T033, T034, T035, T036}
{T032, T033, T034, T035, T036} -> T037 -> T038
```

---

## Phase 1: Setup (Shared Infrastructure)

### T001: Create `src/ui/widgets/auth_toast.py` with an empty `AuthToastSurface` placeholder class and module docstring

**File**:

`src/ui/widgets/auth_toast.py` (new)

**Requirements**:

FR-001, FR-002, FR-004, FR-010, FR-012, FR-016

**Dependencies**:

None

```python
"""
Assistant 高危工具确认浮层。

该组件只负责展示与发出终态决策，不直接写业务状态。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

AUTH_TOAST_OBJECT_NAME = "auth_confirmation_toast"
AUTH_TOAST_TITLE_NAME = "auth_confirmation_title"
AUTH_TOAST_SUMMARY_NAME = "auth_confirmation_summary"
AUTH_TOAST_HINT_NAME = "auth_confirmation_hint"
AUTH_TOAST_ALLOW_ALL_BUTTON_NAME = "auth_confirmation_allow_all_button"
AUTH_TOAST_ACCEPT_BUTTON_NAME = "auth_confirmation_accept_button"
AUTH_TOAST_REJECT_BUTTON_NAME = "auth_confirmation_reject_button"

AUTH_TOAST_STATE_IDLE = "idle"
AUTH_TOAST_STATE_RESOLVED = "resolved"

DECISION_ALLOW_ALL = "allow_all"
DECISION_ACCEPT = "accept"
DECISION_REJECT = "reject"
DECISION_TIMEOUT = "timeout"


class AuthToastSurface(QFrame):
    """右下角非模态确认浮层。"""

    decision_made = pyqtSignal(str, str)

    def __init__(
        self,
        request_id: str,
        tool_name: str,
        summary: str,
        timeout_ms: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.request_id = request_id
        self.tool_name = tool_name
        self.summary = summary
        self._timeout_ms = max(timeout_ms, 1000)
        self._state = AUTH_TOAST_STATE_IDLE
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName(AUTH_TOAST_OBJECT_NAME)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(14)

        title = QLabel(f"高危操作确认 · {self.tool_name}")
        title.setObjectName(AUTH_TOAST_TITLE_NAME)
        root.addWidget(title)

        summary_label = QLabel(self.summary)
        summary_label.setObjectName(AUTH_TOAST_SUMMARY_NAME)
        summary_label.setWordWrap(True)
        root.addWidget(summary_label)

        hint = QLabel("仅影响当前会话；不展示完整文件内容或完整命令体。")
        hint.setObjectName(AUTH_TOAST_HINT_NAME)
        hint.setWordWrap(True)
        root.addWidget(hint)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        allow_all_button = QPushButton("全部允许")
        allow_all_button.setObjectName(AUTH_TOAST_ALLOW_ALL_BUTTON_NAME)
        allow_all_button.clicked.connect(lambda: self._emit_decision(DECISION_ALLOW_ALL))
        button_row.addWidget(allow_all_button)

        accept_button = QPushButton("同意")
        accept_button.setObjectName(AUTH_TOAST_ACCEPT_BUTTON_NAME)
        accept_button.clicked.connect(lambda: self._emit_decision(DECISION_ACCEPT))
        button_row.addWidget(accept_button)

        reject_button = QPushButton("拒绝")
        reject_button.setObjectName(AUTH_TOAST_REJECT_BUTTON_NAME)
        reject_button.clicked.connect(lambda: self._emit_decision(DECISION_REJECT))
        button_row.addWidget(reject_button)

        root.addLayout(button_row)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._state == AUTH_TOAST_STATE_IDLE and not self._timer.isActive():
            self._timer.start(self._timeout_ms)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._state == AUTH_TOAST_STATE_IDLE:
            event.ignore()
            return
        super().closeEvent(event)

    def _emit_decision(self, decision: str) -> None:
        if self._state == AUTH_TOAST_STATE_RESOLVED:
            return
        self._state = AUTH_TOAST_STATE_RESOLVED
        if self._timer.isActive():
            self._timer.stop()
        self.decision_made.emit(self.request_id, decision)

    def _on_timeout(self) -> None:
        self._emit_decision(DECISION_TIMEOUT)
```

**Verification**:

文件可直接导入；`AuthToastSurface.decision_made` 能发出 `allow_all / accept / reject / timeout` 四类终态。

---

### T002: Create `tests/test_auth_toast_confirmation.py` with pytest imports and an autouse fixture that resets confirmation state via `src/business/agents/tools/builtin_general_tools.py`

**File**:

`tests/test_auth_toast_confirmation.py` (new)

**Requirements**:

FR-003, FR-007, FR-008, FR-010, FR-015, FR-017, SC-002, SC-006, SC-007

**Dependencies**:

T001

```python
import threading
import time
from pathlib import Path

import pytest

import src.business.agents.tools.builtin_general_tools as general_tools


@pytest.fixture(autouse=True)
def reset_confirmation_state():
    general_tools.reset_confirmation_state_for_tests()
    yield
    general_tools.reset_confirmation_state_for_tests()


def _make_pending(
    request_id: str = "req-1",
    tool_name: str = "write_file",
    summary: str = "目标文件: demo.txt",
):
    return general_tools.PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=summary,
        created_at=time.monotonic(),
        event=threading.Event(),
    )


def test_set_confirm_result_supports_backward_compatible_default_source(caplog):
    pending = _make_pending()
    with general_tools._confirm_lock:
        general_tools._pending_confirms[pending.request_id] = pending

    with caplog.at_level("INFO"):
        general_tools.set_confirm_result(pending.request_id, True)

    assert pending.event.is_set() is True
    assert pending.result is True
    assert pending.source == general_tools.CONFIRM_SOURCE_TOAST
    assert pending.decision == general_tools.CONFIRM_DECISION_ACCEPTED
    assert '"decision": "accepted"' in caplog.text


def test_write_summary_only_contains_target_path():
    summary = general_tools._build_write_summary(Path("demo.txt"))
    assert "demo.txt" in summary
    assert "content" not in summary.lower()


def test_edit_summary_truncates_old_and_new_text():
    summary = general_tools._build_edit_summary(
        Path("demo.txt"),
        "before-" * 40,
        "after-" * 40,
    )
    assert "demo.txt" in summary
    assert "before-before" in summary
    assert "after-after" in summary
    assert len(summary) < 320


def test_exec_summary_keeps_only_first_line():
    summary = general_tools._build_exec_summary("python --version\nRemove-Item important.txt")
    assert "python --version" in summary
    assert "Remove-Item" not in summary


def test_auto_approve_scope_flips_on_and_off():
    assert general_tools.is_auto_approve_enabled() is False
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)
    assert general_tools.is_auto_approve_enabled() is True
    general_tools.reset_auto_approve()
    assert general_tools.is_auto_approve_enabled() is False


def test_confirm_or_reject_logs_auto_approved_path(caplog):
    general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)

    with caplog.at_level("INFO"):
        result = general_tools._confirm_or_reject("write_file", "目标文件: demo.txt")

    assert result is None
    assert '"decision": "auto_approved"' in caplog.text
    assert '"source": "auto_scope"' in caplog.text


def test_timeout_source_maps_to_timeout_decision(caplog):
    pending = _make_pending(
        request_id="req-timeout",
        tool_name="exec",
        summary="命令首行: python --version",
    )
    with general_tools._confirm_lock:
        general_tools._pending_confirms[pending.request_id] = pending

    with caplog.at_level("INFO"):
        general_tools.set_confirm_result(
            pending.request_id,
            False,
            general_tools.CONFIRM_SOURCE_TOAST_TIMEOUT,
        )

    assert pending.event.is_set() is True
    assert pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    assert '"decision": "timeout"' in caplog.text
```

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py -q`

---

### T003: Create `tests/ui/test_auth_toast_surface.py` with Qt offscreen setup and imports for `src/ui/widgets/auth_toast.py`

**File**:

`tests/ui/test_auth_toast_surface.py` (new)

**Requirements**:

FR-002, FR-004, FR-010, FR-016

**Dependencies**:

T001

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from src.ui.widgets.auth_toast import (
    AUTH_TOAST_ACCEPT_BUTTON_NAME,
    AUTH_TOAST_ALLOW_ALL_BUTTON_NAME,
    AUTH_TOAST_REJECT_BUTTON_NAME,
    DECISION_ACCEPT,
    DECISION_ALLOW_ALL,
    DECISION_REJECT,
    DECISION_TIMEOUT,
    AuthToastSurface,
)


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


def _button(surface: AuthToastSurface, object_name: str) -> QPushButton:
    button = surface.findChild(QPushButton, object_name)
    assert button is not None
    return button


def test_auth_toast_surface_accept_emits_terminal_signal(app):
    surface = AuthToastSurface("req-1", "write_file", "目标文件: demo.txt", 1000)
    events = []
    surface.decision_made.connect(lambda request_id, decision: events.append((request_id, decision)))
    surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(_button(surface, AUTH_TOAST_ACCEPT_BUTTON_NAME), Qt.MouseButton.LeftButton)
        app.processEvents()
        assert events == [("req-1", DECISION_ACCEPT)]
    finally:
        surface.deleteLater()


def test_auth_toast_surface_has_exactly_three_actions(app):
    surface = AuthToastSurface("req-2", "edit_file", "目标文件: demo.txt", 1000)
    surface.show()
    app.processEvents()

    try:
        button_names = sorted(button.objectName() for button in surface.findChildren(QPushButton))
        assert button_names == [
            AUTH_TOAST_ACCEPT_BUTTON_NAME,
            AUTH_TOAST_ALLOW_ALL_BUTTON_NAME,
            AUTH_TOAST_REJECT_BUTTON_NAME,
        ]
    finally:
        surface.deleteLater()


def test_auth_toast_surface_allow_all_and_reject_emit_expected_decisions(app):
    allow_all_surface = AuthToastSurface("req-3", "write_file", "目标文件: demo.txt", 1000)
    allow_all_events = []
    allow_all_surface.decision_made.connect(
        lambda request_id, decision: allow_all_events.append((request_id, decision))
    )
    allow_all_surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(
            _button(allow_all_surface, AUTH_TOAST_ALLOW_ALL_BUTTON_NAME),
            Qt.MouseButton.LeftButton,
        )
        app.processEvents()
        assert allow_all_events == [("req-3", DECISION_ALLOW_ALL)]
    finally:
        allow_all_surface.deleteLater()

    reject_surface = AuthToastSurface("req-4", "exec", "命令首行: python --version", 1000)
    reject_events = []
    reject_surface.decision_made.connect(
        lambda request_id, decision: reject_events.append((request_id, decision))
    )
    reject_surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(
            _button(reject_surface, AUTH_TOAST_REJECT_BUTTON_NAME),
            Qt.MouseButton.LeftButton,
        )
        app.processEvents()
        assert reject_events == [("req-4", DECISION_REJECT)]
    finally:
        reject_surface.deleteLater()


def test_auth_toast_surface_timeout_is_single_shot(app):
    surface = AuthToastSurface("req-5", "exec", "命令首行: python --version", 40)
    events = []
    surface.decision_made.connect(lambda request_id, decision: events.append((request_id, decision)))
    surface.show()
    app.processEvents()

    try:
        QTest.qWait(80)
        app.processEvents()
        assert events == [("req-5", DECISION_TIMEOUT)]
    finally:
        surface.deleteLater()


def test_auth_toast_surface_ignores_second_terminal_action(app):
    surface = AuthToastSurface("req-6", "write_file", "目标文件: demo.txt", 1000)
    events = []
    surface.decision_made.connect(lambda request_id, decision: events.append((request_id, decision)))
    surface.show()
    app.processEvents()

    try:
        QTest.mouseClick(_button(surface, AUTH_TOAST_ACCEPT_BUTTON_NAME), Qt.MouseButton.LeftButton)
        QTest.mouseClick(_button(surface, AUTH_TOAST_REJECT_BUTTON_NAME), Qt.MouseButton.LeftButton)
        app.processEvents()
        assert events == [("req-6", DECISION_ACCEPT)]
    finally:
        surface.deleteLater()
```

**Verification**:

`uv run python -m pytest tests/ui/test_auth_toast_surface.py -q`

---

### T004: Create `tests/ui/test_chat_widget_auth_toggle.py` with Qt offscreen setup and imports for `src/ui/widgets/chat_widget.py`

**File**:

`tests/ui/test_chat_widget_auth_toggle.py` (new)

**Requirements**:

FR-008, FR-009, FR-013, SC-004

**Dependencies**:

T001

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from src.ui.widgets.chat_widget import ChatWidget


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


@pytest.fixture()
def widget(monkeypatch, app):
    monkeypatch.setattr(ChatWidget, "_load_sessions", lambda self: None)
    chat_widget = ChatWidget()
    chat_widget.show()
    app.processEvents()
    yield chat_widget
    chat_widget.close()
    chat_widget.deleteLater()


def _toggle(widget: ChatWidget) -> QPushButton:
    toggle = widget.findChild(QPushButton, "chat_auto_approve_toggle")
    assert toggle is not None
    return toggle


def test_toggle_defaults_off_and_emits_state_change(widget, app):
    events = []
    widget.auto_approve_toggled.connect(events.append)
    toggle = _toggle(widget)

    assert toggle.isChecked() is False
    assert "关闭" in toggle.text()

    QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)
    app.processEvents()

    assert events == [True]
    assert toggle.isChecked() is True
    assert "开启" in toggle.text()


def test_programmatic_state_sync_is_reflected_without_extra_signal(widget, app):
    events = []
    widget.auto_approve_toggled.connect(events.append)

    widget.set_auto_approve_enabled(True)
    assert _toggle(widget).isChecked() is True
    assert "开启" in _toggle(widget).text()
    assert events == []

    app.processEvents()

    widget.set_auto_approve_enabled(False)
    assert _toggle(widget).isChecked() is False
    assert "关闭" in _toggle(widget).text()
    assert events == []

    app.processEvents()


def test_new_chat_resets_toggle_and_emits_new_chat_started(widget, app):
    started = []
    widget.new_chat_started.connect(lambda: started.append(True))

    widget.set_auto_approve_enabled(True)
    widget.on_new_chat()
    app.processEvents()

    assert started == [True]
    assert _toggle(widget).isChecked() is False
    assert "关闭" in _toggle(widget).text()
```

**Verification**:

`uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py -q`

---

## Phase 2: Foundational (Blocking Prerequisites)

### T005: Extend `set_confirm_result` in `src/business/agents/tools/builtin_general_tools.py` with a backward-compatible optional `source` parameter

**File**:

`src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**:

FR-003, FR-007, FR-008, FR-010, FR-015, FR-017, SC-002, SC-006, SC-007

**Dependencies**:

T002

**Before** (line ~16):

```python
import json
import logging
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path
from typing import List

from src.business.agents.config import ToolDefinition
from src.business.agents.hook_models import PreHookResult, ToolCallContext
from src.business.agents.tool_helpers import make_tool_schema, error_json

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

# 用户确认超时（秒）
_CONFIRM_TIMEOUT = 120

# web_fetch 返回内容最大字符数
_WEB_FETCH_MAX_LENGTH = 5000

# read_file 最大读取字节数
_READ_FILE_MAX_BYTES = 50000

# exec 输出截断（stdout / stderr 最大字符数）
_EXEC_STDOUT_MAX = 5000
_EXEC_STDERR_MAX = 2000

# exec 安全白名单（无需用户确认即可执行的命令）
EXEC_SAFE_COMMANDS = frozenset(
    [
        "dir",
        "ls",
        "ls -la",
        "ls -l",
        "ls -a",
        "pwd",
        "echo",
        "type",
        "cat",
        "ping",
        "ipconfig",
        "ifconfig",
        "python --version",
        "python3 --version",
        "pip list",
        "pip3 list",
        "date",
        "time",
        "whoami",
        "hostname",
        "tasklist",
        "ps",
        "ps aux",
    ]
)

# =========================================================================
# 用户确认机制（高危工具，线程安全）
# 每个 worker 线程用独立的 threading.Event 等待，结果按 request_id 隔离。
# =========================================================================

_confirm_signal = None  # pyqtSignal(str, str)，(request_id, message)
_pending_confirms: dict = {}  # request_id → {"event": Event, "result": bool}
_confirm_lock = threading.Lock()


def register_confirm_mechanism(signal):
    """
    注入跨线程确认信号（由 MainWindow 在初始化时调用）。

    Args:
        signal: pyqtSignal(str, str)，emit(request_id, message) 后 UI 线程弹框
    """
    global _confirm_signal
    _confirm_signal = signal


def set_confirm_result(request_id: str, result: bool):
    """UI 线程设置确认结果并唤醒对应的 worker 线程"""
    with _confirm_lock:
        pending = _pending_confirms.get(request_id)
    if pending:
        pending["result"] = result
        pending["event"].set()


def _ask_user_confirm(message: str) -> bool:
    """
    请求用户确认高危操作（线程安全，支持多 worker 并发）。

    每次请求生成唯一 request_id，worker 线程各自阻塞在独立的 Event 上。
    """
    if _confirm_signal is None:
        logger.warning("[builtin_tools] 确认机制未注册，拒绝高危操作")
        return False

    import uuid

    request_id = str(uuid.uuid4())
    event = threading.Event()
    with _confirm_lock:
        _pending_confirms[request_id] = {"event": event, "result": False}

    try:
        _confirm_signal.emit(request_id, message)
        event.wait(timeout=_CONFIRM_TIMEOUT)
    except Exception:
        with _confirm_lock:
            _pending_confirms.pop(request_id, None)
        raise

    with _confirm_lock:
        pending = _pending_confirms.pop(request_id, None)
    return pending["result"] if pending else False
```

**After**:

```python
import json
import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, List

from src.business.agents.config import ToolDefinition
from src.business.agents.hook_models import PreHookResult, ToolCallContext
from src.business.agents.tool_helpers import make_tool_schema, error_json

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

_CONFIRM_TIMEOUT = 120
_WEB_FETCH_MAX_LENGTH = 5000
_READ_FILE_MAX_BYTES = 50000
_EXEC_STDOUT_MAX = 5000
_EXEC_STDERR_MAX = 2000

CONFIRM_DECISION_ACCEPTED = "accepted"
CONFIRM_DECISION_REJECTED = "rejected"
CONFIRM_DECISION_TIMEOUT = "timeout"
CONFIRM_DECISION_AUTO_APPROVED = "auto_approved"
CONFIRM_DECISION_CONFIRM_ERROR = "confirm_error"

CONFIRM_SOURCE_TOAST = "toast"
CONFIRM_SOURCE_TOAST_ACCEPT = "toast_accept"
CONFIRM_SOURCE_TOAST_REJECT = "toast_reject"
CONFIRM_SOURCE_TOAST_TIMEOUT = "toast_timeout"
CONFIRM_SOURCE_TOAST_ALLOW_ALL = "toast_allow_all"
CONFIRM_SOURCE_TOP_TOGGLE = "top_toggle"
CONFIRM_SOURCE_AUTO_SCOPE = "auto_scope"
CONFIRM_SOURCE_SYSTEM_ERROR = "system_error"

AUTO_APPROVE_SOURCE_STARTUP_DEFAULT = "startup_default"

EXEC_SAFE_COMMANDS = frozenset(
    [
        "dir",
        "ls",
        "ls -la",
        "ls -l",
        "ls -a",
        "pwd",
        "echo",
        "type",
        "cat",
        "ping",
        "ipconfig",
        "ifconfig",
        "python --version",
        "python3 --version",
        "pip list",
        "pip3 list",
        "date",
        "time",
        "whoami",
        "hostname",
        "tasklist",
        "ps",
        "ps aux",
    ]
)


@dataclass
class PendingConfirmation:
    request_id: str
    tool_name: str
    summary: str
    created_at: float
    event: threading.Event
    result: bool = False
    decision: str = CONFIRM_DECISION_REJECTED
    source: str = CONFIRM_SOURCE_TOAST


_confirm_signal = None
_pending_confirms: dict[str, PendingConfirmation] = {}
_confirm_lock = threading.Lock()
_confirm_context = threading.local()
_auto_approve_scope = {
    "enabled": False,
    "source": AUTO_APPROVE_SOURCE_STARTUP_DEFAULT,
    "updated_at": 0.0,
}


def register_confirm_mechanism(signal):
    global _confirm_signal
    _confirm_signal = signal


def get_confirm_timeout_ms() -> int:
    return _CONFIRM_TIMEOUT * 1000


def get_pending_confirm_metadata(request_id: str) -> dict[str, Any] | None:
    with _confirm_lock:
        pending = _pending_confirms.get(request_id)
        if pending is None:
            return None
        return {
            "request_id": pending.request_id,
            "tool_name": pending.tool_name,
            "summary": pending.summary,
            "created_at": pending.created_at,
        }


def set_auto_approve_enabled(enabled: bool, source: str) -> None:
    with _confirm_lock:
        _auto_approve_scope["enabled"] = bool(enabled)
        _auto_approve_scope["source"] = source
        _auto_approve_scope["updated_at"] = time.monotonic()


def is_auto_approve_enabled() -> bool:
    with _confirm_lock:
        return bool(_auto_approve_scope["enabled"])


def reset_auto_approve(source: str = "new_chat_reset") -> None:
    set_auto_approve_enabled(False, source)


def reset_confirmation_state_for_tests() -> None:
    with _confirm_lock:
        _pending_confirms.clear()
        _auto_approve_scope["enabled"] = False
        _auto_approve_scope["source"] = AUTO_APPROVE_SOURCE_STARTUP_DEFAULT
        _auto_approve_scope["updated_at"] = 0.0


def _decision_from_result(result: bool, source: str) -> str:
    if source in {
        CONFIRM_SOURCE_TOAST_ALLOW_ALL,
        CONFIRM_SOURCE_TOP_TOGGLE,
        CONFIRM_SOURCE_AUTO_SCOPE,
    }:
        return CONFIRM_DECISION_AUTO_APPROVED
    if source == CONFIRM_SOURCE_TOAST_TIMEOUT:
        return CONFIRM_DECISION_TIMEOUT
    if source == CONFIRM_SOURCE_SYSTEM_ERROR:
        return CONFIRM_DECISION_CONFIRM_ERROR
    return CONFIRM_DECISION_ACCEPTED if result else CONFIRM_DECISION_REJECTED


def _log_confirmation_decision(pending: PendingConfirmation, decision: str, source: str) -> None:
    payload = {
        "request_id": pending.request_id,
        "tool_name": pending.tool_name,
        "decision": decision,
        "source": source,
        "elapsed_ms": max(0, int((time.monotonic() - pending.created_at) * 1000)),
        "summary": pending.summary,
    }
    logger.info("[builtin_tools.confirm] %s", json.dumps(payload, ensure_ascii=False))


def set_confirm_result(request_id: str, result: bool, source: str = CONFIRM_SOURCE_TOAST):
    with _confirm_lock:
        pending = _pending_confirms.get(request_id)
    if pending is None:
        logger.debug("[builtin_tools] 忽略未知确认请求: %s", request_id)
        return
    if pending.event.is_set():
        return
    pending.result = result
    pending.source = source
    pending.decision = _decision_from_result(result, source)
    _log_confirmation_decision(pending, pending.decision, pending.source)
    pending.event.set()


def _ask_user_confirm(message: str) -> bool:
    if _confirm_signal is None:
        logger.warning("[builtin_tools] 确认机制未注册，拒绝高危操作")
        return False

    tool_name = getattr(_confirm_context, "tool_name", "高危操作")
    summary = getattr(_confirm_context, "summary", message)
    request_id = str(uuid.uuid4())
    event = threading.Event()
    pending = PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=summary,
        created_at=time.monotonic(),
        event=event,
    )
    with _confirm_lock:
        _pending_confirms[request_id] = pending

    try:
        _confirm_signal.emit(request_id, message)
        finished = event.wait(timeout=_CONFIRM_TIMEOUT)
    except Exception:
        with _confirm_lock:
            _pending_confirms.pop(request_id, None)
        pending.decision = CONFIRM_DECISION_CONFIRM_ERROR
        pending.source = CONFIRM_SOURCE_SYSTEM_ERROR
        _log_confirmation_decision(pending, pending.decision, pending.source)
        raise

    with _confirm_lock:
        stored = _pending_confirms.pop(request_id, None)
    if stored is None:
        return False
    if not finished and not stored.event.is_set():
        stored.result = False
        stored.source = CONFIRM_SOURCE_TOAST_TIMEOUT
        stored.decision = CONFIRM_DECISION_TIMEOUT
        _log_confirmation_decision(stored, stored.decision, stored.source)
        return False
    return stored.result
```

**Before** (line ~279):

```python
def _confirm_or_reject(message: str) -> PreHookResult | None:
    try:
        confirmed = _ask_user_confirm(message)
    except Exception as exc:
        logger.warning("[builtin_tools] 确认请求失败，拒绝高危操作: %s", exc, exc_info=True)
        return PreHookResult(error="确认请求失败，拒绝执行该高危操作")
    if not confirmed:
        return PreHookResult(error="用户取消了该操作")
    return None


def read_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}")
    return None


def write_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if _is_system_path(p):
        return PreHookResult(error="禁止写入系统目录")
    return _confirm_or_reject(f"将向文件写入内容：\n{p}\n\n是否确认？")


def edit_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}")
    old_text = str(ctx.args["old_text"])
    return _confirm_or_reject(
        f"将编辑文件：{p}\n"
        f"替换：{old_text[:80]}...\n"
        f"为：{str(ctx.args['new_text'])[:80]}...\n"
        "是否确认？"
    )


def list_dir_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx, default=".")
    if not p.exists():
        return PreHookResult(error=f"路径不存在: {p}")
    if not p.is_dir():
        return PreHookResult(error=f"不是目录: {p}")
    return None


def exec_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    command = str(ctx.args["command"])
    if _is_safe_exec_command(command):
        return None
    return _confirm_or_reject(f"将执行以下命令：\n\n{command}\n\n是否确认？")
```

**After**:

```python
def _truncate_for_summary(value: str, max_chars: int = 80) -> str:
    compact = " ".join(value.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1] + "…"


def _first_line(value: str, max_chars: int = 120) -> str:
    return _truncate_for_summary(value.splitlines()[0] if value.splitlines() else value, max_chars)


def _build_write_summary(path: Path) -> str:
    return f"目标文件: {path}"


def _build_edit_summary(path: Path, old_text: str, new_text: str) -> str:
    old_preview = _truncate_for_summary(old_text, 80)
    new_preview = _truncate_for_summary(new_text, 80)
    return (
        f"目标文件: {path}\n"
        f"替换前片段: {old_preview}\n"
        f"替换后片段: {new_preview}"
    )


def _build_exec_summary(command: str) -> str:
    return f"命令首行: {_first_line(command, 140)}"


def _format_confirm_message(tool_name: str, summary: str) -> str:
    return f"{tool_name}\n{summary}"


def _confirm_or_reject(tool_name: str, summary: str) -> PreHookResult | None:
    if is_auto_approve_enabled():
        synthetic = PendingConfirmation(
            request_id=f"auto:{tool_name}",
            tool_name=tool_name,
            summary=summary,
            created_at=time.monotonic(),
            event=threading.Event(),
            result=True,
            decision=CONFIRM_DECISION_AUTO_APPROVED,
            source=CONFIRM_SOURCE_AUTO_SCOPE,
        )
        _log_confirmation_decision(synthetic, synthetic.decision, synthetic.source)
        return None

    try:
        _confirm_context.tool_name = tool_name
        _confirm_context.summary = summary
        confirmed = _ask_user_confirm(_format_confirm_message(tool_name, summary))
    except Exception as exc:
        logger.warning("[builtin_tools] 确认请求失败，拒绝高危操作: %s", exc, exc_info=True)
        return PreHookResult(error="确认请求失败，拒绝执行该高危操作")
    finally:
        for attr in ("tool_name", "summary"):
            if hasattr(_confirm_context, attr):
                delattr(_confirm_context, attr)

    if not confirmed:
        return PreHookResult(error="用户取消了该操作")
    return None


def read_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}")
    return None


def write_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if _is_system_path(p):
        return PreHookResult(error="禁止写入系统目录")
    return _confirm_or_reject("write_file", _build_write_summary(p))


def edit_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}")
    return _confirm_or_reject(
        "edit_file",
        _build_edit_summary(
            p,
            str(ctx.args["old_text"]),
            str(ctx.args["new_text"]),
        ),
    )


def list_dir_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx, default=".")
    if not p.exists():
        return PreHookResult(error=f"路径不存在: {p}")
    if not p.is_dir():
        return PreHookResult(error=f"不是目录: {p}")
    return None


def exec_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    command = str(ctx.args["command"])
    if _is_safe_exec_command(command):
        return None
    return _confirm_or_reject("exec", _build_exec_summary(command))
```

**Before** (line ~581):

```python
__all__ = [
    "BUILTIN_GENERAL_TOOLS",
    "register_confirm_mechanism",
    "set_confirm_result",
]
```

**After**:

```python
__all__ = [
    "AUTO_APPROVE_SOURCE_STARTUP_DEFAULT",
    "BUILTIN_GENERAL_TOOLS",
    "CONFIRM_DECISION_ACCEPTED",
    "CONFIRM_DECISION_AUTO_APPROVED",
    "CONFIRM_DECISION_REJECTED",
    "CONFIRM_DECISION_TIMEOUT",
    "CONFIRM_SOURCE_AUTO_SCOPE",
    "CONFIRM_SOURCE_TOAST",
    "CONFIRM_SOURCE_TOAST_ACCEPT",
    "CONFIRM_SOURCE_TOAST_ALLOW_ALL",
    "CONFIRM_SOURCE_TOAST_REJECT",
    "CONFIRM_SOURCE_TOAST_TIMEOUT",
    "CONFIRM_SOURCE_TOP_TOGGLE",
    "PendingConfirmation",
    "get_confirm_timeout_ms",
    "get_pending_confirm_metadata",
    "is_auto_approve_enabled",
    "register_confirm_mechanism",
    "reset_auto_approve",
    "reset_confirmation_state_for_tests",
    "set_auto_approve_enabled",
    "set_confirm_result",
]
```

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py tests/test_hook_protocol.py -q`

---

### T006: Define confirmation decision/source constants and a reset helper for tests in `src/business/agents/tools/builtin_general_tools.py`

**File**:

`src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**:

FR-015, SC-007

**Dependencies**:

T005

**Required changes**:

本任务已并入 T005 的整合变更；核对 `CONFIRM_DECISION_*`、`CONFIRM_SOURCE_*`、`reset_confirmation_state_for_tests()` 和 `__all__` 导出是否齐全。

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py -q`

---

### T007: Implement sanitized summary helper functions for `write_file`, `edit_file`, and `exec` arguments in `src/business/agents/tools/builtin_general_tools.py`

**File**:

`src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**:

FR-003, FR-015

**Dependencies**:

T005

**Required changes**:

本任务已并入 T005 的整合变更；确认 `_build_write_summary()`、`_build_edit_summary()`、`_build_exec_summary()` 只使用路径、命令首行和截断片段，不泄漏完整内容。

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py -q -k "summary"`

---

### T008: Implement a structured confirmation decision logging helper in `src/business/agents/tools/builtin_general_tools.py`

**File**:

`src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**:

FR-015, SC-007

**Dependencies**:

T005

**Required changes**:

本任务已并入 T005 的整合变更；`_log_confirmation_decision()` 必须统一输出 `request_id / tool_name / decision / source / elapsed_ms / summary`，并保持脱敏。

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py -q -k "log"`

---

### T009: Add object names and public constants for auth toast buttons/states in `src/ui/widgets/auth_toast.py`

**File**:

`src/ui/widgets/auth_toast.py` (new)

**Requirements**:

FR-004, FR-016

**Dependencies**:

T001

**Required changes**:

本任务已直接体现在 T001 的完整文件中；重点核对 `AUTH_TOAST_*` 对象名常量、四类 `DECISION_*` 常量以及单终态保护逻辑。

**Verification**:

`uv run python -m pytest tests/ui/test_auth_toast_surface.py -q -k "exactly_three_actions or single_shot"`

---

## Phase 3: User Story 1 - 单次确认改为非阻塞浮层 (Priority: P1) - MVP

### T010: Add tests for sanitized summaries, accept/reject result handling, timeout logging, and backward-compatible `set_confirm_result` in `tests/test_auth_toast_confirmation.py`

**File**:

`tests/test_auth_toast_confirmation.py` (new)

**Requirements**:

FR-003, FR-005, FR-006, FR-010, FR-015, SC-006, SC-007

**Dependencies**:

T002, T005

**Required changes**:

本任务已直接体现在 T002 的完整文件中；其中 `test_set_confirm_result_supports_backward_compatible_default_source()`、`test_timeout_source_maps_to_timeout_decision()` 和各类摘要测试正是本任务的落点。

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py -q`

---

### T011: Add UI tests for `AuthToastSurface` buttons, no close button, single terminal signal, and timeout rejection in `tests/ui/test_auth_toast_surface.py`

**File**:

`tests/ui/test_auth_toast_surface.py` (new)

**Requirements**:

FR-002, FR-004, FR-010, FR-016

**Dependencies**:

T001, T003

**Required changes**:

本任务已直接体现在 T003 的完整文件中；它覆盖了三按钮、无额外关闭按钮、超时和单终态约束。

**Verification**:

`uv run python -m pytest tests/ui/test_auth_toast_surface.py -q`

---

### T012: Add AgentHandlerMixin tests for 5-Worker FIFO/no-loss confirmation queue handling, ordinary Toast coexistence, main-window interaction responsiveness <= 100ms, and UI/Worker timeout convergence <= 1s in `tests/ui/test_agent_handler_mixin.py`

**File**:

`tests/ui/test_agent_handler_mixin.py` (modify)

**Requirements**:

FR-002, FR-011, FR-012, SC-001, SC-005, SC-006

**Dependencies**:

T001, T005

**Replace entire file**:

```python
import inspect
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

import src.business.agents.tools.builtin_general_tools as general_tools
from src.ui.mixins.agent_handler_mixin import AgentHandlerMixin
from src.ui.widgets.auth_toast import (
    AUTH_TOAST_ACCEPT_BUTTON_NAME,
    AUTH_TOAST_ALLOW_ALL_BUTTON_NAME,
    AUTH_TOAST_REJECT_BUTTON_NAME,
)
from src.utils.logger import get_logger


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


@pytest.fixture(autouse=True)
def reset_confirmation_state():
    general_tools.reset_confirmation_state_for_tests()
    yield
    general_tools.reset_confirmation_state_for_tests()


def _seed_pending(request_id: str, tool_name: str = "write_file", summary: str = "目标文件: demo.txt"):
    pending = general_tools.PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=summary,
        created_at=time.monotonic(),
        event=threading.Event(),
    )
    with general_tools._confirm_lock:
        general_tools._pending_confirms[request_id] = pending
    return pending


class _DummyChat:
    def __init__(self):
        self.states = []

    def set_auto_approve_enabled(self, enabled: bool):
        self.states.append(bool(enabled))


class _DummyWindow(QWidget, AgentHandlerMixin):
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self._chat_widget = _DummyChat()
        self._active_toast = QWidget(self)
        self._active_toast.resize(240, 48)
        self._active_auth_toast = None
        self._active_auth_request = None
        self._auth_confirm_queue = []
        self.toasts = []
        self.resize(800, 600)

    def centralWidget(self):
        return self

    def _get_chat_widget(self):
        return self._chat_widget

    def _position_overlay_toasts(self):
        if self._active_auth_toast is not None:
            self._active_auth_toast.move(16, 16)

    def _show_toast(self, message, **kwargs):
        self.toasts.append((message, kwargs))


def _button(container: QWidget, object_name: str) -> QPushButton:
    button = container.findChild(QPushButton, object_name)
    assert button is not None
    return button


def _click(window: _DummyWindow, object_name: str, app):
    assert window._active_auth_toast is not None
    button = _button(window._active_auth_toast, object_name)
    assert button is not None
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    app.processEvents()


def test_confirm_requests_are_fifo_across_five_workers_and_do_not_replace_existing_toast(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_requests = [
        _seed_pending(f"req-{index}", summary=f"目标文件: file-{index}.txt")
        for index in range(1, 6)
    ]

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        ordinary_toast = window._active_toast
        for pending in pending_requests:
            window._on_confirm_action_requested(pending.request_id, "ignored")

        assert window._active_toast is ordinary_toast
        assert window._active_auth_request["request_id"] == pending_requests[0].request_id
        assert [item["request_id"] for item in window._auth_confirm_queue] == [
            pending.request_id for pending in pending_requests[1:]
        ]

        for pending in pending_requests:
            assert window._active_auth_request["request_id"] == pending.request_id
            _click(window, AUTH_TOAST_ACCEPT_BUTTON_NAME, app)
            assert pending.event.is_set() is True
            assert pending.result is True

        assert window._active_auth_toast is None
        assert window._active_auth_request is None
        assert window._auth_confirm_queue == []
    finally:
        window.close()
        window.deleteLater()


def test_allow_all_drains_ten_consecutive_requests_and_syncs_toggle(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_requests = [
        _seed_pending(
            f"req-{index}",
            tool_name="exec" if index % 3 == 0 else "write_file",
            summary=(
                f"命令首行: python --version #{index}"
                if index % 3 == 0
                else f"目标文件: file-{index}.txt"
            ),
        )
        for index in range(1, 11)
    ]

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        for pending in pending_requests:
            window._on_confirm_action_requested(pending.request_id, "ignored")

        _click(window, AUTH_TOAST_ALLOW_ALL_BUTTON_NAME, app)

        assert general_tools.is_auto_approve_enabled() is True
        assert window._chat_widget.states[-1] is True
        assert window._active_auth_toast is None
        assert window._active_auth_request is None
        assert window._auth_confirm_queue == []
        assert all(pending.event.is_set() and pending.result is True for pending in pending_requests)
    finally:
        window.close()
        window.deleteLater()


def test_toggle_on_drains_pending_requests(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_one = _seed_pending("req-toggle-1")
    pending_two = _seed_pending("req-toggle-2", summary="目标文件: second.txt")

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        window._on_confirm_action_requested("req-toggle-1", "ignored")
        window._on_confirm_action_requested("req-toggle-2", "ignored")

        window._on_chat_auto_approve_toggled(True)
        app.processEvents()

        assert general_tools.is_auto_approve_enabled() is True
        assert pending_one.event.is_set() is True
        assert pending_two.event.is_set() is True
        assert pending_one.result is True
        assert pending_two.result is True
        assert window._chat_widget.states[-1] is True
        assert window._active_auth_toast is None
        assert window._auth_confirm_queue == []
    finally:
        window.close()
        window.deleteLater()


def test_toggle_off_reenables_auth_toast_after_disabling_auto_approve(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending = _seed_pending("req-after-toggle-off", summary="目标文件: after-toggle-off.txt")

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        window._on_chat_auto_approve_toggled(True)
        app.processEvents()
        window._on_chat_auto_approve_toggled(False)
        app.processEvents()

        assert general_tools.is_auto_approve_enabled() is False
        assert window._chat_widget.states[-2:] == [True, False]

        window._on_confirm_action_requested(pending.request_id, "ignored")
        app.processEvents()

        assert window._active_auth_request["request_id"] == pending.request_id
        assert window._active_auth_toast is not None
        assert pending.event.is_set() is False

        _click(window, AUTH_TOAST_REJECT_BUTTON_NAME, app)

        assert pending.event.is_set() is True
        assert pending.result is False
    finally:
        window.close()
        window.deleteLater()


def test_new_chat_settles_prior_session_requests_and_resets_toggle(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_one = _seed_pending("req-new-chat-1")
    pending_two = _seed_pending("req-new-chat-2", summary="目标文件: second.txt")

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        window._on_confirm_action_requested("req-new-chat-1", "ignored")
        window._on_confirm_action_requested("req-new-chat-2", "ignored")
        general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)

        window._on_chat_new_chat_started()
        app.processEvents()

        assert general_tools.is_auto_approve_enabled() is False
        assert pending_one.event.is_set() is True
        assert pending_two.event.is_set() is True
        assert pending_one.result is False
        assert pending_two.result is False
        assert window._chat_widget.states[-1] is False
        assert window._auth_confirm_queue == []
        assert window._active_auth_toast is None
    finally:
        window.close()
        window.deleteLater()


def test_confirm_slot_is_non_blocking_and_timeout_converges(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 40)
    pending = _seed_pending("req-timeout", tool_name="exec", summary="命令首行: python --version")
    ticks = []

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        QTimer.singleShot(20, lambda: ticks.append("tick"))
        started = time.monotonic()
        window._on_confirm_action_requested("req-timeout", "ignored")
        QTest.qWait(80)
        app.processEvents()
        elapsed = time.monotonic() - started

        assert ticks == ["tick"]
        assert elapsed < 1.0
        assert pending.event.is_set() is True
        assert pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    finally:
        window.close()
        window.deleteLater()


def test_guard_confirm_handler_no_longer_uses_qmessagebox_question():
    source = inspect.getsource(AgentHandlerMixin._on_confirm_action_requested)
    assert "QMessageBox.question" not in source
```

**Verification**:

`uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q`

---

### T013: Add typed pending confirmation metadata and `request_id` lifecycle handling in `src/business/agents/tools/builtin_general_tools.py`

**File**:

`src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**:

FR-001, FR-010, FR-015

**Dependencies**:

T005

**Required changes**:

本任务已并入 T005 的整合变更；`PendingConfirmation`、`get_pending_confirm_metadata()` 和 `_ask_user_confirm()` 的完整请求生命周期就是这一任务的实现。

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py tests/test_hook_protocol.py -q`

---

### T014: Update `write_file_pre_hook`, `edit_file_pre_hook`, and `exec_pre_hook` to call typed confirmation helpers with sanitized summaries in `src/business/agents/tools/builtin_general_tools.py`

**File**:

`src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**:

FR-003, FR-005, FR-006, FR-015

**Dependencies**:

T005

**Required changes**:

本任务已并入 T005 的整合变更；三个 pre_hook 都改成了 `tool_name + summary` 形式，并继续保持 handler 不承载 gate 逻辑。

**Verification**:

`uv run python -m pytest tests/test_hook_protocol.py -q`

---

### T015: Implement the non-modal `AuthToastSurface` widget with "全部允许" / "同意" / "拒绝" buttons and timeout timer in `src/ui/widgets/auth_toast.py`

**File**:

`src/ui/widgets/auth_toast.py` (new)

**Requirements**:

FR-001, FR-002, FR-004, FR-010, FR-016

**Dependencies**:

T001, T009

**Required changes**:

本任务已直接体现在 T001 的完整文件中；核心检查点是三按钮、无普通关闭入口、超时单终态和非模态子组件形态。

**Verification**:

`uv run python -m pytest tests/ui/test_auth_toast_surface.py -q`

---

### T016: Replace `AgentHandlerMixin._on_confirm_action_requested` with a non-blocking auth confirmation queue in `src/ui/mixins/agent_handler_mixin.py`

**File**:

`src/ui/mixins/agent_handler_mixin.py` (modify)

**Requirements**:

FR-001, FR-002, FR-007a, FR-011, FR-012, FR-017, SC-001, SC-005, SC-006

**Dependencies**:

T001, T005, T012

**Before** (line ~217):

```python
def _on_confirm_action_requested(self, request_id: str, message: str) -> None:
    """UI 线程槽：收到 worker 线程的确认请求后弹框"""
    from src.business.agents.tools.builtin_general_tools import set_confirm_result

    reply = QMessageBox.question(
        self,
        "操作确认",
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    set_confirm_result(request_id, reply == QMessageBox.StandardButton.Yes)
```

**After**:

```python
def _ensure_auth_confirmation_state(self) -> None:
    if not hasattr(self, "_auth_confirm_queue"):
        self._auth_confirm_queue = []
    if not hasattr(self, "_active_auth_request"):
        self._active_auth_request = None
    if not hasattr(self, "_active_auth_toast"):
        self._active_auth_toast = None


def _sync_chat_auto_approve_toggle(self, enabled: bool) -> None:
    chat = self._get_chat_widget() if hasattr(self, "_get_chat_widget") else None
    if chat is not None and hasattr(chat, "set_auto_approve_enabled"):
        chat.set_auto_approve_enabled(enabled)


def _dismiss_auth_toast(self) -> None:
    toast = getattr(self, "_active_auth_toast", None)
    if toast is not None:
        toast.hide()
        toast.deleteLater()
    self._active_auth_toast = None
    self._active_auth_request = None
    if hasattr(self, "_position_overlay_toasts"):
        self._position_overlay_toasts()


def _show_next_auth_confirmation(self) -> None:
    from src.business.agents.tools.builtin_general_tools import get_confirm_timeout_ms
    from src.ui.widgets.auth_toast import AuthToastSurface

    self._ensure_auth_confirmation_state()
    if self._active_auth_toast is not None or not self._auth_confirm_queue:
        return

    request = self._auth_confirm_queue.pop(0)
    toast = AuthToastSurface(
        request_id=request["request_id"],
        tool_name=request["tool_name"],
        summary=request["summary"],
        timeout_ms=get_confirm_timeout_ms(),
        parent=self.centralWidget(),
    )
    toast.decision_made.connect(self._on_auth_toast_decision)
    self._active_auth_request = request
    self._active_auth_toast = toast
    toast.show()
    if hasattr(self, "_position_overlay_toasts"):
        self._position_overlay_toasts()


def _drain_auth_queue(self, result: bool, source: str) -> None:
    from src.business.agents.tools.builtin_general_tools import set_confirm_result

    self._ensure_auth_confirmation_state()
    queued = list(self._auth_confirm_queue)
    self._auth_confirm_queue.clear()
    for request in queued:
        set_confirm_result(request["request_id"], result, source)


def _settle_auth_requests_for_new_chat(self) -> None:
    from src.business.agents.tools.builtin_general_tools import reset_auto_approve, set_confirm_result

    self._ensure_auth_confirmation_state()
    reset_auto_approve("new_chat_reset")
    active = self._active_auth_request
    if active is not None:
        set_confirm_result(active["request_id"], False, "toast_timeout")
    self._drain_auth_queue(False, "toast_timeout")
    self._dismiss_auth_toast()
    self._sync_chat_auto_approve_toggle(False)


def _on_chat_new_chat_started(self) -> None:
    self._settle_auth_requests_for_new_chat()


def _on_chat_auto_approve_toggled(self, enabled: bool) -> None:
    from src.business.agents.tools.builtin_general_tools import set_auto_approve_enabled, set_confirm_result

    self._ensure_auth_confirmation_state()
    set_auto_approve_enabled(enabled, "top_toggle")
    self._sync_chat_auto_approve_toggle(enabled)
    if not enabled:
        return

    active = self._active_auth_request
    if active is not None:
        set_confirm_result(active["request_id"], True, "top_toggle")
        self._dismiss_auth_toast()
    self._drain_auth_queue(True, "top_toggle")


def _on_auth_toast_decision(self, request_id: str, decision: str) -> None:
    from src.business.agents.tools.builtin_general_tools import set_auto_approve_enabled, set_confirm_result
    from src.ui.widgets.auth_toast import (
        DECISION_ACCEPT,
        DECISION_ALLOW_ALL,
        DECISION_REJECT,
        DECISION_TIMEOUT,
    )

    if self._active_auth_request is None:
        return
    if self._active_auth_request["request_id"] != request_id:
        return

    if decision == DECISION_ALLOW_ALL:
        set_auto_approve_enabled(True, "toast_allow_all")
        set_confirm_result(request_id, True, "toast_allow_all")
        self._dismiss_auth_toast()
        self._drain_auth_queue(True, "toast_allow_all")
        self._sync_chat_auto_approve_toggle(True)
        return

    if decision == DECISION_ACCEPT:
        set_confirm_result(request_id, True, "toast_accept")
    elif decision == DECISION_REJECT:
        set_confirm_result(request_id, False, "toast_reject")
    else:
        set_confirm_result(request_id, False, "toast_timeout")

    self._dismiss_auth_toast()
    self._show_next_auth_confirmation()


def _on_confirm_action_requested(self, request_id: str, message: str) -> None:
    from src.business.agents.tools.builtin_general_tools import (
        get_pending_confirm_metadata,
        is_auto_approve_enabled,
        set_confirm_result,
    )

    self._ensure_auth_confirmation_state()
    if is_auto_approve_enabled():
        set_confirm_result(request_id, True, "top_toggle")
        self._sync_chat_auto_approve_toggle(True)
        return

    metadata = get_pending_confirm_metadata(request_id) or {
        "request_id": request_id,
        "tool_name": "高危操作",
        "summary": message,
    }
    self._auth_confirm_queue.append(metadata)
    if self._active_auth_toast is None:
        self._show_next_auth_confirmation()
```

**Verification**:

`uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q`

---

### T017: Add active auth toast state and resize repositioning alongside ordinary `_active_toast` in `src/ui/main_window.py`

**File**:

`src/ui/main_window.py` (modify)

**Requirements**:

FR-002, FR-012, FR-017

**Dependencies**:

T001, T016

**Before** (line ~82):

```python
self._sidebar_visible = True
self._active_toast = None
self.menubar = None
```

**After**:

```python
self._sidebar_visible = True
self._active_toast = None
self._active_auth_toast = None
self._active_auth_request = None
self._auth_confirm_queue = []
self._auth_toast_gap = 12
self.menubar = None
```

**Before** (line ~150):

```python
chat_page = ChatWidget()
chat_page.send_message_requested.connect(self._on_chat_send_message)
self.main_content.add_page(CONVERSATIONS, chat_page)
```

**After**:

```python
chat_page = ChatWidget()
chat_page.send_message_requested.connect(self._on_chat_send_message)
chat_page.auto_approve_toggled.connect(self._on_chat_auto_approve_toggled)
chat_page.new_chat_started.connect(self._on_chat_new_chat_started)
self.main_content.add_page(CONVERSATIONS, chat_page)
```

**Before** (line ~342):

```python
def _show_toast(
    self, text: str, auto_dismiss_ms: int = 8000, toast_type: str = "success"
) -> None:
    """右下角浮层 toast 通知"""
    if self._active_toast is not None:
        self._active_toast.deleteLater()
        self._active_toast = None

    toast = QFrame(self.centralWidget())
    toast.setProperty("toastType", toast_type)
    toast.setObjectName("notification_toast")

    layout = QHBoxLayout(toast)
    layout.setContentsMargins(14, 8, 14, 8)

    icon = QLabel("❌" if toast_type == "error" else "✅")
    icon.setFixedWidth(20)
    layout.addWidget(icon)

    label = QLabel(text)
    label.setObjectName("notification_toast_text")
    label.setWordWrap(True)
    layout.addWidget(label, 1)

    close_btn = QPushButton("×")
    close_btn.setObjectName("notification_toast_close")
    close_btn.setFixedSize(18, 18)
    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    layout.addWidget(close_btn)

    toast.setFixedWidth(320)
    toast.adjustSize()
    x = self.centralWidget().width() - toast.width() - 16
    y = self.centralWidget().height() - toast.height() - 16
    toast.move(x, y)
    toast.raise_()
    style = toast.style()
    for w in (toast, label):
        style.unpolish(w)
        style.polish(w)
    toast.show()

    self._active_toast = toast

    auto_timer = QTimer(toast)
    auto_timer.setSingleShot(True)

    def _dismiss():
        if self._active_toast is toast:
            self._active_toast = None
        toast.deleteLater()

    close_btn.clicked.connect(_dismiss)
    auto_timer.timeout.connect(_dismiss)
    auto_timer.start(auto_dismiss_ms)

def resizeEvent(self, event: QResizeEvent):
    """窗口大小变化时重新定位 toast"""
    super().resizeEvent(event)
    if self._active_toast is not None:
        central = self.centralWidget()
        x = central.width() - self._active_toast.width() - 16
        y = central.height() - self._active_toast.height() - 16
        self._active_toast.move(x, y)
```

**After**:

```python
def _position_overlay_toasts(self) -> None:
    central = self.centralWidget()
    if central is None:
        return

    if self._active_toast is not None:
        toast_x = central.width() - self._active_toast.width() - 16
        toast_y = central.height() - self._active_toast.height() - 16
        self._active_toast.move(toast_x, toast_y)

    if self._active_auth_toast is not None:
        auth_x = central.width() - self._active_auth_toast.width() - 16
        auth_y = central.height() - self._active_auth_toast.height() - 16
        if self._active_toast is not None:
            auth_y -= self._active_toast.height() + self._auth_toast_gap
        self._active_auth_toast.move(auth_x, max(16, auth_y))
        self._active_auth_toast.raise_()


def _show_toast(
    self, text: str, auto_dismiss_ms: int = 8000, toast_type: str = "success"
) -> None:
    """右下角普通通知，和确认浮层独立定位。"""
    if self._active_toast is not None:
        self._active_toast.deleteLater()
        self._active_toast = None

    toast = QFrame(self.centralWidget())
    toast.setProperty("toastType", toast_type)
    toast.setObjectName("notification_toast")

    layout = QHBoxLayout(toast)
    layout.setContentsMargins(14, 8, 14, 8)

    icon = QLabel("❌" if toast_type == "error" else "✅")
    icon.setFixedWidth(20)
    layout.addWidget(icon)

    label = QLabel(text)
    label.setObjectName("notification_toast_text")
    label.setWordWrap(True)
    layout.addWidget(label, 1)

    close_btn = QPushButton("×")
    close_btn.setObjectName("notification_toast_close")
    close_btn.setFixedSize(18, 18)
    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    layout.addWidget(close_btn)

    toast.setFixedWidth(320)
    toast.adjustSize()
    toast.raise_()
    style = toast.style()
    for w in (toast, label):
        style.unpolish(w)
        style.polish(w)
    toast.show()

    self._active_toast = toast
    self._position_overlay_toasts()

    auto_timer = QTimer(toast)
    auto_timer.setSingleShot(True)

    def _dismiss():
        if self._active_toast is toast:
            self._active_toast = None
        toast.deleteLater()
        self._position_overlay_toasts()

    close_btn.clicked.connect(_dismiss)
    auto_timer.timeout.connect(_dismiss)
    auto_timer.start(auto_dismiss_ms)


def resizeEvent(self, event: QResizeEvent):
    """窗口大小变化时重新定位普通 Toast 与确认浮层。"""
    super().resizeEvent(event)
    self._position_overlay_toasts()
```

**Verification**:

`uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q -k "fifo or timeout"`

---

### T018: Add auth toast QSS rules without changing ordinary Toast rules in `src/ui/resources/styles.qss`

**File**:

`src/ui/resources/styles.qss` (modify)

**Requirements**:

FR-012, FR-013, FR-016

**Dependencies**:

T001, T017

**Before** (line ~332):

```qss
QWidget#input_container {
    background-color: #ffffff;
    border-top: 1px solid #e9ecef;
}

QWidget#input_wrapper {
    background-color: transparent;
}

QTextEdit#message_input {
    border: 2px solid #e9ecef;
    border-radius: 12px;
    padding: 14px 16px;
    background-color: #ffffff;
    font-size: 15px;
    color: #212529;
    selection-background-color: #667eea;
    selection-color: #ffffff;
}

QTextEdit#message_input:focus {
    border: 2px solid #667eea;
    background-color: #ffffff;
}

QTextEdit#message_input:hover {
    border-color: #adb5bd;
}
```

**After**:

```qss
QWidget#chat_header {
    background-color: #ffffff;
    border-bottom: 1px solid #e9ecef;
}

QLabel#chat_header_title {
    color: #1a1a1a;
    font-size: 16px;
    font-weight: 600;
    background-color: transparent;
}

QLabel#chat_header_subtitle {
    color: #6c757d;
    font-size: 12px;
    background-color: transparent;
}

QPushButton#chat_auto_approve_toggle {
    background-color: #fff7e6;
    color: #9a6700;
    border: 1px solid #f3d38a;
    border-radius: 16px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
}

QPushButton#chat_auto_approve_toggle:hover {
    background-color: #ffefc2;
}

QPushButton#chat_auto_approve_toggle:checked {
    background-color: #f59f00;
    color: #ffffff;
    border-color: #d08700;
}

QWidget#input_container {
    background-color: #ffffff;
    border-top: 1px solid #e9ecef;
}

QWidget#input_wrapper {
    background-color: transparent;
}

QTextEdit#message_input {
    border: 2px solid #e9ecef;
    border-radius: 12px;
    padding: 14px 16px;
    background-color: #ffffff;
    font-size: 15px;
    color: #212529;
    selection-background-color: #667eea;
    selection-color: #ffffff;
}

QTextEdit#message_input:focus {
    border: 2px solid #667eea;
    background-color: #ffffff;
}

QTextEdit#message_input:hover {
    border-color: #adb5bd;
}
```

**Before** (line ~1063):

```qss
QFrame#notification_toast {
    background-color: #e8f5e9;
    border: 1px solid #a5d6a7;
    border-radius: 8px;
}
QFrame#notification_toast QLabel#notification_toast_text {
    color: #2e7d32;
    font-size: 13px;
}
QPushButton#notification_toast_close {
    background: transparent;
    border: none;
    padding: 0px;
    color: #999;
    font-size: 14px;
}
QPushButton#notification_toast_close:hover {
    color: #333;
}

QFrame#notification_toast[toastType="error"] {
    background-color: #fdecea;
    border: 1px solid #f5c6cb;
}
QFrame#notification_toast[toastType="error"] QLabel#notification_toast_text {
    color: #c62828;
}
```

**After**:

```qss
QFrame#notification_toast {
    background-color: #e8f5e9;
    border: 1px solid #a5d6a7;
    border-radius: 8px;
}

QFrame#notification_toast QLabel#notification_toast_text {
    color: #2e7d32;
    font-size: 13px;
}

QPushButton#notification_toast_close {
    background: transparent;
    border: none;
    padding: 0px;
    color: #999;
    font-size: 14px;
}

QPushButton#notification_toast_close:hover {
    color: #333;
}

QFrame#notification_toast[toastType="error"] {
    background-color: #fdecea;
    border: 1px solid #f5c6cb;
}

QFrame#notification_toast[toastType="error"] QLabel#notification_toast_text {
    color: #c62828;
}

QFrame#auth_confirmation_toast {
    background-color: #fff8e1;
    border: 1px solid #f0c36d;
    border-radius: 14px;
}

QLabel#auth_confirmation_title {
    color: #7c4a03;
    font-size: 15px;
    font-weight: 700;
    background-color: transparent;
}

QLabel#auth_confirmation_summary {
    color: #4f3a1c;
    font-size: 13px;
    line-height: 1.5;
    background-color: transparent;
}

QLabel#auth_confirmation_hint {
    color: #8f6b3f;
    font-size: 12px;
    background-color: transparent;
}

QPushButton#auth_confirmation_allow_all_button,
QPushButton#auth_confirmation_accept_button,
QPushButton#auth_confirmation_reject_button {
    min-height: 34px;
    border-radius: 10px;
    font-size: 13px;
    font-weight: 600;
    padding: 0 14px;
}

QPushButton#auth_confirmation_allow_all_button {
    background-color: #f59f00;
    color: #ffffff;
    border: 1px solid #d08700;
}

QPushButton#auth_confirmation_allow_all_button:hover {
    background-color: #db8a00;
}

QPushButton#auth_confirmation_accept_button {
    background-color: #2f855a;
    color: #ffffff;
    border: 1px solid #276749;
}

QPushButton#auth_confirmation_accept_button:hover {
    background-color: #276749;
}

QPushButton#auth_confirmation_reject_button {
    background-color: #ffffff;
    color: #8a2d1f;
    border: 1px solid #e6b8a2;
}

QPushButton#auth_confirmation_reject_button:hover {
    background-color: #fff1eb;
}
```

**Verification**:

运行界面后确认普通 Toast 仍保持原样；`AuthToastSurface` 使用新的琥珀色视觉和三按钮样式。

---

### T019: Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/business/agents/tools/builtin_general_tools.py`, `src/ui/widgets/auth_toast.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, and `src/ui/resources/styles.qss`

**File**:

`src/business/agents/tools/builtin_general_tools.py`, `src/ui/widgets/auth_toast.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, `src/ui/resources/styles.qss` (verification)

**Requirements**:

FR-001, FR-002, FR-004, FR-010, FR-011, FR-012, FR-015, FR-016, SC-001, SC-005, SC-006, SC-007

**Dependencies**:

T001, T002, T003, T005, T012, T016, T017, T018

**Verification**:

```powershell
uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_agent_handler_mixin.py -q
```

---

## Phase 4: User Story 2 - 会话级"全部允许"快捷通道 (Priority: P2)

### T020: Add business tests for auto-approve enable/disable, auto-approved decision logging, and new-chat reset state in `tests/test_auth_toast_confirmation.py`

**File**:

`tests/test_auth_toast_confirmation.py` (new)

**Requirements**:

FR-007, FR-008, FR-015, FR-017, SC-002, SC-003, SC-007

**Dependencies**:

T002, T005

**Required changes**:

本任务已直接体现在 T002 的完整文件中；`test_auto_approve_scope_flips_on_and_off()` 和 `test_confirm_or_reject_logs_auto_approved_path()` 是本任务的核心验证。

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py -q -k "auto_approve or new_chat"`

---

### T021: Add UI tests for "全部允许" auto-approving active/queued requests across 10 consecutive high-risk requests and new-chat settling prior-session active/queued requests in `tests/ui/test_agent_handler_mixin.py`

**File**:

`tests/ui/test_agent_handler_mixin.py` (modify)

**Requirements**:

FR-007, FR-007a, FR-017, SC-002, SC-003

**Dependencies**:

T012

**Required changes**:

本任务已并入 T012 的整合替换；最终整合版里的 `test_allow_all_drains_ten_consecutive_requests_and_syncs_toggle()` 和 `test_new_chat_settles_prior_session_requests_and_resets_toggle()` 直接覆盖本任务要求，不再额外拆测试文件。

**Verification**:

`uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q -k "allow_all or new_chat"`

---

### T022: Implement `set_auto_approve_enabled`, `is_auto_approve_enabled`, `reset_auto_approve`, and auto-approved bypass in `src/business/agents/tools/builtin_general_tools.py`

**File**:

`src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**:

FR-007, FR-008, FR-015, FR-017, SC-002, SC-003, SC-007

**Dependencies**:

T005

**Required changes**:

本任务已并入 T005 的整合变更；`_auto_approve_scope`、`set_auto_approve_enabled()`、`is_auto_approve_enabled()`、`reset_auto_approve()` 和 `_confirm_or_reject()` 中的 bypass 逻辑共同构成本任务实现。

**Verification**:

`uv run python -m pytest tests/test_auth_toast_confirmation.py -q -k "auto_approve"`

---

### T023: Wire the `allow_all` auth toast decision to enable auto-approve and drain queued requests in `src/ui/mixins/agent_handler_mixin.py`

**File**:

`src/ui/mixins/agent_handler_mixin.py` (modify)

**Requirements**:

FR-007, FR-007a, FR-009

**Dependencies**:

T016, T022

**Required changes**:

本任务已并入 T016 的整合变更；`_on_auth_toast_decision()` 中的 `DECISION_ALLOW_ALL` 分支会打开会话级自动放行、放行当前请求、清空队列并同步顶栏状态。

**Verification**:

`uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q -k "allow_all"`

---

### T024: Reset auto-approve and settle/clear visible or queued prior-session confirmation requests from the new-chat flow in `src/ui/main_window.py` and `src/ui/widgets/chat_widget.py`

**File**:

`src/ui/widgets/chat_widget.py` (modify)

**Requirements**:

FR-008, FR-017, CC-005, SC-003

**Dependencies**:

T005, T016, T017

**Before** (line ~75):

```python
class ChatWidget(QWidget):
    """AI 助手对话界面组件（双视图：会话列表 + 对话）"""

    # 发出信号给 MainWindow，让它通过 UIBridge 启动 Agent
    send_message_requested = pyqtSignal(str, str, str)  # session_id, agent_type, user_input

    # 视图索引常量
    VIEW_SESSION_LIST = 0
    VIEW_CONVERSATION = 1
```

**After**:

```python
class ChatWidget(QWidget):
    """AI 助手对话界面组件（双视图：会话列表 + 对话）"""

    send_message_requested = pyqtSignal(str, str, str)
    auto_approve_toggled = pyqtSignal(bool)
    new_chat_started = pyqtSignal()

    VIEW_SESSION_LIST = 0
    VIEW_CONVERSATION = 1
```

**Before** (line ~82):

```python
def __init__(self, parent=None):
    super().__init__(parent)
    self.logger = get_logger(__name__)
    self._session_id = None  # 当前会话 ID（None = 尚未创建）
    self._pending_tool_ids = None  # 延迟创建时暂存的 tool_ids
    self._loading = False  # 是否正在等待 Agent 响应
    self._sessions_page = 0  # 当前滚动加载页码
    self._sessions_page_size = 20  # 每页加载数
    self._all_sessions = []  # 缓存的会话数据
    self._search_text = ""  # 搜索关键词
    self._welcome_visible = False  # 欢迎页是否显示中
    self._welcome_input = None  # 欢迎页输入框引用
    self.init_ui()
```

**After**:

```python
def __init__(self, parent=None):
    super().__init__(parent)
    self.logger = get_logger(__name__)
    self._session_id = None
    self._pending_tool_ids = None
    self._loading = False
    self._sessions_page = 0
    self._sessions_page_size = 20
    self._all_sessions = []
    self._search_text = ""
    self._welcome_visible = False
    self._welcome_input = None
    self._auto_approve_enabled = False
    self.init_ui()
```

**Before** (line ~174):

```python
view.setObjectName("chat_area")
chat_layout = QVBoxLayout(view)
chat_layout.setSpacing(0)
chat_layout.setContentsMargins(0, 0, 0, 0)

# 消息展示区域
messages_scroll = QScrollArea()
messages_scroll.setWidgetResizable(True)
messages_scroll.setObjectName("messages_scroll")
messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

self.messages_container = QWidget()
self.messages_container.setObjectName("messages_container")
self.messages_layout = QVBoxLayout(self.messages_container)
self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
self.messages_layout.setSpacing(24)
self.messages_layout.setContentsMargins(32, 24, 32, 24)
messages_scroll.setWidget(self.messages_container)

chat_layout.addWidget(messages_scroll, 1)
```

**After**:

```python
view.setObjectName("chat_area")
chat_layout = QVBoxLayout(view)
chat_layout.setSpacing(0)
chat_layout.setContentsMargins(0, 0, 0, 0)

header = QWidget()
header.setObjectName("chat_header")
header_layout = QHBoxLayout(header)
header_layout.setContentsMargins(32, 20, 32, 16)
header_layout.setSpacing(12)

header_copy = QVBoxLayout()
header_copy.setSpacing(4)

header_title = QLabel("Assistant 对话")
header_title.setObjectName("chat_header_title")
header_copy.addWidget(header_title)

header_subtitle = QLabel("高危工具会在这里请求确认；“免确认”只对当前会话生效。")
header_subtitle.setObjectName("chat_header_subtitle")
header_subtitle.setWordWrap(True)
header_copy.addWidget(header_subtitle)

header_layout.addLayout(header_copy, 1)

self.auto_approve_toggle = QPushButton("免确认：关闭")
self.auto_approve_toggle.setObjectName("chat_auto_approve_toggle")
self.auto_approve_toggle.setCheckable(True)
self.auto_approve_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
self.auto_approve_toggle.clicked.connect(self._on_auto_approve_toggle_clicked)
header_layout.addWidget(self.auto_approve_toggle)

chat_layout.addWidget(header)

messages_scroll = QScrollArea()
messages_scroll.setWidgetResizable(True)
messages_scroll.setObjectName("messages_scroll")
messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

self.messages_container = QWidget()
self.messages_container.setObjectName("messages_container")
self.messages_layout = QVBoxLayout(self.messages_container)
self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
self.messages_layout.setSpacing(24)
self.messages_layout.setContentsMargins(32, 24, 32, 24)
messages_scroll.setWidget(self.messages_container)

chat_layout.addWidget(messages_scroll, 1)
```

**Before** (line ~314):

```python
def _prepare_new_chat(self, tool_ids=None):
    """准备新对话界面（不立即创建 DB 会话，等用户发第一条消息时再创建）"""
    self._session_id = None
    self._pending_tool_ids = tool_ids
    self._clear_messages()
    self._add_welcome_message()
    self._stack.setCurrentIndex(self.VIEW_CONVERSATION)

def on_new_chat(self):
    """新建对话（外部调用入口）— 只准备 UI，不创建 DB 会话"""
    self._prepare_new_chat()
```

**After**:

```python
def _prepare_new_chat(self, tool_ids=None):
    """准备新对话界面（不立即创建 DB 会话，等用户发第一条消息时再创建）"""
    self._session_id = None
    self._pending_tool_ids = tool_ids
    self._clear_messages()
    self._add_welcome_message()
    self._stack.setCurrentIndex(self.VIEW_CONVERSATION)


def set_auto_approve_enabled(self, enabled: bool) -> None:
    self._auto_approve_enabled = bool(enabled)
    button = getattr(self, "auto_approve_toggle", None)
    if button is None:
        return
    previous = button.blockSignals(True)
    button.setChecked(self._auto_approve_enabled)
    button.setText("免确认：开启" if self._auto_approve_enabled else "免确认：关闭")
    button.setToolTip(
        "当前会话内的高危工具将直接放行"
        if self._auto_approve_enabled
        else "恢复逐次确认"
    )
    button.blockSignals(previous)


def _on_auto_approve_toggle_clicked(self, checked: bool) -> None:
    self.set_auto_approve_enabled(checked)
    self.auto_approve_toggled.emit(self._auto_approve_enabled)


def on_new_chat(self):
    """新建对话（外部调用入口）— 只准备 UI，不创建 DB 会话"""
    self.new_chat_started.emit()
    self.set_auto_approve_enabled(False)
    self._prepare_new_chat()
```

**Verification**:

`uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py -q`

---

### T025: Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/business/agents/tools/builtin_general_tools.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, and `src/ui/widgets/chat_widget.py`

**File**:

`src/business/agents/tools/builtin_general_tools.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, `src/ui/widgets/chat_widget.py` (verification)

**Requirements**:

FR-007, FR-007a, FR-008, FR-017, SC-002, SC-003, SC-007

**Dependencies**:

T005, T016, T017, T024

**Verification**:

```powershell
uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_agent_handler_mixin.py -q
```

---

## Phase 5: User Story 3 - 顶栏 Toggle 与浮层状态双向同步 (Priority: P3)

### T026: Add ChatWidget tests for top "免确认" Toggle default-off, state-change signal, visible enabled-state cue, new-chat reset/off-state contract, and same-frame-or-next-frame state reflection contract in `tests/ui/test_chat_widget_auth_toggle.py`

**File**:

`tests/ui/test_chat_widget_auth_toggle.py` (new)

**Requirements**:

FR-009, FR-013, SC-004

**Dependencies**:

T004, T024

**Required changes**:

本任务已直接体现在 T004 的完整文件中；默认关闭、状态变化、可见提示、新对话复位和同帧/下一帧反射契约都在这一个文件里落地。

**Verification**:

`uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py -q`

---

### T027: Add integration-style UI tests for Toggle auto-approve, Toggle-on draining active/queued requests, Toggle-off re-enables auth toast, and allow-all syncing Toggle state within the same frame or next frame in `tests/ui/test_agent_handler_mixin.py`

**File**:

`tests/ui/test_agent_handler_mixin.py` (modify)

**Requirements**:

FR-007a, FR-009, FR-013, SC-004

**Dependencies**:

T012, T024

**Required changes**:

本任务已并入 T012 的整合替换；最终整合版里的 `test_toggle_on_drains_pending_requests()` 覆盖 Toggle 开启 drain 队列，`test_toggle_off_reenables_auth_toast_after_disabling_auto_approve()` 覆盖重新打开确认浮层，`test_allow_all_drains_ten_consecutive_requests_and_syncs_toggle()` 覆盖反向同步路径。

**Verification**:

`uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q -k "toggle or allow_all"`

---

### T028: Add a conversation header with a checkable "免确认" Toggle and reset API in `src/ui/widgets/chat_widget.py`

**File**:

`src/ui/widgets/chat_widget.py` (modify)

**Requirements**:

FR-009, FR-013

**Dependencies**:

T024

**Required changes**:

本任务已并入 T024 的整合变更；新增对话头部、按钮对象名、`set_auto_approve_enabled()` 和 `auto_approve_toggled` 信号。

**Verification**:

`uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py -q`

---

### T029: Connect ChatWidget Toggle changes to business auto-approve state, drain active/queued confirmation requests on Toggle-on, and sync Toggle after "全部允许" with same-frame-or-next-frame semantics in `src/ui/main_window.py` and `src/ui/mixins/agent_handler_mixin.py`

**File**:

`src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py` (modify)

**Requirements**:

FR-007a, FR-009, FR-013, SC-004

**Dependencies**:

T016, T017, T024

**Required changes**:

本任务已并入 T016 与 T017 的整合变更；`MainWindow` 负责连接 `auto_approve_toggled / new_chat_started` 两个信号，`AgentHandlerMixin` 负责 drain 当前浮层与队列，并把 `toast_allow_all` / `top_toggle` 两条路径都同步回 `ChatWidget`。

**Verification**:

`uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py -q`

---

### T030: Add visible enabled-state styling and warning copy for the "免确认" Toggle in `src/ui/resources/styles.qss`

**File**:

`src/ui/resources/styles.qss` (modify)

**Requirements**:

FR-013, SC-004

**Dependencies**:

T018, T024

**Required changes**:

本任务已并入 T018 的样式整合；重点核对 `QPushButton#chat_auto_approve_toggle` 的默认态、hover 和 `:checked` 态，以及头部副标题的提示文案。

**Verification**:

肉眼检查：关闭态为浅琥珀，开启态为高亮琥珀，按钮文本从“关闭”切到“开启”。

---

### T031: Run `uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py tests/test_auth_toast_confirmation.py -q` and fix failures in `src/ui/widgets/chat_widget.py`, `src/ui/main_window.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/resources/styles.qss`, and `src/business/agents/tools/builtin_general_tools.py`

**File**:

`src/ui/widgets/chat_widget.py`, `src/ui/main_window.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/resources/styles.qss`, `src/business/agents/tools/builtin_general_tools.py` (verification)

**Requirements**:

FR-007a, FR-009, FR-013, SC-004

**Dependencies**:

T018, T024, T029

**Verification**:

```powershell
uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py tests/test_auth_toast_confirmation.py -q
```

---

## Phase 6: Polish & Cross-Cutting Concerns

### T032: Add or update guard assertions that Assistant confirmation wiring no longer imports or calls `QMessageBox.question` in `tests/ui/test_agent_handler_mixin.py`

**File**:

`tests/ui/test_agent_handler_mixin.py` (modify)

**Requirements**:

FR-014, Constitution IV

**Dependencies**:

T012, T016

**Required changes**:

本任务已并入 T012 的整合替换；`test_guard_confirm_handler_no_longer_uses_qmessagebox_question()` 直接对 `AgentHandlerMixin._on_confirm_action_requested` 做 source guard。

**Verification**:

`uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q -k "guard"`

---

### T033: Add regression coverage proving `IntentConfirmationUI` and `ToolExecutionDialog` behavior is unchanged in `tests/test_skill_composition_regressions.py` and `tests/ui/test_agent_handler_mixin.py`

**File**:

`tests/test_skill_composition_regressions.py`, `tests/ui/test_agent_handler_mixin.py` (modify)

**Requirements**:

FR-014

**Dependencies**:

T012

**Before** (line ~844):

```python
def test_intent_confirmation_cancel_emits_signal_without_closing_parent(qt_app):
    from PyQt6.QtWidgets import QWidget

    from src.ui.intent_confirmation_ui import IntentConfirmationUI

    class _ParentWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.closed_via_event = False

        def closeEvent(self, event):
            self.closed_via_event = True
            super().closeEvent(event)

    parent = _ParentWidget()
    page = IntentConfirmationUI(parent)
    triggered = []
    page.cancel_requested.connect(lambda: triggered.append(True))

    parent.show()
    page.show()
    qt_app.processEvents()

    try:
        page.cancel_button.click()
        qt_app.processEvents()

        assert triggered == [True]
        assert parent.closed_via_event is False
        assert parent.isVisible() is True
    finally:
        page.close()
        page.deleteLater()
        parent.close()
        parent.deleteLater()
```

**After**:

```python
def test_intent_confirmation_cancel_emits_signal_without_closing_parent(qt_app):
    from PyQt6.QtWidgets import QWidget

    from src.ui.intent_confirmation_ui import IntentConfirmationUI

    class _ParentWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.closed_via_event = False

        def closeEvent(self, event):
            self.closed_via_event = True
            super().closeEvent(event)

    parent = _ParentWidget()
    page = IntentConfirmationUI(parent)
    triggered = []
    page.cancel_requested.connect(lambda: triggered.append(True))

    parent.show()
    page.show()
    qt_app.processEvents()

    try:
        page.cancel_button.click()
        qt_app.processEvents()

        assert triggered == [True]
        assert parent.closed_via_event is False
        assert parent.isVisible() is True
    finally:
        page.close()
        page.deleteLater()
        parent.close()
        parent.deleteLater()


def test_tool_execution_dialog_cancel_and_execute_keep_existing_result_contract(qt_app):
    from PyQt6.QtWidgets import QDialog, QPushButton

    from src.data.models import Tool
    from src.ui.tool_execution_dialog import ToolExecutionDialog

    tool = Tool(
        tool_id="tool_exec_dialog",
        tool_name="执行测试工具",
        parameters=[],
        status="published",
    )

    dialog = ToolExecutionDialog(tool)
    dialog.show()
    qt_app.processEvents()

    try:
        cancel_button = dialog.findChild(QPushButton, "tool_execution_cancel_button")
        execute_button = dialog.findChild(QPushButton, "tool_execution_execute_button")
        assert cancel_button is not None
        assert execute_button is not None

        cancel_button.click()
        qt_app.processEvents()
        assert dialog.result() == QDialog.DialogCode.Rejected
    finally:
        dialog.close()
        dialog.deleteLater()

    dialog = ToolExecutionDialog(tool)
    dialog.show()
    qt_app.processEvents()

    try:
        execute_button = dialog.findChild(QPushButton, "tool_execution_execute_button")
        assert execute_button is not None

        execute_button.click()
        qt_app.processEvents()
        assert dialog.result() == QDialog.DialogCode.Accepted
    finally:
        dialog.close()
        dialog.deleteLater()
```

**Verification**:

`uv run python -m pytest tests/test_skill_composition_regressions.py tests/ui/test_agent_handler_mixin.py -q -k "intent_confirmation or tool_execution_dialog or guard"`

### Final Consolidated Appendix: `tests/ui/test_agent_handler_mixin.py`

```python
import inspect
import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

import src.business.agents.tools.builtin_general_tools as general_tools
from src.ui.mixins.agent_handler_mixin import AgentHandlerMixin
from src.ui.widgets.auth_toast import (
    AUTH_TOAST_ACCEPT_BUTTON_NAME,
    AUTH_TOAST_ALLOW_ALL_BUTTON_NAME,
    AUTH_TOAST_REJECT_BUTTON_NAME,
)
from src.utils.logger import get_logger


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


@pytest.fixture(autouse=True)
def reset_confirmation_state():
    general_tools.reset_confirmation_state_for_tests()
    yield
    general_tools.reset_confirmation_state_for_tests()


def _seed_pending(request_id: str, tool_name: str = "write_file", summary: str = "目标文件: demo.txt"):
    pending = general_tools.PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=summary,
        created_at=time.monotonic(),
        event=threading.Event(),
    )
    with general_tools._confirm_lock:
        general_tools._pending_confirms[request_id] = pending
    return pending


class _DummyChat:
    def __init__(self):
        self.states = []

    def set_auto_approve_enabled(self, enabled: bool):
        self.states.append(bool(enabled))


class _DummyWindow(QWidget, AgentHandlerMixin):
    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self._chat_widget = _DummyChat()
        self._active_toast = QWidget(self)
        self._active_toast.resize(240, 48)
        self._active_auth_toast = None
        self._active_auth_request = None
        self._auth_confirm_queue = []
        self.toasts = []
        self.resize(800, 600)

    def centralWidget(self):
        return self

    def _get_chat_widget(self):
        return self._chat_widget

    def _position_overlay_toasts(self):
        if self._active_auth_toast is not None:
            self._active_auth_toast.move(16, 16)

    def _show_toast(self, message, **kwargs):
        self.toasts.append((message, kwargs))


def _button(container: QWidget, object_name: str) -> QPushButton:
    button = container.findChild(QPushButton, object_name)
    assert button is not None
    return button


def _click(window: _DummyWindow, object_name: str, app):
    assert window._active_auth_toast is not None
    button = _button(window._active_auth_toast, object_name)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    app.processEvents()


def test_confirm_requests_are_fifo_across_five_workers_and_do_not_replace_existing_toast(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_requests = [
        _seed_pending(f"req-{index}", summary=f"目标文件: file-{index}.txt")
        for index in range(1, 6)
    ]

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        ordinary_toast = window._active_toast
        for pending in pending_requests:
            window._on_confirm_action_requested(pending.request_id, "ignored")

        assert window._active_toast is ordinary_toast
        assert window._active_auth_request["request_id"] == pending_requests[0].request_id
        assert [item["request_id"] for item in window._auth_confirm_queue] == [
            pending.request_id for pending in pending_requests[1:]
        ]

        for pending in pending_requests:
            assert window._active_auth_request["request_id"] == pending.request_id
            _click(window, AUTH_TOAST_ACCEPT_BUTTON_NAME, app)
            assert pending.event.is_set() is True
            assert pending.result is True

        assert window._active_auth_toast is None
        assert window._active_auth_request is None
        assert window._auth_confirm_queue == []
    finally:
        window.close()
        window.deleteLater()


def test_allow_all_drains_ten_consecutive_requests_and_syncs_toggle(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_requests = [
        _seed_pending(
            f"req-{index}",
            tool_name="exec" if index % 3 == 0 else "write_file",
            summary=(
                f"命令首行: python --version #{index}"
                if index % 3 == 0
                else f"目标文件: file-{index}.txt"
            ),
        )
        for index in range(1, 11)
    ]

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        for pending in pending_requests:
            window._on_confirm_action_requested(pending.request_id, "ignored")

        _click(window, AUTH_TOAST_ALLOW_ALL_BUTTON_NAME, app)

        assert general_tools.is_auto_approve_enabled() is True
        assert window._chat_widget.states[-1] is True
        assert window._active_auth_toast is None
        assert window._active_auth_request is None
        assert window._auth_confirm_queue == []
        assert all(pending.event.is_set() and pending.result is True for pending in pending_requests)
    finally:
        window.close()
        window.deleteLater()


def test_toggle_on_drains_pending_requests(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_one = _seed_pending("req-toggle-1")
    pending_two = _seed_pending("req-toggle-2", summary="目标文件: second.txt")

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        window._on_confirm_action_requested("req-toggle-1", "ignored")
        window._on_confirm_action_requested("req-toggle-2", "ignored")

        window._on_chat_auto_approve_toggled(True)
        app.processEvents()

        assert general_tools.is_auto_approve_enabled() is True
        assert pending_one.event.is_set() is True
        assert pending_two.event.is_set() is True
        assert pending_one.result is True
        assert pending_two.result is True
        assert window._chat_widget.states[-1] is True
        assert window._active_auth_toast is None
        assert window._auth_confirm_queue == []
    finally:
        window.close()
        window.deleteLater()


def test_toggle_off_reenables_auth_toast_after_disabling_auto_approve(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending = _seed_pending("req-after-toggle-off", summary="目标文件: after-toggle-off.txt")

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        window._on_chat_auto_approve_toggled(True)
        app.processEvents()
        window._on_chat_auto_approve_toggled(False)
        app.processEvents()

        assert general_tools.is_auto_approve_enabled() is False
        assert window._chat_widget.states[-2:] == [True, False]

        window._on_confirm_action_requested(pending.request_id, "ignored")
        app.processEvents()

        assert window._active_auth_request["request_id"] == pending.request_id
        assert window._active_auth_toast is not None
        assert pending.event.is_set() is False

        _click(window, AUTH_TOAST_REJECT_BUTTON_NAME, app)

        assert pending.event.is_set() is True
        assert pending.result is False
    finally:
        window.close()
        window.deleteLater()


def test_new_chat_settles_prior_session_requests_and_resets_toggle(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 5000)
    pending_one = _seed_pending("req-new-chat-1")
    pending_two = _seed_pending("req-new-chat-2", summary="目标文件: second.txt")

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        window._on_confirm_action_requested("req-new-chat-1", "ignored")
        window._on_confirm_action_requested("req-new-chat-2", "ignored")
        general_tools.set_auto_approve_enabled(True, general_tools.CONFIRM_SOURCE_TOP_TOGGLE)

        window._on_chat_new_chat_started()
        app.processEvents()

        assert general_tools.is_auto_approve_enabled() is False
        assert pending_one.event.is_set() is True
        assert pending_two.event.is_set() is True
        assert pending_one.result is False
        assert pending_two.result is False
        assert window._chat_widget.states[-1] is False
        assert window._auth_confirm_queue == []
        assert window._active_auth_toast is None
    finally:
        window.close()
        window.deleteLater()


def test_confirm_slot_is_non_blocking_and_timeout_converges(app, monkeypatch):
    monkeypatch.setattr(general_tools, "get_confirm_timeout_ms", lambda: 40)
    pending = _seed_pending("req-timeout", tool_name="exec", summary="命令首行: python --version")
    ticks = []

    window = _DummyWindow()
    window.show()
    app.processEvents()

    try:
        QTimer.singleShot(20, lambda: ticks.append("tick"))
        started = time.monotonic()
        window._on_confirm_action_requested("req-timeout", "ignored")
        QTest.qWait(80)
        app.processEvents()
        elapsed = time.monotonic() - started

        assert ticks == ["tick"]
        assert elapsed < 1.0
        assert pending.event.is_set() is True
        assert pending.decision == general_tools.CONFIRM_DECISION_TIMEOUT
    finally:
        window.close()
        window.deleteLater()


def test_guard_confirm_handler_no_longer_uses_qmessagebox_question():
    source = inspect.getsource(AgentHandlerMixin._on_confirm_action_requested)
    assert "QMessageBox.question" not in source
```

---

### T034: Update current code reality for Assistant high-risk confirmation behavior in `AGENTS.md`

**File**:

`AGENTS.md` (modify)

**Requirements**:

Constitution V

**Dependencies**:

T005, T016, T017, T024

**Before** (line ~27):

```markdown
## 当前代码现实

- `src/business/orchestration/agent_orchestrator.py` 只是**兼容入口**；真实实现已拆到 `src/business/orchestration/agent/`
- 当前 Orchestrator 由多个子组件协作：`AgentSessionStore`、`AssistantPromptBuilder`、`AssistantTaskWorker`、`TeachingFailureTracker`、`WorkflowRetryCoordinator`
- `AgentLoop.run()` 支持两种工具注入方式：
  - 直接传 `list[ToolDefinition]`（PM / 程序员 / 试用）
  - 传 `callable` 每轮重建工具列表（assistant 的动态工具懒加载依赖这个）
```

**After**:

```markdown
## 当前代码现实

- `src/business/orchestration/agent_orchestrator.py` 只是**兼容入口**；真实实现已拆到 `src/business/orchestration/agent/`
- 当前 Orchestrator 由多个子组件协作：`AgentSessionStore`、`AssistantPromptBuilder`、`AssistantTaskWorker`、`TeachingFailureTracker`、`WorkflowRetryCoordinator`
- `AgentLoop.run()` 支持两种工具注入方式：
  - 直接传 `list[ToolDefinition]`（PM / 程序员 / 试用）
  - 传 `callable` 每轮重建工具列表（assistant 的动态工具懒加载依赖这个）
- Assistant 的高危工具确认不再使用 `QMessageBox.question`；改为 `AuthToastSurface` + UI FIFO 队列
- “全部允许 / 免确认”是当前会话内的内存态；从浮层或顶栏开启后会立即放行当前请求、清空待展示队列，并在新对话时复位
- 每次高危确认终态都会写脱敏结构化日志；日志只记录 `request_id`、工具名、决策、来源、耗时和摘要，不记录完整内容
```

**Verification**:

文档与 `specs/004-auth-toast/spec.md`、`src/business/agents/tools/builtin_general_tools.py`、`src/ui/mixins/agent_handler_mixin.py` 保持一致。

---

### T035: Update active development constraints for sanitized confirmation logging and non-persistent auto-approve scope in `docs/PROJECT_CONSTRAINTS.md`

**File**:

`docs/PROJECT_CONSTRAINTS.md` (modify)

**Requirements**:

Constitution III, Constitution V

**Dependencies**:

T005, T016

**Before** (line ~29):

```markdown
## Review Guardrails

Reviewer 必须拒绝下列改动：

- 在 pre_hook 中加入参数改写或参数流水线语义。
- 在 `ToolCallContext` 中加入确认回调、结果字段或可写参数引用。
- 在 handler 中保留已经迁移到 pre_hook 的拒绝、确认、限流或安全策略分支。
- 让 AgentLoop 内建注入的 `load_reference` 或 `talk_to_user` 进入 tool/global hook 链。
- 绕过 `src/recording/filtering/` 的 SQL 改写或 DuckDB 代理边界读取录制网络数据。
```

**After**:

```markdown
## Assistant Auth Confirmation Toast

- Assistant 的 `write_file`、`edit_file`、`exec` 高危确认仍属于 `builtin_general_tools` 的 pre_hook 边界；UI 只负责展示和回传决策。
- 确认摘要与结构化日志必须脱敏：允许路径、命令首行和截断片段，禁止完整文件内容、完整替换文本和完整多行命令体进入日志或 UI。
- “全部允许 / 免确认”是会话级运行时内存态；不得写入 `unified_config`、SQLite、DuckDB 或任何持久化存储。

## Review Guardrails

Reviewer 必须拒绝下列改动：

- 在 pre_hook 中加入参数改写或参数流水线语义。
- 在 `ToolCallContext` 中加入确认回调、结果字段或可写参数引用。
- 在 handler 中保留已经迁移到 pre_hook 的拒绝、确认、限流或安全策略分支。
- 让 AgentLoop 内建注入的 `load_reference` 或 `talk_to_user` 进入 tool/global hook 链。
- 绕过 `src/recording/filtering/` 的 SQL 改写或 DuckDB 代理边界读取录制网络数据。
- 把 Assistant 的会话级自动放行状态持久化到配置、数据库或普通日志。
```

**Verification**:

文档内容与 constitution、`spec.md` 和 `builtin_general_tools.py` 中的真实约束保持一致。

---

### T036: Validate the manual flow in `specs/004-auth-toast/quickstart.md` against `src/ui/main_window.py`, `src/ui/widgets/chat_widget.py`, and `src/ui/widgets/auth_toast.py`

**File**:

`specs/004-auth-toast/quickstart.md`, `src/ui/main_window.py`, `src/ui/widgets/chat_widget.py`, `src/ui/widgets/auth_toast.py` (verification)

**Requirements**:

FR-001, FR-007, FR-008, FR-009, FR-012, FR-017

**Dependencies**:

T017, T024

**Verification**:

1. 启动 GUI。
2. 进入 Assistant 对话页。
3. 触发 `write_file`，确认右下角出现非模态确认浮层。
4. 保持浮层可见时滚动消息区域，确认 UI 仍可响应。
5. 点击“同意”，确认工具继续执行。
6. 再次触发并点击“拒绝”，确认工具被取消。
7. 再次触发并点击“全部允许”，确认后续同会话高危请求不再弹浮层。
8. 开启新对话，确认顶栏 Toggle 复位为关闭，旧会话未决请求不再继续展示。

---

### T037: Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_chat_widget_auth_toggle.py tests/test_hook_protocol.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/` and `tests/`

**File**:

`tests/test_auth_toast_confirmation.py`, `tests/ui/test_auth_toast_surface.py`, `tests/ui/test_chat_widget_auth_toggle.py`, `tests/test_hook_protocol.py`, `tests/ui/test_agent_handler_mixin.py` (verification)

**Requirements**:

Constitution IV

**Dependencies**:

T019, T025, T031, T033

**Verification**:

```powershell
uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_chat_widget_auth_toggle.py tests/test_hook_protocol.py tests/ui/test_agent_handler_mixin.py -q
```

---

### T038: Run `uv run black --check src tests` and `uv run flake8 src tests`, then fix formatting/lint issues in `src/` and `tests/`

**File**:

`src/`, `tests/` (verification)

**Requirements**:

Constitution IV

**Dependencies**:

T037

**Verification**:

```powershell
uv run black --check src tests
uv run flake8 src tests
```

## Checklist

- [ ] T001: Create `src/ui/widgets/auth_toast.py` with an empty `AuthToastSurface` placeholder class and module docstring
- [ ] T002: Create `tests/test_auth_toast_confirmation.py` with pytest imports and an autouse fixture that resets confirmation state via `src/business/agents/tools/builtin_general_tools.py`
- [ ] T003: Create `tests/ui/test_auth_toast_surface.py` with Qt offscreen setup and imports for `src/ui/widgets/auth_toast.py`
- [ ] T004: Create `tests/ui/test_chat_widget_auth_toggle.py` with Qt offscreen setup and imports for `src/ui/widgets/chat_widget.py`
- [ ] T005: Extend `set_confirm_result` in `src/business/agents/tools/builtin_general_tools.py` with a backward-compatible optional `source` parameter
- [ ] T006: Define confirmation decision/source constants and a reset helper for tests in `src/business/agents/tools/builtin_general_tools.py`
- [ ] T007: Implement sanitized summary helper functions for `write_file`, `edit_file`, and `exec` arguments in `src/business/agents/tools/builtin_general_tools.py`
- [ ] T008: Implement a structured confirmation decision logging helper in `src/business/agents/tools/builtin_general_tools.py`
- [ ] T009: Add object names and public constants for auth toast buttons/states in `src/ui/widgets/auth_toast.py`
- [ ] T010: Add tests for sanitized summaries, accept/reject result handling, timeout logging, and backward-compatible `set_confirm_result` in `tests/test_auth_toast_confirmation.py`
- [ ] T011: Add UI tests for `AuthToastSurface` buttons, no close button, single terminal signal, and timeout rejection in `tests/ui/test_auth_toast_surface.py`
- [ ] T012: Add AgentHandlerMixin tests for 5-Worker FIFO/no-loss confirmation queue handling, ordinary Toast coexistence, main-window interaction responsiveness <= 100ms, and UI/Worker timeout convergence <= 1s in `tests/ui/test_agent_handler_mixin.py`
- [ ] T013: Add typed pending confirmation metadata and `request_id` lifecycle handling in `src/business/agents/tools/builtin_general_tools.py`
- [ ] T014: Update `write_file_pre_hook`, `edit_file_pre_hook`, and `exec_pre_hook` to call typed confirmation helpers with sanitized summaries in `src/business/agents/tools/builtin_general_tools.py`
- [ ] T015: Implement the non-modal `AuthToastSurface` widget with "全部允许" / "同意" / "拒绝" buttons and timeout timer in `src/ui/widgets/auth_toast.py`
- [ ] T016: Replace `AgentHandlerMixin._on_confirm_action_requested` with a non-blocking auth confirmation queue in `src/ui/mixins/agent_handler_mixin.py`
- [ ] T017: Add active auth toast state and resize repositioning alongside ordinary `_active_toast` in `src/ui/main_window.py`
- [ ] T018: Add auth toast QSS rules without changing ordinary Toast rules in `src/ui/resources/styles.qss`
- [ ] T019: Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/business/agents/tools/builtin_general_tools.py`, `src/ui/widgets/auth_toast.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, and `src/ui/resources/styles.qss`
- [ ] T020: Add business tests for auto-approve enable/disable, auto-approved decision logging, and new-chat reset state in `tests/test_auth_toast_confirmation.py`
- [ ] T021: Add UI tests for "全部允许" auto-approving active/queued requests across 10 consecutive high-risk requests and new-chat settling prior-session active/queued requests in `tests/ui/test_agent_handler_mixin.py`
- [ ] T022: Implement `set_auto_approve_enabled`, `is_auto_approve_enabled`, `reset_auto_approve`, and auto-approved bypass in `src/business/agents/tools/builtin_general_tools.py`
- [ ] T023: Wire the `allow_all` auth toast decision to enable auto-approve and drain queued requests in `src/ui/mixins/agent_handler_mixin.py`
- [ ] T024: Reset auto-approve and settle/clear visible or queued prior-session confirmation requests from the new-chat flow in `src/ui/main_window.py` and `src/ui/widgets/chat_widget.py`
- [ ] T025: Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/business/agents/tools/builtin_general_tools.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/main_window.py`, and `src/ui/widgets/chat_widget.py`
- [ ] T026: Add ChatWidget tests for top "免确认" Toggle default-off, state-change signal, visible enabled-state cue, new-chat reset/off-state contract, and same-frame-or-next-frame state reflection contract in `tests/ui/test_chat_widget_auth_toggle.py`
- [ ] T027: Add integration-style UI tests for Toggle auto-approve, Toggle-on draining active/queued requests, Toggle-off re-enables auth toast, and allow-all syncing Toggle state within the same frame or next frame in `tests/ui/test_agent_handler_mixin.py`
- [ ] T028: Add a conversation header with a checkable "免确认" Toggle and reset API in `src/ui/widgets/chat_widget.py`
- [ ] T029: Connect ChatWidget Toggle changes to business auto-approve state, drain active/queued confirmation requests on Toggle-on, and sync Toggle after "全部允许" with same-frame-or-next-frame semantics in `src/ui/main_window.py` and `src/ui/mixins/agent_handler_mixin.py`
- [ ] T030: Add visible enabled-state styling and warning copy for the "免确认" Toggle in `src/ui/resources/styles.qss`
- [ ] T031: Run `uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py tests/test_auth_toast_confirmation.py -q` and fix failures in `src/ui/widgets/chat_widget.py`, `src/ui/main_window.py`, `src/ui/mixins/agent_handler_mixin.py`, `src/ui/resources/styles.qss`, and `src/business/agents/tools/builtin_general_tools.py`
- [ ] T032: Add or update guard assertions that Assistant confirmation wiring no longer imports or calls `QMessageBox.question` in `tests/ui/test_agent_handler_mixin.py`
- [ ] T033: Add regression coverage proving `IntentConfirmationUI` and `ToolExecutionDialog` behavior is unchanged in `tests/test_skill_composition_regressions.py` and `tests/ui/test_agent_handler_mixin.py`
- [ ] T034: Update current code reality for Assistant high-risk confirmation behavior in `AGENTS.md`
- [ ] T035: Update active development constraints for sanitized confirmation logging and non-persistent auto-approve scope in `docs/PROJECT_CONSTRAINTS.md`
- [ ] T036: Validate the manual flow in `specs/004-auth-toast/quickstart.md` against `src/ui/main_window.py`, `src/ui/widgets/chat_widget.py`, and `src/ui/widgets/auth_toast.py`
- [ ] T037: Run `uv run python -m pytest tests/test_auth_toast_confirmation.py tests/ui/test_auth_toast_surface.py tests/ui/test_chat_widget_auth_toggle.py tests/test_hook_protocol.py tests/ui/test_agent_handler_mixin.py -q` and fix failures in `src/` and `tests/`
- [ ] T038: Run `uv run black --check src tests` and `uv run flake8 src tests`, then fix formatting/lint issues in `src/` and `tests/`
