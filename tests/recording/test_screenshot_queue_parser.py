"""Tests for src/recording/browser/screenshot_queue_parser.py"""

import base64
import json
from pathlib import Path

from src.recording.browser.screenshot_queue_parser import (
    ScreenshotRow,
    batch_insert_screenshots,
    iter_screenshots_queue,
)


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _make_record(**overrides) -> dict:
    img_bytes = b"\xff\xd8\xff\xe0fake_jpeg_data"
    base = {
        "recording_id": "rec_test",
        "capture_id": "cap_0001",
        "moment": "before",
        "source_trigger": "mouse_left",
        "input_started_at": 1734508923.456,
        "input_completed_at": None,
        "captured_at": 1734508923.468,
        "data_b64": base64.b64encode(img_bytes).decode("ascii"),
        "media_type": "image/jpeg",
        "skipped_reason": None,
    }
    base.update(overrides)
    return base


class TestIterScreenshotsQueue:
    def test_parses_valid_records(self, tmp_path):
        path = tmp_path / "test_screenshots.jsonl"
        _write_jsonl(
            path,
            [
                _make_record(moment="before"),
                _make_record(moment="after", captured_at=1734508923.700),
            ],
        )

        rows = list(iter_screenshots_queue(path))
        assert len(rows) == 2
        assert rows[0].moment == "before"
        assert rows[1].moment == "after"

    def test_decodes_base64_data(self, tmp_path):
        img = b"\x89PNG\r\n\x1a\nfake"
        path = tmp_path / "test_screenshots.jsonl"
        _write_jsonl(path, [_make_record(data_b64=base64.b64encode(img).decode())])

        rows = list(iter_screenshots_queue(path))
        assert rows[0].data == img

    def test_skipped_row_has_no_data(self, tmp_path):
        path = tmp_path / "test_screenshots.jsonl"
        _write_jsonl(path, [_make_record(data_b64=None, skipped_reason="not_foreground")])

        rows = list(iter_screenshots_queue(path))
        assert len(rows) == 1
        assert rows[0].data is None
        assert rows[0].skipped_reason == "not_foreground"

    def test_malformed_json_line_skipped(self, tmp_path):
        path = tmp_path / "test_screenshots.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write("{bad json}\n")
            f.write(json.dumps(_make_record()) + "\n")

        rows = list(iter_screenshots_queue(path))
        assert len(rows) == 1

    def test_missing_required_field_skipped(self, tmp_path):
        path = tmp_path / "test_screenshots.jsonl"
        # missing "captured_at"
        path.write_text(
            json.dumps({"recording_id": "x", "moment": "before"}) + "\n", encoding="utf-8"
        )

        rows = list(iter_screenshots_queue(path))
        assert len(rows) == 0

    def test_empty_lines_ignored(self, tmp_path):
        path = tmp_path / "test_screenshots.jsonl"
        path.write_text("\n\n" + json.dumps(_make_record()) + "\n\n", encoding="utf-8")

        rows = list(iter_screenshots_queue(path))
        assert len(rows) == 1

    def test_captured_at_used_as_timestamp(self, tmp_path):
        ts = 1734508900.123
        path = tmp_path / "test_screenshots.jsonl"
        _write_jsonl(path, [_make_record(captured_at=ts)])

        rows = list(iter_screenshots_queue(path))
        assert rows[0].timestamp == ts

    def test_bad_base64_skipped(self, tmp_path):
        path = tmp_path / "test_screenshots.jsonl"
        _write_jsonl(path, [_make_record(data_b64="!!!not-base64!!!")])

        rows = list(iter_screenshots_queue(path))
        assert len(rows) == 0


class TestBatchInsertScreenshots:
    def test_inserts_valid_rows(self):
        from unittest.mock import MagicMock

        mock_repo = MagicMock()
        mock_repo.insert_screenshot_batch.return_value = [1, 2]
        img = b"\xff\xd8\xff\xe0fake"
        rows = [
            ScreenshotRow(
                recording_id="rec_1",
                moment="before",
                timestamp=100.0,
                data=img,
                media_type="image/jpeg",
            ),
            ScreenshotRow(
                recording_id="rec_1",
                moment="after",
                timestamp=100.2,
                data=img,
                media_type="image/jpeg",
            ),
        ]

        count = batch_insert_screenshots(mock_repo, rows)
        assert count == 2
        assert mock_repo.insert_screenshot_batch.call_count == 1

    def test_filters_skipped_rows(self):
        from unittest.mock import MagicMock

        mock_repo = MagicMock()
        mock_repo.insert_screenshot_batch.return_value = [1]
        img = b"\xff\xd8\xff\xe0fake"
        rows = [
            ScreenshotRow(recording_id="rec_1", moment="before", timestamp=100.0, data=img),
            ScreenshotRow(
                recording_id="rec_1",
                moment="before",
                timestamp=101.0,
                data=None,
                skipped_reason="not_foreground",
            ),
        ]

        count = batch_insert_screenshots(mock_repo, rows)
        assert count == 1
        batch_arg = mock_repo.insert_screenshot_batch.call_args[0][0]
        assert len(batch_arg) == 1
        assert batch_arg[0]["source_trigger"] is None

    def test_preserves_source_trigger_metadata(self):
        from unittest.mock import MagicMock

        mock_repo = MagicMock()
        mock_repo.insert_screenshot_batch.return_value = [1]
        rows = [
            ScreenshotRow(
                recording_id="rec_1",
                moment="before",
                timestamp=100.0,
                data=b"\xff\xd8",
                source_trigger="mouse_left",
            )
        ]

        count = batch_insert_screenshots(mock_repo, rows)

        assert count == 1
        batch_arg = mock_repo.insert_screenshot_batch.call_args[0][0]
        assert batch_arg[0]["source_trigger"] == "mouse_left"

    def test_batches_correctly(self):
        from unittest.mock import MagicMock

        mock_repo = MagicMock()
        mock_repo.insert_screenshot_batch.return_value = [1]
        rows = [
            ScreenshotRow(recording_id="r", moment="before", timestamp=float(i), data=b"\x00")
            for i in range(5)
        ]

        batch_insert_screenshots(mock_repo, rows, batch_size=2)
        assert mock_repo.insert_screenshot_batch.call_count == 3

    def test_empty_input(self):
        from unittest.mock import MagicMock

        mock_repo = MagicMock()
        assert batch_insert_screenshots(mock_repo, []) == 0
        mock_repo.insert_screenshot_batch.assert_not_called()
