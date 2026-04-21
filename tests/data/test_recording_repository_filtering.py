import json

import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository
from src.recording.filtering.decision import FilterDecision


def _create_fresh_db(tmp_path, db_name: str):
    old_instance = duckdb_module._duckdb_instance
    old_auto_recover = RecordingRepository._auto_recover_done

    if old_instance is not None:
        try:
            old_instance.close()
        except Exception:
            pass

    duckdb_module._duckdb_instance = None
    RecordingRepository._auto_recover_done = True

    db = DuckDBManager(str(tmp_path / db_name))
    db.initialize()
    repo = RecordingRepository(db_manager=db)
    return repo, db, old_instance, old_auto_recover


def _restore_db(db, old_instance, old_auto_recover):
    try:
        db.close()
    except Exception:
        pass

    duckdb_module._duckdb_instance = old_instance
    RecordingRepository._auto_recover_done = old_auto_recover


def test_save_network_requests_returns_batch_index_map_and_uses_schema_defaults(tmp_path):
    repo, db, old_instance, old_auto_recover = _create_fresh_db(tmp_path, "repo_filtering.duckdb")

    try:
        request_id_map = repo.save_network_requests(
            [
                {
                    "action_id": None,
                    "url": "https://example.com/api/orders",
                    "method": "GET",
                    "request_type": "xhr",
                    "response_status": 200,
                    "timestamp": 1734508923.0,
                    "filtered": True,
                    "filter_reason": {
                        "decision": "filter",
                        "source": "rule",
                        "reason": "static_asset",
                    },
                    "filtered_at": 1734508924.0,
                },
                {
                    "action_id": 42,
                    "url": "https://example.com/api/profile",
                    "method": "POST",
                    "request_type": "fetch",
                    "response_status": 201,
                    "timestamp": 1734508925.0,
                    "filtered": False,
                    "filter_reason": None,
                    "filtered_at": None,
                },
            ],
            recording_id="rec-filter",
        )

        assert request_id_map == {0: 1, 1: 2}

        rows = db.fetchall(
            """
            SELECT action_id, filtered, filter_reason, filtered_at, is_recommendation, importance_level
            FROM network_requests
            WHERE recording_id = ?
            ORDER BY request_id
            """,
            ("rec-filter",),
        )

        assert rows[0][0] is None
        assert rows[0][1] is True
        assert json.loads(rows[0][2])["reason"] == "static_asset"
        assert rows[0][3] is not None
        assert rows[0][4] is False
        assert rows[0][5] == "unknown"

        assert rows[1][0] == 42
        assert rows[1][1] is False
        assert rows[1][2] is None
        assert rows[1][3] is None
        assert rows[1][4] is False
        assert rows[1][5] == "unknown"
    finally:
        _restore_db(db, old_instance, old_auto_recover)


def test_save_filter_decisions_persists_serialized_rows(tmp_path):
    repo, db, old_instance, old_auto_recover = _create_fresh_db(tmp_path, "repo_decisions.duckdb")

    try:
        decision_ids = repo.save_filter_decisions(
            [
                FilterDecision(
                    decision="filter",
                    source="rule",
                    reason="static_asset",
                    pattern_matched=".png",
                    scores={"rule": 1.0},
                    request_id="1",
                    action_id=7,
                    recording_id="rec-filter",
                )
            ]
        )

        assert decision_ids == [1]
        row = db.fetchone(
            """
            SELECT request_id, action_id, recording_id, decision, source, reason, pattern_matched, scores
            FROM filter_decisions
            WHERE recording_id = ?
            """,
            ("rec-filter",),
        )

        assert row[:7] == ("1", 7, "rec-filter", "filter", "rule", "static_asset", ".png")
        assert json.loads(row[7]) == {"rule": 1.0}
    finally:
        _restore_db(db, old_instance, old_auto_recover)


def test_filtering_repository_methods_participate_in_outer_transaction(tmp_path):
    repo, db, old_instance, old_auto_recover = _create_fresh_db(tmp_path, "repo_tx.duckdb")

    try:
        try:
            with db.transaction():
                repo.save_network_requests(
                    [
                        {
                            "action_id": None,
                            "url": "https://example.com/api/orders",
                            "timestamp": 1734508923.0,
                            "filtered": True,
                            "filter_reason": {"decision": "filter", "source": "rule", "reason": "static_asset"},
                            "filtered_at": 1734508924.0,
                        }
                    ],
                    recording_id="rec-tx",
                )
                repo.save_filter_decisions(
                    [
                        FilterDecision(
                            decision="filter",
                            source="rule",
                            reason="static_asset",
                            request_id="1",
                            recording_id="rec-tx",
                        )
                    ]
                )
                raise RuntimeError("rollback")
        except RuntimeError as exc:
            assert str(exc) == "rollback"

        assert db.fetchone(
            "SELECT count(*) FROM network_requests WHERE recording_id = ?",
            ("rec-tx",),
        )[0] == 0
        assert db.fetchone(
            "SELECT count(*) FROM filter_decisions WHERE recording_id = ?",
            ("rec-tx",),
        )[0] == 0
    finally:
        _restore_db(db, old_instance, old_auto_recover)


def test_save_network_requests_does_not_commit_outer_transaction_early(tmp_path):
    repo, db, old_instance, old_auto_recover = _create_fresh_db(tmp_path, "repo_depth.duckdb")

    try:
        with db.transaction():
            repo.save_network_requests(
                [
                    {
                        "action_id": None,
                        "url": "https://example.com/api/orders",
                        "timestamp": 1734508923.0,
                        "filtered": False,
                        "filter_reason": None,
                        "filtered_at": None,
                    }
                ],
                recording_id="rec-depth",
            )
            assert db._transaction_depth() > 0
            assert db.fetchone(
                "SELECT count(*) FROM network_requests WHERE recording_id = ?",
                ("rec-depth",),
            )[0] == 1

        assert db.fetchone(
            "SELECT count(*) FROM network_requests WHERE recording_id = ?",
            ("rec-depth",),
        )[0] == 1
    finally:
        _restore_db(db, old_instance, old_auto_recover)


def test_network_requests_migration_path_keeps_importance_level_default(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    old_auto_recover = RecordingRepository._auto_recover_done

    if old_instance is not None:
        try:
            old_instance.close()
        except Exception:
            pass

    duckdb_module._duckdb_instance = None
    RecordingRepository._auto_recover_done = True

    db = DuckDBManager(str(tmp_path / "repo_migration.duckdb"))
    conn = db.connect()
    conn.execute("CREATE SEQUENCE IF NOT EXISTS request_id_seq START 1")
    conn.execute(
        """
        CREATE TABLE network_requests (
            request_id INTEGER PRIMARY KEY DEFAULT nextval('request_id_seq'),
            action_id INTEGER,
            recording_id TEXT,
            url TEXT,
            method TEXT,
            request_type TEXT,
            request_headers JSON,
            request_body TEXT,
            response_status INTEGER,
            response_headers JSON,
            response_body TEXT,
            duration FLOAT,
            timestamp TIMESTAMP,
            filtered BOOLEAN DEFAULT FALSE,
            filter_reason JSON,
            filtered_at TIMESTAMP,
            is_recommendation BOOLEAN DEFAULT FALSE
        )
        """
    )

    try:
        db.initialize()
        repo = RecordingRepository(db_manager=db)
        repo.save_network_requests(
            [
                {
                    "action_id": None,
                    "url": "https://example.com/api/orders",
                    "timestamp": 1734508923.0,
                    "filtered": False,
                    "filter_reason": None,
                    "filtered_at": None,
                }
            ],
            recording_id="rec-migration",
        )

        row = db.fetchone(
            """
            SELECT is_recommendation, importance_level
            FROM network_requests
            WHERE recording_id = ?
            """,
            ("rec-migration",),
        )
        assert row == (False, "unknown")
    finally:
        _restore_db(db, old_instance, old_auto_recover)
