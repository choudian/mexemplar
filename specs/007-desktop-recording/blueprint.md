# Blueprint: 桌面录制 Phase 1

**Branch**: `007-desktop-recording` | **Date**: 2026-05-05
**Mode**: `scaffold`
**Total Tasks**: 91 | **Files**: 61 new, 24 modified, 0 deleted

## Key Decisions

- 桌面录制与浏览器录制分库内分表，不把桌面录制镜像写入 `recording_sessions`；唯一 mode 查询入口是 `RecordingRepository.get_recording_mode(recording_id)`。→ T006, T007, T008, T048
- 5 个通用录制工具保持同名同 schema，内部按 mode 闭包切表；浏览器路径需要 byte-equal 门卫，跨 mode 表访问统一返回 `table_not_in_mode`。→ T037, T038, T039, T048, T049, T059
- 桌面专属多模态能力通过 3 个新工具注入，并在 `recording.desktop.vision_model` 缺失时只移除 `analyze_desktop_action`。→ T047, T047a, T050, T051, T052, T052a, T082, T083
- Trial 子进程归 execution 层所有：创建 `data/trials/<trial_id>/`、白名单 env、120 秒整树终止、stdout/stderr 落盘都在 `desktop_trial_runner.py` 内完成。→ T060, T061, T062, T063, T064, T065, T068, T069, T070, T071, T072, T075
- UI 层只通过 `DesktopRecordingService` 和 blinker bridge 协调桌面录制；主窗 minimize 完成后才启动 hook，停止后 restore 并弹 sanity check。→ T009, T019, T019a, T031, T032, T033, T034, T035, T079, T080, T081
- 高危 API 判定只保留一个共享实现，事前提示、SC-004 判定与测试都调用同一个 detector，避免规则漂移。→ T011a, T011b, T066, T073, T088

## Implementation Order

```text
Phase 1 Setup
  T001 -> T022
  T002
  T003 -> T004 -> T010 -> T010a -> T083

Phase 2 Foundation
  T006 -> T007 -> T008 -> T012 -> T048 -> T059
  T009 -> T019a -> T034 -> T079 -> T080 -> T081
  T011 -> T067 -> T067a
  T011a -> T011b -> T066 -> T073 -> T088
  T011c -> T030 -> T034 -> T058 -> T075

Phase 3 US1
  T013 -> T023
  T014 -> T024
  T015 -> T025
  T016 -> T026
  T017 -> T027 -> T028
  T020 -> T021 -> T030
  T023 + T024 + T025 + T026 + T027 + T028 + T029 -> T030
  T030 -> T031 -> T032 -> T033 -> T034 -> T035 -> T036 -> T036a -> T036b

Phase 4 US2
  T037 + T038 + T039 + T040 + T041 + T042 + T043 -> T048 + T049 + T050 + T051 + T052 + T059
  T044 + T045 -> T053 -> T054 -> T055
  T046 -> T057 -> T058
  T047 + T047a -> T052a
  T047b + T059a validates US1 and US2

Phase 5 US3
  T060 + T061 + T062 + T063 + T064 + T065 + T068 -> T069 -> T070 -> T071 -> T072
  T066 + T066a -> T073 -> T074 -> T075

Phase 6 US4
  T076 -> T080
  T077 -> T079 -> T081
  T078 -> T082 -> T083

Phase 7 Polish
  T084 + T085 + T086 + T087 + T089 + T090 -> T088 -> T091
```

---

## File-Level Final Blueprint

这一节是实施时的文件级最终形状。下面的代码块是可复制的完整实现片段；对同一文件有多个任务时，以本节的最终形状为准，再按各任务条目执行验证。

### New File: `src/recording/desktop/dpi_awareness.py`

**Covers**: T001, T022

```python
from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DpiAwarenessResult:
    ok: bool
    level: str
    reason: str | None = None


def apply() -> DpiAwarenessResult:
    """Apply Windows Per-Monitor V2 DPI awareness before QApplication exists."""
    if sys.platform != "win32":
        return DpiAwarenessResult(ok=False, level="unsupported", reason="non_windows")

    try:
        context = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(context)
        return DpiAwarenessResult(ok=True, level="per_monitor_v2")
    except Exception as exc:
        logger.info("[desktop dpi] Per-Monitor V2 failed: %s", exc)

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return DpiAwarenessResult(ok=True, level="per_monitor_v1")
    except Exception as exc:
        logger.info("[desktop dpi] Per-Monitor V1 failed: %s", exc)

    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return DpiAwarenessResult(ok=True, level="system")
    except Exception as exc:
        logger.warning("[desktop dpi] DPI awareness unavailable: %s", exc)
        return DpiAwarenessResult(ok=False, level="unavailable", reason=type(exc).__name__)
```

### New File: `src/business/utils/high_risk_api_detector.py`

**Covers**: T011a, T066, T088

```python
from __future__ import annotations

import ast
import re

PYWIN32_MODULES = {
    "win32api",
    "win32gui",
    "win32com",
    "win32process",
    "win32service",
    "win32clipboard",
    "pythoncom",
}
PYWINAUTO_MODULE = "pywinauto"
URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def _top_name(name: str | None) -> str:
    return (name or "").split(".")[0]


def _full_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _full_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _is_protocol_literal(value: str) -> bool:
    if WINDOWS_DRIVE_RE.match(value):
        return False
    return bool(URL_SCHEME_RE.match(value))


def detect_high_risk_apis(code: str) -> list[str]:
    """Return stable labels for shortcut or high-risk desktop APIs used by code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    labels: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_name(alias.name)
                if top == "subprocess":
                    labels.add("subprocess")
                if top == "webbrowser":
                    labels.add("webbrowser")
                if top in PYWIN32_MODULES:
                    labels.add("pywin32")
                if top == PYWINAUTO_MODULE:
                    labels.add("pywinauto")

        elif isinstance(node, ast.ImportFrom):
            top = _top_name(node.module)
            if top == "subprocess":
                labels.add("subprocess")
            if top == "webbrowser":
                labels.add("webbrowser")
            if top in PYWIN32_MODULES:
                labels.add("pywin32")
            if top == PYWINAUTO_MODULE:
                labels.add("pywinauto")

        elif isinstance(node, ast.Call):
            name = _full_name(node.func)
            top = _top_name(name)
            if top == "subprocess":
                labels.add("subprocess")
            if name == "os.startfile":
                labels.add("os.startfile")
            if top == "webbrowser":
                labels.add("webbrowser")
            if top in PYWIN32_MODULES:
                labels.add("pywin32")
            if name == "pywinauto.Application" or top == PYWINAUTO_MODULE:
                labels.add("pywinauto")

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_protocol_literal(node.value):
                labels.add("win32_protocol_url")

    return sorted(labels)
```

### New File: `src/execution/desktop_trial_models.py`

**Covers**: T072

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TrialResult:
    ok: bool
    summary: str
    details: dict[str, Any] | None
    exit_code: int | None
    timed_out: bool
    stdout_path: Path
    stderr_path: Path
    trial_id: str
```

### New File: `src/execution/desktop_trial_runner.py`

**Covers**: T069, T070, T071

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.execution.desktop_trial_models import TrialResult

WHITELISTED_ENV_VARS = {
    "PATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "PYTHONPATH",
    "PYTHONHOME",
    "LANG",
    "LC_ALL",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
}
SENSITIVE_PATTERNS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "KEYRING")
TRIAL_TIMEOUT_SECONDS = 120

WRAPPER_TEMPLATE = r'''
import asyncio
import json
import traceback

{user_code}

async def _main():
    try:
        result = await execute()
        if not isinstance(result, dict):
            return {{"ok": False, "summary": "execute() 返回非 dict: " + type(result).__name__, "details": None}}
        if "ok" not in result or "summary" not in result:
            return {{"ok": False, "summary": "execute() 返回缺少 ok 或 summary 字段", "details": result}}
        return result
    except Exception as exc:
        return {{
            "ok": False,
            "summary": type(exc).__name__ + ": " + str(exc),
            "details": {{"traceback": traceback.format_exc()}},
        }}

if __name__ == "__main__":
    try:
        payload = asyncio.run(_main())
    except Exception as exc:
        payload = {{
            "ok": False,
            "summary": type(exc).__name__ + ": " + str(exc),
            "details": {{"traceback": traceback.format_exc()}},
        }}
    print(json.dumps(payload, ensure_ascii=False))
'''


def build_whitelisted_env(parent_env: dict[str, str] | None = None) -> dict[str, str]:
    source = parent_env or os.environ
    result: dict[str, str] = {}
    for key, value in source.items():
        key_upper = key.upper()
        if key_upper not in WHITELISTED_ENV_VARS:
            continue
        if any(pattern in key_upper for pattern in SENSITIVE_PATTERNS):
            continue
        result[key] = value
    return result


def _stderr_tail(stderr_text: str) -> str:
    tail = "\n".join(stderr_text.splitlines()[-5:])[:200]
    return tail or "(无 stderr 输出)"


def parse_trial_stdout(stdout_bytes: bytes, stderr_bytes: bytes, exit_code: int) -> dict[str, Any]:
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    lines = [line.strip() for line in stdout_text.splitlines() if line.strip()]
    if lines:
        try:
            parsed = json.loads(lines[-1])
            if isinstance(parsed, dict) and "ok" in parsed and "summary" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass
    return {
        "ok": False,
        "summary": _stderr_tail(stderr_text),
        "details": {"_fallback": "stdout_no_json", "exit_code": exit_code},
    }


def is_trial_success(result: TrialResult) -> bool:
    return result.exit_code == 0 and result.ok and not result.timed_out


def _trial_root() -> Path:
    return Path("data") / "trials"


def _write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def run_desktop_trial(code: str, trial_id: str) -> TrialResult:
    trial_dir = _trial_root() / trial_id
    trial_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = trial_dir / "stdout.log"
    stderr_path = trial_dir / "stderr.log"
    wrapper_code = WRAPPER_TEMPLATE.format(user_code=code)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", wrapper_code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(trial_dir),
        env=build_whitelisted_env(),
        creationflags=creationflags,
    )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = proc.communicate(timeout=TRIAL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.terminate()
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                timeout=5,
                capture_output=True,
                check=False,
            )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout_bytes, stderr_bytes = proc.communicate()

    _write_bytes(stdout_path, stdout_bytes)
    _write_bytes(stderr_path, stderr_bytes)

    if timed_out:
        return TrialResult(
            ok=False,
            summary="代码执行超过 120 秒已被终止",
            details={"timed_out": True},
            exit_code=proc.returncode,
            timed_out=True,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            trial_id=trial_id,
        )

    parsed = parse_trial_stdout(stdout_bytes, stderr_bytes, proc.returncode or 0)
    return TrialResult(
        ok=bool(parsed.get("ok")),
        summary=str(parsed.get("summary", "")),
        details=parsed.get("details"),
        exit_code=proc.returncode,
        timed_out=False,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        trial_id=trial_id,
    )
```

### New File: `src/business/orchestration/agent/desktop_syntax_gate.py`

**Covers**: T046, T057, T058

```python
from __future__ import annotations

import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyntaxGateResult:
    ok: bool
    feedback: str | None = None
    lineno: int | None = None
    message: str | None = None


def _snippet(code: str, lineno: int | None, radius: int = 2) -> str:
    if lineno is None:
        return ""
    lines = code.splitlines()
    start = max(1, lineno - radius)
    end = min(len(lines), lineno + radius)
    return "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, end + 1))


def build_feedback(code: str, exc: SyntaxError) -> str:
    lineno = exc.lineno or 1
    return (
        f"你之前生成的代码在 line {lineno} 出现语法错误：{exc.msg}\n\n"
        "出错位置（含上下 2 行）：\n"
        f"{_snippet(code, lineno)}\n\n"
        "请重新输出修复后的完整 `async def execute() -> dict` 函数。"
    )


def check_code(code: str) -> SyntaxGateResult:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return SyntaxGateResult(
            ok=False,
            feedback=build_feedback(code, exc),
            lineno=exc.lineno,
            message=exc.msg,
        )
    return SyntaxGateResult(ok=True)


def should_retry(attempt_index: int, max_retries: int = 2) -> bool:
    return attempt_index < max_retries


def log_terminal_failure(workflow_id: str, attempts: list[str], feedbacks: list[str]) -> None:
    logger.error(
        "[desktop syntax gate] workflow=%s attempts=%d feedbacks=%d",
        workflow_id,
        len(attempts),
        len(feedbacks),
    )
```

### New File: `src/ui/widgets/desktop_sanity_check_dialog.py`

**Covers**: T076, T077, T079, T080, T081

```python
from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

ACTION_TYPES = ("mouse_left", "mouse_right", "mouse_middle", "wheel", "drag", "typing", "hotkey")


@dataclass(frozen=True)
class HealthStats:
    uia_hit: int = 0
    uia_total: int = 0
    clip_success: int = 0
    clip_total: int = 0
    clipboard_event_count: int = 0
    action_type_counts: dict[str, int] = field(default_factory=dict)
    frame_total: int = 0
    duration_seconds: float = 0.0

    @classmethod
    def from_dict(cls, value: dict) -> "HealthStats":
        counts = {name: int(value.get("action_type_counts", {}).get(name, 0)) for name in ACTION_TYPES}
        return cls(
            uia_hit=int(value.get("uia_hit", 0)),
            uia_total=int(value.get("uia_total", 0)),
            clip_success=int(value.get("clip_success", 0)),
            clip_total=int(value.get("clip_total", 0)),
            clipboard_event_count=int(value.get("clipboard_event_count", 0)),
            action_type_counts=counts,
            frame_total=int(value.get("frame_total", 0)),
            duration_seconds=float(value.get("duration_seconds", 0.0)),
        )

    @property
    def action_total(self) -> int:
        return sum(self.action_type_counts.values())


def determine_health_color(stats: HealthStats, enable_clip: bool) -> str:
    if stats.action_total == 0:
        return "red"
    yellow = False
    if stats.uia_total > 0 and stats.uia_hit / stats.uia_total < 0.5:
        yellow = True
    if enable_clip and stats.clip_total > 0:
        failure_rate = (stats.clip_total - stats.clip_success) / stats.clip_total
        if failure_rate > 0.2:
            yellow = True
    return "yellow" if yellow else "green"


class DesktopSanityCheckDialog(QDialog):
    continueAnalysisRequested = pyqtSignal(str)
    abandonRequested = pyqtSignal(str)
    rerecordRequested = pyqtSignal(str)

    def __init__(self, recording_id: str, stats: HealthStats, enable_clip: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self._recording_id = recording_id
        self._stats = stats
        self._enable_clip = enable_clip
        self.setWindowTitle("录制健康反馈")
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        color = determine_health_color(self._stats, self._enable_clip)
        layout.addWidget(QLabel(f"状态：{color}"))
        layout.addWidget(QLabel(f"动作总数：{self._stats.action_total}"))
        layout.addWidget(QLabel(f"帧总数：{self._stats.frame_total}"))
        layout.addWidget(QLabel(f"clip 数：{self._stats.clip_success}/{self._stats.clip_total}"))
        layout.addWidget(QLabel(f"剪贴板事件：{self._stats.clipboard_event_count}"))
        layout.addWidget(QLabel(f"UIA 命中率：{self._stats.uia_hit}/{self._stats.uia_total}"))
        layout.addWidget(QLabel(f"录制时长：{self._stats.duration_seconds:.1f} 秒"))
        for action_type in ACTION_TYPES:
            layout.addWidget(QLabel(f"{action_type}: {self._stats.action_type_counts.get(action_type, 0)}"))

        buttons = QHBoxLayout()
        continue_button = QPushButton("继续分析")
        abandon_button = QPushButton("放弃录制")
        rerecord_button = QPushButton("重新录制")
        continue_button.clicked.connect(self._continue_analysis)
        abandon_button.clicked.connect(self._abandon)
        rerecord_button.clicked.connect(self._rerecord)
        buttons.addWidget(continue_button)
        buttons.addWidget(abandon_button)
        buttons.addWidget(rerecord_button)
        layout.addLayout(buttons)

    def _continue_analysis(self) -> None:
        self.continueAnalysisRequested.emit(self._recording_id)
        self.accept()

    def _abandon(self) -> None:
        self.abandonRequested.emit(self._recording_id)
        self.reject()

    def _rerecord(self) -> None:
        self.rerecordRequested.emit(self._recording_id)
        self.reject()
```

### New File: `src/ui/widgets/recording_floating_widget.py`

**Covers**: T033

```python
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class RecordingFloatingWidget(QWidget):
    stopRequested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self._drag_origin: QPoint | None = None
        self._count_label = QLabel("录制中 0 个动作")
        self._stop_button = QPushButton("停止")
        self._stop_button.clicked.connect(self.stopRequested.emit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(QLabel("🔴"))
        layout.addWidget(self._count_label)
        layout.addWidget(self._stop_button)
        self.setFixedSize(160, 40)

    def set_action_count(self, count: int) -> None:
        self._count_label.setText(f"录制中 {count} 个动作")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_origin = None
        super().mouseReleaseEvent(event)
```

### New File: `src/ui/widgets/desktop_trial_dialogs.py`

**Covers**: T066a, T073, T074

```python
from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from src.business.utils.high_risk_api_detector import detect_high_risk_apis
from src.execution.desktop_trial_models import TrialResult


class DesktopTrialPreviewDialog(QDialog):
    def __init__(self, code: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._accepted = False
        self.setWindowTitle("试用提示")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("试用代码即将在桌面真实执行（最长 120s）"))
        preview = QPlainTextEdit("\n".join(code.splitlines()[:20]))
        preview.setReadOnly(True)
        layout.addWidget(preview)
        labels = detect_high_risk_apis(code)
        label_text = "、".join(labels) if labels else "未检测到"
        layout.addWidget(QLabel(f"检测到的高危 API：{label_text}"))
        buttons = QHBoxLayout()
        start = QPushButton("开始")
        cancel = QPushButton("取消")
        start.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(start)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)


def trial_toast_payload(result: TrialResult) -> tuple[str, str]:
    if result.timed_out:
        return "试用超时", "代码执行超过 120 秒已被终止"
    if result.ok and result.exit_code == 0:
        return "试用成功", result.summary
    return "试用失败", result.summary
```

### Config And Repository Modifications

**Covers**: T003, T004, T006, T007, T008, T010, T011

**Required changes**:

1. In `pyproject.toml`, keep existing `mss`, `opencv-python`, `pillow`, `pynput`, `pywinauto`; add `"comtypes>=1.4.12; platform_system == 'Windows'"` and `"pywin32>=311; platform_system == 'Windows'"`.
2. In `config.example.json`, change `recording.default_recording_mode` to `"browser"` and add:

```json
"desktop": {
  "enable_clip": true,
  "vision_model": null
}
```

3. In `src/data/config_models.py`, add `RecordingDesktopConfig` beside `LargeFieldConfig`, add `desktop: RecordingDesktopConfig = field(default_factory=RecordingDesktopConfig)` to `RecordingConfig`, include it in `AppConfig.from_dict()` nested dataclass loading, and change `default_recording_mode` to `"browser"`.
4. In `src/data/unified_config.py`, import `RecordingDesktopConfig`, add `get_recording_desktop_config()`, `get_desktop_enable_clip()`, and `get_desktop_vision_model()`.
5. In `src/data/recording_repository.py`, change browser session/action fallback defaults to `"browser"`, then add:

```python
def ensure_desktop_tables(self) -> None:
    self.db.execute(
        """
        CREATE TABLE IF NOT EXISTS desktop_recordings (
            recording_id VARCHAR PRIMARY KEY,
            recording_mode VARCHAR NOT NULL DEFAULT 'desktop',
            start_time TIMESTAMP NOT NULL,
            end_time TIMESTAMP,
            monitor_index INTEGER NOT NULL,
            status VARCHAR NOT NULL CHECK (status IN ('recording', 'stopped', 'abandoned')),
            health_stats JSON,
            created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
        )
        """
    )
    self.db.execute(
        """
        CREATE TABLE IF NOT EXISTS desktop_actions (
            action_id VARCHAR PRIMARY KEY,
            recording_id VARCHAR NOT NULL,
            recording_mode VARCHAR NOT NULL DEFAULT 'desktop',
            type VARCHAR NOT NULL CHECK (type IN ('mouse_left', 'mouse_right', 'mouse_middle', 'wheel', 'drag', 'typing', 'hotkey')),
            coord_x INTEGER,
            coord_y INTEGER,
            monitor_index INTEGER NOT NULL,
            window_title VARCHAR,
            uia_summary JSON,
            clipboard_text VARCHAR,
            clipboard_image_path VARCHAR,
            text_content VARCHAR,
            timestamp TIMESTAMP NOT NULL,
            duration_ms INTEGER,
            frame_count INTEGER NOT NULL DEFAULT 0,
            has_clip BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
        )
        """
    )
    self.db.execute(
        "CREATE INDEX IF NOT EXISTS desktop_actions_recording_timestamp_idx ON desktop_actions (recording_id, timestamp)"
    )
    self.db.execute(
        "CREATE INDEX IF NOT EXISTS desktop_actions_recording_type_idx ON desktop_actions (recording_id, type)"
    )
```

6. Add repository methods `insert_desktop_recording`, `update_desktop_recording_status`, `update_desktop_recording_health_stats`, `get_desktop_recording_meta`, `insert_desktop_action`, `list_desktop_actions`, and `get_recording_mode`. Use existing `self.db.insert`, `self.db.fetchone`, `self.db.execute`, `self.db.execute_and_fetchall` patterns; serialize `health_stats` and `uia_summary` with `json.dumps(value, ensure_ascii=False)`.
7. In `ensure_startup_recovery()`, after queue recovery, call a private `_cleanup_old_trial_dirs()` that removes only `data/trials/*` directories whose mtime is older than seven days. It must not scan `data/recordings/` and must not delete desktop rows.

### Tooling And Prompt Modifications

**Covers**: T037, T038, T039, T040, T041, T042, T043, T044, T045, T047, T047a, T047b, T048, T049, T050, T051, T052, T052a, T053, T054, T055, T056, T059, T090

**Required changes**:

1. Extend `src/recording/filtering/decision.py` with mode allowlists:

```python
BROWSER_MODE_TABLES = frozenset({
    "recording_sessions",
    "actions",
    "network_requests",
    "sibling_snapshots",
    "recording_screenshots",
})
DESKTOP_MODE_TABLES = frozenset({"desktop_recordings", "desktop_actions"})
MODE_TABLES = {"browser": BROWSER_MODE_TABLES, "desktop": DESKTOP_MODE_TABLES}
```

2. Add `validate_table_against_mode_allowlist(sql: str, mode: str) -> None` to `sql_rewriter.py`. Parse with sqlglot, collect every concrete `exp.Table`, ignore subquery aliases, and raise `SqlRewriteError("table_not_in_mode:<table>:<mode>")` for a table outside `MODE_TABLES[mode]`.
3. Change `recording_data_tools.create_recording_tools(recording_id)` to fetch mode once via `RecordingRepository.get_recording_mode(recording_id)`. Pass mode into `_describe_data`, `_query_data`, `_execute_code`, `_read_recording`, `_read_field_chunk`, and `query_data_pre_hook`.
4. Keep browser metadata and output byte-identical for mode `browser`; add desktop metadata only when mode is `desktop`.
5. Create `src/business/agents/tools/desktop_tools.py` with `create_desktop_specific_tools(recording_id)`. It returns `list_desktop_actions`, conditionally `analyze_desktop_action`, and `read_action_clip`. `analyze_desktop_action` is omitted when `get_unified_config().get_desktop_vision_model()` returns a false value.
6. In `desktop_tools.py`, use `PIL.Image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)` before base64 upload; call the same `LangChainLLMClient` construction path currently used by `analyze_image`, but pass `model=config.get_desktop_vision_model()`.
7. Create `src/business/agents/prompts/desktop_prompts.py`; browser builders return imported legacy constants unchanged, desktop builders concatenate common header, desktop guidance, and footer. Required phrases are `按 window_title 聚焦`, `list_desktop_actions`, `analyze_desktop_action`, `read_action_clip`, and `async def execute() -> dict`.
8. In `programmer_tools.py`, extend `execution_strategy` enum to include `desktop`; update `src/business/tool_trial/trial_models.py` comments and validators to accept it.
9. In `orchestrator.py`, do not mutate global configs. Use `dataclasses.replace(PM_CONFIG, system_prompt=build_pm_prompt(mode))` and the matching Programmer call when constructing a loop for PM or Programmer. Add desktop tool composition rules for PM, Programmer, and Trial. Browser mode keeps `analyze_image` and never receives desktop-specific tools.
10. In Programmer completion, if mode is `desktop`, run `desktop_syntax_gate.check_code()` before review and before Trial. On retryable syntax errors, send the generated feedback back to Programmer; after three failed attempts, emit `desktop_syntax_gate_retry_failed`.

### Recording Layer New Files

**Covers**: T013, T014, T015, T016, T017, T018, T020, T021, T023, T024, T025, T026, T027, T028, T029, T030, T036

Create `src/recording/desktop/__init__.py`, `pynput_hook.py`, `uia_querier.py`, `clipboard_watcher.py`, `frame_ring_buffer.py`, `png_sink.py`, `clip_sink.py`, and `hotkey_register.py`, plus `src/recording/desktop_recorder.py`.

**Implementation contract**:

- `pynput_hook.py` exposes `RecorderStartFailed`, `DesktopActionEvent`, and `DesktopPynputHook`. It never records mouse move. It groups character input into typing slices split by one second pause, non-character hotkey, window change, or mouse action. Ctrl, Alt, and Win produce hotkey events; Shift with a character stays typing.
- `uia_querier.py` exposes `UiaQuerier.query_at(x, y, timeout_ms=50)` and returns shallow fields `control_type`, `name`, `automation_id`, `class_name`, `framework_id`, `is_enabled`, `is_offscreen`, and owning `window_title`. It does not call `GetForegroundWindow`.
- `clipboard_watcher.py` exposes `_ClipboardLatest` and `ClipboardWatcher`. It subscribes through `AddClipboardFormatListener` when available, polls every 500 ms as fallback, reads immediately on Ctrl+V notification, and writes images to `data/recordings/<recording_id>/clipboard/<recording_id>_<event_seq>.png`.
- `frame_ring_buffer.py` exposes `_FrameRingBuffer(fps=15, capacity=30)`. `frames_for_action(action_time)` returns all frames from one second before to two seconds after the action, including all available early frames without duplication.
- `png_sink.py` writes native-resolution frames with `Image.save(path, "PNG", compress_level=6)` under `frames/<action_id>/frame_001.png`.
- `clip_sink.py` writes mp4v clips under `clips/<action_id>.mp4` only when `enable_clip=True`; failed writer initialization returns `has_clip=False` and increments `clip_total` without incrementing `clip_success`.
- `hotkey_register.py` exposes `HotkeyRegistrationResult` and a Ctrl+Alt+S registrar. Failure returns `ok=False` with reason `hotkey_register_failed` and never blocks recording.
- `desktop_recorder.py` owns the in-memory active-recorder mutex, aggregates health stats, writes desktop actions through Repository, applies large-field substitution before insert, emits `desktop_action_count_changed`, `desktop_recorder_start_failed`, `desktop_recording_degraded`, and existing `recording_stopped`, and writes `health_stats` exactly once on stop.

### UI And Service Modifications

**Covers**: T009, T019, T019a, T031, T032, T034, T035, T036a, T036b, T078, T082, T083

1. Create `src/business/services/desktop_recording_service.py` with `DesktopRecordingService` and `HealthStats`. Methods are `start_after_minimize(recording_id)`, `get_health_stats(recording_id)`, `stop(recording_id)`, `mark_abandoned(recording_id)`, and `mark_stopped(recording_id)`. The service owns the `DesktopRecorder` instance map and is the only UI-facing business API.
2. In `recording_mixin.py`, replace the unsupported desktop branch with a call into the recording page desktop flow. UI must not instantiate `DesktopRecorder`.
3. In `recording_widget.py`, store geometry and window state, call `showMinimized()`, install an event filter for `QEvent.WindowStateChange`, and call `DesktopRecordingService.start_after_minimize(recording_id)` only after the minimized state is observed.
4. In `recording_widget.py`, subscribe to desktop blinker events through a UI-local Qt bridge. On stop, hide floating widget, `showNormal()`, `restoreGeometry()`, `setWindowState()`, then open `DesktopSanityCheckDialog` as modal child.
5. Add UI disable logic for the desktop card when any browser or extension-triggered recorder state is active. Tooltip text is `已有其他模式录制中`.
6. Add `_vision_model_warning_shown_for_recordings: set[str]`. On first intent-page entry per desktop `recording_id`, if `recording.desktop.vision_model` is empty, show an 8-second non-modal toast and continue PM startup.
7. Create `src/ui/widgets/settings/desktop_recording_settings.py` with a `QLineEdit` for `vision_model`, a `QCheckBox` for `enable_clip`, and writes through `UnifiedConfigManager.set("recording.desktop.vision_model", value)` and `set("recording.desktop.enable_clip", checked, value_type="boolean")`.

### Events Modification

**Covers**: T011c

In `src/utils/events.py`, add signal objects, append them to `_signal_names`, and export them in `__all__`:

```python
desktop_action_count_changed = _signals.signal("desktop_action_count_changed")
desktop_recorder_start_failed = _signals.signal("desktop_recorder_start_failed")
desktop_recording_degraded = _signals.signal("desktop_recording_degraded")
desktop_syntax_gate_retry_failed = _signals.signal("desktop_syntax_gate_retry_failed")
desktop_trial_preview_ready = _signals.signal("desktop_trial_preview_ready")
desktop_trial_finished = _signals.signal("desktop_trial_finished")
```

### Main Entry Modification

**Covers**: T022

Replace the inline DPI block in `src/main.py:_launch_gui()` with:

```python
from src.recording.desktop.dpi_awareness import apply as apply_desktop_dpi_awareness

dpi_result = apply_desktop_dpi_awareness()
if not dpi_result.ok:
    logger.info("[desktop dpi] degraded: level=%s reason=%s", dpi_result.level, dpi_result.reason)
```

The import and call must happen before `QApplication([])` and after logging is ready. Do not call Qt before DPI awareness.

---

## Phase 1: Setup (Shared Infrastructure)

### T001: 创建 `src/recording/desktop/dpi_awareness.py`

**File**: `src/recording/desktop/dpi_awareness.py` (new)

**Requirements**: FR-006

**Dependencies**: none

Use the complete file content in File-Level Final Blueprint.

**Verification**: `python -m py_compile src/recording/desktop/dpi_awareness.py`; on non-Windows `apply().reason == "non_windows"` and no import-time crash.

---

### T002: 添加或验证桌面录制依赖

**File**: `pyproject.toml` (modify)

**Requirements**: FR-002, FR-003, FR-004, FR-005, FR-006

**Dependencies**: none

**Before** (dependencies block currently includes):

```toml
"mss>=10.1.0",
"opencv-python>=4.12.0.88",
"pillow>=12.1.0",
"pynput>=1.8.1",
"pywinauto>=0.6.9",
```

**After**:

```toml
"comtypes>=1.4.12; platform_system == 'Windows'",
"mss>=10.1.0",
"opencv-python>=4.12.0.88",
"pillow>=12.1.0",
"pynput>=1.8.1",
"pywin32>=311; platform_system == 'Windows'",
"pywinauto>=0.6.9",
```

**Verification**: `uv lock --check` if lockfile exists, otherwise `uv run python -c "import pynput, mss, cv2, PIL"` on a prepared environment.

---

### T003: 添加桌面录制配置示例

**File**: `config.example.json`, `config.example.comments.md` (modify)

**Requirements**: FR-026, FR-026a

**Dependencies**: T002

Add `recording.desktop.enable_clip=true` and `recording.desktop.vision_model=null`; update comments to state that empty `vision_model` disables `analyze_desktop_action` while keeping metadata tools available.

**Verification**: Parse `config.example.json` with `json.load`; comments document both keys.

---

## Phase 2: Foundational (Blocking Prerequisites)

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T005: 修正 recording_widget fallback | `src/ui/widgets/recording_widget.py` | Already complete — current line uses `default=RecordingMode.BROWSER` |

---

### T004: 修正录制配置模型

**File**: `src/data/config_models.py` (modify)

**Requirements**: FR-010, FR-026, FR-026a

**Dependencies**: T003

Use Config And Repository Modifications item 3.

**Verification**: `python -m py_compile src/data/config_models.py`; `AppConfig.from_dict({"recording": {"desktop": {"enable_clip": False, "vision_model": "vision-x"}}}).recording.desktop.vision_model == "vision-x"`.

---

### T006: 修正 `save_recording_session()` 默认 mode

**File**: `src/data/recording_repository.py` (modify)

**Requirements**: FR-009

**Dependencies**: T004

Change `session.get("recording_mode", "desktop")` to `"browser"` and apply the same browser fallback to legacy `save_actions()` unless explicit action mode exists.

**Verification**: Existing browser recording tests still pass; new repository test asserts no SQLite schema default changes are required.

---

### T007: 创建 DuckDB 桌面表

**File**: `src/data/recording_repository.py` (modify)

**Requirements**: FR-007, FR-008

**Dependencies**: T006

Use Config And Repository Modifications item 5.

**Verification**: T012 schema test checks `monitor_index`, status CHECK, and both composite indexes.

---

### T008: 添加桌面表 Repository 方法与 mode 查询入口

**File**: `src/data/recording_repository.py` (modify)

**Requirements**: FR-007, FR-008, FR-012

**Dependencies**: T007

Use Config And Repository Modifications item 6. `get_recording_mode()` returns `"browser"` or `"desktop"`; missing recording raises or returns a standardized error consumed by tool factories as `recording_not_found`.

**Verification**: T012 and T038 cover insert, update, list, and mode lookup.

---

### T009: 创建 DesktopRecordingService

**File**: `src/business/services/desktop_recording_service.py` (new)

**Requirements**: FR-001, FR-024, FR-025

**Dependencies**: T008

Use UI And Service Modifications item 1.

**Verification**: Service tests mock `DesktopRecorder` and `RecordingRepository`; UI tests only depend on the service API.

---

### T010: 暴露桌面录制统一配置

**File**: `src/data/unified_config.py` (modify)

**Requirements**: FR-026, FR-026a

**Dependencies**: T004

Use Config And Repository Modifications item 4.

**Verification**: T010a round-trip test.

---

### T010a: 配置模型/统一配置单测

**File**: `tests/data/test_recording_desktop_config.py` (new)

**Requirements**: FR-026, FR-026a

**Dependencies**: T004, T010

Test default `enable_clip=True`, `vision_model=None`, JSON round-trip, and example config key parity.

**Verification**: `uv run python -m pytest tests/data/test_recording_desktop_config.py -q`.

---

### T011: 追加 Trial 目录 7 天 cleanup

**File**: `src/data/recording_repository.py` (modify)

**Requirements**: FR-021a, FR-027

**Dependencies**: T006

Use Config And Repository Modifications item 7.

**Verification**: T067 and T067a.

---

### T011a: 创建共享高危 API detector

**File**: `src/business/utils/high_risk_api_detector.py` (new)

**Requirements**: SC-004, FR-021

**Dependencies**: none

Use the complete file content in File-Level Final Blueprint.

**Verification**: T011b and T066.

---

### T011b: 高危 API detector 单测

**File**: `tests/business/test_high_risk_api_detector.py` (new)

**Requirements**: SC-004

**Dependencies**: T011a

Cover imports, attr calls, protocol URL literals, Windows drive paths, pywin32, pywinauto, and pyautogui negative case.

**Verification**: `uv run python -m pytest tests/business/test_high_risk_api_detector.py -q`.

---

### T011c: 新增桌面录制 blinker 事件

**File**: `src/utils/events.py` (modify)

**Requirements**: Constitution Principle I

**Dependencies**: none

Use Events Modification.

**Verification**: `from src.utils.events import desktop_trial_finished`; `clear_all()` clears the new signals too.

---

## Phase 3: User Story 1 - 录制桌面操作并产出可分析数据

### T012: Repository desktop schema + insert/query 单测

**File**: `tests/data/test_recording_repository_desktop.py` (new)

**Requirements**: FR-007, FR-008

**Dependencies**: T007, T008

Cover schema, indexes, insert/list, status updates, health stats update, mode lookup, and large-field placeholder behavior for desktop text columns.

**Verification**: `uv run python -m pytest tests/data/test_recording_repository_desktop.py -q`.

---

### T013: pynput hook 归类规则单测

**File**: `tests/recording/test_desktop_pynput_hook.py` (new)

**Requirements**: FR-002, FR-008

**Dependencies**: T023

Cover mouse click, wheel, drag, Ctrl/Alt/Win hotkey, Shift typing, IME typing, function keys, and no mouse move capture.

**Verification**: Targeted pytest.

---

### T014: UIA querier 单测

**File**: `tests/recording/test_desktop_uia_querier.py` (new)

**Requirements**: FR-003

**Dependencies**: T024

Cover 50 ms timeout, async update queue handoff, COM init failure degradation, and owning window title.

**Verification**: Targeted pytest with mocked COM objects.

---

### T015: Clipboard watcher 单测

**File**: `tests/recording/test_desktop_clipboard_watcher.py` (new)

**Requirements**: FR-004

**Dependencies**: T025

Cover subscription, 500 ms poll fallback, Ctrl+V immediate read, text snapshot, image naming, latest reference, and subscription failure degradation.

**Verification**: Targeted pytest with mocked Win32 clipboard APIs.

---

### T016: Frame ring buffer 单测

**File**: `tests/recording/test_desktop_frame_ring_buffer.py` (new)

**Requirements**: FR-005

**Dependencies**: T026

Cover fixed 30-frame FIFO, one-second-before plus two-second-after selection, and early-buffer no-padding behavior.

**Verification**: Targeted pytest.

---

### T017: PNG sink + clip sink 单测

**File**: `tests/recording/test_desktop_sinks.py` (new)

**Requirements**: FR-005, FR-026

**Dependencies**: T027, T028

Cover native PNG writing, `compress_level=6`, mp4v success, writer failure, and `enable_clip=false`.

**Verification**: Targeted pytest with temporary directories.

---

### T018: DesktopRecorder lifecycle 集成测试

**File**: `tests/integration/test_desktop_recorder_lifecycle.py` (new)

**Requirements**: FR-001, FR-007, FR-024, FR-025

**Dependencies**: T030

Cover health counters, status transitions, action count events, and stop-time health stats write.

**Verification**: Targeted pytest.

---

### T019: minimize 后启动时机 UI 测试

**File**: `tests/ui/test_desktop_hook_start_after_minimize.py` (new)

**Requirements**: FR-022

**Dependencies**: T032

Assert no recorder subsystem starts before minimized state change and the start-button click is not persisted as desktop action.

**Verification**: Targeted UI pytest.

---

### T019a: 基础 sanity check 继续分析路径 UI 测试

**File**: `tests/ui/test_desktop_basic_continue_analysis.py` (new)

**Requirements**: FR-024

**Dependencies**: T009, T034

Cover action total display, `mark_stopped(recording_id)`, and intent page navigation.

**Verification**: Targeted UI pytest.

---

### T020: drag 语义单测

**File**: `tests/recording/test_desktop_drag_semantics.py` (new)

**Requirements**: FR-008

**Dependencies**: T023, T030

Assert drag coordinates, timestamp, UIA point, and monitor index come from mouse-up endpoint.

**Verification**: Targeted pytest.

---

### T021: typing 序列切片单测

**File**: `tests/recording/test_desktop_typing_segmentation.py` (new)

**Requirements**: FR-008

**Dependencies**: T023

Cover splitting on one-second pause, non-character key, window change, and mouse action.

**Verification**: Targeted pytest.

---

### T022: 进程启动期接线 DPI awareness

**File**: `src/main.py` (modify)

**Requirements**: FR-006

**Dependencies**: T001

Use Main Entry Modification.

**Verification**: `python -m py_compile src/main.py src/recording/desktop/dpi_awareness.py`.

---

### T023: 实现 pynput hook

**File**: `src/recording/desktop/pynput_hook.py` (new)

**Requirements**: FR-002, FR-008

**Dependencies**: T001

Use Recording Layer New Files.

**Verification**: T013, T020, T021.

---

### T024: 实现 UIA querier

**File**: `src/recording/desktop/uia_querier.py` (new)

**Requirements**: FR-003

**Dependencies**: T002

Use Recording Layer New Files.

**Verification**: T014.

---

### T025: 实现 clipboard watcher

**File**: `src/recording/desktop/clipboard_watcher.py` (new)

**Requirements**: FR-004

**Dependencies**: T002

Use Recording Layer New Files.

**Verification**: T015.

---

### T026: 实现 frame ring buffer

**File**: `src/recording/desktop/frame_ring_buffer.py` (new)

**Requirements**: FR-005

**Dependencies**: T002

Use Recording Layer New Files.

**Verification**: T016.

---

### T027: 实现 PNG sink

**File**: `src/recording/desktop/png_sink.py` (new)

**Requirements**: FR-005

**Dependencies**: T026

Use Recording Layer New Files.

**Verification**: T017.

---

### T028: 实现 clip sink

**File**: `src/recording/desktop/clip_sink.py` (new)

**Requirements**: FR-005, FR-026

**Dependencies**: T026, T027

Use Recording Layer New Files.

**Verification**: T017.

---

### T029: 实现 Ctrl+Alt+S hotkey register

**File**: `src/recording/desktop/hotkey_register.py` (new)

**Requirements**: FR-023

**Dependencies**: T011c

Use Recording Layer New Files.

**Verification**: Mock RegisterHotKey success and failure; failure emits degradation event through T030.

---

### T030: 实现 DesktopRecorder 顶层

**File**: `src/recording/desktop_recorder.py` (new)

**Requirements**: FR-001, FR-002, FR-003, FR-004, FR-005, FR-024, FR-025

**Dependencies**: T007, T008, T011c, T023, T024, T025, T026, T027, T028, T029

Use Recording Layer New Files.

**Verification**: T018 and T036 business mutex tests.

---

### T031: 接线 desktop branch 到 service

**File**: `src/ui/mixins/recording_mixin.py` (modify)

**Requirements**: FR-001

**Dependencies**: T009, T030

Use UI And Service Modifications item 2.

**Verification**: No unsupported desktop `QMessageBox` path remains.

---

### T032: recording_widget minimize 后启动

**File**: `src/ui/widgets/recording_widget.py` (modify)

**Requirements**: FR-022

**Dependencies**: T009, T031

Use UI And Service Modifications item 3.

**Verification**: T019.

---

### T033: 实现录制态浮窗

**File**: `src/ui/widgets/recording_floating_widget.py` (new)

**Requirements**: FR-022, FR-023

**Dependencies**: T032

Use the complete file content in File-Level Final Blueprint.

**Verification**: Widget unit test for count updates and `stopRequested`.

---

### T034: restore 主窗并弹基础 sanity check

**File**: `src/ui/widgets/recording_widget.py` (modify)

**Requirements**: FR-022, FR-024

**Dependencies**: T009, T033

Use UI And Service Modifications item 4.

**Verification**: T019a.

---

### T035: 录制启动失败弹错与降级 toast

**File**: `src/ui/widgets/recording_widget.py` (modify)

**Requirements**: FR-002, FR-003, FR-004, FR-023

**Dependencies**: T011c, T030

Pynput failure shows blocking dialog; UIA, clipboard, and hotkey degradations show one non-blocking toast each per recording.

**Verification**: UI test with emitted desktop events.

---

### T036: 业务层三模式互斥

**File**: `src/recording/desktop_recorder.py` (modify)

**Requirements**: FR-025

**Dependencies**: T030

Use in-memory active recorder state; do not query DB.

**Verification**: T018 and a dedicated mutex unit test.

---

### T036a: UI 侧桌面卡片防呆

**File**: `src/ui/widgets/recording_widget.py` (modify)

**Requirements**: FR-025

**Dependencies**: T036

Use UI And Service Modifications item 5.

**Verification**: T036b.

---

### T036b: 桌面卡片禁用 UI 单测

**File**: `tests/ui/test_desktop_card_disabled_when_other_recording_active.py` (new)

**Requirements**: FR-025

**Dependencies**: T036a

Mock active and idle states; assert `desktop_card.isEnabled()` and tooltip behavior.

**Verification**: Targeted UI pytest.

---

## Phase 4: User Story 2 - Agent 用多模态分析桌面录制

### T037: 浏览器 5 通用工具 byte-equal 门卫

**File**: `tests/integration/test_desktop_browser_path_byte_equal.py` (new)

**Requirements**: SC-005, CC-002

**Dependencies**: T048, T049

Build canonical browser fixture before and after mode dispatch; compare normalized JSON bytes; assert `recording_data_tools.py` does not import `sqlglot`.

**Verification**: Targeted pytest.

---

### T038: 5 通用工具 mode dispatch 链路冒烟

**File**: `tests/integration/test_desktop_tools_mode_dispatch.py` (new)

**Requirements**: FR-011, FR-012a

**Dependencies**: T048, T049, T059

Cover browser tables, desktop tables, cross-mode rejection, and desktop stable locator chunk reads.

**Verification**: Targeted pytest.

---

### T039: mode allowlist 单测

**File**: `tests/recording/filtering/test_mode_allowlist.py` (new)

**Requirements**: FR-012a

**Dependencies**: T049

Assert browser blocks desktop tables, desktop blocks browser tables, and desktop two-table JOIN is allowed.

**Verification**: Targeted pytest.

---

### T040: read_recording desktop summary 测试

**File**: `tests/integration/test_desktop_read_recording.py` (new)

**Requirements**: FR-011

**Dependencies**: T048

Assert desktop session, health stats, counts, top window titles, time range, and head/tail boundary rows without middle rows.

**Verification**: Targeted pytest.

---

### T041: list_desktop_actions 参数校验测试

**File**: `tests/integration/test_list_desktop_actions.py` (new)

**Requirements**: FR-013

**Dependencies**: T050

Cover invalid enum, limit over 500, offset paging, and action type filtering.

**Verification**: Targeted pytest.

---

### T042: analyze_desktop_action 多模态组装测试

**File**: `tests/integration/test_analyze_desktop_action.py` (new)

**Requirements**: FR-013

**Dependencies**: T051

Mock vision client, inspect content order, action limit, shrink-only behavior, and error segment concatenation.

**Verification**: Targeted pytest.

---

### T043: read_action_clip 测试

**File**: `tests/integration/test_read_action_clip.py` (new)

**Requirements**: FR-013

**Dependencies**: T052

Cover unavailable clip error and metadata response.

**Verification**: Targeted pytest.

---

### T044: 双轨 prompt 测试

**File**: `tests/integration/test_desktop_prompts.py` (new)

**Requirements**: FR-016, FR-020

**Dependencies**: T053, T054

Assert browser identity return and desktop required phrases.

**Verification**: Targeted pytest.

---

### T045: 浏览器 prompt 行为守卫

**File**: `tests/integration/test_browser_prompts_guard.py` (new)

**Requirements**: SC-006

**Dependencies**: T053, T054

Assert legacy prompt key phrases and browser builder identity.

**Verification**: Targeted pytest.

---

### T046: syntax gate + retry 单测

**File**: `tests/integration/test_desktop_syntax_gate.py` (new)

**Requirements**: FR-017a

**Dependencies**: T057, T058

Cover success, one retry success, terminal failure, feedback rendering, and browser bypass.

**Verification**: Targeted pytest.

---

### T047: vision_model gating 测试

**File**: `tests/integration/test_vision_model_gating.py` (new)

**Requirements**: FR-026a

**Dependencies**: T050, T051

Assert missing model omits only `analyze_desktop_action`.

**Verification**: Targeted pytest.

---

### T047a: 工具集 composition 门卫

**File**: `tests/integration/test_desktop_toolset_composition.py` (new)

**Requirements**: FR-014, FR-015, FR-026a

**Dependencies**: T052a

Assert the six toolset paths and shared vision client factory route.

**Verification**: Targeted pytest.

---

### T047b: PM Agent 桌面 fixture 半集成测试

**File**: `tests/integration/test_desktop_pm_agent_intent.py` (new)

**Requirements**: SC-002

**Dependencies**: T050, T051, T052a, T053

Use a desktop fixture with at least five actions and one clipboard event; assert tool calls and `talk_to_user` terminal intent.

**Verification**: Targeted pytest with scripted LLM.

---

### T048: 改造 create_recording_tools mode dispatch

**File**: `src/business/agents/tools/recording_data_tools.py` (modify)

**Requirements**: FR-011, FR-012

**Dependencies**: T008

Use Tooling And Prompt Modifications items 3 and 4.

**Verification**: T037, T038, T040.

---

### T049: 改造 sql_rewriter + decision allowlist

**File**: `src/recording/filtering/sql_rewriter.py`, `src/recording/filtering/decision.py` (modify)

**Requirements**: FR-012a

**Dependencies**: T048

Use Tooling And Prompt Modifications items 1 and 2.

**Verification**: T038, T039.

---

### T050: 创建 desktop_tools + list_desktop_actions

**File**: `src/business/agents/tools/desktop_tools.py` (new)

**Requirements**: FR-013, FR-014, FR-015

**Dependencies**: T008

Use Tooling And Prompt Modifications item 5.

**Verification**: T041, T047.

---

### T051: 实现 analyze_desktop_action

**File**: `src/business/agents/tools/desktop_tools.py` (modify)

**Requirements**: FR-013, FR-026a

**Dependencies**: T050

Use Tooling And Prompt Modifications item 6.

**Verification**: T042, T047a.

---

### T052: 实现 read_action_clip

**File**: `src/business/agents/tools/desktop_tools.py` (modify)

**Requirements**: FR-013

**Dependencies**: T050

Return JSON metadata or `clip_unavailable`.

**Verification**: T043.

---

### T052a: 接线 6 条 Agent 工具集路径

**File**: `src/business/orchestration/agent/orchestrator.py` (modify)

**Requirements**: FR-014, FR-015

**Dependencies**: T048, T050, T051, T052

Use Tooling And Prompt Modifications item 9.

**Verification**: T047a.

---

### T053: 创建 desktop PM prompt builder

**File**: `src/business/agents/prompts/desktop_prompts.py` (new)

**Requirements**: FR-016, FR-019

**Dependencies**: T048, T050

Use Tooling And Prompt Modifications item 7.

**Verification**: T044, T045.

---

### T054: 添加 Programmer desktop prompt builder

**File**: `src/business/agents/prompts/desktop_prompts.py` (modify)

**Requirements**: FR-020

**Dependencies**: T053

Use Tooling And Prompt Modifications item 7.

**Verification**: T044.

---

### T055: Orchestrator 接入双轨 prompt

**File**: `src/business/orchestration/agent/orchestrator.py` (modify)

**Requirements**: FR-017

**Dependencies**: T053, T054

Use Tooling And Prompt Modifications item 9.

**Verification**: T044 and orchestrator dispatch test.

---

### T056: execution_strategy 增 desktop

**File**: `src/business/agents/tools/programmer_tools.py`, `src/business/tool_trial/trial_models.py` (modify)

**Requirements**: FR-018

**Dependencies**: T054

Use Tooling And Prompt Modifications item 8.

**Verification**: schema enum contains `desktop`; trial model accepts it.

---

### T057: 创建 desktop syntax gate

**File**: `src/business/orchestration/agent/desktop_syntax_gate.py` (new)

**Requirements**: FR-017a

**Dependencies**: T055

Use the complete file content in File-Level Final Blueprint.

**Verification**: T046.

---

### T058: Orchestrator 接入 syntax gate

**File**: `src/business/orchestration/agent/orchestrator.py` (modify)

**Requirements**: FR-017a

**Dependencies**: T057

Use Tooling And Prompt Modifications item 10.

**Verification**: T046 and event emission test.

---

### T059: read_field_chunk desktop stable locator

**File**: `src/business/agents/tools/recording_data_tools.py` (modify)

**Requirements**: FR-012

**Dependencies**: T048

Extend stable locator support to `desktop_actions.<column>.<action_id>` for `text_content`, `clipboard_text`, and `uia_summary`.

**Verification**: T038.

---

### T059a: STOP and VALIDATE MVP

**File**: `specs/007-desktop-recording/quickstart.md` (manual validation artifact)

**Requirements**: SC-001, SC-002

**Dependencies**: US1 and US2 complete

Run the five standard scenarios, record 5/5 recording success and 5/5 intent output with Programmer syntax pass.

**Verification**: Manual checklist in quickstart.

---

## Phase 5: User Story 3 - 试用桌面自动化代码

### T060: subprocess 正常路径单测

**File**: `tests/integration/test_desktop_trial_subprocess.py` (new)

**Requirements**: SC-003

**Dependencies**: T069, T071, T072

Assert simple async `execute()` returns ok, exit code zero, and success toast payload.

**Verification**: Targeted pytest.

---

### T061: wrapper 异常包装单测

**File**: `tests/integration/test_desktop_trial_wrapper.py` (new)

**Requirements**: FR-021

**Dependencies**: T069

Assert exceptions become JSON with `ok=False`, summary type/message, and traceback details.

**Verification**: Targeted pytest.

---

### T062: timeout + taskkill 单测

**File**: `tests/integration/test_desktop_trial_timeout.py` (new)

**Requirements**: FR-021a

**Dependencies**: T069

Mock timeout path, `terminate()`, and Windows `taskkill /F /T /PID`.

**Verification**: Targeted pytest.

---

### T063: env 白名单单测

**File**: `tests/integration/test_desktop_trial_env_whitelist.py` (new)

**Requirements**: FR-021a

**Dependencies**: T070

Assert sensitive names are filtered and `PATH` is retained.

**Verification**: Targeted pytest.

---

### T064: cwd 隔离单测

**File**: `tests/integration/test_desktop_trial_cwd.py` (new)

**Requirements**: FR-021a

**Dependencies**: T069

Assert child cwd is `data/trials/<trial_id>/`.

**Verification**: Targeted pytest.

---

### T065: stdout 无 JSON 兜底单测

**File**: `tests/integration/test_desktop_trial_stdout_fallback.py` (new)

**Requirements**: FR-021a

**Dependencies**: T071

Assert stderr tail is truncated to 200 characters and fallback marker is present.

**Verification**: Targeted pytest.

---

### T066: 高危 API 检测 UI 路径测试

**File**: `tests/integration/test_desktop_trial_high_risk_api.py` (new)

**Requirements**: FR-021, SC-004

**Dependencies**: T011a, T073

Mock shared detector and assert dialog displays returned labels.

**Verification**: Targeted pytest.

---

### T066a: Trial UI 三步骤测试

**File**: `tests/ui/test_desktop_trial_dialogs.py` (new)

**Requirements**: FR-021

**Dependencies**: T073, T074

Cover preview dialog, cancel path, start path, success, failure, and timeout toast payloads.

**Verification**: Targeted UI pytest.

---

### T067: Trial cleanup 单测

**File**: `tests/integration/test_desktop_trial_cleanup.py` (new)

**Requirements**: FR-021a

**Dependencies**: T011

Assert old trial dirs are removed.

**Verification**: Targeted pytest.

---

### T067a: startup recovery 不清桌面录制门卫

**File**: `tests/integration/test_desktop_startup_recovery_non_cleanup.py` (new)

**Requirements**: FR-027

**Dependencies**: T011, T007

Assert orphan desktop rows and recording dirs remain.

**Verification**: Targeted pytest.

---

### T068: stdout/stderr 落盘单测

**File**: `tests/integration/test_desktop_trial_logs.py` (new)

**Requirements**: FR-021a

**Dependencies**: T069

Assert both log files exist and contain process output.

**Verification**: Targeted pytest.

---

### T069: 创建 desktop_trial_runner

**File**: `src/execution/desktop_trial_runner.py` (new)

**Requirements**: FR-021, FR-021a

**Dependencies**: T072

Use the complete file content in File-Level Final Blueprint.

**Verification**: T060, T061, T062, T064, T068.

---

### T070: 实现 build_whitelisted_env

**File**: `src/execution/desktop_trial_runner.py` (modify)

**Requirements**: FR-021a

**Dependencies**: T069

Use `build_whitelisted_env()` from File-Level Final Blueprint.

**Verification**: T063.

---

### T071: 实现 parse_trial_stdout

**File**: `src/execution/desktop_trial_runner.py` (modify)

**Requirements**: FR-021a, SC-003

**Dependencies**: T069

Use `parse_trial_stdout()` and `is_trial_success()` from File-Level Final Blueprint.

**Verification**: T060, T065.

---

### T072: 创建 TrialResult dataclass

**File**: `src/execution/desktop_trial_models.py` (new)

**Requirements**: FR-021a

**Dependencies**: none

Use the complete file content in File-Level Final Blueprint.

**Verification**: `python -m py_compile src/execution/desktop_trial_models.py`.

---

### T073: 创建 Trial 事前提示对话框

**File**: `src/ui/widgets/desktop_trial_dialogs.py` (new)

**Requirements**: FR-021, SC-004

**Dependencies**: T011a

Use the complete file content in File-Level Final Blueprint.

**Verification**: T066 and T066a.

---

### T074: 完成 Trial toast 路由

**File**: `src/ui/widgets/desktop_trial_dialogs.py` (modify)

**Requirements**: FR-021

**Dependencies**: T073

Use `trial_toast_payload()` from File-Level Final Blueprint and wire it into the existing ordinary toast surface.

**Verification**: T066a.

---

### T075: Orchestrator 接入 desktop trial runner

**File**: `src/business/orchestration/agent/orchestrator.py` (modify)

**Requirements**: FR-021, FR-021a

**Dependencies**: T069, T073, T074

On trial request, emit `desktop_trial_preview_ready`; on user start, call `run_desktop_trial`; then emit `desktop_trial_finished`. Business orchestrates only and does not create trial dirs directly.

**Verification**: T066a, T068.

---

## Phase 6: User Story 4 - 录制健康反馈与早期止损

### T076: 颜色判定单测

**File**: `tests/ui/test_desktop_sanity_check_color.py` (new)

**Requirements**: FR-024

**Dependencies**: T080

Cover red, yellow UIA, yellow clip, green, UIA skip, and clip skip.

**Verification**: Targeted pytest.

---

### T077: 三按钮状态机单测

**File**: `tests/ui/test_desktop_sanity_check_buttons.py` (new)

**Requirements**: FR-024

**Dependencies**: T081

Cover continue, abandon, and rerecord UI routing and status updates.

**Verification**: Targeted pytest.

---

### T078: vision_model 缺失 toast 一次性单测

**File**: `tests/ui/test_vision_model_missing_toast.py` (new)

**Requirements**: FR-026a

**Dependencies**: T082

Cover once per recording, separate recording behavior, duration, and PM non-blocking.

**Verification**: Targeted UI pytest.

---

### T079: 扩展 DesktopSanityCheckDialog 展示

**File**: `src/ui/widgets/desktop_sanity_check_dialog.py` (new)

**Requirements**: FR-024

**Dependencies**: T009, T034

Use the complete file content in File-Level Final Blueprint, then wire service-backed construction in `recording_widget.py`.

**Verification**: T076, T077.

---

### T080: 实现 determine_health_color

**File**: `src/ui/widgets/desktop_sanity_check_dialog.py` (modify)

**Requirements**: FR-024

**Dependencies**: T079

Use `determine_health_color()` from File-Level Final Blueprint.

**Verification**: T076.

---

### T081: 三按钮 slot 增强

**File**: `src/ui/widgets/desktop_sanity_check_dialog.py`, `src/ui/widgets/recording_widget.py` (modify)

**Requirements**: FR-024

**Dependencies**: T079, T080

Continue calls `mark_stopped` and opens intent page; abandon calls `mark_abandoned` and returns to recording page without mode preselect; rerecord calls `mark_abandoned` and returns with desktop mode selected.

**Verification**: T077.

---

### T082: vision_model 缺失一次性 toast

**File**: `src/ui/widgets/recording_widget.py` (modify)

**Requirements**: FR-026a

**Dependencies**: T010

Use UI And Service Modifications item 6.

**Verification**: T078.

---

### T083: 设置面板桌面录制配置区

**File**: `src/ui/widgets/settings/desktop_recording_settings.py` (new)

**Requirements**: FR-026, FR-026a

**Dependencies**: T010

Use UI And Service Modifications item 7 and integrate the widget into the existing settings page.

**Verification**: UI unit test or settings smoke test; config values persist through `UnifiedConfigManager`.

---

## Phase 7: Polish & Cross-Cutting Concerns

### T084: 更新架构活文档

**File**: `docs/ARCHITECTURE.md` (modify)

**Requirements**: Constitution Principle V

**Dependencies**: all implementation phases

Add a section for desktop recording, Trial subprocess isolation, 5-tool mode dispatch, and dual-track prompts.

**Verification**: Document cites runtime paths and does not describe `docs/local/` as durable truth.

---

### T085: 更新项目约束活文档

**File**: `docs/PROJECT_CONSTRAINTS.md` (modify)

**Requirements**: Constitution Principle V

**Dependencies**: T049, T069, T070, T071

Document DuckDB allowlists, cross-mode rejection, Trial env whitelist, Trial cwd, and vision provider reuse.

**Verification**: Constraints map back to tests T037, T038, T063, T064.

---

### T086: 更新 AGENTS.md 与 CLAUDE.md

**File**: `AGENTS.md`, `CLAUDE.md` (modify)

**Requirements**: Constitution Principle V

**Dependencies**: all implementation phases

Update current-code reality and keep SPECKIT markers pointing to `specs/007-desktop-recording/plan.md`.

**Verification**: Both files mention mode dispatch, dual prompts, minimize timing, sanity check service read, Trial runner boundary, syntax gate, DPI, monitor_index, and blinker bridge.

---

### T087: 验证示例配置字段

**File**: `config.example.json`, `config.example.comments.md` (verify)

**Requirements**: FR-026, FR-026a

**Dependencies**: T003

Confirm fields exist in this worktree only.

**Verification**: `rg "recording.desktop|enable_clip|vision_model" config.example.json config.example.comments.md`.

---

### T088: quickstart 5 场景 manual e2e

**File**: `specs/007-desktop-recording/quickstart.md` (manual validation)

**Requirements**: SC-001, SC-002, SC-003, SC-004, SC-007

**Dependencies**: US1, US2, US3, US4 complete

Run and record the five funnel rows. SC-004 uses `detect_high_risk_apis(code)` mechanically before human spot check.

**Verification**: Filled quickstart funnel table and notes for performance anomalies.

---

### T089: PR 描述记录 SC-008 合规签字

**File**: PR description (manual)

**Requirements**: SC-008

**Dependencies**: T084, T085, T086

Record that public installer release requires product/security signoff for global recording, no runtime privacy mechanism, and vision uploads on demand.

**Verification**: PR description includes the signoff section.

---

### T090: 增加桌面 mode 14 场景工具集成测试

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (modify)

**Requirements**: SC-005

**Dependencies**: T048, T050, T052a

Mirror existing browser multi-tool-call cases for desktop mode and assert the same batch execution/recovery semantics.

**Verification**: Targeted pytest.

---

### T091: 全量验证

**File**: repository validation (verify)

**Requirements**: all

**Dependencies**: T001 through T090

Run:

```bash
uv run pytest tests/
uv run black src/ tests/
uv run flake8 src/ tests/
```

**Verification**: All commands exit zero before commit.

---

## Checklist

- [ ] T001: 创建 `src/recording/desktop/dpi_awareness.py`
- [ ] T002: 添加或验证桌面录制依赖
- [ ] T003: 添加桌面录制配置示例
- [ ] T004: 修正录制配置模型
- [X] T005: 修正 recording_widget fallback
- [ ] T006: 修正 `save_recording_session()` 默认 mode
- [ ] T007: 创建 DuckDB 桌面表
- [ ] T008: 添加桌面表 Repository 方法与 mode 查询入口
- [ ] T009: 创建 DesktopRecordingService
- [ ] T010: 暴露桌面录制统一配置
- [ ] T010a: 配置模型/统一配置单测
- [ ] T011: 追加 Trial 目录 7 天 cleanup
- [ ] T011a: 创建共享高危 API detector
- [ ] T011b: 高危 API detector 单测
- [ ] T011c: 新增桌面录制 blinker 事件
- [ ] T012: Repository desktop schema + insert/query 单测
- [ ] T013: pynput hook 归类规则单测
- [ ] T014: UIA querier 单测
- [ ] T015: Clipboard watcher 单测
- [ ] T016: Frame ring buffer 单测
- [ ] T017: PNG sink + clip sink 单测
- [ ] T018: DesktopRecorder lifecycle 集成测试
- [ ] T019: minimize 后启动时机 UI 测试
- [ ] T019a: 基础 sanity check 继续分析路径 UI 测试
- [ ] T020: drag 语义单测
- [ ] T021: typing 序列切片单测
- [ ] T022: 进程启动期接线 DPI awareness
- [ ] T023: 实现 pynput hook
- [ ] T024: 实现 UIA querier
- [ ] T025: 实现 clipboard watcher
- [ ] T026: 实现 frame ring buffer
- [ ] T027: 实现 PNG sink
- [ ] T028: 实现 clip sink
- [ ] T029: 实现 Ctrl+Alt+S hotkey register
- [ ] T030: 实现 DesktopRecorder 顶层
- [ ] T031: 接线 desktop branch 到 service
- [ ] T032: recording_widget minimize 后启动
- [ ] T033: 实现录制态浮窗
- [ ] T034: restore 主窗并弹基础 sanity check
- [ ] T035: 录制启动失败弹错与降级 toast
- [ ] T036: 业务层三模式互斥
- [ ] T036a: UI 侧桌面卡片防呆
- [ ] T036b: 桌面卡片禁用 UI 单测
- [ ] T037: 浏览器 5 通用工具 byte-equal 门卫
- [ ] T038: 5 通用工具 mode dispatch 链路冒烟
- [ ] T039: mode allowlist 单测
- [ ] T040: read_recording desktop summary 测试
- [ ] T041: list_desktop_actions 参数校验测试
- [ ] T042: analyze_desktop_action 多模态组装测试
- [ ] T043: read_action_clip 测试
- [ ] T044: 双轨 prompt 测试
- [ ] T045: 浏览器 prompt 行为守卫
- [ ] T046: syntax gate + retry 单测
- [ ] T047: vision_model gating 测试
- [ ] T047a: 工具集 composition 门卫
- [ ] T047b: PM Agent 桌面 fixture 半集成测试
- [ ] T048: 改造 create_recording_tools mode dispatch
- [ ] T049: 改造 sql_rewriter + decision allowlist
- [ ] T050: 创建 desktop_tools + list_desktop_actions
- [ ] T051: 实现 analyze_desktop_action
- [ ] T052: 实现 read_action_clip
- [ ] T052a: 接线 6 条 Agent 工具集路径
- [ ] T053: 创建 desktop PM prompt builder
- [ ] T054: 添加 Programmer desktop prompt builder
- [ ] T055: Orchestrator 接入双轨 prompt
- [ ] T056: execution_strategy 增 desktop
- [ ] T057: 创建 desktop syntax gate
- [ ] T058: Orchestrator 接入 syntax gate
- [ ] T059: read_field_chunk desktop stable locator
- [ ] T059a: STOP and VALIDATE MVP
- [ ] T060: subprocess 正常路径单测
- [ ] T061: wrapper 异常包装单测
- [ ] T062: timeout + taskkill 单测
- [ ] T063: env 白名单单测
- [ ] T064: cwd 隔离单测
- [ ] T065: stdout 无 JSON 兜底单测
- [ ] T066: 高危 API 检测 UI 路径测试
- [ ] T066a: Trial UI 三步骤测试
- [ ] T067: Trial cleanup 单测
- [ ] T067a: startup recovery 不清桌面录制门卫
- [ ] T068: stdout/stderr 落盘单测
- [ ] T069: 创建 desktop_trial_runner
- [ ] T070: 实现 build_whitelisted_env
- [ ] T071: 实现 parse_trial_stdout
- [ ] T072: 创建 TrialResult dataclass
- [ ] T073: 创建 Trial 事前提示对话框
- [ ] T074: 完成 Trial toast 路由
- [ ] T075: Orchestrator 接入 desktop trial runner
- [ ] T076: 颜色判定单测
- [ ] T077: 三按钮状态机单测
- [ ] T078: vision_model 缺失 toast 一次性单测
- [ ] T079: 扩展 DesktopSanityCheckDialog 展示
- [ ] T080: 实现 determine_health_color
- [ ] T081: 三按钮 slot 增强
- [ ] T082: vision_model 缺失一次性 toast
- [ ] T083: 设置面板桌面录制配置区
- [ ] T084: 更新架构活文档
- [ ] T085: 更新项目约束活文档
- [ ] T086: 更新 AGENTS.md 与 CLAUDE.md
- [ ] T087: 验证示例配置字段
- [ ] T088: quickstart 5 场景 manual e2e
- [ ] T089: PR 描述记录 SC-008 合规签字
- [ ] T090: 增加桌面 mode 14 场景工具集成测试
- [ ] T091: 全量验证
