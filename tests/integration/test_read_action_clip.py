import json
from types import SimpleNamespace

import src.data.duckdb_manager as duckdb_module
from src.business.agents.tools import desktop_tools
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository


def test_read_action_clip_returns_metadata_or_unavailable(tmp_path, monkeypatch):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    db = DuckDBManager(str(tmp_path / "clip.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.insert_desktop_recording({"recording_id": "rec-1", "start_time": 1, "monitor_index": 0})
    repo.insert_desktop_action(
        {
            "action_id": "a1",
            "recording_id": "rec-1",
            "type": "typing",
            "monitor_index": 0,
            "timestamp": 2,
            "has_clip": False,
        }
    )
    repo.insert_desktop_action(
        {
            "action_id": "a2",
            "recording_id": "rec-1",
            "type": "mouse_left",
            "monitor_index": 0,
            "timestamp": 3,
            "has_clip": True,
            "clip_path": "data/recordings/rec-1/clips/a2.mp4",
            "clip_duration_ms": 1000,
            "clip_fps": 15,
            "clip_resolution": "800x600",
        }
    )
    monkeypatch.setattr(
        desktop_tools,
        "get_unified_config",
        lambda: SimpleNamespace(get_desktop_vision_model=lambda: None),
    )
    try:
        tools = {tool.name: tool for tool in desktop_tools.create_desktop_specific_tools("rec-1")}

        assert json.loads(tools["read_action_clip"].handler("a1")) == {
            "error": "clip_unavailable",
            "action_id": "a1",
        }
        metadata = json.loads(tools["read_action_clip"].handler("a2"))
        assert metadata["path"].endswith("a2.mp4")
        assert metadata["duration_ms"] == 1000
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
