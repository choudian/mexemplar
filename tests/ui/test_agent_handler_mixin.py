import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget

from src.ui.mixins.agent_handler_mixin import AgentHandlerMixin
from src.ui.page_ids import INTENT_CONFIRMATION, SKILLS
from src.utils.logger import get_logger


@pytest.fixture(scope="module")
def app():
    try:
        qt_app = QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")
    return qt_app


class _DummySkillsPage:
    def __init__(self):
        self.refresh_calls = 0
        self.refresh_failures_calls = 0

    def refresh(self):
        self.refresh_calls += 1

    def refresh_failures(self):
        self.refresh_failures_calls += 1


class _DummyMainContent:
    def __init__(self, skills_page):
        self.skills_page = skills_page
        self.switched_pages = []

    def get_page(self, page_name):
        if page_name == SKILLS:
            return self.skills_page
        return None

    def switch_page(self, page_name):
        self.switched_pages.append(page_name)


class _DummyWindow(QWidget, AgentHandlerMixin):
    def __init__(self, skills_page):
        super().__init__()
        self.logger = get_logger(__name__)
        self.main_content = _DummyMainContent(skills_page)
        self.toasts = []

    def _show_toast(self, message, **kwargs):
        self.toasts.append((message, kwargs))

    def _switch_to_pending_tools(self):
        self.main_content.switch_page(SKILLS)


def test_failure_resolved_triggers_full_skills_refresh(app):
    page = _DummySkillsPage()
    window = _DummyWindow(page)

    window._on_failure_updated("wf-1", "programmer", "resolved", False)
    QTest.qWait(250)

    assert page.refresh_calls == 1
    assert page.refresh_failures_calls == 0

    window.deleteLater()


def test_failure_update_only_refreshes_failures(app):
    page = _DummySkillsPage()
    window = _DummyWindow(page)

    window._on_failure_updated("wf-1", "programmer", "updated", False)
    QTest.qWait(250)

    assert page.refresh_calls == 0
    assert page.refresh_failures_calls == 1

    window.deleteLater()


def test_tool_saved_from_triage_triggers_full_refresh(app):
    page = _DummySkillsPage()
    window = _DummyWindow(page)

    window._on_tool_saved("wf-1", "tool-1", from_triage=True)
    QTest.qWait(250)

    assert page.refresh_calls == 1
    assert page.refresh_failures_calls == 0
    assert window.main_content.switched_pages == [INTENT_CONFIRMATION]

    window.deleteLater()

