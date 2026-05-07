from src.execution.desktop_trial_runner import run_desktop_trial


def test_desktop_trial_writes_stdout_and_stderr_logs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = run_desktop_trial(
        """
async def execute() -> dict:
    print("hello")
    return {"ok": True, "summary": "done", "details": {}}
""",
        "trial-logs",
    )

    assert result.stdout_path.exists()
    assert result.stderr_path.exists()
    assert "hello" in result.stdout_path.read_text(encoding="utf-8")
