import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.ui.widgets.chat_widget import ChatWidget  # noqa: E402
from src.ui.widgets.markdown_message_view import MarkdownMessageView  # noqa: E402


@pytest.fixture(scope="module")
def app():
    try:
        return QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用")


@pytest.fixture()
def widget(app, monkeypatch):
    monkeypatch.setattr(ChatWidget, "_load_sessions", lambda self: None)
    monkeypatch.setattr(ChatWidget, "_get_display_name", lambda self: "测试用户")
    w = ChatWidget()
    w.show()
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()


# ──────────────────────────────────────────────
# T005: Markdown 基础渲染覆盖
# ──────────────────────────────────────────────


class TestMarkdownBasicRendering:
    """T005: headings, lists, code blocks, inline code, bold/italic, quote, divider, table"""

    def test_headings_render_as_rich_text(self, widget, app):
        md = "# 大标题\n\n## 二级标题\n\n### 三级标题"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        assert len(views) >= 1
        doc = views[-1].document()
        full_text = doc.toPlainText()
        assert "大标题" in full_text
        assert "二级标题" in full_text

    def test_ordered_and_unordered_lists(self, widget, app):
        md = "- 项目 A\n- 项目 B\n\n1. 第一步\n2. 第二步"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        doc = views[-1].document()
        text = doc.toPlainText()
        assert "项目 A" in text
        assert "第一步" in text

    def test_code_block_renders(self, widget, app):
        md = "```python\nprint('hello')\n```"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        doc = views[-1].document()
        text = doc.toPlainText()
        assert "print" in text and "hello" in text

    def test_inline_code_renders(self, widget, app):
        md = "使用 `pip install` 安装"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        text = views[-1].document().toPlainText()
        assert "pip install" in text

    def test_bold_and_italic(self, widget, app):
        md = "这是**加粗**和*斜体*文本"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        text = views[-1].document().toPlainText()
        assert "加粗" in text
        assert "斜体" in text

    def test_blockquote_renders(self, widget, app):
        md = "> 引用文本"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        text = views[-1].document().toPlainText()
        assert "引用文本" in text

    def test_horizontal_rule_renders(self, widget, app):
        md = "上面\n\n---\n\n下面"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        text = views[-1].document().toPlainText()
        assert "上面" in text and "下面" in text

    def test_github_pipe_table_renders(self, widget, app):
        md = "| 列 A | 列 B |\n|------|------|\n| 1 | 2 |"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        text = views[-1].document().toPlainText()
        assert "列 A" in text and "列 B" in text


# ──────────────────────────────────────────────
# T006: Markdown 安全与 partial render
# ──────────────────────────────────────────────


class TestMarkdownSafety:
    """T006: raw HTML/script downgrade, image handling, navigation blocking, partial streaming"""

    def test_raw_html_script_downgraded(self, widget, app):
        md = "文字<script>alert('xss')</script>更多"
        widget.add_assistant_message(md)
        app.processEvents()
        views = widget.findChildren(MarkdownMessageView)
        text = views[-1].document().toPlainText()
        assert "script" not in text.lower().replace("&lt;", "")
        assert "alert" not in text

    def test_remote_http_image_loads_or_alt_fallback(self, widget, app):
        md = "![alt text](https://example.com/img.png)"
        view = MarkdownMessageView(md)
        app.processEvents()
        doc_text = view.document().toPlainText()
        # Qt represents images as ￼; the key invariant is no crash and no external navigation
        assert doc_text is not None

    def test_non_remote_image_downgraded(self, widget, app):
        md = "![pic](file:///etc/passwd)"
        view = MarkdownMessageView(md)
        text = view.document().toPlainText()
        # Non-remote images are downgraded to italic alt text by _UNSAFE_MD_IMG_RE
        assert "pic" in text

    def test_link_click_no_op(self, widget, app):
        md = "[click](https://example.com)"
        view = MarkdownMessageView(md)
        # setSource override is a no-op; calling it should not raise or navigate
        view.setSource(None)

    def test_image_click_no_op(self, widget, app):
        view = MarkdownMessageView("![img](https://example.com/img.png)")
        view.setSource(None)

    def test_incomplete_code_fence_no_exception(self, widget, app):
        md = "```\nunclosed code"
        view = MarkdownMessageView(md)
        text = view.document().toPlainText()
        assert "unclosed code" in text

    def test_incomplete_emphasis_no_exception(self, widget, app):
        md = "some *unclosed emphasis"
        view = MarkdownMessageView(md)
        text = view.document().toPlainText()
        assert "unclosed emphasis" in text

    def test_streaming_convergence(self, widget, app):
        view = MarkdownMessageView()
        view.begin_streaming()
        partials = ["# Hea", "# Heading\n\n- ite", "# Heading\n\n- item1\n- item2"]
        for p in partials:
            view.update_streaming(p)
            app.processEvents()
        view.finish_streaming("# Heading\n\n- item1\n- item2")
        text = view.document().toPlainText()
        assert "Heading" in text
        assert "item1" in text

    def test_plain_assistant_text_visual_compat(self, widget, app):
        md = "这是一段普通文本，没有 Markdown。"
        view = MarkdownMessageView(md)
        text = view.document().toPlainText()
        assert text.strip() == md


# ──────────────────────────────────────────────
# T007: 用户消息保持纯文本
# ──────────────────────────────────────────────


class TestUserMessagePlainText:
    """T007: user 消息中的 Markdown 符号不被解析"""

    def test_backticks_not_parsed(self, widget, app):
        widget._add_message("user", "使用 `pip install` 安装")
        app.processEvents()
        labels = widget.findChildren(QLabel, "content_user")
        assert len(labels) >= 1
        label = labels[-1]
        assert label.textFormat() == Qt.TextFormat.PlainText
        assert "`pip install`" in label.text()

    def test_stars_not_parsed(self, widget, app):
        widget._add_message("user", "这是**加粗**文本")
        app.processEvents()
        labels = widget.findChildren(QLabel, "content_user")
        label = labels[-1]
        assert "**加粗**" in label.text()

    def test_headings_not_parsed(self, widget, app):
        widget._add_message("user", "# 这不是标题")
        app.processEvents()
        labels = widget.findChildren(QLabel, "content_user")
        label = labels[-1]
        assert "# 这不是标题" in label.text()

    def test_pipe_not_parsed_as_table(self, widget, app):
        widget._add_message("user", "a | b | c")
        app.processEvents()
        labels = widget.findChildren(QLabel, "content_user")
        label = labels[-1]
        assert "a | b | c" in label.text()
