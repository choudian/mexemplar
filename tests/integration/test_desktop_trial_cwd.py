from pathlib import Path

from src.execution.desktop_trial_runner import run_desktop_trial


def test_desktop_trial_runs_inside_trial_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.utils.helpers.get_default_data_dir",
        lambda: tmp_path / "data",
    )
    result = run_desktop_trial(
        """
from pathlib import Path

async def execute() -> dict:
    return {"ok": True, "summary": str(Path.cwd()), "details": {}}
""",
        "trial-cwd",
    )

    assert Path(result.summary) == tmp_path / "data" / "trials" / "trial-cwd"
