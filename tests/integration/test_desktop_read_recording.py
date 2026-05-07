from collections import Counter
import json

import src.data.duckdb_manager as duckdb_module
from src.business.agents.tools.recording_data_tools import create_recording_tools
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository


def test_desktop_recording_meta_and_action_summary(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    db = DuckDBManager(str(tmp_path / "summary.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.insert_desktop_recording({"recording_id": "rec-1", "start_time": 1, "monitor_index": 0})
    for index in range(12):
        repo.insert_desktop_action(
            {
                "action_id": f"a{index}",
                "recording_id": "rec-1",
                "type": "typing" if index % 2 else "mouse_left",
                "monitor_index": 0,
                "timestamp": index + 2,
            }
        )
    try:
        actions = repo.list_desktop_actions("rec-1", limit=500)
        counts = Counter(action["type"] for action in actions)
        read_recording = {tool.name: tool for tool in create_recording_tools("rec-1")}[
            "read_recording"
        ]
        summary = read_recording.handler()
        payload = json.loads(summary)

        assert repo.get_desktop_recording_meta("rec-1")["recording_mode"] == "desktop"
        assert len(actions[:5] + actions[-5:]) == 10
        assert counts["typing"] == 6
        assert payload["recording"]["recording_id"] == "rec-1"
        assert payload["summary"]["action_count"] == 12
        assert payload["summary"]["type_counts"] == {"mouse_left": 6, "typing": 6}
        assert len(payload["summary"]["actions_preview"]) == 10
        assert "a5" not in {
            action["action_id"] for action in payload["summary"]["actions_preview"]
        }
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
