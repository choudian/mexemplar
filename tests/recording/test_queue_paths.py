"""Tests for src/recording/queue_paths.py"""

from unittest.mock import patch

from src.recording.queue_paths import (
    get_recording_actions_queue_path,
    get_recording_queue_dir,
    get_recording_screenshots_queue_path,
)


class TestGetRecordingQueueDir:
    def test_returns_data_queues_subdir(self, tmp_path):
        fake_data_dir = tmp_path / "data"
        with patch("src.data.queue_paths.get_default_data_dir", return_value=fake_data_dir):
            result = get_recording_queue_dir()

        assert result == fake_data_dir / "queues"

    def test_creates_directory_if_missing(self, tmp_path):
        fake_data_dir = tmp_path / "data"
        assert not fake_data_dir.exists()
        with patch("src.data.queue_paths.get_default_data_dir", return_value=fake_data_dir):
            result = get_recording_queue_dir()

        assert result.is_dir()

    def test_exemplar_data_dir_env_respected(self, tmp_path):
        custom_dir = tmp_path / "custom_location"
        with patch("src.data.queue_paths.get_default_data_dir", return_value=custom_dir):
            result = get_recording_queue_dir()

        assert str(result).startswith(str(custom_dir))


class TestQueueFilePaths:
    def test_actions_queue_path_format(self, tmp_path):
        with patch(
            "src.data.queue_paths.get_default_data_dir", return_value=tmp_path / "data"
        ):
            path = get_recording_actions_queue_path("rec_001")

        assert path.name == "rec_001_actions.jsonl"
        assert path.parent.name == "queues"

    def test_screenshots_queue_path_format(self, tmp_path):
        with patch(
            "src.data.queue_paths.get_default_data_dir", return_value=tmp_path / "data"
        ):
            path = get_recording_screenshots_queue_path("rec_001")

        assert path.name == "rec_001_screenshots.jsonl"
        assert path.parent.name == "queues"

    def test_both_paths_share_same_directory(self, tmp_path):
        with patch(
            "src.data.queue_paths.get_default_data_dir", return_value=tmp_path / "data"
        ):
            actions = get_recording_actions_queue_path("rec_abc")
            screenshots = get_recording_screenshots_queue_path("rec_abc")

        assert actions.parent == screenshots.parent
