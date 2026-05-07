import json
from types import SimpleNamespace

import src.data.duckdb_manager as duckdb_module
from src.business.agents.tools import desktop_tools
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository


def _seed(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    db = DuckDBManager(str(tmp_path / "desktop-tools.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.insert_desktop_recording({"recording_id": "rec-1", "start_time": 1, "monitor_index": 0})
    repo.insert_desktop_action(
        {
            "action_id": "a1",
            "recording_id": "rec-1",
            "type": "typing",
            "monitor_index": 0,
            "text_content": "hello",
            "timestamp": 2,
        }
    )
    return db, old_instance


def test_list_desktop_actions_validation_and_paging(tmp_path, monkeypatch):
    db, old_instance = _seed(tmp_path)
    monkeypatch.setattr(
        desktop_tools,
        "get_unified_config",
        lambda: SimpleNamespace(get_desktop_vision_model=lambda: None),
    )
    try:
        tools = {tool.name: tool for tool in desktop_tools.create_desktop_specific_tools("rec-1")}

        result = json.loads(tools["list_desktop_actions"].handler(action_types=["typing"], limit=1))
        assert result["count"] == 1
        assert result["actions"][0]["action_id"] == "a1"
        assert json.loads(tools["list_desktop_actions"].handler(action_types=["bad"])) == {
            "error": "invalid_action_type",
            "value": "bad",
        }
        assert json.loads(tools["list_desktop_actions"].handler(limit=501))["error"] == "limit_too_large"
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
