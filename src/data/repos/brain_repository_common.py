"""Shared helpers for brain repositories."""

import json
from typing import Optional

_BRAIN_ZONES = ("hot", "persistent", "archive", "subconscious", "failure", "prediction")
_SEGMENT_UPDATE_COLUMNS = frozenset(
    {
        "all_empty_retried",
        "completed_at",
        "distilling_started_at",
        "message_id_end",
        "message_id_start",
        "retry_count",
        "sealed_at",
        "updated_at",
    }
)


class _RecordId(str):
    """String id with a snapshot of ORM attributes for legacy call sites."""

    def __new__(cls, value: str, source):
        obj = str.__new__(cls, value)
        for key, val in vars(source).items():
            if not key.startswith("_"):
                setattr(obj, key, val)
        return obj


def _append_json_list_item(raw: Optional[str], item: Optional[str], *, limit: int) -> str:
    """Append a non-empty item to a JSON string list while keeping recent examples bounded."""
    try:
        values = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        values = []
    if not isinstance(values, list):
        values = []
    if item:
        item_text = str(item).strip()
        if item_text and item_text not in values:
            values.append(item_text)
    return json.dumps(values[-limit:], ensure_ascii=False)
