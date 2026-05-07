import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.ui.widgets.desktop_sanity_check_dialog import DesktopSanityCheckDialog
from src.recording.desktop_recorder import DesktopRecorderHealth


def test_desktop_sanity_check_button_signals():
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = DesktopSanityCheckDialog(
        "rec-1", DesktopRecorderHealth(action_type_counts={"typing": 1}), enable_clip=True
    )
    seen = []
    dialog.continueAnalysisRequested.connect(seen.append)
    dialog._continue_analysis()
    app.processEvents()

    assert seen == ["rec-1"]
