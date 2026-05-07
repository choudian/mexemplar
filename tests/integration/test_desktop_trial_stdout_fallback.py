from src.execution.desktop_trial_runner import parse_trial_stdout


def test_desktop_trial_stdout_fallback_uses_stderr_tail():
    parsed = parse_trial_stdout(
        b"not json\n",
        b"line1\nline2\nline3\nline4\nline5\nline6",
        1,
    )

    assert parsed["ok"] is False
    assert parsed["summary"] == "line2\nline3\nline4\nline5\nline6"
    assert parsed["details"]["_fallback"] == "stdout_no_json"
    assert parsed["details"]["exit_code"] == 1
