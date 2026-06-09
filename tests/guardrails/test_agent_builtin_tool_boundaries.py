import inspect
import json
from pathlib import Path

from src.business.agents.tools import builtin_general_tools as general_tools
from src.business.agents.tools import file_tools
from src.business.agents.tools.builtin_permissions import (
    build_edit_summary,
    build_exec_summary,
    mark_external_read_confirmed,
    permission_for_path,
)
from src.business.agents.tools.output_governance import get_tool_output_health_counters
from src.utils.agent_tool_health import reset_agent_tool_health_for_tests

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _py_files(root: Path):
    return [path for path in root.rglob("*.py") if ".venv" not in path.parts]


def test_business_code_does_not_directly_manage_tool_output_sql():
    offenders = []
    for path in _py_files(PROJECT_ROOT / "src" / "business"):
        text = path.read_text(encoding="utf-8")
        if "tool_output_references" in text:
            offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_ui_desktop_api_and_tauri_do_not_manage_builtin_execution_state():
    needles = [
        "ProcessManager",
        "process_manager",
        "ToolOutputRepository",
        "tool_output_references",
        "tool_outputs/",
    ]
    roots = [
        PROJECT_ROOT / "frontend",
        PROJECT_ROOT / "src" / "desktop_api",
        PROJECT_ROOT / "src-tauri",
    ]
    offenders = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir() or path.suffix not in {".py", ".ts", ".tsx", ".rs"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(needle in text for needle in needles):
                offenders.append(path.relative_to(PROJECT_ROOT).as_posix())

    assert offenders == []


def test_outside_workspace_mutation_rejects_before_side_effect(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-agent-write.txt"
    try:
        result = json.loads(file_tools.write_file_handler(str(outside), "unsafe"))

        assert result["outcome"] == "rejected"
        assert result["error"]["code"] == "path_outside_workspace"
        assert not outside.exists()
    finally:
        outside.unlink(missing_ok=True)


def test_external_read_confirmation_is_scoped_to_session_and_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-agent-read.txt"
    outside.write_text("outside\n", encoding="utf-8")
    try:
        initial = permission_for_path(
            outside,
            operation="read",
            workspace_root=tmp_path,
            session_id="session-a",
        )
        mark_external_read_confirmed(
            outside,
            workspace_root=tmp_path,
            session_id="session-a",
        )
        confirmed = permission_for_path(
            outside,
            operation="read",
            workspace_root=tmp_path,
            session_id="session-a",
        )
        other_session = permission_for_path(
            outside,
            operation="read",
            workspace_root=tmp_path,
            session_id="session-b",
        )
    finally:
        outside.unlink(missing_ok=True)

    assert initial.decision.decision == "confirmation_required"
    assert confirmed.decision.decision == "confirmed"
    assert other_session.decision.decision == "confirmation_required"


def test_confirmation_summaries_do_not_leak_full_content_or_secrets():
    edit_summary = build_edit_summary(
        Path("demo.txt"),
        "password=super-secret-value\n" * 20,
        "token=secret-token-value\n" * 20,
    )
    exec_summary = build_exec_summary("python --version\nRemove-Item important.txt")

    assert "super-secret-value" not in edit_summary
    assert "secret-token-value" not in edit_summary
    assert "Remove-Item" not in exec_summary
    assert len(edit_summary) <= 240


def test_confirmation_fail_closed_records_health_counter(monkeypatch):
    reset_agent_tool_health_for_tests()

    def deny_with_timeout(*args, **kwargs):
        general_tools._last_confirmation_source.set(general_tools.CONFIRM_SOURCE_TOAST_TIMEOUT)
        return False

    monkeypatch.setattr(general_tools, "_ask_user_confirm", deny_with_timeout)

    result = general_tools._confirm_or_reject("exec", "Run elevated command in workspace: demo")

    assert result is not None
    assert result.error_code == "confirmation_failed_closed"
    assert get_tool_output_health_counters()["confirmation_fail_closed"] == 1


def test_no_legacy_contract_for_migrated_builtin_schemas_and_handlers():
    tools = {td.name: td for td in general_tools.BUILTIN_GENERAL_TOOLS}

    assert (
        "expectedBaselineId" in tools["write_file"].schema["function"]["parameters"]["properties"]
    )
    assert "expectedBaselineId" in tools["edit_file"].schema["function"]["parameters"]["properties"]
    assert "max_bytes" not in tools["read_file"].schema["function"]["parameters"]["properties"]
    assert '"success": True' not in inspect.getsource(general_tools.list_dir_handler)
    assert "returncode" not in inspect.getsource(general_tools.exec_handler)
    assert "bytes_written" not in inspect.getsource(general_tools.write_file_handler)
