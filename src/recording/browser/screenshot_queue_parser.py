"""
Parse JSONL screenshot queue files and batch-insert into DuckDB.

Screenshots are captured during browser recording and written as JSONL lines.
Each line contains metadata plus either a base64-encoded image (``data_b64``)
or a ``skipped_reason`` explaining why the capture was skipped.

After recording stops, the persister reads these queue files via
:func:`iter_screenshots_queue` and persists valid rows through
:func:`batch_insert_screenshots`.
"""


import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Literal, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScreenshotRow:
    """A single screenshot record parsed from the JSONL queue."""

    recording_id: str
    moment: Literal["before", "after"]
    timestamp: float  # epoch seconds float (captured_at)
    capture_id: Optional[str] = None
    source_trigger: Optional[str] = None  # bypass metadata
    input_started_at: Optional[float] = None
    input_completed_at: Optional[float] = None
    media_type: Optional[str] = None
    data: Optional[bytes] = None  # None means skipped
    skipped_reason: Optional[str] = None


def iter_screenshots_queue(path: Path) -> Iterator[ScreenshotRow]:
    """Yield :class:`ScreenshotRow` objects from a JSONL queue file.

    The file is read line-by-line to keep memory usage low.  Malformed lines
    are skipped with a warning.

    Parameters
    ----------
    path:
        Path to the JSONL file produced by the screenshot capture subsystem.

    Yields
    ------
    ScreenshotRow
        One per valid line in the queue file.
    """
    with open(path, "r", encoding="utf-8") as fh:
        for line_num, raw_line in enumerate(fh, 1):
            stripped = raw_line.strip()
            if not stripped:
                continue

            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning("截图队列第 %d 行 JSON 解析失败: %s", line_num, exc)
                continue

            try:
                recording_id: str = obj["recording_id"]
                moment: Literal["before", "after"] = obj["moment"]
                timestamp: float = obj["captured_at"]
            except KeyError as exc:
                logger.warning("截图队列第 %d 行缺少必要字段 %s，已跳过", line_num, exc)
                continue

            capture_id: Optional[str] = obj.get("capture_id")
            source_trigger: Optional[str] = obj.get("source_trigger")
            input_started_at: Optional[float] = obj.get("input_started_at")
            input_completed_at: Optional[float] = obj.get("input_completed_at")
            media_type: Optional[str] = obj.get("media_type")
            skipped_reason: Optional[str] = obj.get("skipped_reason")

            data_b64: Optional[str] = obj.get("data_b64")
            if data_b64 is not None:
                try:
                    data: Optional[bytes] = base64.b64decode(data_b64)
                except Exception as exc:
                    logger.warning(
                        "截图队列第 %d 行 base64 解码失败: %s，已跳过",
                        line_num,
                        exc,
                    )
                    continue
            else:
                data = None

            yield ScreenshotRow(
                recording_id=recording_id,
                moment=moment,
                timestamp=timestamp,
                capture_id=capture_id,
                source_trigger=source_trigger,
                input_started_at=input_started_at,
                input_completed_at=input_completed_at,
                media_type=media_type,
                data=data,
                skipped_reason=skipped_reason,
            )


def _row_to_dict(row: ScreenshotRow) -> dict:
    """Convert a :class:`ScreenshotRow` to a dict ready for DB insertion.

    Timestamp fields stay as epoch floats here; the repository is responsible
    for normalizing them to DuckDB's naive UTC datetime convention.
    """
    return {
        "recording_id": row.recording_id,
        "moment": row.moment,
        "timestamp": row.timestamp,
        "capture_id": row.capture_id,
        "source_trigger": row.source_trigger,
        "input_started_at": row.input_started_at,
        "input_completed_at": row.input_completed_at,
        "media_type": row.media_type,
        "data": row.data,
    }


def batch_insert_screenshots(
    repository,
    rows: Iterable[ScreenshotRow],
    *,
    batch_size: int = 100,
) -> int:
    """Filter valid rows and insert them in batches.

    Rows whose ``data`` field is ``None`` (skipped captures) are silently
    excluded.  The remaining rows are grouped into batches of *batch_size* and
    passed to ``repository.insert_screenshot_batch(batch)``.

    Parameters
    ----------
    repository:
        A recording repository exposing ``insert_screenshot_batch``.
    rows:
        An iterable of :class:`ScreenshotRow` objects, typically produced by
        :func:`iter_screenshots_queue`.
    batch_size:
        Maximum number of rows per batch insert call.

    Returns
    -------
    int
        Total number of rows inserted.
    """
    batch: List[dict] = []
    total = 0

    for row in rows:
        if row.data is None:
            continue

        batch.append(_row_to_dict(row))

        if len(batch) >= batch_size:
            repository.insert_screenshot_batch(batch, auto_commit=False)
            total += len(batch)
            batch.clear()

    # Flush remaining rows with final commit
    if batch:
        repository.insert_screenshot_batch(batch, auto_commit=True)
        total += len(batch)

    return total
