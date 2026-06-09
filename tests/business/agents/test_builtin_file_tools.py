import json

from src.business.agents.tools import file_tools
from src.business.agents.tools.builtin_contracts import use_tool_runtime
from src.business.agents.tools.output_governance import get_tool_output_health_counters
from src.utils.agent_tool_health import reset_agent_tool_health_for_tests


def _obj(result: str) -> dict:
    return json.loads(result)


def test_read_file_returns_bounded_window_baseline_redaction_and_repeat_metadata(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "sample.txt"
    target.write_text("line1\napi_key=secret-value\nline3\nline4\n", encoding="utf-8")

    first = _obj(file_tools.read_file_handler("sample.txt", startLine=1, maxLines=2))
    second = _obj(file_tools.read_file_handler("sample.txt", startLine=1, maxLines=2))

    assert first["outcome"] == "success"
    assert first["payload"]["lineStart"] == 1
    assert first["payload"]["hasMoreAfter"] is True
    assert first["payload"]["baseline"]["baselineId"].startswith("base_")
    assert "capName" not in first["limits"]
    assert "secret-value" not in first["payload"]["content"]
    assert "api_key=***" in first["payload"]["content"]
    assert second["payload"]["repeatRead"]["seenCount"] >= 2


def test_read_file_can_continue_past_decode_byte_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "large.txt"
    target.write_text(
        "".join(f"{idx:04d}-" + ("x" * 64) + "\n" for idx in range(80)),
        encoding="utf-8",
    )

    def fake_config(getter: str, default: int, **_kwargs) -> int:
        if getter == "get_agent_tools_file_max_decode_bytes":
            return 220
        if getter == "get_agent_tools_file_max_window_chars":
            return 5000
        if getter == "get_agent_tools_file_default_max_lines":
            return 1000
        return default

    monkeypatch.setattr(file_tools, "get_config_int", fake_config)

    first = _obj(file_tools.read_file_handler("large.txt", startLine=1, maxLines=1000))
    second = _obj(
        file_tools.read_file_handler(
            "large.txt",
            startLine=first["payload"]["lineEnd"] + 1,
            maxLines=1000,
        )
    )

    assert first["payload"]["hasMoreAfter"] is True
    assert first["limits"]["nextPageToken"] != second["limits"]["nextPageToken"]
    assert second["payload"]["lineStart"] == first["payload"]["lineEnd"] + 1
    assert second["payload"]["lineEnd"] > first["payload"]["lineEnd"]
    assert second["payload"]["content"]


def test_repeat_read_metadata_is_scoped_by_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "sample.txt"
    target.write_text("line1\nline2\n", encoding="utf-8")

    with use_tool_runtime(
        session_id="session-a",
        tool_call_id="call-a1",
        tool_name="read_file",
        workspace_root=tmp_path,
    ):
        first_a = _obj(file_tools.read_file_handler("sample.txt", startLine=1, maxLines=1))
    with use_tool_runtime(
        session_id="session-a",
        tool_call_id="call-a2",
        tool_name="read_file",
        workspace_root=tmp_path,
    ):
        second_a = _obj(file_tools.read_file_handler("sample.txt", startLine=1, maxLines=1))
    with use_tool_runtime(
        session_id="session-b",
        tool_call_id="call-b1",
        tool_name="read_file",
        workspace_root=tmp_path,
    ):
        first_b = _obj(file_tools.read_file_handler("sample.txt", startLine=1, maxLines=1))

    assert "repeatRead" not in first_a["payload"]
    assert second_a["payload"]["repeatRead"]["seenCount"] == 2
    assert "repeatRead" not in first_b["payload"]


def test_read_file_refuses_binary_without_raw_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\x00raw-binary")

    result = _obj(file_tools.read_file_handler("image.png"))

    assert result["outcome"] == "unsupported"
    assert result["error"]["code"] == "unsupported_binary"
    assert "raw-binary" not in json.dumps(result, ensure_ascii=False)


def test_write_file_requires_current_baseline_for_existing_file(tmp_path, monkeypatch):
    reset_agent_tool_health_for_tests()
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "note.txt"
    target.write_text("before\n", encoding="utf-8")
    baseline = _obj(file_tools.read_file_handler("note.txt"))["payload"]["baseline"]["baselineId"]

    ok = _obj(
        file_tools.write_file_handler(
            "note.txt",
            "after\n",
            expectedBaselineId=baseline,
        )
    )
    stale = _obj(
        file_tools.write_file_handler(
            "note.txt",
            "again\n",
            expectedBaselineId=baseline,
        )
    )
    created = _obj(file_tools.write_file_handler("new.txt", "new\n"))

    assert ok["outcome"] == "success"
    assert ok["verification"]["oldBaseline"] == baseline
    assert stale["error"]["code"] == "baseline_stale"
    assert target.read_text(encoding="utf-8") == "after\n"
    assert created["payload"]["created"] is True
    assert get_tool_output_health_counters()["stale_mutation_rejections"] >= 1


def test_edit_file_rejects_missing_or_stale_baseline_and_preserves_crlf(tmp_path, monkeypatch):
    reset_agent_tool_health_for_tests()
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "script.py"
    target.write_bytes(b"one\r\ntwo\r\n")
    baseline = _obj(file_tools.read_file_handler("script.py"))["payload"]["baseline"]["baselineId"]

    missing = _obj(
        file_tools.edit_file_handler(
            "script.py",
            replacements=[{"oldText": "two", "newText": "three"}],
        )
    )
    ok = _obj(
        file_tools.edit_file_handler(
            "script.py",
            expectedBaselineId=baseline,
            replacements=[{"oldText": "two", "newText": "three"}],
        )
    )
    stale = _obj(
        file_tools.edit_file_handler(
            "script.py",
            expectedBaselineId=baseline,
            replacements=[{"oldText": "three", "newText": "four"}],
        )
    )

    assert missing["error"]["code"] == "baseline_required"
    assert ok["outcome"] == "success"
    assert ok["payload"]["preservedStyle"]["newline"] == "crlf"
    assert target.read_bytes() == b"one\r\nthree\r\n"
    assert stale["error"]["code"] == "baseline_stale"
    counters = get_tool_output_health_counters()
    assert counters["missing_baseline_rejections"] >= 1
    assert counters["stale_mutation_rejections"] >= 1


def test_apply_patch_validates_all_targets_and_baselines_before_mutation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "existing.txt"
    existing.write_text("old\n", encoding="utf-8")
    baseline = _obj(file_tools.read_file_handler("existing.txt"))["payload"]["baseline"][
        "baselineId"
    ]

    unsafe = _obj(
        file_tools.apply_patch_handler(
            [
                {"operationId": "op1", "type": "add", "path": "../escape.txt", "content": "x"},
                {
                    "operationId": "op2",
                    "type": "update",
                    "path": "existing.txt",
                    "expectedBaselineId": baseline,
                    "content": "new\n",
                },
            ]
        )
    )
    assert unsafe["outcome"] == "rejected"
    assert existing.read_text(encoding="utf-8") == "old\n"

    ok = _obj(
        file_tools.apply_patch_handler(
            [
                {"operationId": "op1", "type": "add", "path": "created.txt", "content": "x\n"},
                {
                    "operationId": "op2",
                    "type": "update",
                    "path": "existing.txt",
                    "expectedBaselineId": baseline,
                    "content": "new\n",
                },
            ]
        )
    )

    assert ok["outcome"] == "success"
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "x\n"


def test_apply_patch_replacement_failure_does_not_partially_mutate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old\n", encoding="utf-8")
    second.write_text("keep\n", encoding="utf-8")
    first_baseline = _obj(file_tools.read_file_handler("first.txt"))["payload"]["baseline"][
        "baselineId"
    ]
    second_baseline = _obj(file_tools.read_file_handler("second.txt"))["payload"]["baseline"][
        "baselineId"
    ]

    result = _obj(
        file_tools.apply_patch_handler(
            [
                {
                    "operationId": "op1",
                    "type": "update",
                    "path": "first.txt",
                    "expectedBaselineId": first_baseline,
                    "content": "new\n",
                },
                {
                    "operationId": "op2",
                    "type": "update",
                    "path": "second.txt",
                    "expectedBaselineId": second_baseline,
                    "replacements": [{"oldText": "missing", "newText": "changed"}],
                },
            ]
        )
    )

    assert result["outcome"] == "rejected"
    assert result["error"]["code"] == "edit_target_not_found"
    assert first.read_text(encoding="utf-8") == "old\n"
    assert second.read_text(encoding="utf-8") == "keep\n"
