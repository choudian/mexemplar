"""Unified queue directory and file path helpers for the recording system."""

import logging
from pathlib import Path
from typing import Optional

from src.utils.helpers import get_default_data_dir

_logger = logging.getLogger(__name__)


def get_recording_queue_dir() -> Path:
    """Return the queue directory path, creating it if it doesn't exist."""
    queue_dir = get_default_data_dir() / "queues"
    queue_dir.mkdir(parents=True, exist_ok=True)
    return queue_dir


def get_recording_actions_queue_path(recording_id: str) -> Path:
    """Return the actions queue file path for a given recording_id."""
    return get_recording_queue_dir() / f"{recording_id}_actions.jsonl"


def get_recording_screenshots_queue_path(recording_id: str) -> Path:
    """Return the screenshots queue file path for a given recording_id."""
    return get_recording_queue_dir() / f"{recording_id}_screenshots.jsonl"


def delete_queue_file(queue_path: Optional[Path]) -> None:
    """Safely delete a queue file, ignoring missing or inaccessible files."""
    if not queue_path or not queue_path.exists():
        return
    try:
        queue_path.unlink()
    except Exception as exc:
        _logger.warning(f"删除队列文件失败 {queue_path}: {exc}")
