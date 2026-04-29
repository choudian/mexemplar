# Blueprint: Chat UI Polish

**Branch**: `006-chat-ui-polish` | **Date**: 2026-04-28
**Mode**: `scaffold`
**Total Tasks**: 36 | **Files**: 8 new, 8 modified, 0 deleted

## Key Decisions

- 助手消息使用独立 `MarkdownMessageView`，用户消息继续使用 `QLabel` 与 `Qt.TextFormat.PlainText`，避免改变用户输入路径。→ T001, T005, T007, T008, T010
- Markdown 安全策略在 UI 渲染层完成：raw HTML/script 转义，链接不打开外部目标，图片仅允许 `http` / `https` 目标进入降级路径，最终展示 alt 文本。→ T006, T009, T011, T012
- 历史回看保持 `ChatWidget -> ChatService -> MessageRepository` 分层，UI 只消费展示 DTO，不直接接触 Repository。→ T003, T013, T014, T016, T017, T018
- 展示历史采用 keyset pagination：初始最新 10 条，向上滚动用当前最早 `sequence` 拉更早页。→ T015, T016, T018, T019, T020, T021, T022, T023
- “免确认” Toggle 只改可见性，不改 checked/text/property 同步语义，也不触发额外 `auto_approve_toggled`。→ T024, T025, T026, T027, T028, T029, T030
- 长历史性能验证必须同时覆盖首屏、向上滚动 handler 和输入/发送路径 handler。→ T015, T023, T033, T034

## Implementation Order

```text
T001 T002 T003 T004
  -> T005 T006 T007 -> T008 T009 -> T010 T011 T012
  -> T013 T014 T015 -> T016 T017 -> T018 T019 T020 T021 T022 T023
  -> T024 T025 -> T026 T027 T028 T029 T030
  -> T031 T032 -> T033 T034 T035 T036
```

---

## Phase 1: Setup

### T001: Create `src/ui/widgets/markdown_message_view.py`

**File**: `src/ui/widgets/markdown_message_view.py` (new)

**Requirements**: FR-001, FR-003, FR-004, FR-005, FR-006, SC-001, SC-002, SC-008

**Dependencies**: none

**Implementation**: Use the complete file content in Appendix A.

**Verification**: `uv run python -m py_compile src/ui/widgets/markdown_message_view.py`

### T002: Create `tests/ui/chat_widget_test_helpers.py`

**File**: `tests/ui/chat_widget_test_helpers.py` (new)

**Requirements**: SC-001, SC-003, SC-005, SC-007

**Dependencies**: none

**Implementation**: Use the complete file content in Appendix A.

**Verification**: Import the helper module from any UI test without creating a second `QApplication`.

---

## Phase 2: Foundational

### T003: Add UI layering guard tests

**File**: `tests/ui/test_chat_widget_layering.py` (new)

**Requirements**: CC-006, constitution layered boundary

**Dependencies**: T002

**Implementation**: Use the complete file content in Appendix A.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_layering.py -q`

### T004: Add shared SQLite message seed helpers

**File**: `tests/data/chat_history_test_helpers.py` (new)

**Requirements**: FR-007, FR-010, FR-014, SC-003, SC-007

**Dependencies**: none

**Implementation**: Use the complete file content in Appendix A.

**Verification**: Import the helper from data, business, and UI tests.

---

## Phase 3: User Story 1 - AI 回复消息以富文本展示 Markdown

### T005: Add Markdown rendering coverage

**File**: `tests/ui/test_chat_widget_markdown.py` (new)

**Requirements**: FR-001, SC-001

**Dependencies**: T001, T002

**Implementation**: Use the complete test file in Appendix A. The file includes the rendering assertions for headings, lists, code, quote, divider, and pipe table.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q`

### T006: Add Markdown safety and partial-render coverage

**File**: `tests/ui/test_chat_widget_markdown.py` (new)

**Requirements**: FR-003, FR-004, FR-006, SC-008

**Dependencies**: T005

**Implementation**: The Appendix A test file includes raw HTML/script downgrade, remote image alt fallback, non-remote image downgrade, no external navigation, incomplete code fence, incomplete emphasis, and final convergence checks.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q -k "markdown or image or partial"`

### T007: Add user-message plain-text coverage

**File**: `tests/ui/test_chat_widget_markdown.py` (new)

**Requirements**: FR-002, CC-003

**Dependencies**: T005

**Implementation**: The Appendix A test file asserts that user messages containing backticks, stars, headings, and pipes remain plain text.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q -k user_message`

### T008: Implement `MarkdownMessageView`

**File**: `src/ui/widgets/markdown_message_view.py` (new)

**Requirements**: FR-001, FR-004, FR-005

**Dependencies**: T001, T005, T006

**Implementation**: Use the complete file content in Appendix A.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q`

### T009: Implement Markdown safety downgrade and navigation blocking

**File**: `src/ui/widgets/markdown_message_view.py` (new)

**Requirements**: FR-003, FR-006, SC-008

**Dependencies**: T008

**Implementation**: Use the same complete file content in Appendix A. The implementation blocks external navigation by disabling open links and converting Markdown image targets to safe alt fallback text.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q`

### T010: Integrate `MarkdownMessageView` into assistant branches

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-001, FR-002, FR-005, CC-003

**Dependencies**: T008, T009

**Implementation**: Apply the `chat_widget.py` change blocks in Appendix B. Assistant content uses `MarkdownMessageView`; user content keeps `QLabel` with plain-text formatting.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q`

### T011: Add Markdown visual styles

**File**: `src/ui/resources/styles.qss` (modify)

**Requirements**: FR-001, FR-005, SC-001, SC-002

**Dependencies**: T010

**Implementation**: Apply the `styles.qss` change block in Appendix B.

**Verification**: Manual GUI check plus `tests/ui/test_chat_widget_markdown.py`.

### T012: Validate User Story 1

**File**: `tests/ui/test_chat_widget_markdown.py`, `src/ui/widgets/markdown_message_view.py`, `src/ui/widgets/chat_widget.py`

**Requirements**: SC-001, SC-002, SC-008

**Dependencies**: T005-T011

**Implementation**: Run the validation commands listed below.

```powershell
uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q
uv run python -m py_compile src/ui/widgets/markdown_message_view.py src/ui/widgets/chat_widget.py
```

**Verification**: The tests pass and assistant Markdown rendering does not change user message rendering.

---

## Phase 4: User Story 2 - 压缩后的旧聊天记录仍可回看

### T013: Add repository pagination tests

**File**: `tests/data/test_message_repository.py` (new)

**Requirements**: FR-007, FR-010, FR-014, SC-003, SC-007

**Dependencies**: T004

**Implementation**: Use the complete file content in Appendix A.

**Verification**: `uv run python -m pytest tests/data/test_message_repository.py -q`

### T014: Add ChatService contract tests

**File**: `tests/business/test_chat_service_history.py` (new)

**Requirements**: FR-008, CC-006

**Dependencies**: T004

**Implementation**: Use the complete file content in Appendix A.

**Verification**: `uv run python -m pytest tests/business/test_chat_service_history.py -q`

### T015: Add ChatWidget history UI tests

**File**: `tests/ui/test_chat_widget_history.py` (new)

**Requirements**: FR-007, FR-008, FR-009, FR-011, FR-014, SC-003, SC-004, SC-007

**Dependencies**: T002

**Implementation**: Use the complete file content in Appendix A. The file validates latest-10, prepend, viewport preservation, absence of archive labels, initial render timing, scroll handler timing, and input/send-path timing.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_history.py -q`

### T016: Add `MessageRepository.get_display_page`

**File**: `src/data/repos/message_repository.py` (modify)

**Requirements**: FR-007, FR-010, FR-014, CC-006

**Dependencies**: T013

**Implementation**: Apply the `message_repository.py` change blocks in Appendix B.

**Verification**: `uv run python -m pytest tests/data/test_message_repository.py -q`

### T017: Add display DTOs and `ChatService.get_display_messages`

**File**: `src/business/services/chat_service.py` (modify)

**Requirements**: FR-008, FR-009, FR-012, FR-014, CC-006

**Dependencies**: T014, T016

**Implementation**: Apply the `chat_service.py` change blocks in Appendix B.

**Verification**: `uv run python -m pytest tests/business/test_chat_service_history.py -q`

### T018: Replace `ChatWidget._load_session_messages`

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-007, FR-011, FR-014

**Dependencies**: T017

**Implementation**: Apply the `chat_widget.py` history-loading blocks in Appendix B.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_history.py -q -k latest`

### T019: Track pagination state

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-014, SC-007

**Dependencies**: T018

**Implementation**: Apply the `chat_widget.py` state initialization and reset blocks in Appendix B.

**Verification**: `tests/ui/test_chat_widget_history.py` observes `_oldest_loaded_sequence`, `_has_more_history`, and `_loading_history_page`.

### T020: Connect top-threshold loader

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-014, SC-007

**Dependencies**: T019

**Implementation**: Apply the `messages_scroll` attribute and scrollbar handler blocks in Appendix B.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_history.py -q -k top_scroll`

### T021: Prepend older message widgets and preserve viewport

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-007, FR-009, FR-014

**Dependencies**: T020

**Implementation**: Apply the `_prepend_display_messages` block in Appendix B.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_history.py -q -k preserved`

### T022: Reset history pagination state

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-013, FR-014

**Dependencies**: T019

**Implementation**: Apply reset calls in `_prepare_new_chat`, `_switch_to_session`, `_clear_messages`, `show_session_list`, and `on_new_chat` from Appendix B.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_history.py -q`

### T023: Validate User Story 2

**File**: `tests/data/test_message_repository.py`, `tests/business/test_chat_service_history.py`, `tests/ui/test_chat_widget_history.py`

**Requirements**: SC-003, SC-004, SC-007

**Dependencies**: T013-T022

**Implementation**: Run the validation commands below and record any local timing caveat in the implementation response.

```powershell
uv run python -m pytest tests/data/test_message_repository.py tests/business/test_chat_service_history.py tests/ui/test_chat_widget_history.py -q
```

**Verification**: Latest-10, pagination, filtering, no labels, `<=2s`, `<=100ms` scroll handler, and `<=100ms` input/send-path checks pass or have a documented local environment caveat.

---

## Phase 5: User Story 3 - 新对话/欢迎界面不展示免确认 Toggle

### T024: Extend ChatWidget auth Toggle tests

**File**: `tests/ui/test_chat_widget_auth_toggle.py` (modify)

**Requirements**: FR-015, FR-016, FR-017, FR-018, SC-005, SC-006

**Dependencies**: T002

**Implementation**: Apply the `test_chat_widget_auth_toggle.py` change block in Appendix B.

**Verification**: `uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py -q`

### T025: Extend AgentHandlerMixin tests

**File**: `tests/ui/test_agent_handler_mixin.py` (modify)

**Requirements**: FR-017, CC-002, CC-005

**Dependencies**: none

**Implementation**: Apply the `test_agent_handler_mixin.py` change block in Appendix B.

**Verification**: `uv run python -m pytest tests/ui/test_agent_handler_mixin.py -q`

### T026: Add Toggle visibility helpers

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-015, FR-016, FR-017

**Dependencies**: T024

**Implementation**: Apply `_set_auto_approve_toggle_visible` and `_mark_conversation_started` blocks in Appendix B.

**Verification**: Toggle visibility changes do not append to `auto_approve_toggled` event capture.

### T027: Hide Toggle for welcome/list/new-chat states

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-015, FR-016, FR-018, SC-005

**Dependencies**: T026

**Implementation**: Apply hide calls in `_prepare_new_chat`, `_add_welcome_message`, `show_session_list`, and `on_new_chat` from Appendix B.

**Verification**: `tests/ui/test_chat_widget_auth_toggle.py` confirms hidden states.

### T028: Show Toggle after conversation starts

**File**: `src/ui/widgets/chat_widget.py` (modify)

**Requirements**: FR-017, SC-005

**Dependencies**: T026

**Implementation**: Apply show calls in `_do_send` and non-empty session load from Appendix B.

**Verification**: Existing non-empty sessions and first send both show the Toggle.

### T029: Adjust header layout styling

**File**: `src/ui/widgets/chat_widget.py`, `src/ui/resources/styles.qss` (modify)

**Requirements**: FR-018, SC-006

**Dependencies**: T026-T028

**Implementation**: Apply the visibility property update in `chat_widget.py` and the QSS block in Appendix B.

**Verification**: Toggle hide/show produces no disabled placeholder and no extra user toggle signal.

### T030: Validate User Story 3

**File**: `tests/ui/test_chat_widget_auth_toggle.py`, `tests/ui/test_agent_handler_mixin.py`

**Requirements**: SC-005, SC-006

**Dependencies**: T024-T029

**Implementation**: Run the validation commands below.

```powershell
uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py -q
```

**Verification**: Toggle visibility is correct and 004-auth-toast confirmation protocol remains unchanged.

---

## Phase 6: Polish & Cross-Cutting Concerns

### T031: Update architecture document

**File**: `docs/ARCHITECTURE.md` (modify)

**Requirements**: Living docs, CC-006

**Dependencies**: T016-T023

**Implementation**: Apply the `docs/ARCHITECTURE.md` change block in Appendix B.

**Verification**: Document mentions `ChatWidget -> ChatService -> MessageRepository` display-history pagination and keeps UI/data layering explicit.

### T032: Add assistant new-session smoke coverage

**File**: `tests/integration/test_assistant_new_session.py` (modify)

**Requirements**: constitution verifiable delivery

**Dependencies**: T010, T018, T026

**Implementation**: Apply the `test_assistant_new_session.py` change block in Appendix B.

**Verification**: `uv run python -m pytest tests/integration/test_assistant_new_session.py -q`

### T033: Run UI test command

**File**: validation only

**Requirements**: SC-001, SC-002, SC-005, SC-006, SC-007, SC-008

**Dependencies**: T012, T023, T030

**Implementation**:

```powershell
uv run python -m pytest tests/ui/test_chat_widget_markdown.py tests/ui/test_chat_widget_history.py tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py -q
```

**Verification**: Use `.venv\Scripts\python.exe` fallback if `uv run` hits the local cache permission issue documented in `quickstart.md`.

### T034: Run data/business/integration command

**File**: validation only

**Requirements**: FR-007-FR-014, constitution verifiable delivery

**Dependencies**: T013-T023, T032

**Implementation**:

```powershell
uv run python -m pytest tests/data/test_message_repository.py tests/business/test_chat_service_history.py tests/integration/test_assistant_new_session.py -q
```

**Verification**: Use `.venv\Scripts\python.exe` fallback if needed.

### T035: Run compile and diff checks

**File**: validation only

**Requirements**: all modified Python files compile, diff whitespace clean

**Dependencies**: T001-T034

**Implementation**:

```powershell
uv run python -m py_compile src/ui/widgets/chat_widget.py src/ui/widgets/markdown_message_view.py src/business/services/chat_service.py src/data/repos/message_repository.py
git diff --check
```

**Verification**: Both commands exit with code 0.

### T036: Verify manual acceptance

**File**: `specs/006-chat-ui-polish/quickstart.md` (read-only validation target)

**Requirements**: user-facing acceptance

**Dependencies**: T001-T035

**Implementation**: Execute the six manual acceptance items in `quickstart.md` and record any caveat in the final implementation response.

**Verification**: GUI behavior matches Markdown rendering, history paging, and Toggle visibility requirements.

---

## Appendix A: Complete New Files

### `src/ui/widgets/markdown_message_view.py`

```python
"""
Markdown rendering widget for assistant chat messages.

The widget is intentionally UI-local: it does not change storage, agent prompts,
or user-message rendering. It accepts raw assistant text, applies conservative
safety downgrades, and renders through Qt's Markdown support.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QTextDocument, QTextOption
from PyQt6.QtWidgets import QSizePolicy, QTextBrowser


_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>\n]*>")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


class MarkdownMessageView(QTextBrowser):
    """Read-only Markdown view for assistant messages."""

    allowed_image_schemes = {"http", "https"}

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._raw_text = ""
        self.setObjectName("content_assistant_markdown")
        self.setReadOnly(True)
        self.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._ignore_anchor)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.document().setDefaultTextOption(QTextOption(QTextOption.WrapMode.WordWrap))
        if text:
            self.set_content(text)

    @property
    def raw_text(self) -> str:
        return self._raw_text

    def set_content(self, text: str) -> None:
        self._raw_text = text or ""
        markdown = self._prepare_markdown(self._raw_text)
        try:
            self.document().setMarkdown(
                markdown,
                QTextDocument.MarkdownFeature.MarkdownDialectGitHub,
            )
        except TypeError:
            self.setMarkdown(markdown)
        self.document().adjustSize()
        self.setMinimumHeight(max(24, int(self.document().size().height()) + 4))

    def _ignore_anchor(self, _url: QUrl) -> None:
        return

    @classmethod
    def _prepare_markdown(cls, text: str) -> str:
        safe = _IMAGE_RE.sub(cls._replace_image, text or "")
        safe = _HTML_TAG_RE.sub(lambda match: html.escape(match.group(0)), safe)
        safe = cls._stabilize_partial_markdown(safe)
        return safe

    @classmethod
    def _replace_image(cls, match: re.Match[str]) -> str:
        alt_text = match.group(1).strip()
        target = match.group(2).strip()
        scheme = urlparse(target).scheme.lower()
        label = alt_text or "image"
        if scheme in cls.allowed_image_schemes:
            return f"**{label}**"
        return label

    @staticmethod
    def _stabilize_partial_markdown(text: str) -> str:
        stabilized = text
        if stabilized.count("```") % 2 == 1:
            stabilized += "\n```"
        if stabilized.count("**") % 2 == 1:
            stabilized += "**"
        single_star_count = len(re.findall(r"(?<!\*)\*(?!\*)", stabilized))
        if single_star_count % 2 == 1:
            stabilized += "*"
        return stabilized
```

### `tests/ui/chat_widget_test_helpers.py`

```python
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

from src.ui.widgets.chat_widget import ChatWidget  # noqa: E402


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")


@pytest.fixture()
def chat_widget(monkeypatch, app):
    monkeypatch.setattr(ChatWidget, "_load_sessions", lambda self: None)
    monkeypatch.setattr(ChatWidget, "_get_display_name", lambda self: "测试用户")
    widget = ChatWidget()
    widget.resize(900, 700)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()


def auto_approve_toggle(widget: ChatWidget) -> QPushButton:
    toggle = widget.findChild(QPushButton, "chat_auto_approve_toggle")
    assert toggle is not None
    return toggle


def plain_labels(widget: ChatWidget) -> list[QLabel]:
    return widget.findChildren(QLabel)


def label_texts(widget: ChatWidget) -> list[str]:
    return [label.text() for label in plain_labels(widget)]


def process_events(app, times: int = 2) -> None:
    for _ in range(times):
        app.processEvents()
```

### `tests/ui/test_chat_widget_layering.py`

```python
import ast
from pathlib import Path


CHAT_WIDGET = Path("src/ui/widgets/chat_widget.py")


def _imports_from_chat_widget() -> list[str]:
    tree = ast.parse(CHAT_WIDGET.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return imports


def test_chat_widget_imports_chat_service():
    imports = _imports_from_chat_widget()
    assert "src.business.services" in imports


def test_chat_widget_does_not_import_repositories():
    imports = _imports_from_chat_widget()
    forbidden = {
        "src.data.repos",
        "src.data.repositories",
        "src.data.repos.message_repository",
        "src.data.repos.session_repository",
    }
    assert forbidden.isdisjoint(set(imports))
```

### `tests/data/chat_history_test_helpers.py`

```python
from __future__ import annotations

import uuid

from src.business.agents.config import AgentType
from src.data.models_sqlite import Message, Session
from src.data.repositories import MessageRepository, SessionRepository


def create_assistant_session(session_id: str | None = None) -> str:
    actual_session_id = session_id or f"ast_{uuid.uuid4().hex[:12]}"
    SessionRepository().create(
        Session(
            session_id=actual_session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            tool_ids=None,
        )
    )
    return actual_session_id


def seed_message(
    session_id: str,
    sequence: int,
    role: str,
    content: str | None,
    message_type: str = "normal",
    is_archived: bool = False,
    tool_calls: str | None = None,
    tool_call_id: str | None = None,
) -> Message:
    message = Message(
        message_id=f"{session_id}_{sequence}_{uuid.uuid4().hex[:6]}",
        session_id=session_id,
        sequence=sequence,
        role=role,
        content=content,
        message_type=message_type,
        is_archived=is_archived,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )
    return MessageRepository().create(message)


def seed_display_messages(session_id: str, count: int, archived_until: int = 0) -> None:
    for sequence in range(1, count + 1):
        role = "user" if sequence % 2 else "assistant"
        seed_message(
            session_id=session_id,
            sequence=sequence,
            role=role,
            content=f"{role}-{sequence}",
            is_archived=sequence <= archived_until,
        )
```

### `tests/ui/test_chat_widget_markdown.py`

```python
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from src.ui.widgets.markdown_message_view import MarkdownMessageView
from tests.ui.chat_widget_test_helpers import process_events


def test_assistant_markdown_renders_rich_text(chat_widget, app):
    content = "\n".join(
        [
            "# 标题",
            "1. 第一项",
            "- 第二项",
            "**重要** 和 *斜体* 以及 `value`",
            "> 引用",
            "---",
            "| A | B |",
            "|---|---|",
            "| 1 | 2 |",
            "```python",
            "print('ok')",
            "```",
        ]
    )
    chat_widget._add_message("assistant", content)
    process_events(app)

    view = chat_widget.findChild(MarkdownMessageView, "content_assistant_markdown")
    assert view is not None
    plain = view.toPlainText()
    assert "标题" in plain
    assert "重要" in plain
    assert "value" in plain
    assert "print('ok')" in plain
    assert "```" not in plain


def test_markdown_safety_and_images_do_not_navigate(chat_widget, app):
    content = "\n".join(
        [
            "<script>alert('x')</script>",
            "[label](https://example.com)",
            "![remote alt](https://example.com/image.png)",
            "![local alt](file:///tmp/secret.png)",
            "![script alt](javascript:alert(1))",
        ]
    )
    chat_widget._add_message("assistant", content)
    process_events(app)

    view = chat_widget.findChild(MarkdownMessageView, "content_assistant_markdown")
    assert view is not None
    plain = view.toPlainText()
    assert "alert('x')" in plain
    assert "remote alt" in plain
    assert "local alt" in plain
    assert "script alt" in plain
    assert "file:///tmp/secret.png" not in plain
    assert "javascript:alert" not in plain
    assert view.openExternalLinks() is False


def test_partial_markdown_streaming_converges_without_exception(app):
    view = MarkdownMessageView()
    view.set_content("```python\nprint('a')")
    process_events(app)
    assert "print('a')" in view.toPlainText()

    final = "```python\nprint('a')\n```"
    view.set_content(final)
    process_events(app)
    one_shot = MarkdownMessageView(final)
    process_events(app)
    assert view.toPlainText() == one_shot.toPlainText()


def test_plain_assistant_text_keeps_content(chat_widget, app):
    chat_widget._add_message("assistant", "普通文本")
    process_events(app)

    view = chat_widget.findChild(MarkdownMessageView, "content_assistant_markdown")
    assert view is not None
    assert view.toPlainText() == "普通文本"


def test_user_message_markdown_like_text_is_plain(chat_widget, app):
    raw = "# 标题 `value` **bold** | A | B |"
    chat_widget._add_message("user", raw)
    process_events(app)

    labels = chat_widget.findChildren(QLabel, "content_user")
    assert labels
    assert labels[-1].text() == raw
    assert labels[-1].textFormat() == Qt.TextFormat.PlainText
```

### `tests/data/test_message_repository.py`

```python
import pytest

from src.data.repos.message_repository import MessageRepository
from tests.data.chat_history_test_helpers import (
    create_assistant_session,
    seed_display_messages,
    seed_message,
)


def test_get_display_page_returns_latest_ten_in_ascending_sequence(in_memory_db):
    session_id = create_assistant_session()
    seed_display_messages(session_id, 15, archived_until=8)

    messages, has_more = MessageRepository().get_display_page(session_id, limit=10)

    assert [message.sequence for message in messages] == list(range(6, 16))
    assert has_more is True


def test_get_display_page_before_sequence_returns_older_page(in_memory_db):
    session_id = create_assistant_session()
    seed_display_messages(session_id, 25, archived_until=20)

    messages, has_more = MessageRepository().get_display_page(
        session_id,
        limit=10,
        before_sequence=16,
    )

    assert [message.sequence for message in messages] == list(range(6, 16))
    assert has_more is True


def test_get_display_page_filters_internal_messages(in_memory_db):
    session_id = create_assistant_session()
    seed_message(session_id, 1, "system", "system")
    seed_message(session_id, 2, "user", "visible user", is_archived=True)
    seed_message(session_id, 3, "assistant", "visible assistant", is_archived=True)
    seed_message(session_id, 4, "tool", "tool result")
    seed_message(session_id, 5, "summary", "summary")
    seed_message(session_id, 6, "assistant", None, tool_calls="[]")
    seed_message(session_id, 7, "assistant", "", tool_calls="[]")
    seed_message(session_id, 8, "assistant", "compressed", message_type="compressed")

    messages, has_more = MessageRepository().get_display_page(session_id, limit=10)

    assert [(message.sequence, message.role, message.content) for message in messages] == [
        (2, "user", "visible user"),
        (3, "assistant", "visible assistant"),
    ]
    assert has_more is False


def test_get_display_page_rejects_non_positive_limit(in_memory_db):
    session_id = create_assistant_session()

    with pytest.raises(ValueError):
        MessageRepository().get_display_page(session_id, limit=0)
```

### `tests/business/test_chat_service_history.py`

```python
from src.business.services.chat_service import ChatHistoryPage, ChatService, DisplayChatMessage
from tests.data.chat_history_test_helpers import create_assistant_session, seed_message


def test_get_display_messages_returns_dtos_without_internal_fields(in_memory_db):
    session_id = create_assistant_session()
    seed_message(session_id, 1, "user", "old user", is_archived=True)
    seed_message(session_id, 2, "assistant", "old assistant", is_archived=True)
    seed_message(session_id, 3, "tool", "tool result")

    page = ChatService().get_display_messages(session_id, limit=10)

    assert isinstance(page, ChatHistoryPage)
    assert page.has_more_before is False
    assert page.next_before_sequence == 1
    assert page.messages == [
        DisplayChatMessage(sequence=1, role="user", content="old user", created_at=page.messages[0].created_at),
        DisplayChatMessage(sequence=2, role="assistant", content="old assistant", created_at=page.messages[1].created_at),
    ]
    assert not hasattr(page.messages[0], "is_archived")
    assert not hasattr(page.messages[0], "message_type")


def test_get_display_messages_uses_before_sequence(in_memory_db):
    session_id = create_assistant_session()
    for sequence in range(1, 16):
        seed_message(session_id, sequence, "user", f"user-{sequence}", is_archived=True)

    page = ChatService().get_display_messages(session_id, limit=5, before_sequence=11)

    assert [message.sequence for message in page.messages] == [6, 7, 8, 9, 10]
    assert page.has_more_before is True
    assert page.next_before_sequence == 6
```

### `tests/ui/test_chat_widget_history.py`

```python
import time
from types import SimpleNamespace

from PyQt6.QtWidgets import QLabel

from tests.ui.chat_widget_test_helpers import process_events


def _msg(sequence: int, role: str | None = None, content: str | None = None):
    actual_role = role or ("user" if sequence % 2 else "assistant")
    return SimpleNamespace(
        sequence=sequence,
        role=actual_role,
        content=content or f"{actual_role}-{sequence}",
        created_at=None,
    )


class _FakeChatService:
    calls: list[tuple[int, int | None]] = []
    pages: dict[int | None, object] = {}

    def get_display_messages(self, session_id: str, limit: int = 10, before_sequence: int | None = None):
        self.calls.append((limit, before_sequence))
        return self.pages[before_sequence]

    def get_display_name(self) -> str:
        return "测试用户"


def _page(messages, has_more):
    next_before = messages[0].sequence if messages else None
    return SimpleNamespace(
        messages=messages,
        has_more_before=has_more,
        next_before_sequence=next_before,
    )


def test_initial_render_uses_latest_ten(monkeypatch, chat_widget, app):
    import src.ui.widgets.chat_widget as chat_widget_module

    _FakeChatService.calls = []
    _FakeChatService.pages = {None: _page([_msg(i) for i in range(11, 21)], True)}
    monkeypatch.setattr(chat_widget_module, "ChatService", _FakeChatService)

    started = time.perf_counter()
    chat_widget._switch_to_session("ast-history")
    process_events(app)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms <= 2000
    assert _FakeChatService.calls == [(10, None)]
    assert chat_widget._oldest_loaded_sequence == 11
    assert chat_widget._has_more_history is True


def test_top_scroll_prepends_older_page_and_preserves_view(monkeypatch, chat_widget, app):
    import src.ui.widgets.chat_widget as chat_widget_module

    _FakeChatService.calls = []
    _FakeChatService.pages = {
        None: _page([_msg(i) for i in range(11, 21)], True),
        11: _page([_msg(i) for i in range(1, 11)], False),
    }
    monkeypatch.setattr(chat_widget_module, "ChatService", _FakeChatService)
    chat_widget._switch_to_session("ast-history")
    process_events(app)

    scrollbar = chat_widget.messages_scroll.verticalScrollBar()
    scrollbar.setValue(0)
    started = time.perf_counter()
    chat_widget._maybe_load_older_messages(0)
    process_events(app)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms <= 100
    assert (10, 11) in _FakeChatService.calls
    assert chat_widget._oldest_loaded_sequence == 1
    assert chat_widget._has_more_history is False


def test_history_does_not_show_archive_or_compression_labels(monkeypatch, chat_widget, app):
    import src.ui.widgets.chat_widget as chat_widget_module

    _FakeChatService.pages = {None: _page([_msg(1, "user", "archived text")], False)}
    monkeypatch.setattr(chat_widget_module, "ChatService", _FakeChatService)

    chat_widget._switch_to_session("ast-history")
    process_events(app)

    all_text = " ".join(label.text() for label in chat_widget.findChildren(QLabel))
    assert "归档" not in all_text
    assert "压缩" not in all_text


def test_input_send_path_under_long_history_stays_responsive(monkeypatch, chat_widget, app):
    import src.ui.widgets.chat_widget as chat_widget_module

    _FakeChatService.pages = {None: _page([_msg(i) for i in range(991, 1001)], True)}
    monkeypatch.setattr(chat_widget_module, "ChatService", _FakeChatService)
    chat_widget._switch_to_session("ast-history")
    process_events(app)

    received = []
    chat_widget.send_message_requested.connect(lambda *args: received.append(args))
    chat_widget.message_input.setPlainText("继续")
    started = time.perf_counter()
    chat_widget.on_send_message()
    process_events(app)
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert elapsed_ms <= 100
    assert received
    assert received[0][2] == "继续"
```

---

## Appendix B: Modified File Change Blocks

### `src/data/repos/message_repository.py`

**Before** (line 8):

```python
from sqlalchemy import and_, func
```

**After**:

```python
from sqlalchemy import and_, func, or_
```

**Before** (line 61):

```python
    def get_all(self, session_id: str) -> List[Message]:
        """获取会话的所有消息"""
        return (
            self.session.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.sequence)
            .all()
        )
```

**After**:

```python
    def get_all(self, session_id: str) -> List[Message]:
        """获取会话的所有消息"""
        return (
            self.session.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.sequence)
            .all()
        )

    def get_display_page(
        self,
        session_id: str,
        limit: int,
        before_sequence: int | None = None,
    ) -> tuple[List[Message], bool]:
        """读取用户可见聊天消息页，包含 archived 原始用户/助手消息。"""
        if limit <= 0:
            raise ValueError("limit must be positive")

        query = self.session.query(Message).filter(
            and_(
                Message.session_id == session_id,
                Message.role.in_(("user", "assistant")),
                Message.content.isnot(None),
                func.length(func.trim(Message.content)) > 0,
                or_(Message.message_type.is_(None), Message.message_type != "compressed"),
            )
        )
        if before_sequence is not None:
            query = query.filter(Message.sequence < before_sequence)

        rows = query.order_by(Message.sequence.desc()).limit(limit + 1).all()
        has_more_before = len(rows) > limit
        page_rows = rows[:limit]
        page_rows.reverse()
        return page_rows, has_more_before
```

### `src/business/services/chat_service.py`

**Before** (line 7):

```python
import json
import logging
import uuid
from typing import Optional
```

**After**:

```python
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
```

**Before** (line 17):

```python
logger = logging.getLogger(__name__)
```

**After**:

```python
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DisplayChatMessage:
    sequence: int
    role: str
    content: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class ChatHistoryPage:
    messages: list[DisplayChatMessage]
    has_more_before: bool
    next_before_sequence: int | None
```

**Before** (line 61):

```python
    def get_session_messages(self, session_id: str) -> list[Message]:
        """返回会话的非归档消息列表（供 UI 渲染历史记录）"""
        return MessageRepository().get_context(session_id)
```

**After**:

```python
    def get_session_messages(self, session_id: str) -> list[Message]:
        """返回会话的非归档消息列表（供 UI 渲染历史记录）"""
        return MessageRepository().get_context(session_id)

    def get_display_messages(
        self,
        session_id: str,
        limit: int = 10,
        before_sequence: int | None = None,
    ) -> ChatHistoryPage:
        """返回用户可见聊天历史页，不暴露归档和压缩内部字段。"""
        rows, has_more_before = MessageRepository().get_display_page(
            session_id=session_id,
            limit=limit,
            before_sequence=before_sequence,
        )
        messages = [
            DisplayChatMessage(
                sequence=row.sequence,
                role=row.role,
                content=row.content or "",
                created_at=row.created_at,
            )
            for row in rows
        ]
        return ChatHistoryPage(
            messages=messages,
            has_more_before=has_more_before,
            next_before_sequence=messages[0].sequence if messages else None,
        )
```

### `src/ui/widgets/chat_widget.py`

Apply these blocks in bottom-to-top order when editing manually.

**Before** (line 617):

```python
        self._add_message("user", message)
        self.message_input.clear()
        self.set_loading(True)
```

**After**:

```python
        self._mark_conversation_started()
        self._add_message("user", message)
        self.message_input.clear()
        self.set_loading(True)
```

**Before** (line 591):

```python
    def _refresh_auto_approve_toggle_text(self, enabled: bool) -> None:
        state = "开启" if enabled else "关闭"
        self.auto_approve_toggle.setText(f"免确认：{state}")
        self.auto_approve_toggle.setProperty("autoApproveEnabled", enabled)
        style = self.auto_approve_toggle.style()
        style.unpolish(self.auto_approve_toggle)
        style.polish(self.auto_approve_toggle)
```

**After**:

```python
    def _refresh_auto_approve_toggle_text(self, enabled: bool) -> None:
        state = "开启" if enabled else "关闭"
        self.auto_approve_toggle.setText(f"免确认：{state}")
        self.auto_approve_toggle.setProperty("autoApproveEnabled", enabled)
        style = self.auto_approve_toggle.style()
        style.unpolish(self.auto_approve_toggle)
        style.polish(self.auto_approve_toggle)

    def _set_auto_approve_toggle_visible(self, visible: bool) -> None:
        self.auto_approve_toggle.setVisible(visible)
        self.auto_approve_toggle.setProperty("autoApproveVisible", visible)
        style = self.auto_approve_toggle.style()
        style.unpolish(self.auto_approve_toggle)
        style.polish(self.auto_approve_toggle)

    def _mark_conversation_started(self) -> None:
        self._conversation_started = True
        self._set_auto_approve_toggle_visible(True)
```

**Before** (line 553):

```python
    def show_session_list(self):
        """显示会话列表视图（供 MainWindow 在页面切换时调用）"""
        self._load_sessions()
        self._stack.setCurrentIndex(self.VIEW_SESSION_LIST)
```

**After**:

```python
    def show_session_list(self):
        """显示会话列表视图（供 MainWindow 在页面切换时调用）"""
        self._set_auto_approve_toggle_visible(False)
        self._load_sessions()
        self._stack.setCurrentIndex(self.VIEW_SESSION_LIST)
```

**Before** (line 547):

```python
    def on_new_chat(self):
        """新建对话（外部调用入口）— 只准备 UI，不创建 DB 会话"""
        self.set_auto_approve_enabled(False)
        self._prepare_new_chat()
        self.new_chat_started.emit()
```

**After**:

```python
    def on_new_chat(self):
        """新建对话（外部调用入口）— 只准备 UI，不创建 DB 会话"""
        self.set_auto_approve_enabled(False)
        self._set_auto_approve_toggle_visible(False)
        self._prepare_new_chat()
        self.new_chat_started.emit()
```

**Before** (line 539):

```python
    def add_assistant_message(self, content: str):
        """添加 AI 助手消息（供 MainWindow 的信号 handler 调用）"""
        self._add_message("assistant", content)
```

**After**:

```python
    def add_assistant_message(self, content: str):
        """添加 AI 助手消息（供 MainWindow 的信号 handler 调用）"""
        self._mark_conversation_started()
        self._add_message("assistant", content)
```

**Before** (line 456):

```python
    def _add_message(self, role: str, content: str):
        """添加消息到对话区域"""
        message_container = QWidget()
        message_container.setObjectName("message_row")
```

**After**:

```python
    def _add_message(
        self,
        role: str,
        content: str,
        *,
        sequence: int | None = None,
        prepend: bool = False,
        scroll_to_end: bool = True,
    ):
        """添加消息到对话区域"""
        message_container = QWidget()
        message_container.setObjectName("message_row")
        if sequence is not None:
            message_container.setProperty("messageSequence", sequence)
```

**Before** (line 491):

```python
        content_label = QLabel(content)
        content_label.setObjectName(f"content_{role}")
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.PlainText)
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_content_layout.addWidget(content_label)
```

**After**:

```python
        if role == "assistant":
            content_widget = MarkdownMessageView(content)
        else:
            content_widget = QLabel(content)
            content_widget.setWordWrap(True)
            content_widget.setTextFormat(Qt.TextFormat.PlainText)
            content_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content_widget.setObjectName(f"content_{role}" if role != "assistant" else "content_assistant_markdown")
        bubble_content_layout.addWidget(content_widget)
```

**Before** (line 503):

```python
        self.messages_layout.addWidget(message_container)
        QTimer.singleShot(100, self._scroll_to_bottom)
```

**After**:

```python
        if prepend:
            self.messages_layout.insertWidget(0, message_container)
        else:
            self.messages_layout.addWidget(message_container)
        if scroll_to_end:
            QTimer.singleShot(100, self._scroll_to_bottom)
        return message_container
```

**Before** (line 373):

```python
    def _clear_messages(self):
        """清空消息区域"""
        self._welcome_visible = False
        self._welcome_input = None
        clear_layout(self.messages_layout)
```

**After**:

```python
    def _clear_messages(self):
        """清空消息区域"""
        self._welcome_visible = False
        self._welcome_input = None
        self._reset_history_state()
        clear_layout(self.messages_layout)
```

**Before** (line 379):

```python
    def _add_welcome_message(self):
        """添加 Claude 风格的欢迎页面 — 居中输入框"""
        if self._welcome_visible:
            return
```

**After**:

```python
    def _add_welcome_message(self):
        """添加 Claude 风格的欢迎页面 — 居中输入框"""
        self._conversation_started = False
        self._set_auto_approve_toggle_visible(False)
        if self._welcome_visible:
            return
```

**Before** (line 355):

```python
    def _load_session_messages(self, session_id: str):
        """从数据库加载会话历史消息（只加载非归档消息）"""
        try:
            messages = ChatService().get_session_messages(session_id)
            if not messages:
                self._add_welcome_message()
                return
            for msg in messages:
                if msg.role in ("user", "assistant") and msg.content:
                    self._add_message(msg.role, msg.content)
        except Exception as e:
            self.logger.error(f"加载会话消息失败: {e}")
            self._add_welcome_message()
```

**After**:

```python
    def _load_session_messages(self, session_id: str):
        """从业务层加载用户可见会话历史消息。"""
        try:
            page = ChatService().get_display_messages(session_id, limit=10)
            if not page.messages:
                self._add_welcome_message()
                return
            self._render_display_messages(page.messages, prepend=False, scroll_to_end=True)
            self._has_more_history = page.has_more_before
            self._oldest_loaded_sequence = page.next_before_sequence
            self._mark_conversation_started()
        except Exception as e:
            self.logger.error(f"加载会话消息失败: {e}")
            self._add_welcome_message()

    def _render_display_messages(self, messages, *, prepend: bool, scroll_to_end: bool):
        for msg in messages:
            self._add_message(
                msg.role,
                msg.content,
                sequence=msg.sequence,
                prepend=prepend,
                scroll_to_end=scroll_to_end,
            )

    def _maybe_load_older_messages(self, value: int) -> None:
        if value > 12 or not self._has_more_history or self._loading_history_page:
            return
        if self._oldest_loaded_sequence is None or self._session_id is None:
            return
        self._loading_history_page = True
        scrollbar = self.messages_scroll.verticalScrollBar()
        old_max = scrollbar.maximum()
        old_value = scrollbar.value()
        try:
            page = ChatService().get_display_messages(
                self._session_id,
                limit=10,
                before_sequence=self._oldest_loaded_sequence,
            )
            self._prepend_display_messages(page.messages, old_max, old_value)
            self._has_more_history = page.has_more_before
            if page.next_before_sequence is not None:
                self._oldest_loaded_sequence = page.next_before_sequence
        except Exception as e:
            self.logger.error(f"加载更早消息失败: {e}")
        finally:
            self._loading_history_page = False

    def _prepend_display_messages(self, messages, old_max: int, old_value: int) -> None:
        for msg in reversed(messages):
            self._add_message(
                msg.role,
                msg.content,
                sequence=msg.sequence,
                prepend=True,
                scroll_to_end=False,
            )
        self.messages_container.adjustSize()
        scrollbar = self.messages_scroll.verticalScrollBar()
        delta = scrollbar.maximum() - old_max
        scrollbar.setValue(old_value + delta)
```

**Before** (line 337):

```python
    def _prepare_new_chat(self, tool_ids=None):
        """准备新对话界面（不立即创建 DB 会话，等用户发第一条消息时再创建）"""
        self._session_id = None
        self._pending_tool_ids = tool_ids
        self._clear_messages()
        self._add_welcome_message()
        self._stack.setCurrentIndex(self.VIEW_CONVERSATION)
```

**After**:

```python
    def _prepare_new_chat(self, tool_ids=None):
        """准备新对话界面（不立即创建 DB 会话，等用户发第一条消息时再创建）"""
        self._session_id = None
        self._pending_tool_ids = tool_ids
        self._conversation_started = False
        self._set_auto_approve_toggle_visible(False)
        self._clear_messages()
        self._add_welcome_message()
        self._stack.setCurrentIndex(self.VIEW_CONVERSATION)
```

**Before** (line 345):

```python
    def _switch_to_session(self, session_id: str):
        """切换到指定会话（加载历史消息）"""
        self._session_id = session_id
        self._loading = False
        self.send_button.setEnabled(False)
        self.send_button.setText("发送")
        self._clear_messages()
        self.input_container.show()
        self._load_session_messages(session_id)
```

**After**:

```python
    def _switch_to_session(self, session_id: str):
        """切换到指定会话（加载历史消息）"""
        self._session_id = session_id
        self._loading = False
        self._conversation_started = False
        self._set_auto_approve_toggle_visible(False)
        self.send_button.setEnabled(False)
        self.send_button.setText("发送")
        self._clear_messages()
        self.input_container.show()
        self._load_session_messages(session_id)
```

**Before** (line 203):

```python
        messages_scroll = QScrollArea()
        messages_scroll.setWidgetResizable(True)
        messages_scroll.setObjectName("messages_scroll")
        messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
```

**After**:

```python
        self.messages_scroll = QScrollArea()
        self.messages_scroll.setWidgetResizable(True)
        self.messages_scroll.setObjectName("messages_scroll")
        self.messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages_scroll.verticalScrollBar().valueChanged.connect(self._maybe_load_older_messages)
```

**Before** (line 197):

```python
        self._refresh_auto_approve_toggle_text(False)
        header_layout.addWidget(self.auto_approve_toggle)
```

**After**:

```python
        self._refresh_auto_approve_toggle_text(False)
        header_layout.addWidget(self.auto_approve_toggle)
        self._set_auto_approve_toggle_visible(False)
```

**Before** (line 215):

```python
        messages_scroll.setWidget(self.messages_container)

        chat_layout.addWidget(messages_scroll, 1)
```

**After**:

```python
        self.messages_scroll.setWidget(self.messages_container)

        chat_layout.addWidget(self.messages_scroll, 1)
```

**Before** (line 23):

```python
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap
from src.business.agents.config import AgentType
from src.business.services import ChatService
from src.ui.widgets.message_input import MessageInputEdit
from src.ui.widgets.layout_utils import clear_layout, scroll_to_bottom
```

**After**:

```python
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap
from src.business.agents.config import AgentType
from src.business.services import ChatService
from src.ui.widgets.markdown_message_view import MarkdownMessageView
from src.ui.widgets.message_input import MessageInputEdit
from src.ui.widgets.layout_utils import clear_layout, scroll_to_bottom
```

**Before** (line 96):

```python
        self.init_ui()
```

**After**:

```python
        self._oldest_loaded_sequence = None
        self._has_more_history = False
        self._loading_history_page = False
        self._conversation_started = False
        self.init_ui()
```

Add this helper near other private helpers:

```python
    def _reset_history_state(self) -> None:
        self._oldest_loaded_sequence = None
        self._has_more_history = False
        self._loading_history_page = False
```

### `src/ui/resources/styles.qss`

**Before** (line 352):

```css
QLabel#content_assistant {
    color: #212529;
    font-size: 15px;
    line-height: 1.6;
    background-color: transparent;
}
```

**After**:

```css
QLabel#content_assistant,
QTextBrowser#content_assistant_markdown {
    color: #212529;
    font-size: 15px;
    line-height: 1.6;
    background-color: transparent;
    border: none;
}

QTextBrowser#content_assistant_markdown {
    padding: 0;
    selection-background-color: #d7e8ff;
}

QTextBrowser#content_assistant_markdown code {
    background-color: #f1f3f5;
    color: #2f3a45;
}
```

**Before** (line 259):

```css
QPushButton#chat_auto_approve_toggle {
    background-color: #f8f9fa;
    color: #495057;
    border: 1px solid #ced4da;
    border-radius: 8px;
    padding: 7px 14px;
}
```

**After**:

```css
QPushButton#chat_auto_approve_toggle {
    background-color: #f8f9fa;
    color: #495057;
    border: 1px solid #ced4da;
    border-radius: 8px;
    padding: 7px 14px;
}

QPushButton#chat_auto_approve_toggle[autoApproveVisible="false"] {
    min-width: 0;
    max-width: 0;
    padding: 0;
    border: none;
}
```

### `tests/ui/test_chat_widget_auth_toggle.py`

Apply this adjustment to existing tests that click the Toggle:

```python
    widget._mark_conversation_started()
    app.processEvents()
```

Place the adjustment before the first `QTest.mouseClick(toggle, Qt.MouseButton.LeftButton)` call and before assertions that require the Toggle to be visible in non-welcome states.

Append these tests to the file:

```python
def test_toggle_hidden_on_welcome_and_new_chat_states(widget, app):
    toggle = _toggle(widget)

    widget.show_session_list()
    app.processEvents()
    assert toggle.isVisible() is False

    widget.on_new_chat()
    app.processEvents()
    assert toggle.isVisible() is False


def test_toggle_visible_after_first_send_without_extra_toggle_signal(widget, app):
    events = []
    widget.auto_approve_toggled.connect(events.append)
    toggle = _toggle(widget)

    widget.on_new_chat()
    widget.message_input.setPlainText("你好")
    widget.on_send_message()
    app.processEvents()

    assert toggle.isVisible() is True
    assert events == []


def test_toggle_visible_for_existing_non_empty_session(monkeypatch, widget, app):
    from types import SimpleNamespace
    import src.ui.widgets.chat_widget as chat_widget_module

    class FakeChatService:
        def get_display_messages(self, session_id, limit=10, before_sequence=None):
            return SimpleNamespace(
                messages=[
                    SimpleNamespace(sequence=1, role="user", content="你好"),
                    SimpleNamespace(sequence=2, role="assistant", content="你好"),
                ],
                has_more_before=False,
                next_before_sequence=1,
            )

    monkeypatch.setattr(chat_widget_module, "ChatService", FakeChatService)
    widget._switch_to_session("ast-existing")
    app.processEvents()

    assert _toggle(widget).isVisible() is True
```

### `tests/ui/test_agent_handler_mixin.py`

Append this test to the file:

```python
def test_hidden_chat_toggle_still_accepts_programmatic_state_sync(app):
    window = _DummyWindow(_DummySkillsPage())
    window.chat_widget.set_auto_approve_enabled(False)

    window._on_chat_auto_approve_toggled(True)
    app.processEvents()

    assert general_tools.is_auto_approve_enabled() is True
    assert window.chat_widget.auto_approve_states[-1] is True
    window.deleteLater()
```

### `docs/ARCHITECTURE.md`

Add this subsection after the “用技能：办公助理日常入口” flow:

```markdown
### 办公助理聊天展示边界

`ChatWidget` 只负责聊天界面、输入信号和消息气泡展示。已有会话的可见聊天历史通过 `ChatService.get_display_messages()` 分页读取，业务层再调用 `MessageRepository.get_display_page()` 对 SQLite `messages` 做只读 keyset 查询。UI 不直接导入或调用 Repository。

展示历史只包含用户消息和助手对话回复，按 `sequence` 合并为同一时间线；tool、summary、compressed 和空内容消息不会作为普通聊天气泡展示。内部 `is_archived`、`message_type`、`compressed_range` 等字段不会传给 UI DTO。聊天框初始展示最近 10 条可见消息，向上滚动时用当前最早 `sequence` 加载更早消息。

助手消息的 Markdown 渲染限制在 `MarkdownMessageView`。用户消息仍走纯文本路径。Markdown 链接和图片不会触发外部导航，本地文件和脚本协议目标会安全降级。
```

### `tests/integration/test_assistant_new_session.py`

Append this method inside `TestAssistantNewSession`:

```python
    def test_chat_widget_send_signal_survives_markdown_and_history_changes(self, in_memory_db):
        try:
            from PyQt6.QtWidgets import QApplication
            import sys

            app = QApplication.instance() or QApplication(sys.argv)
        except (ImportError, RuntimeError):
            pytest.skip("PyQt6 不可用或无法创建 QApplication")

        from src.ui.widgets.chat_widget import ChatWidget

        widget = ChatWidget()
        received = []
        widget.send_message_requested.connect(
            lambda sid, atype, msg: received.append((sid, atype, msg))
        )

        widget.on_new_chat()
        widget.message_input.setPlainText("请用 Markdown 回复")
        widget.on_send_message()
        app.processEvents()

        assert len(received) == 1
        session_id, agent_type, user_input = received[0]
        assert session_id.startswith("ast_")
        assert agent_type == AgentType.ASSISTANT
        assert user_input == "请用 Markdown 回复"
        widget.close()
```

## Checklist

- [ ] T001 Create `src/ui/widgets/markdown_message_view.py` with a minimal `MarkdownMessageView` class shell and keep `pyproject.toml` free of new Markdown parser dependencies.
- [ ] T002 Create `tests/ui/chat_widget_test_helpers.py` with reusable offscreen `QApplication`, `ChatWidget` factory, and widget lookup helpers.
- [ ] T003 Add UI layering guard tests in `tests/ui/test_chat_widget_layering.py`.
- [ ] T004 Add shared SQLite message seed helpers in `tests/data/chat_history_test_helpers.py`.
- [ ] T005 Add Markdown rendering coverage in `tests/ui/test_chat_widget_markdown.py`.
- [ ] T006 Add Markdown safety and partial-render coverage in `tests/ui/test_chat_widget_markdown.py`.
- [ ] T007 Add user-message plain-text coverage in `tests/ui/test_chat_widget_markdown.py`.
- [ ] T008 Implement `MarkdownMessageView` in `src/ui/widgets/markdown_message_view.py`.
- [ ] T009 Implement Markdown safety downgrade and navigation blocking in `src/ui/widgets/markdown_message_view.py`.
- [ ] T010 Integrate `MarkdownMessageView` into assistant branches of `ChatWidget._add_message`.
- [ ] T011 Add rich-text visual styles in `src/ui/resources/styles.qss`.
- [ ] T012 Validate User Story 1.
- [ ] T013 Add repository pagination tests in `tests/data/test_message_repository.py`.
- [ ] T014 Add ChatService contract tests in `tests/business/test_chat_service_history.py`.
- [ ] T015 Add ChatWidget history UI tests in `tests/ui/test_chat_widget_history.py`.
- [ ] T016 Add `MessageRepository.get_display_page`.
- [ ] T017 Add `DisplayChatMessage`, `ChatHistoryPage`, and `ChatService.get_display_messages`.
- [ ] T018 Replace `ChatWidget._load_session_messages`.
- [ ] T019 Track ChatWidget pagination state.
- [ ] T020 Connect top-threshold loader.
- [ ] T021 Prepend older message widgets and preserve viewport.
- [ ] T022 Reset history pagination state.
- [ ] T023 Validate User Story 2.
- [ ] T024 Extend `tests/ui/test_chat_widget_auth_toggle.py`.
- [ ] T025 Extend `tests/ui/test_agent_handler_mixin.py`.
- [ ] T026 Add Toggle visibility helpers.
- [ ] T027 Hide Toggle for welcome/list/new-chat states.
- [ ] T028 Show Toggle after conversation starts.
- [ ] T029 Adjust header layout handling and styles.
- [ ] T030 Validate User Story 3.
- [ ] T031 Update `docs/ARCHITECTURE.md`.
- [ ] T032 Add assistant new-session smoke coverage.
- [ ] T033 Run UI test command.
- [ ] T034 Run data/business/integration command.
- [ ] T035 Run compile and diff checks.
- [ ] T036 Verify quickstart manual acceptance items.
