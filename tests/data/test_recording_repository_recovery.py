from unittest.mock import MagicMock, patch

from src.data.recording_repository import RecordingRepository
from src.recording.browser.duckdb_recording_persister import _default_repo_factory
from src.recording.recovery import RecordingRecoveryCoordinator


def setup_function():
    RecordingRecoveryCoordinator._auto_recover_done = False


def teardown_function():
    RecordingRecoveryCoordinator._auto_recover_done = False


def test_recording_repository_init_does_not_auto_recover_by_default():
    fake_db = MagicMock()

    with patch.object(RecordingRecoveryCoordinator, "_recover_from_queues") as mock_recover:
        RecordingRepository(db_manager=fake_db)

    mock_recover.assert_not_called()


def test_startup_recovery_runs_only_once():
    fake_db = MagicMock()

    with patch.object(RecordingRecoveryCoordinator, "_recover_from_queues") as mock_recover:
        RecordingRecoveryCoordinator.ensure_startup_recovery(fake_db)
        RecordingRecoveryCoordinator.ensure_startup_recovery(fake_db)

    mock_recover.assert_called_once()


def test_default_persister_repository_factory_disables_auto_recovery():
    with patch("src.data.recording_repository.RecordingRepository") as mock_repo_cls:
        _default_repo_factory()

    mock_repo_cls.assert_called_once_with(auto_recover=False)
