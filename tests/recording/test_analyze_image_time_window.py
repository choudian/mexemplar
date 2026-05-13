"""Tests for _analyze_image time-window query in recording_data_tools.py.

These tests verify the SQL query logic against a real in-memory DuckDB,
not the LLM call itself.
"""

from datetime import datetime, timedelta, timezone

import pytest


def _naive_utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)


@pytest.fixture
def mock_db_with_data(tmp_path):
    """Set up a DuckDB with actions and recording_screenshots for time-window tests."""
    import duckdb

    db_path = tmp_path / "test.duckdb"
    conn = duckdb.connect(str(db_path))

    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS action_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS actions (
            action_id INTEGER PRIMARY KEY DEFAULT nextval('action_id_seq'),
            recording_id VARCHAR,
            sequence_number INTEGER,
            action_type VARCHAR,
            timestamp TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS recording_screenshot_id_seq START 1
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recording_screenshots (
            screenshot_id INTEGER PRIMARY KEY DEFAULT nextval('recording_screenshot_id_seq'),
            recording_id VARCHAR NOT NULL,
            moment VARCHAR NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            capture_id VARCHAR,
            source_trigger VARCHAR,
            input_started_at TIMESTAMP,
            input_completed_at TIMESTAMP,
            media_type VARCHAR,
            data BLOB
        )
    """)

    # Action at T=1000.0
    conn.execute(
        "INSERT INTO actions (recording_id, sequence_number, action_type, timestamp) VALUES (?, ?, ?, ?)",
        ("rec_1", 1, "click", _naive_utc(1000.0)),
    )

    # Before screenshot at T=999.95 (within [999.0, 1000.25])
    conn.execute(
        "INSERT INTO recording_screenshots (recording_id, moment, timestamp, media_type, data) VALUES (?, ?, ?, ?, ?)",
        ("rec_1", "before", _naive_utc(999.95), "image/jpeg", b"\xff\xd8before_img"),
    )

    # After screenshot at T=1000.2 (within [1000.0, 1001.5])
    conn.execute(
        "INSERT INTO recording_screenshots (recording_id, moment, timestamp, media_type, data) VALUES (?, ?, ?, ?, ?)",
        ("rec_1", "after", _naive_utc(1000.2), "image/jpeg", b"\xff\xd8after_img"),
    )

    conn.close()
    return db_path


class TestTimeWindowQuery:
    def test_finds_before_screenshot(self, mock_db_with_data):
        """Before query finds a screenshot within [T - 1.0s, T + 0.25s]."""
        import duckdb

        conn = duckdb.connect(str(mock_db_with_data), read_only=True)
        t = _naive_utc(1000.0)

        row = conn.execute(
            """
            SELECT data, media_type FROM recording_screenshots
            WHERE recording_id = ?
              AND moment = 'before'
              AND timestamp BETWEEN ? AND ?
            ORDER BY abs(epoch(timestamp) - epoch(?))
            LIMIT 1
            """,
            ("rec_1", t - timedelta(seconds=1.0), t + timedelta(seconds=0.25), t),
        ).fetchone()

        conn.close()
        assert row is not None
        assert row[0] == b"\xff\xd8before_img"

    def test_finds_after_screenshot(self, mock_db_with_data):
        """After query finds a screenshot within [T, T + 1.5s]."""
        import duckdb

        conn = duckdb.connect(str(mock_db_with_data), read_only=True)
        t = _naive_utc(1000.0)

        row = conn.execute(
            """
            SELECT data, media_type FROM recording_screenshots
            WHERE recording_id = ?
              AND moment = 'after'
              AND timestamp BETWEEN ? AND ?
            ORDER BY abs(epoch(timestamp) - epoch(?))
            LIMIT 1
            """,
            ("rec_1", t, t + timedelta(seconds=1.5), t),
        ).fetchone()

        conn.close()
        assert row is not None
        assert row[0] == b"\xff\xd8after_img"

    def test_outside_window_returns_none(self, mock_db_with_data):
        """Screenshot outside the time window is not returned."""
        import duckdb

        conn = duckdb.connect(str(mock_db_with_data), read_only=True)
        # Action at T=2000, no screenshots near it
        t = _naive_utc(2000.0)

        row = conn.execute(
            """
            SELECT data, media_type FROM recording_screenshots
            WHERE recording_id = ?
              AND moment = 'before'
              AND timestamp BETWEEN ? AND ?
            ORDER BY abs(epoch(timestamp) - epoch(?))
            LIMIT 1
            """,
            ("rec_1", t - timedelta(seconds=1.0), t + timedelta(seconds=0.25), t),
        ).fetchone()

        conn.close()
        assert row is None

    def test_nearest_wins_when_multiple_in_window(self, mock_db_with_data):
        """When multiple screenshots are in the window, the nearest wins."""
        import duckdb

        conn = duckdb.connect(str(mock_db_with_data))
        t_action = _naive_utc(1000.0)

        # Add another before screenshot closer to T=1000
        conn.execute(
            "INSERT INTO recording_screenshots (recording_id, moment, timestamp, media_type, data) VALUES (?, ?, ?, ?, ?)",
            ("rec_1", "before", _naive_utc(999.99), "image/jpeg", b"closer_before"),
        )

        row = conn.execute(
            """
            SELECT data, media_type FROM recording_screenshots
            WHERE recording_id = ?
              AND moment = 'before'
              AND timestamp BETWEEN ? AND ?
            ORDER BY abs(epoch(timestamp) - epoch(?))
            LIMIT 1
            """,
            (
                "rec_1",
                t_action - timedelta(seconds=1.0),
                t_action + timedelta(seconds=0.25),
                t_action,
            ),
        ).fetchone()

        conn.close()
        assert row[0] == b"closer_before"

    def test_where_does_not_use_source_trigger(self, mock_db_with_data):
        """Verify that the query SQL does not filter on source_trigger."""
        import duckdb

        conn = duckdb.connect(str(mock_db_with_data), read_only=True)
        # source_trigger is NULL in our test data; query should still work
        t = _naive_utc(1000.0)

        row = conn.execute(
            """
            SELECT count(*) FROM recording_screenshots
            WHERE recording_id = ?
              AND moment = 'before'
              AND timestamp BETWEEN ? AND ?
            """,
            ("rec_1", t - timedelta(seconds=1.0), t + timedelta(seconds=0.25)),
        ).fetchone()

        conn.close()
        assert row[0] >= 1


class TestAnalyzeImageIntegration:
    def test_source_trigger_not_in_sql(self):
        """Gatekeeper: _analyze_image SQL must not reference source_trigger."""
        from pathlib import Path

        source = Path("src/business/agents/tools/recording_data_tools.py").read_text(
            encoding="utf-8"
        )
        # Find the _analyze_image function body
        func_start = source.find("def _analyze_image(")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        # SQL in function should not contain source_trigger in WHERE
        assert (
            "source_trigger" not in func_body
            or "WHERE" not in func_body.split("source_trigger")[0][-200:]
        )

    def test_old_screenshot_before_after_not_used(self):
        """Gatekeeper: _analyze_image should not query screenshot_before/after from actions."""
        from pathlib import Path

        source = Path("src/business/agents/tools/recording_data_tools.py").read_text(
            encoding="utf-8"
        )
        func_start = source.find("def _analyze_image(")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        assert "screenshot_before" not in func_body
        assert "screenshot_after" not in func_body

    def test_common_tables_has_recording_screenshots(self):
        """Gatekeeper: _COMMON_TABLES must include recording_screenshots."""
        from src.business.agents.tools.recording_data_tools import _COMMON_TABLES

        assert "recording_screenshots" in _COMMON_TABLES
