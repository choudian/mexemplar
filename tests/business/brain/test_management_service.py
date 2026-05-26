from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.business.brain.management_service import BrainManagementService
from src.utils.events import clear_all, connect


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


def test_edit_entry_emits_business_owned_zone_notification():
    original = SimpleNamespace(entry_id="entry-old", zone="hot", status="active")
    replacement = SimpleNamespace(
        entry_id="entry-new",
        zone="hot",
        status="active",
        content="updated",
    )
    repo = MagicMock()
    repo.get_entry.side_effect = [original, replacement]
    repo.user_edit_entry.return_value = "entry-new"
    received = []
    connect("brain_zone_changed", lambda sender, **kwargs: received.append(kwargs), weak=False)

    result = BrainManagementService(repo=repo).edit_entry("entry-old", content="updated")

    assert result["entry_id"] == "entry-new"
    assert received[0]["operation"] == "edit"
    assert received[0]["zone"] == "hot"


def test_soft_delete_emits_business_owned_zone_notification():
    repo = MagicMock()
    repo.get_entry.return_value = SimpleNamespace(entry_id="entry-1", zone="failure")
    received = []
    connect("brain_zone_changed", lambda sender, **kwargs: received.append(kwargs), weak=False)

    BrainManagementService(repo=repo).soft_delete_entry("entry-1")

    repo.soft_delete_entry.assert_called_once_with("entry-1", feedback_operation="delete")
    assert received[0]["operation"] == "soft_delete"
    assert received[0]["zone"] == "failure"


def test_retry_segment_rejects_non_failed_segment():
    repo = MagicMock()
    repo.get_segment.return_value = SimpleNamespace(status="pending")

    with pytest.raises(ValueError, match="segment_not_failed"):
        BrainManagementService(repo=repo).retry_segment("segment-1")


def test_retry_segment_reports_failed_compare_and_swap():
    repo = MagicMock()
    repo.get_segment.return_value = SimpleNamespace(status="failed")
    repo.transition_segment.return_value = False

    with pytest.raises(RuntimeError, match="transition_failed"):
        BrainManagementService(repo=repo).retry_segment("segment-1")
