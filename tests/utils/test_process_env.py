"""Configured environment variables reach the process and its children.

The sidecar is started by the desktop shell, so it inherits nothing a terminal
profile would set — and everything downstream inherits that same bare
environment. When the proxy was missing, Claude Code returned a bare 403 that
read like an authentication failure; the cause took several rounds to find.
"""

from __future__ import annotations

import logging
import os

from src.utils.process_env import apply_process_env


def test_nothing_configured_changes_nothing():
    assert apply_process_env(None) == []
    assert apply_process_env({}) == []


def test_values_land_in_the_process_environment(monkeypatch):
    monkeypatch.delenv("EXEMPLAR_ENV_TEST_A", raising=False)

    applied = apply_process_env({"EXEMPLAR_ENV_TEST_A": "value-a"})

    assert applied == ["EXEMPLAR_ENV_TEST_A"]
    assert os.environ["EXEMPLAR_ENV_TEST_A"] == "value-a"


def test_configured_values_win_over_inherited_ones(monkeypatch):
    # Editing the config must take effect; the inherited environment is
    # whatever the desktop shell happened to pass through.
    monkeypatch.setenv("EXEMPLAR_ENV_TEST_B", "inherited")

    apply_process_env({"EXEMPLAR_ENV_TEST_B": "configured"})

    assert os.environ["EXEMPLAR_ENV_TEST_B"] == "configured"


def test_blank_values_do_not_shadow_an_inherited_one(monkeypatch):
    # Writing "" would hide a value the process could otherwise use.
    monkeypatch.setenv("EXEMPLAR_ENV_TEST_C", "inherited")

    applied = apply_process_env({"EXEMPLAR_ENV_TEST_C": "   "})

    assert applied == []
    assert os.environ["EXEMPLAR_ENV_TEST_C"] == "inherited"


def test_blank_names_are_skipped(monkeypatch):
    # An empty name makes Popen fail outright on some platforms.
    assert apply_process_env({"": "x", "   ": "y"}) == []


def test_surrounding_whitespace_is_trimmed(monkeypatch):
    monkeypatch.delenv("EXEMPLAR_ENV_TEST_D", raising=False)

    apply_process_env({"  EXEMPLAR_ENV_TEST_D  ": "  spaced  "})

    assert os.environ["EXEMPLAR_ENV_TEST_D"] == "spaced"


def test_secret_values_are_never_logged(monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)

    with caplog.at_level(logging.INFO):
        apply_process_env(
            {
                "ANTHROPIC_AUTH_TOKEN": "sk-super-secret",
                # A proxy URL can carry credentials in its userinfo.
                "https_proxy": "http://user:pw@127.0.0.1:33210",
                "ANTHROPIC_BASE_URL": "https://api.example.com",
            }
        )

    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "sk-super-secret" not in logged
    assert "user:pw" not in logged
    # Non-sensitive names stay readable so the log is still useful.
    assert "ANTHROPIC_BASE_URL" in logged
    assert "ANTHROPIC_AUTH_TOKEN=<hidden>" in logged


def test_children_inherit_what_was_applied(monkeypatch):
    # The whole point: subprocesses pick this up without any per-call plumbing.
    import subprocess
    import sys

    monkeypatch.delenv("EXEMPLAR_ENV_TEST_CHILD", raising=False)
    apply_process_env({"EXEMPLAR_ENV_TEST_CHILD": "seen-by-child"})

    result = subprocess.run(
        [sys.executable, "-c", "import os; print(os.environ.get('EXEMPLAR_ENV_TEST_CHILD'))"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.stdout.strip() == "seen-by-child"
