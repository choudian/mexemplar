from pathlib import Path

from src.execution.desktop_trial_runner import run_desktop_trial


def test_desktop_trial_runs_inside_trial_cwd_and_exposes_output_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.utils.helpers.get_default_data_dir",
        lambda: tmp_path / "data",
    )
    result = run_desktop_trial(
        """
import os
from pathlib import Path

async def execute() -> dict:
    Path("desktop-report.txt").write_text("desktop", encoding="utf-8")
    return {
        "ok": True,
        "summary": str(Path.cwd()),
        "details": {
            "data_dir": os.environ["MEXEMPLAR_DATA_DIR"],
            "tool_run_dir": os.environ["MEXEMPLAR_TOOL_RUN_DIR"],
            "output_dir": os.environ["MEXEMPLAR_OUTPUT_DIR"],
        },
    }
""",
        "trial-cwd",
    )

    trial_dir = tmp_path / "data" / "trials" / "trial-cwd"
    assert Path(result.summary) == trial_dir
    assert result.details == {
        "data_dir": str(tmp_path / "data"),
        "tool_run_dir": str(trial_dir),
        "output_dir": str(trial_dir),
    }
    assert (trial_dir / "desktop-report.txt").read_text(encoding="utf-8") == "desktop"
