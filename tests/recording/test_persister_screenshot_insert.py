"""Tests for DuckDBRecordingPersister screenshot integration."""

import base64
import json
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository
from src.recording.browser.duckdb_recording_persister import DuckDBRecordingPersister


def _write_screenshots_queue(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _screenshot_record(moment="before", captured_at=1734508923.5) -> dict:
    return {
        "recording_id": "rec_test",
        "capture_id": "cap_0001",
        "moment": moment,
        "source_trigger": "mouse_left",
        "input_started_at": 1734508923.4,
        "input_completed_at": None,
        "captured_at": captured_at,
        "data_b64": base64.b64encode(b"\xff\xd8fake").decode(),
        "media_type": "image/jpeg",
        "skipped_reason": None,
    }


def _action_event(timestamp: float = 1734508923.0) -> dict:
    return {
        "recording_id": "rec_test",
        "action": {
            "action_type": "click",
            "timestamp": timestamp,
            "url": "https://example.com",
            "parameters": {"x": 1, "y": 2},
        },
    }


@contextmanager
def _temporary_repository(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    old_auto_recover = RecordingRepository._auto_recover_done

    if old_instance is not None:
        try:
            old_instance.close()
        except Exception:
            pass

    duckdb_module._duckdb_instance = None
    RecordingRepository._auto_recover_done = True

    db = DuckDBManager(str(tmp_path / "persister_test.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    try:
        yield repo, db
    finally:
        try:
            db.close()
        except Exception:
            pass
        duckdb_module._duckdb_instance = old_instance
        RecordingRepository._auto_recover_done = old_auto_recover


class TestSaveScreenshots:
    def test_saves_when_screenshots_queue_exists(self, tmp_path):
        actions_path = tmp_path / "rec_test_actions.jsonl"
        actions_path.write_text("", encoding="utf-8")
        screenshots_path = tmp_path / "rec_test_screenshots.jsonl"
        _write_screenshots_queue(screenshots_path, [_screenshot_record()])

        mock_repo = MagicMock()
        mock_repo.save_recording_session.return_value = None
        mock_repo.save_actions.return_value = []
        mock_repo.insert_screenshot_batch.return_value = [1]

        persister = DuckDBRecordingPersister(repo_factory=lambda: mock_repo)
        with patch.object(
            persister,
            "convert_event_to_action_dict",
            side_effect=lambda *a, **kw: {"action_type": "click"},
        ):
            persister.save_to_duckdb(
                recording_id="rec_test",
                recording_start_time=100.0,
                action_queue_path=actions_path,
                active_recording_mode="browser",
                end_time=200.0,
            )

        mock_repo.insert_screenshot_batch.assert_called_once()
        batch = mock_repo.insert_screenshot_batch.call_args[0][0]
        assert len(batch) == 1
        assert batch[0]["moment"] == "before"

    def test_no_error_when_screenshots_queue_missing(self, tmp_path):
        actions_path = tmp_path / "rec_test_actions.jsonl"
        actions_path.write_text("", encoding="utf-8")

        mock_repo = MagicMock()
        mock_repo.save_recording_session.return_value = None
        mock_repo.save_actions.return_value = []

        persister = DuckDBRecordingPersister(repo_factory=lambda: mock_repo)
        persister.save_to_duckdb(
            recording_id="rec_test",
            recording_start_time=100.0,
            action_queue_path=actions_path,
            active_recording_mode="browser",
            end_time=200.0,
        )

        mock_repo.insert_screenshot_batch.assert_not_called()

    def test_skipped_rows_not_inserted(self, tmp_path):
        actions_path = tmp_path / "rec_test_actions.jsonl"
        actions_path.write_text("", encoding="utf-8")
        screenshots_path = tmp_path / "rec_test_screenshots.jsonl"
        _write_screenshots_queue(
            screenshots_path,
            [
                {**_screenshot_record(), "data_b64": None, "skipped_reason": "not_foreground"},
            ],
        )

        mock_repo = MagicMock()
        mock_repo.save_recording_session.return_value = None
        mock_repo.save_actions.return_value = []

        persister = DuckDBRecordingPersister(repo_factory=lambda: mock_repo)
        persister.save_to_duckdb(
            recording_id="rec_test",
            recording_start_time=100.0,
            action_queue_path=actions_path,
            active_recording_mode="browser",
            end_time=200.0,
        )

        mock_repo.insert_screenshot_batch.assert_not_called()

    def test_no_action_queue_path_means_no_screenshots(self):
        mock_repo = MagicMock()
        mock_repo.save_recording_session.return_value = None

        persister = DuckDBRecordingPersister(repo_factory=lambda: mock_repo)
        result = persister.save_to_duckdb(
            recording_id="rec_test",
            recording_start_time=100.0,
            action_queue_path=None,
            active_recording_mode="browser",
            end_time=200.0,
        )

        assert result == 0
        mock_repo.insert_screenshot_batch.assert_not_called()

    def test_transaction_commit_deletes_both_queues(self, tmp_path):
        actions_path = tmp_path / "rec_test_actions.jsonl"
        actions_path.write_text(json.dumps(_action_event()) + "\n", encoding="utf-8")
        screenshots_path = tmp_path / "rec_test_screenshots.jsonl"
        _write_screenshots_queue(screenshots_path, [_screenshot_record()])

        with _temporary_repository(tmp_path) as (repo, db):
            persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
            result = persister.save_to_duckdb(
                recording_id="rec_test",
                recording_start_time=100.0,
                action_queue_path=actions_path,
                active_recording_mode="browser",
                end_time=200.0,
            )

            assert result == 1
            assert (
                db.fetchone(
                    "SELECT count(*) FROM recording_sessions WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 1
            )
            assert (
                db.fetchone(
                    "SELECT count(*) FROM actions WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 1
            )
            assert (
                db.fetchone(
                    "SELECT count(*) FROM recording_screenshots WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 1
            )

        assert not actions_path.exists()
        assert not screenshots_path.exists()

    def test_row_level_skip_does_not_roll_back_transaction(self, tmp_path):
        actions_path = tmp_path / "rec_test_actions.jsonl"
        actions_path.write_text(json.dumps(_action_event()) + "\n", encoding="utf-8")
        screenshots_path = tmp_path / "rec_test_screenshots.jsonl"
        screenshots_path.write_text(
            "{bad json}\n" + json.dumps(_screenshot_record()) + "\n",
            encoding="utf-8",
        )

        with _temporary_repository(tmp_path) as (repo, db):
            persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
            result = persister.save_to_duckdb(
                recording_id="rec_test",
                recording_start_time=100.0,
                action_queue_path=actions_path,
                active_recording_mode="browser",
                end_time=200.0,
            )

            assert result == 1
            assert (
                db.fetchone(
                    "SELECT count(*) FROM actions WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 1
            )
            assert (
                db.fetchone(
                    "SELECT count(*) FROM recording_screenshots WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 1
            )

        assert not actions_path.exists()
        assert not screenshots_path.exists()

    def test_screenshots_insert_failure_rolls_back_actions_and_preserves_queues(self, tmp_path):
        actions_path = tmp_path / "rec_test_actions.jsonl"
        actions_path.write_text(json.dumps(_action_event()) + "\n", encoding="utf-8")
        screenshots_path = tmp_path / "rec_test_screenshots.jsonl"
        _write_screenshots_queue(screenshots_path, [_screenshot_record()])

        with _temporary_repository(tmp_path) as (repo, db):
            persister = DuckDBRecordingPersister(repo_factory=lambda: repo)

            with patch.object(repo, "insert_screenshot_batch", side_effect=RuntimeError("boom")):
                with pytest.raises(RuntimeError, match="boom"):
                    persister.save_to_duckdb(
                        recording_id="rec_test",
                        recording_start_time=100.0,
                        action_queue_path=actions_path,
                        active_recording_mode="browser",
                        end_time=200.0,
                    )

            assert (
                db.fetchone(
                    "SELECT count(*) FROM recording_sessions WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 0
            )
            assert (
                db.fetchone(
                    "SELECT count(*) FROM actions WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 0
            )
            assert (
                db.fetchone(
                    "SELECT count(*) FROM recording_screenshots WHERE recording_id = ?",
                    ("rec_test",),
                )[0]
                == 0
            )

        assert actions_path.exists()
        assert screenshots_path.exists()
