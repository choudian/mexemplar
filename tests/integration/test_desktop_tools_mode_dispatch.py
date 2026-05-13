import json
from types import SimpleNamespace

import src.data.duckdb_manager as duckdb_module
import pytest
from src.business.agents.config import AgentType
from src.business.agents.tools.recording_data_tools import create_recording_tools
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository


def test_recording_tools_dispatch_to_desktop_tables(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    db = DuckDBManager(str(tmp_path / "mode.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.insert_desktop_recording({"recording_id": "rec-d", "start_time": 1, "monitor_index": 0})
    repo.insert_desktop_action(
        {
            "action_id": "act-d",
            "recording_id": "rec-d",
            "type": "typing",
            "monitor_index": 0,
            "text_content": "x" * 1100,
            "timestamp": 2,
        }
    )
    try:
        tools = {tool.name: tool for tool in create_recording_tools("rec-d")}
        details = json.loads(tools["describe_data"].handler())
        assert [table["name"] for table in details["tables"]] == [
            "desktop_recordings",
            "desktop_actions",
        ]

        blocked = json.loads(tools["query_data"].handler("SELECT * FROM actions"))
        assert blocked == {
            "error": "table_not_in_mode",
            "table": "actions",
            "mode": "desktop",
        }
        execute_blocked = json.loads(
            tools["execute_code"].handler(
                "rows = conn.execute('SELECT * FROM actions').fetchall()\nprint(rows)"
            )
        )
        assert execute_blocked == {
            "error": "table_not_in_mode",
            "table": "actions",
            "mode": "desktop",
        }

        rows = json.loads(
            tools["query_data"].handler(
                "SELECT action_id, text_content FROM desktop_actions WHERE recording_id = 'rec-d'"
            )
        )["rows"]
        placeholder = rows[0]["text_content"]
        chunk = json.loads(
            tools["read_field_chunk"].handler(placeholder["locator"], "text_content", 0, 10)
        )
        assert chunk["content"] == "x" * 10

        browser_locator = {"table": "actions", "id_field": "action_id", "id_value": 1}
        cross_mode = json.loads(
            tools["read_field_chunk"].handler(browser_locator, "dom_tree_snapshot", 0, 10)
        )
        assert cross_mode["error"]["code"] == "table_not_in_mode"
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance


def test_browser_execute_code_cannot_read_desktop_tables(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    db = DuckDBManager(str(tmp_path / "browser-mode.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.save_recording_session({"recording_id": "rec-b", "start_time": 1})
    repo.insert_desktop_recording({"recording_id": "rec-d", "start_time": 1, "monitor_index": 0})
    try:
        tools = {tool.name: tool for tool in create_recording_tools("rec-b")}

        execute_blocked = json.loads(
            tools["execute_code"].handler(
                "rows = conn.execute('SELECT * FROM desktop_actions').fetchall()\nprint(rows)"
            )
        )

        assert execute_blocked == {
            "error": "table_not_in_mode",
            "table": "desktop_actions",
            "mode": "browser",
        }

        desktop_locator = {"table": "desktop_actions", "id_field": "action_id", "id_value": "a1"}
        chunk_blocked = json.loads(
            tools["read_field_chunk"].handler(desktop_locator, "text_content", 0, 10)
        )
        assert chunk_blocked["error"]["code"] == "table_not_in_mode"
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance


def test_orchestrator_build_tools_uses_real_desktop_recording_mode(tmp_path, mock_config):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    db = DuckDBManager(str(tmp_path / "orchestrator-mode.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.insert_desktop_recording({"recording_id": "rec-d", "start_time": 1, "monitor_index": 0})
    try:
        orchestrator = AgentOrchestrator(
            llm_client=SimpleNamespace(),
            config=mock_config,
            llm_reviewer=SimpleNamespace(),
        )

        names = [
            tool.name
            for tool in orchestrator._build_tools(AgentType.PROGRAMMER, workflow_id="rec-d")
        ]

        assert "list_desktop_actions" in names
        assert "read_action_clip" in names
        assert "analyze_image" not in names
        assert "submit_code" in names
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance


def test_orchestrator_recording_mode_errors_do_not_fallback_to_browser(monkeypatch):
    orchestrator = AgentOrchestrator.__new__(AgentOrchestrator)
    orchestrator._mode_cache = {}
    orchestrator._MAX_DYNAMIC_MANAGERS = 20
    orchestrator._desktop_syntax_state = {}

    def _boom(self, recording_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(RecordingRepository, "get_recording_mode", _boom)

    with pytest.raises(RuntimeError, match="无法读取录制模式"):
        orchestrator._recording_mode("rec-broken")
