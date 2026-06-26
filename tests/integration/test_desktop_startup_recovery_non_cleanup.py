import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository
from src.recording.recovery import RecordingRecoveryCoordinator


def test_startup_recovery_does_not_cleanup_desktop_recordings_or_files(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    old_recover = RecordingRecoveryCoordinator._auto_recover_done
    duckdb_module._duckdb_instance = None
    RecordingRecoveryCoordinator._auto_recover_done = False
    db = DuckDBManager(str(tmp_path / "data" / "mexemplar.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.insert_desktop_recording({"recording_id": "rec-1", "start_time": 1, "monitor_index": 0})
    recording_dir = tmp_path / "data" / "recordings" / "rec-1"
    recording_dir.mkdir(parents=True)
    try:
        RecordingRecoveryCoordinator.ensure_startup_recovery(db)

        assert repo.get_desktop_recording_meta("rec-1") is not None
        assert recording_dir.exists()
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
        RecordingRecoveryCoordinator._auto_recover_done = old_recover
