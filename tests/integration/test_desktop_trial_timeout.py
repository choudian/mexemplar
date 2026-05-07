from src.execution import desktop_trial_runner


def test_desktop_trial_timeout_kills_process(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(desktop_trial_runner, "TRIAL_TIMEOUT_SECONDS", 0.1)

    result = desktop_trial_runner.run_desktop_trial(
        """
import asyncio

async def execute() -> dict:
    await asyncio.sleep(5)
    return {"ok": True, "summary": "late", "details": {}}
""",
        "trial-timeout",
    )

    assert result.timed_out is True
    assert result.ok is False
