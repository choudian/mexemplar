import json
from pathlib import Path

from src.business.agents.tools import search_tools
from src.business.agents.tools.builtin_permissions import (
    clear_external_confirmations_for_tests,
    mark_external_read_confirmed,
)


def _obj(result: str) -> dict:
    return json.loads(result)


def test_search_files_is_sorted_bounded_and_ignores_dependency_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("", encoding="utf-8")

    first = _obj(search_tools.search_files_handler(root=".", pattern="*.py", pageSize=1))
    second = _obj(
        search_tools.search_files_handler(
            root=".",
            pattern="*.py",
            pageSize=1,
            pageToken=first["payload"]["nextPageToken"],
        )
    )

    assert first["outcome"] == "success"
    assert first["payload"]["matches"][0]["path"] == "src/a.py"
    assert first["payload"]["hasMore"] is True
    assert second["payload"]["matches"][0]["path"] == "src/b.py"
    assert "ignored.py" not in json.dumps([first, second], ensure_ascii=False)


def test_search_content_groups_matches_redacts_and_skips_binary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "one.txt").write_text(
        "before\nneedle token=secret-value\nafter\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "bin.dat").write_bytes(b"\x00needle")

    result = _obj(
        search_tools.search_content_handler(
            root="src",
            pattern="needle",
            mode="literal",
            includeGlobs=["*.txt", "*.dat"],
            contextLines=1,
        )
    )

    assert result["outcome"] == "success"
    assert result["payload"]["matchCount"] == 1
    assert result["payload"]["files"][0]["path"] == "one.txt"
    match = result["payload"]["files"][0]["matches"][0]
    assert match["line"] == 2
    assert "secret-value" not in match["text"]
    assert result["payload"]["skippedBinary"] == 1


def test_search_content_reads_only_the_configured_file_prefix(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "large.txt").write_text("needle\n" + ("x" * 4096), encoding="utf-8")
    original_config_int = search_tools.get_config_int

    def config_int(getter, default, **kwargs):
        if getter == "get_agent_tools_search_max_bytes_per_file":
            return 32
        return original_config_int(getter, default, **kwargs)

    monkeypatch.setattr(search_tools, "get_config_int", config_int)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(AssertionError("unbounded read_bytes call")),
    )

    result = _obj(
        search_tools.search_content_handler(
            root=".",
            pattern="needle",
            includeGlobs=["*.txt"],
        )
    )

    assert result["outcome"] == "success"
    assert result["payload"]["matchCount"] == 1


def test_search_rejects_outside_workspace_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent

    result = _obj(search_tools.search_files_handler(root=str(outside), pattern="*"))

    assert result["outcome"] == "rejected"
    assert result["error"]["code"] == "path_outside_workspace"


def test_search_files_reads_confirmed_outside_workspace_root(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "found.py").write_text("", encoding="utf-8")
    monkeypatch.chdir(workspace)
    clear_external_confirmations_for_tests()
    mark_external_read_confirmed(outside, workspace_root=workspace)

    try:
        result = _obj(search_tools.search_files_handler(root=str(outside), pattern="*.py"))
    finally:
        clear_external_confirmations_for_tests()

    assert result["outcome"] == "success"
    assert result["permission"]["decision"] == "confirmed"
    assert [match["path"] for match in result["payload"]["matches"]] == ["found.py"]


def test_search_content_keeps_source_matches_unredacted(tmp_path, monkeypatch):
    """Matches inside source files are code, not secrets — same rule as read_file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "types.ts").write_text(
        "interface C {\n  password: string;\n  token: string;\n}\n", encoding="utf-8"
    )

    result = _obj(
        search_tools.search_content_handler(
            root="src",
            pattern="password",
        )
    )

    text = json.dumps(result, ensure_ascii=False)
    assert "password: string;" in text
    assert "password:***" not in text
