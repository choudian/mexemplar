from src.execution.desktop_trial_runner import run_desktop_trial


def test_desktop_trial_wrapper_packages_exceptions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_desktop_trial(
        """
async def execute() -> dict:
    raise ValueError("boom")
""",
        "trial-error",
    )

    assert result.ok is False
    assert result.exit_code == 0
    assert result.summary == "ValueError: boom"
    assert "traceback" in result.details
