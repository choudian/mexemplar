"""Tests for screenshots queue lifecycle management.

Scenarios from the design doc §3.5:
- save_to_duckdb success: both queue files deleted
- save_to_duckdb failure: both queue files retained
- Recovery startup: orphan screenshots queue files are cleaned up
"""

import json
from unittest.mock import MagicMock

import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository
from src.data.recording_recovery import RecordingRecovery


class TestScreenshotsQueueLifecycle:
    def test_orphan_screenshots_queue_deleted_on_startup(self, tmp_path):
        """Orphan *_screenshots.jsonl is deleted with a warning on startup scan."""
        queues_dir = tmp_path / "queues"
        queues_dir.mkdir()
        orphan = queues_dir / "rec_orphan_screenshots.jsonl"
        orphan.write_text('{"moment": "before"}\n', encoding="utf-8")

        mock_db = MagicMock()
        mock_db.db_path = str(tmp_path / "fake.duckdb")
        # No WAL file
        recovery = RecordingRecovery(queues_dir=queues_dir, db_manager=mock_db)
        recovery._cleanup_orphan_screenshots()

        assert not orphan.exists()

    def test_orphan_screenshots_cleanup_does_not_touch_actions(self, tmp_path):
        """_cleanup_orphan_screenshots should not touch *_actions.jsonl files."""
        queues_dir = tmp_path / "queues"
        queues_dir.mkdir()
        actions_file = queues_dir / "rec_001_actions.jsonl"
        actions_file.write_text('{"action": {}}\n', encoding="utf-8")
        screenshots_file = queues_dir / "rec_001_screenshots.jsonl"
        screenshots_file.write_text('{"moment": "before"}\n', encoding="utf-8")

        mock_db = MagicMock()
        mock_db.db_path = str(tmp_path / "fake.duckdb")

        recovery = RecordingRecovery(queues_dir=queues_dir, db_manager=mock_db)
        recovery._cleanup_orphan_screenshots()

        # Screenshots deleted, actions preserved
        assert not screenshots_file.exists()
        assert actions_file.exists()

    def test_cleanup_noop_when_directory_missing(self, tmp_path):
        """Graceful no-op when queues dir doesn't exist."""
        missing = tmp_path / "nonexistent"
        mock_db = MagicMock()
        mock_db.db_path = str(tmp_path / "fake.duckdb")

        recovery = RecordingRecovery(queues_dir=missing, db_manager=mock_db)
        # Should not raise
        recovery._cleanup_orphan_screenshots()

    def test_cleanup_called_in_auto_recover_no_wal(self, tmp_path):
        """auto_recover_on_startup calls _cleanup_orphan_screenshots even without WAL."""
        queues_dir = tmp_path / "queues"
        queues_dir.mkdir()
        orphan = queues_dir / "rec_test_screenshots.jsonl"
        orphan.write_text('{"moment": "before"}\n', encoding="utf-8")

        mock_db = MagicMock()
        mock_db.db_path = str(tmp_path / "fake.duckdb")

        recovery = RecordingRecovery(queues_dir=queues_dir, db_manager=mock_db)
        recovery.auto_recover_on_startup()

        assert not orphan.exists()

    def test_cleanup_called_in_auto_recover_with_wal(self, tmp_path):
        """auto_recover_on_startup calls _cleanup_orphan_screenshots after WAL recovery too."""
        queues_dir = tmp_path / "queues"
        queues_dir.mkdir()
        orphan = queues_dir / "rec_test_screenshots.jsonl"
        orphan.write_text('{"moment": "before"}\n', encoding="utf-8")

        db_path = tmp_path / "test.duckdb"
        wal_path = tmp_path / "test.duckdb.wal"
        wal_path.write_text("fake wal", encoding="utf-8")

        mock_db = MagicMock()
        mock_db.db_path = str(db_path)
        mock_db.connect.return_value = None

        recovery = RecordingRecovery(queues_dir=queues_dir, db_manager=mock_db)
        recovery.auto_recover_on_startup()

        assert not orphan.exists()

    def test_startup_scan_recovers_actions_even_without_wal(self, tmp_path):
        queues_dir = tmp_path / "queues"
        queues_dir.mkdir()
        actions_file = queues_dir / "rec_test_actions.jsonl"
        actions_file.write_text(
            json.dumps(
                {
                    "recording_id": "rec_test",
                    "action": {
                        "action_type": "click",
                        "timestamp": 1734508923.0,
                        "parameters": {"x": 1, "y": 2},
                        "url": "https://example.com",
                        "recording_mode": "browser",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        screenshots_file = queues_dir / "rec_test_screenshots.jsonl"
        screenshots_file.write_text('{"moment": "before"}\n', encoding="utf-8")

        old_instance = duckdb_module._duckdb_instance
        old_auto_recover = RecordingRepository._auto_recover_done
        if old_instance is not None:
            try:
                old_instance.close()
            except Exception:
                pass
        duckdb_module._duckdb_instance = None
        RecordingRepository._auto_recover_done = True

        try:
            db = DuckDBManager(str(tmp_path / "recovery_test.duckdb"))
            db.initialize()
            recovery = RecordingRecovery(queues_dir=queues_dir, db_manager=db)

            recovered = recovery.auto_recover_on_startup()

            assert recovered is True
            assert db.fetchone(
                "SELECT count(*) FROM actions WHERE recording_id = ?",
                ("rec_test",),
            )[0] == 1
            assert not screenshots_file.exists()
            assert actions_file.exists()
        finally:
            try:
                db.close()
            except Exception:
                pass
            duckdb_module._duckdb_instance = old_instance
            RecordingRepository._auto_recover_done = old_auto_recover
