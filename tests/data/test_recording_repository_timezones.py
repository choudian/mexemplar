import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

import src.utils.timezone as timezone_utils
from src.data.migrations import run_migrations
from src.data.recording_repository import RecordingRepository


class _FakeDuckDBManager:
    def __init__(self):
        self.insert_calls = []
        self.insert_many_calls = []

    def insert(self, table, data, auto_commit=False):
        self.insert_calls.append((table, data, auto_commit))
        return len(self.insert_calls)

    def insert_many(self, table, data_list, auto_commit=False):
        self.insert_many_calls.append((table, data_list, auto_commit))
        return list(range(1, len(data_list) + 1))


def _parse_db_datetime(value):
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def test_recording_repository_persists_naive_utc_for_duckdb_timestamps():
    db = _FakeDuckDBManager()
    repo = RecordingRepository(db_manager=db)

    repo.save_recording_session(
        {
            "recording_id": "rec-1",
            "start_time": 1,
            "end_time": 61,
        }
    )
    repo.save_actions(
        "rec-1",
        [
            {
                "action_type": "click",
                "timestamp": 121,
            }
        ],
    )
    repo.save_network_requests(
        recording_id="rec-1",
        network_requests=[
            {
                "action_id": 1,
                "url": "https://example.com",
                "timestamp": 181,
                "filtered": False,
                "filter_reason": None,
                "filtered_at": None,
            }
        ],
    )
    repo.save_sibling_snapshot(
        action_id=1,
        recording_id="rec-1",
        siblings_snapshot={
            "siblings": [],
            "timestamp": 241,
        },
    )

    session_row = db.insert_calls[0][1]
    assert session_row["start_time"] == datetime(1970, 1, 1, 0, 0, 1)
    assert session_row["end_time"] == datetime(1970, 1, 1, 0, 1, 1)
    assert session_row["start_time"].tzinfo is None
    assert session_row["end_time"].tzinfo is None

    actions_row = db.insert_many_calls[0][1][0]
    assert actions_row["timestamp"] == datetime(1970, 1, 1, 0, 2, 1)
    assert actions_row["timestamp"].tzinfo is None

    request_row = db.insert_many_calls[1][1][0]
    assert request_row["timestamp"] == datetime(1970, 1, 1, 0, 3, 1)
    assert request_row["timestamp"].tzinfo is None

    snapshot_row = db.insert_calls[1][1]
    assert snapshot_row["timestamp"] == datetime(1970, 1, 1, 0, 4, 1)
    assert snapshot_row["timestamp"].tzinfo is None


def test_recording_repository_uses_naive_utc_now_when_timestamp_missing(monkeypatch):
    fixed_now = datetime(2026, 4, 18, 8, 0, 0, 123456)
    monkeypatch.setattr("src.data.recording_repository.utc_now_naive", lambda: fixed_now)

    db = _FakeDuckDBManager()
    repo = RecordingRepository(db_manager=db)

    repo.save_network_requests(
        recording_id="rec-1",
        network_requests=[
            {
                "action_id": 1,
                "url": "https://example.com",
                "filtered": False,
                "filter_reason": None,
                "filtered_at": None,
            }
        ],
    )
    repo.save_sibling_snapshot(
        action_id=1,
        recording_id="rec-1",
        siblings_snapshot={"siblings": []},
    )

    request_row = db.insert_many_calls[0][1][0]
    snapshot_row = db.insert_calls[0][1]
    assert request_row["timestamp"] == fixed_now
    assert snapshot_row["timestamp"] == fixed_now
    assert request_row["timestamp"].tzinfo is None
    assert snapshot_row["timestamp"].tzinfo is None


def test_run_migrations_v9_normalizes_legacy_skill_composition_updated_at(monkeypatch):
    fixed_local_now = datetime(2026, 4, 18, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(timezone_utils, "local_now", lambda: fixed_local_now)

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        db_path = Path(temp_dir) / "migration-v9.sqlite3"
        engine = create_engine(f"sqlite:///{db_path}")

        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE schema_version (version INTEGER)"))
            conn.execute(text("INSERT INTO schema_version (version) VALUES (8)"))
            conn.execute(text("""
                    CREATE TABLE skill_compositions (
                        composition_id TEXT PRIMARY KEY,
                        updated_at DATETIME
                    )
                    """))
            conn.execute(
                text("""
                    INSERT INTO skill_compositions (composition_id, updated_at)
                    VALUES (:composition_id, :updated_at)
                    """),
                [
                    {
                        "composition_id": "legacy-local",
                        "updated_at": "2026-04-18 10:00:00.123456",
                    },
                    {
                        "composition_id": "already-utc",
                        "updated_at": "2026-04-18 02:00:00",
                    },
                ],
            )

        try:
            run_migrations(engine)

            with engine.connect() as conn:
                version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
                rows = conn.execute(text("""
                        SELECT composition_id, updated_at
                        FROM skill_compositions
                        ORDER BY composition_id
                        """)).fetchall()

            updated_at_by_id = {row[0]: _parse_db_datetime(row[1]) for row in rows}
            from src.data import migrations

            assert version == migrations._MIGRATIONS[-1][0]
            assert updated_at_by_id["already-utc"] == datetime(2026, 4, 18, 2, 0, 0)
            assert updated_at_by_id["legacy-local"] == datetime(2026, 4, 18, 2, 0, 0, 123456)
        finally:
            engine.dispose()
