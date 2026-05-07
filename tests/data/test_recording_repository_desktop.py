import json

import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository


def _fresh_repo(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    old_recover = RecordingRepository._auto_recover_done
    old_desktop_ensured = RecordingRepository._desktop_tables_ensured
    duckdb_module._duckdb_instance = None
    RecordingRepository._auto_recover_done = True
    RecordingRepository._desktop_tables_ensured = False
    db = DuckDBManager(str(tmp_path / "desktop.duckdb"))
    db.initialize()
    repo = RecordingRepository(db_manager=db)
    return repo, db, old_instance, old_recover, old_desktop_ensured


def test_desktop_schema_insert_query_and_mode_lookup(tmp_path):
    repo, db, old_instance, old_recover, old_desktop_ensured = _fresh_repo(tmp_path)
    try:
        repo.ensure_desktop_tables()
        columns = {row[0] for row in db.fetchall("DESCRIBE desktop_actions")}
        assert "monitor_index" in columns

        indexes = [row[0] for row in db.fetchall("SELECT index_name FROM duckdb_indexes()")]
        assert "desktop_actions_recording_timestamp_idx" in indexes
        assert "desktop_actions_recording_type_idx" in indexes

        repo.insert_desktop_recording(
            {"recording_id": "rec-1", "start_time": 1, "monitor_index": 2}
        )
        repo.insert_desktop_action(
            {
                "action_id": "act-1",
                "recording_id": "rec-1",
                "type": "typing",
                "monitor_index": 2,
                "text_content": "hello",
                "uia_summary": {"name": "editor"},
                "timestamp": 2,
            }
        )

        assert repo.get_recording_mode("rec-1") == "desktop"
        actions = repo.list_desktop_actions("rec-1", action_types=["typing"])
        assert actions[0]["action_id"] == "act-1"
        assert actions[0]["uia_summary"] == {"name": "editor"}

        repo.update_desktop_action_frames(
            "act-1",
            {
                "frame_count": 3,
                "has_clip": True,
                "clip_path": "clips/act-1.mp4",
                "clip_duration_ms": 200,
                "clip_fps": 15,
                "clip_resolution": "[10, 10]",
            },
        )
        actions = repo.list_desktop_actions("rec-1", action_types=["typing"])
        assert actions[0]["frame_count"] == 3
        assert actions[0]["has_clip"] is True
        assert actions[0]["clip_path"] == "clips/act-1.mp4"

        repo.update_desktop_recording_health_stats("rec-1", {"action_type_counts": {"typing": 1}})
        meta = repo.get_desktop_recording_meta("rec-1")
        assert meta["health_stats"] == {"action_type_counts": {"typing": 1}}
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
        RecordingRepository._auto_recover_done = old_recover
        RecordingRepository._desktop_tables_ensured = old_desktop_ensured


def test_browser_default_mode_is_not_desktop(tmp_path):
    repo, db, old_instance, old_recover, old_desktop_ensured = _fresh_repo(tmp_path)
    try:
        repo.save_recording_session({"recording_id": "browser-rec", "start_time": 1})
        assert repo.get_recording_mode("browser-rec") == "browser"
        row = db.fetchone(
            "SELECT metadata FROM recording_sessions WHERE recording_id = ?", ("browser-rec",)
        )
        assert json.loads(row[0]) == {}
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
        RecordingRepository._auto_recover_done = old_recover
        RecordingRepository._desktop_tables_ensured = old_desktop_ensured


def test_extension_triggered_mode_uses_browser_data_path(tmp_path):
    repo, db, old_instance, old_recover, old_desktop_ensured = _fresh_repo(tmp_path)
    try:
        repo.save_recording_session(
            {
                "recording_id": "ext-rec",
                "start_time": 1,
                "recording_mode": "extension_triggered",
            }
        )

        assert repo.get_recording_mode("ext-rec") == "browser"
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
        RecordingRepository._auto_recover_done = old_recover
        RecordingRepository._desktop_tables_ensured = old_desktop_ensured
