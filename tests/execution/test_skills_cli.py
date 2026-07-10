from __future__ import annotations

import subprocess

import pytest

from src.execution.skills_cli import (
    SkillsCliUnavailableError,
    search_skills_with_cli,
)


def test_search_skills_with_cli_parses_find_output(monkeypatch):
    monkeypatch.setattr("src.execution.skills_cli._find_npx", lambda: "npx")

    def runner(args, *, timeout, env):
        assert args == ["npx", "--yes", "skills", "find", "typescript"]
        assert env["NO_COLOR"] == "1"
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=(
                "Install with npx skills add <owner/repo@skill>\n\n"
                "wshobson/agents@typescript-advanced-types 51.9K installs\n"
                "└ https://skills.sh/wshobson/agents/typescript-advanced-types\n"
            ),
            stderr="",
        )

    results = search_skills_with_cli("typescript", runner=runner)

    assert len(results) == 1
    assert results[0].source_ref == "wshobson/agents@typescript-advanced-types"
    assert results[0].installs == 51_900
    assert results[0].source_url == ("https://skills.sh/wshobson/agents/typescript-advanced-types")


def test_search_skills_with_cli_never_runs_empty_query(monkeypatch):
    monkeypatch.setattr("src.execution.skills_cli._find_npx", lambda: "npx")
    calls = []

    results = search_skills_with_cli("", runner=lambda *args, **kwargs: calls.append(args))

    assert results == []
    assert calls == []


def test_search_skills_with_cli_reports_missing_npx(monkeypatch):
    monkeypatch.setattr("src.execution.skills_cli.shutil.which", lambda _name: None)

    with pytest.raises(SkillsCliUnavailableError) as exc_info:
        search_skills_with_cli("react")

    assert "npx" in str(exc_info.value)
