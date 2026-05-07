import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel

from src.execution.desktop_trial_models import TrialResult
from src.ui.widgets.desktop_trial_dialogs import DesktopTrialPreviewDialog, trial_toast_payload


def test_desktop_trial_preview_dialog_shows_high_risk_labels(tmp_path):
    app = QApplication.instance() or QApplication(sys.argv)
    dialog = DesktopTrialPreviewDialog("import subprocess\n")
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    app.processEvents()

    assert any("subprocess" in text for text in labels)


def test_desktop_trial_toast_payloads(tmp_path):
    base = dict(
        details={},
        exit_code=0,
        stdout_path=tmp_path / "stdout.log",
        stderr_path=tmp_path / "stderr.log",
        trial_id="t",
    )

    assert trial_toast_payload(TrialResult(ok=True, summary="ok", timed_out=False, **base))[0] == "试用成功"
    assert trial_toast_payload(TrialResult(ok=False, summary="bad", timed_out=False, **base))[0] == "试用失败"
    assert trial_toast_payload(TrialResult(ok=False, summary="slow", timed_out=True, **base))[0] == "试用超时"
