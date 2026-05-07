"""
MarkdownMessageView — assistant 消息安全 Markdown 渲染

使用 Qt 内建 QTextDocument.setMarkdown() 渲染 GitHub 风格 Markdown，
渲染前降级 raw HTML/script/非远程图片，渲染后拦截链接/图片导航。
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QUrl, Qt, QSize
from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QFrame, QSizePolicy, QTextBrowser


class MarkdownMessageView(QTextBrowser):
    """Assistant 消息安全 Markdown 渲染 widget。"""

    allowed_image_schemes = {"http", "https"}

    # raw HTML 标签（含 script / style / iframe 等）
    _RAW_HTML_RE = re.compile(r"<(?!\s*/?\s*(?:br|hr)\b)[^>]+>", re.IGNORECASE)
    # HTML script 块
    _SCRIPT_BLOCK_RE = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
    # 非 http(s) 图片 src (HTML <img> tag)
    _UNSAFE_IMG_RE = re.compile(
        r'<img\s[^>]*src\s*=\s*["\'](?!(?:https?://))[^"\']*["\']',
        re.IGNORECASE,
    )
    # 非 http(s) 图片 (Markdown 语法: ![alt](url))
    _UNSAFE_MD_IMG_RE = re.compile(
        r"!\[([^\]]*)\]\((?!(?:https?://))[^)]*\)",
    )
    # file: / javascript: 链接
    _UNSAFE_LINK_RE = re.compile(
        r'<a\s[^>]*href\s*=\s*["\'](?:file|javascript):[^"\']*["\']',
        re.IGNORECASE,
    )

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._raw_text = text or ""
        self._is_streaming = False
        self._adjusting = False
        self._cached_size_hint: QSize | None = None

        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setOpenLinks(False)
        self.setObjectName("markdown_message_view")

        # 去掉 QTextBrowser 默认的边框、滚动条，使其作为内联渲染 widget
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(0)

        self.document().contentsChanged.connect(self._on_contents_changed)

        if self._raw_text:
            self._apply_content(self._raw_text)

    @property
    def raw_text(self) -> str:
        return self._raw_text

    def set_content(self, text: str) -> None:
        self._raw_text = text or ""
        self._apply_content(self._raw_text)

    def begin_streaming(self) -> None:
        self._is_streaming = True

    def update_streaming(self, text: str) -> None:
        self._raw_text = text
        self._apply_content(text)

    def finish_streaming(self, final_text: str) -> None:
        self._is_streaming = False
        self._raw_text = final_text
        self._apply_content(final_text)

    def _apply_content(self, text: str) -> None:
        safe = self._sanitize_markdown(text)
        doc = self.document()
        doc.blockSignals(True)
        try:
            doc.setMarkdown(safe, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
            self.setTextCursor(QTextCursor(doc))
        finally:
            doc.blockSignals(False)
        self._on_contents_changed()

    def _on_contents_changed(self) -> None:
        self._cached_size_hint = None
        self._adjust_size()

    def sizeHint(self):
        if self._cached_size_hint is not None:
            return self._cached_size_hint
        w = max(int(self.document().idealWidth()), 50)
        h = max(int(self.document().size().height()) + 4, 1)
        self._cached_size_hint = QSize(w, h)
        return self._cached_size_hint

    def minimumSizeHint(self):
        return QSize(0, 0)

    def _adjust_size(self) -> None:
        """根据文档内容自动调整高度（含重入保护）。"""
        if self._adjusting:
            return
        self._adjusting = True
        try:
            w = self.width()
            if w <= 0:
                self.updateGeometry()
                return
            doc = self.document()
            doc.setTextWidth(w)
            new_h = max(int(doc.size().height()) + 4, 1)
            self._cached_size_hint = QSize(w, new_h)
            if self.height() != new_h:
                self.setFixedHeight(new_h)
                self.updateGeometry()
        finally:
            self._adjusting = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._adjust_size()

    def _sanitize_markdown(self, text: str) -> str:
        text = self._SCRIPT_BLOCK_RE.sub("", text)
        text = self._UNSAFE_LINK_RE.sub(
            lambda m: m.group(0).rsplit("href", 1)[0] + "href=\"#\"",
            text,
        )
        text = self._UNSAFE_IMG_RE.sub(
            lambda m: _extract_img_alt(m.group(0)),
            text,
        )
        text = self._UNSAFE_MD_IMG_RE.sub(
            lambda m: f"*{m.group(1) or '[image]'}*",
            text,
        )
        text = self._RAW_HTML_RE.sub(
            lambda m: _maybe_passthrough(m.group(0)),
            text,
        )
        return text

    # ── 事件拦截 ──

    def setSource(self, name: QUrl) -> None:
        pass

    def anchorClicked(self, _link: QUrl) -> None:
        pass


def _extract_img_alt(tag: str) -> str:
    m = re.search(r'alt\s*=\s*["\']([^"\']*)["\']', tag, re.IGNORECASE)
    alt = m.group(1) if m else "[image]"
    return f"*{alt}*"


def _maybe_passthrough(tag: str) -> str:
    lower = tag.lower().strip()
    if lower.startswith("<br") or lower.startswith("<hr") or lower.startswith("</br") or lower.startswith("</hr"):
        return tag
    escaped = tag.replace("<", "&lt;").replace(">", "&gt;")
    return escaped
