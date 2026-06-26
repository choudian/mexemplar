import os
import time

import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.recording.recovery import RecordingRecoveryCoordinator


def test_startup_recovery_removes_old_trial_dirs(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    old_recover = RecordingRecoveryCoordinator._auto_recover_done
    duckdb_module._duckdb_instance = None
    RecordingRecoveryCoordinator._auto_recover_done = False
    db = DuckDBManager(str(tmp_path / "data" / "mexemplar.duckdb"))
    db.initialize()
    old_trial = tmp_path / "data" / "trials" / "old"
    new_trial = tmp_path / "data" / "trials" / "new"
    old_trial.mkdir(parents=True)
    new_trial.mkdir(parents=True)
    old_time = time.time() - 8 * 24 * 60 * 60
    os.utime(old_trial, (old_time, old_time))
    try:
        RecordingRecoveryCoordinator.ensure_startup_recovery(db)

        assert not old_trial.exists()
        assert new_trial.exists()
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance
        RecordingRecoveryCoordinator._auto_recover_done = old_recover
